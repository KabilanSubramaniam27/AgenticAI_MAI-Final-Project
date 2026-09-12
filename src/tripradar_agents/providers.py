"""Read-only provider adapters. Provider text and amounts never become model authority."""

import time
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import httpx

from .security import digest

AIRPORTS = {
    "Lisbon": {"city": "LIS", "airports": {"LIS"}},
    "Paris": {"city": "PAR", "airports": {"CDG", "ORY"}},
    "London": {"city": "LON", "airports": {"LHR", "LGW"}},
    "New York City": {"city": "NYC", "airports": {"JFK", "EWR"}},
}


class ProviderError(ValueError):
    """Safe error category; never includes authentication headers or provider bodies."""


class Reader:
    def __init__(self, limit=20, deadline=None, client=None):
        self.limit, self.attempts = limit, 0
        self.events = []
        self.deadline = deadline or time.monotonic() + 120
        self.client = client or httpx.Client(follow_redirects=False)

    def close(self):
        self.client.close()

    def request(self, method, url, **kwargs):
        for retry in range(3):
            remaining = self.deadline - time.monotonic()
            if self.attempts >= self.limit or remaining <= 0:
                raise ProviderError("read_budget_exhausted")
            self.attempts += 1
            delay = 2**retry
            from urllib.parse import urlsplit

            target = urlsplit(url)
            event = {
                "method": method,
                "host": target.hostname,
                "path": target.path,
                "attempt": self.attempts,
            }
            self.events.append(event)
            started = time.monotonic()
            try:
                response = self.client.request(method, url, timeout=min(15, remaining), **kwargs)
                event.update(
                    status=response.status_code,
                    latency_ms=round((time.monotonic() - started) * 1000),
                )
                if response.status_code not in {429, 500, 502, 503, 504}:
                    if response.status_code >= 400:
                        raise ProviderError(f"http_{response.status_code}")
                    if len(response.content) > 2_000_000:
                        raise ProviderError("response_too_large")
                    return response.json()
                after = response.headers.get("Retry-After", "")
                if after.isdigit():
                    delay = max(delay, int(after))
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                event.update(
                    error=type(exc).__name__, latency_ms=round((time.monotonic() - started) * 1000)
                )
            except (ValueError, KeyError) as exc:
                if isinstance(exc, ProviderError):
                    raise
                raise ProviderError("malformed_response") from exc
            if retry == 2 or time.monotonic() + delay >= self.deadline:
                raise ProviderError("provider_unavailable")
            time.sleep(delay)
        raise ProviderError("provider_unavailable")


def money(value):
    amount = Decimal(str(value))
    if not amount.is_finite() or amount < 0:
        raise ProviderError("invalid_amount")
    return amount


def unavailable(trip, environment, category, reason):
    return {
        "id": uuid4().hex,
        "kind": "pricing_unavailable",
        "destination": trip["destination"],
        "environment": environment,
        "category": category,
        "reason": reason,
    }


