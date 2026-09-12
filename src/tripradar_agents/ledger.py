"""Evidence-ID-only monetary calculations and conservative dependency reconciliation."""

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import uuid4

from .models import CITIES, trip_days
from .providers import exchange_rate, money
from .security import digest

REQUIRED = {
    "flight_total",
    "hotel_total",
    "food",
    "local_transport",
    "activities",
    "mandatory_fees",
}


def fresh(record, seconds=900):
    try:
        now = datetime.now(UTC)
        age = (now - datetime.fromisoformat(record["retrieved_at"])).total_seconds()
        return 0 <= age <= seconds and (
            not record.get("expires_at") or now < datetime.fromisoformat(record["expires_at"])
        )
    except (KeyError, ValueError, TypeError):
        return False


def calculate(trip, records, ids, allowances=(), reader=None):
    if len(ids) != len(set(ids)) or any(i not in records for i in ids):
        raise ValueError("Unknown or duplicate evidence IDs")
    lines, missing, covered, fx = [], set(REQUIRED), set(), {}
    environments = set()
    for eid in ids:
        offer = records[eid]
        if offer["kind"] != "price" or offer["trip"] != trip or not fresh(offer):
            raise ValueError("Inapplicable or expired offer")
        if offer.get("price_basis") != "whole_party_whole_stay":
            raise ValueError("Unsupported offer basis")
        environments.add(offer.get("provider_environment", offer["environment"]))
        entries = (
            [(offer["category"], offer["amount"])]
            if "category" in offer
            else [(c, offer[c]) for c in ("flight_total", "hotel_total")]
        )
        for category, amount in entries:
            if category not in REQUIRED or category in covered:
                raise ValueError("Overlapping budget components")
            covered.add(category)
            value = money(amount)
            rate_id = None
            if offer["currency"] != trip["currency"]:
                pair = (offer["currency"], trip["currency"])
                try:
                    if not reader:
                        raise ValueError("FX evidence unavailable")
                    if pair not in fx:
                        fx[pair] = exchange_rate(*pair, reader)
                    value *= Decimal(fx[pair]["rate"])
                    rate_id = fx[pair]["id"]
                except ValueError:
                    continue
            rounded = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            lines.append(
                {
                    "category": category,
                    "amount": str(rounded),
                    "evidence_id": eid,
                    "source_amount": str(amount),
                    "source_currency": offer["currency"],
                    "fx_id": rate_id,
                }
            )
            missing.discard(category)
            if not offer.get("taxes_known") or offer.get("fees_known") is False:
                missing.add("unconfirmed_provider_fees")
    for allowance in allowances:
        # The API issues these records from explicit form fields, not model-provided approval.
        if (
            allowance.get("state_hash") != digest(trip)
            or allowance.get("status") != "accepted"
            or allowance.get("source") != "user_form"
            or allowance.get("currency") != trip["currency"]
        ):
            raise ValueError("Invalid allowance provenance")
        category = allowance["category"]
        if category not in REQUIRED - {"flight_total", "hotel_total"} or category in covered:
            raise ValueError("Overlapping allowance")
        covered.add(category)
        missing.discard(category)
        if category == "mandatory_fees":
            # Explicit user acceptance supplies a planning allowance, not a claim that fees were quoted.
            missing.discard("unconfirmed_provider_fees")
        lines.append(
            {
                "category": category,
                "amount": str(
                    money(allowance["amount"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                ),
                "evidence_id": allowance["id"],
                "basis": "user_whole_trip_allowance",
            }
        )
    subtotal = sum((Decimal(line["amount"]) for line in lines), Decimal(0))
    complete = not missing
    total = subtotal if complete else None
    over = subtotal > Decimal(trip["budget"])
    verdict = "over" if over else "fits" if complete else "unknown"
    return {
        "calculation_id": uuid4().hex,
        "state_hash": digest(trip),
        "input_hash": digest([ids, allowances]),
        "lines": lines,
        "currency": trip["currency"],
        "known_subtotal": str(subtotal) if lines else None,
        "total": str(total) if total is not None else None,
        "delta": str(Decimal(trip["budget"]) - total) if total is not None else None,
        "fits_budget": False if over else True if complete else None,
        "verdict": verdict,
        "budget_status": "over_budget" if over else verdict,
        "verdict_basis": "test_data"
        if environments & {"fixture", "test"}
        else "mixed_estimates"
        if complete
        else "incomplete",
        "missing": sorted(missing),
        "fx_evidence": list(fx.values()),
        "rounding_policy": "decimal-half-up-v1",
        "environment": "fixture" if "fixture" in environments else "live",
    }


def reconcile(trip, activities, records, ids):
    """Remove unusable travel days. Never invent flight, hotel or transfer timing."""
    selected = [records[i] for i in ids]
    flights = [r for r in selected if r.get("category") == "flight_total"]
    hotels = [r for r in selected if r.get("category") == "hotel_total"]
    issues, accepted, unavailable = [], [], set()
    if not flights or not hotels:
        issues.append("Selected flight/hotel logistics are unavailable")
    if len(flights) > 1 or len(hotels) > 1:
        raise ValueError("Choose one flight and one hotel")
    if flights:
        flight = flights[0]
        if not fresh(flight):
            issues.append("Selected flight expired")
            unavailable.update(trip_days(trip))
        else:
            arrival = datetime.fromisoformat(flight["arrival"])
            departure = datetime.fromisoformat(flight["departure"])
            # Provider segment datetimes are airport-local; convert offset-aware values to destination zone.
            from zoneinfo import ZoneInfo

            zone = ZoneInfo(CITIES[trip["destination"]][2])
            if arrival.tzinfo:
                arrival = arrival.astimezone(zone)
            if departure.tzinfo:
                departure = departure.astimezone(zone)
            if arrival.date().isoformat() != trip["start_date"]:
                issues.append(
                    "Flight violates the fixed destination arrival date; user clarification is required"
                )
            # Reserve entire arrival/departure days: no supported transfer duration is available.
            unavailable.update(
                d
                for d in trip_days(trip)
                if d <= arrival.date().isoformat() or d >= departure.date().isoformat()
            )
            issues.append(
                "Arrival and departure days are reserved for travel; transfer durations are unverified"
            )
            if hotels and hotels[0].get("check_in") != arrival.date().isoformat():
                issues.append(
                    "Hotel check-in differs from flight arrival; hotel repricing is required"
                )
            if arrival >= departure:
                unavailable.update(trip_days(trip))
    if hotels and (hotels[0].get("latitude") is None or hotels[0].get("longitude") is None):
        issues.append("Hotel location is unverified; local travel logistics remain provisional")
    for activity in activities:
        if activity.date.isoformat() not in unavailable:
            accepted.append(activity)
    return accepted, {
        "version": digest([trip, ids, [a.model_dump(mode="json") for a in accepted]]),
        "selected_offer_ids": ids,
        "travel_days": sorted(unavailable),
        "limitations": issues,
        "removed_claims": len(activities) - len(accepted),
        "compatible": bool(flights and hotels) and len(issues) == 1,
    }


def weather_days(trip, activities, records, ids):
    forecast, sources = {}, {}
    for eid in ids:
        record = records[eid]
        if record["kind"] != "weather" or not fresh(record, 21600):
            continue
        for day, value in record["daily"].items():
            if type(value) in (int, float) and 0 <= value <= 100:
                forecast[day], sources[day] = value, eid
    days = []
    for day in trip_days(trip):
        probability = forecast.get(day)
        planned = [a.model_dump(mode="json") for a in activities if a.date.isoformat() == day]
        conflicts = [
            {
                "activity_index": i,
                "conflict": None
                if probability is None or a["exposure"] == "unknown"
                else probability >= 60 and a["exposure"] == "outdoor",
                "evidence_id": sources.get(day),
                "policy": "rain-60-v1",
            }
            for i, a in enumerate(planned)
        ]
        days.append(
            {
                "date": day,
                "activities": planned,
                "rain_probability": probability,
                "weather": "unknown"
                if probability is None
                else "rain_risk"
                if probability >= 60
                else "low_rain_risk",
                "conflicts": conflicts,
                "weather_evidence_id": sources.get(day),
            }
        )
    return days