def amadeus_prices(trip, settings, reader, hotel_dates=None):
    hotel_dates = hotel_dates or {"check_in": trip["start_date"], "check_out": trip["end_date"]}
    if (
        not trip["start_date"]
        <= hotel_dates["check_in"]
        < hotel_dates["check_out"]
        <= trip["end_date"]
    ):
        raise ProviderError("invalid_lodging_dates")
    environment = settings.amadeus_environment
    if (
        not settings.amadeus_client_id.get_secret_value()
        or not settings.amadeus_client_secret.get_secret_value()
    ):
        return [unavailable(trip, "live", "pricing", "Amadeus credentials not configured")]
    base = (
        "https://api.amadeus.com" if environment == "production" else "https://test.api.amadeus.com"
    )
    token = reader.request(
        "POST",
        base + "/v1/security/oauth2/token",
        data={
            "grant_type": "client_credentials",
            "client_id": settings.amadeus_client_id.get_secret_value(),
            "client_secret": settings.amadeus_client_secret.get_secret_value(),
        },
    ).get("access_token")
    if not isinstance(token, str) or not token:
        raise ProviderError("invalid_token_response")
    headers = {"Authorization": "Bearer " + token}
    city = AIRPORTS[trip["destination"]]
    common = {
        "kind": "price",
        "environment": "live",
        "provider_environment": environment,
        "destination": trip["destination"],
        "trip": trip,
        "retrieved_at": datetime.now(UTC).isoformat(),
        "url": base,
        "price_basis": "whole_party_whole_stay",
    }
    rows = []
    try:
        data = reader.request(
            "GET",
            base + "/v2/shopping/flight-offers",
            headers=headers,
            params={
                "originLocationCode": trip["origin"],
                "destinationLocationCode": city["city"],
                "departureDate": trip.get("outbound_date", trip["start_date"]),
                "returnDate": trip["end_date"],
                "adults": trip["adults"],
                "currencyCode": trip["currency"],
                "max": 5,
            },
        )
        for raw in data["data"]:
            try:
                outbound, inbound = raw["itineraries"]
                out, back = outbound["segments"], inbound["segments"]
                if (
                    out[0]["departure"]["iataCode"] != trip["origin"]
                    or out[-1]["arrival"]["iataCode"] not in city["airports"]
                    or back[0]["departure"]["iataCode"] not in city["airports"]
                    or back[-1]["arrival"]["iataCode"] != trip["origin"]
                    or out[0]["departure"]["at"][:10]
                    != trip.get("outbound_date", trip["start_date"])
                    or back[0]["departure"]["at"][:10] != trip["end_date"]
                    or out[-1]["arrival"]["at"][:10] != trip["start_date"]
                    or len(raw["travelerPricings"]) != trip["adults"]
                ):
                    continue
                rows.append(
                    {
                        **common,
                        "id": uuid4().hex,
                        "provider_id": raw["id"],
                        "source_hash": digest(raw),
                        "category": "flight_total",
                        "amount": str(money(raw["price"].get("grandTotal", raw["price"]["total"]))),
                        "currency": raw["price"]["currency"],
                        "taxes_known": True,
                        "fees_known": False,
                        "reason": "Optional baggage and transfer costs require allowances",
                        "arrival": out[-1]["arrival"]["at"],
                        "departure": back[0]["departure"]["at"],
                        "arrival_airport": out[-1]["arrival"]["iataCode"],
                        "departure_airport": back[0]["departure"]["iataCode"],
                        "stops": len(out) + len(back) - 2,
                    }
                )
            except (KeyError, TypeError, ValueError):
                continue
    except (ProviderError, KeyError, TypeError) as exc:
        rows.append(unavailable(trip, "live", "flight_total", type(exc).__name__))
    if not any(r.get("category") == "flight_total" and r["kind"] == "price" for r in rows):
        rows.append(unavailable(trip, "live", "flight_total", "No eligible flight offer returned"))
    # Amadeus's adults field is per room. Uneven allocations require explicit room-level input.
    if trip["adults"] % trip["rooms"]:
        rows.append(
            unavailable(
                trip, "live", "hotel_total", "Uneven room occupancy requires room-level allocation"
            )
        )
        return rows
    try:
        hotels = reader.request(
            "GET",
            base + "/v1/reference-data/locations/hotels/by-city",
            headers=headers,
            params={"cityCode": city["city"]},
        )["data"]
        ids = [h["hotelId"] for h in hotels[:5]]
        if not ids:
            raise ProviderError("no_hotels")
        data = reader.request(
            "GET",
            base + "/v3/shopping/hotel-offers",
            headers=headers,
            params={
                "hotelIds": ",".join(ids),
                "adults": trip["adults"] // trip["rooms"],
                "roomQuantity": trip["rooms"],
                "checkInDate": hotel_dates["check_in"],
                "checkOutDate": hotel_dates["check_out"],
                "currency": trip["currency"],
                "bestRateOnly": "true",
            },
        )
        for item in data["data"]:
            if not item.get("available") or item["hotel"]["hotelId"] not in ids:
                continue
            for raw in item.get("offers", [])[:2]:
                if (
                    raw.get("checkInDate") != hotel_dates["check_in"]
                    or raw.get("checkOutDate") != hotel_dates["check_out"]
                    or raw.get("guests", {}).get("adults") != trip["adults"] // trip["rooms"]
                    or int(raw.get("roomQuantity", 1)) != trip["rooms"]
                ):
                    continue
                price = raw["price"]
                taxes = price.get("taxes")
                rows.append(
                    {
                        **common,
                        "id": uuid4().hex,
                        "provider_id": raw["id"],
                        "source_hash": digest(raw),
                        "category": "hotel_total",
                        "amount": str(money(price.get("sellingTotal", price["total"]))),
                        "currency": price["currency"],
                        "taxes_known": taxes is not None
                        and all(t.get("included") is True for t in taxes),
                        "fees_known": False,
                        "hotel_id": item["hotel"]["hotelId"],
                        "hotel_name": item["hotel"].get("name", ""),
                        "latitude": item["hotel"].get("latitude"),
                        "longitude": item["hotel"].get("longitude"),
                        "check_in": raw["checkInDate"],
                        "check_out": raw["checkOutDate"],
                        "reason": "Whole-stay quote; unconfirmed fees remain unknown",
                    }
                )
    except (ProviderError, KeyError, TypeError, ValueError) as exc:
        rows.append(unavailable(trip, "live", "hotel_total", type(exc).__name__))
    return rows


def exchange_rate(base, quote, reader):
    if base not in {"USD", "EUR", "GBP"} or quote not in {"USD", "EUR", "GBP"}:
        raise ProviderError("unsupported_currency")
    data = reader.request(
        "GET", f"https://api.frankfurter.dev/v2/rate/{base}/{quote}", params={"providers": "ecb"}
    )
    day = datetime.fromisoformat(data["date"]).date()
    if (
        data["base"] != base
        or data["quote"] != quote
        or not 0 <= (datetime.now(UTC).date() - day).days <= 4
    ):
        raise ProviderError("stale_or_wrong_fx")
    rate = money(data["rate"])
    if rate == 0:
        raise ProviderError("invalid_fx")
    return {
        "id": uuid4().hex,
        "base": base,
        "quote": quote,
        "rate": str(rate),
        "date": str(day),
        "source_hash": digest(data),
        "url": "https://api.frankfurter.dev/",
    }
