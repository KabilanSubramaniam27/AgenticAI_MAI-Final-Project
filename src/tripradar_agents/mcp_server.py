"""Four isolated stdio MCP domain servers. No synthetic writes to Chroma."""

import json
import os
import sys
from datetime import UTC, datetime
from uuid import uuid4

from mcp.server.fastmcp import FastMCP

from .config import ROOT, Settings
from .ledger import calculate
from .models import CITIES, TripFields, trip_days
from .providers import Reader, amadeus_prices


def guide_records(trip, mode, query):
    count = min(12, max(5, len(trip_days(trip))))
    if mode == "fixture":
        records = json.loads((ROOT / "evals/fixtures/guides/passages.json").read_text())
        rows = [
            {"text": r["text"], **r["metadata"]}
            for r in records.values()
            if r["metadata"]["destination_id"] == CITIES[trip["destination"]][3]
        ]
    else:
        from tripradar_ingestion.config import Settings as IngestionSettings
        from tripradar_ingestion.embeddings import LocalEmbedder

        settings = Settings()
        if settings.chroma_backend == "local":
            from tripradar_ingestion.retrieval import search_guide

            rows = search_guide(trip["destination"], query=query, k=count)
        else:
            import chromadb
            from dotenv import dotenv_values

            env = {**dotenv_values(ROOT / ".env"), **os.environ}
            client = chromadb.CloudClient(
                api_key=env["CHROMA_API_KEY"],
                tenant=env["CHROMA_TENANT"],
                database=env["CHROMA_DATABASE"],
            )
            collection = client.get_collection(settings.chroma_collection, embedding_function=None)
            if collection.metadata.get("dimension") != 384:
                raise ValueError("Incompatible Cloud embedding dimension")
            embedder = LocalEmbedder(IngestionSettings.load())
            result = collection.query(
                query_embeddings=embedder.encode([query]),
                n_results=count,
                where={"destination_id": CITIES[trip["destination"]][3]},
                include=["documents", "metadatas"],
            )
            rows = [
                {"text": text, **meta}
                for text, meta in zip(result["documents"][0], result["metadatas"][0], strict=True)
            ]
    return [
        {
            "id": r["chunk_id"],
            "kind": "guide",
            "destination": trip["destination"],
            "text": r["text"],
            "url": r["revision_url"],
            "environment": mode,
            "attribution": r.get("attribution", "Wikivoyage contributors"),
            "license": r.get("license", "CC-BY-SA-4.0"),
            "revision_time": r.get("revision_time"),
            "retrieved_at": r.get("retrieved_at"),
        }
        for r in rows
    ]


def prices(trip, mode, reader=None, hotel_dates=None):
    if mode != "fixture":
        own = reader is None
        reader = reader or Reader()
        try:
            return amadeus_prices(trip, Settings(), reader, hotel_dates)
        finally:
            if own:
                reader.close()
    return [
        {
            "id": "fixture-price",
            "kind": "price",
            "environment": "fixture",
            "destination": trip["destination"],
            "trip": trip,
            "currency": trip["currency"],
            "flight_total": "600.00",
            "hotel_total": "900.00",
            "price_basis": "whole_party_whole_stay",
            "taxes_known": True,
            "retrieved_at": datetime.now(UTC).isoformat(),
            "reason": "Synthetic plumbing example, not an actual offer; excludes daily spending",
        }
    ]


def forecast(trip, mode, reader=None):
    base = {
        "id": uuid4().hex,
        "kind": "weather",
        "destination": trip["destination"],
        "environment": mode,
        "retrieved_at": datetime.now(UTC).isoformat(),
    }
    days = trip_days(trip)
    if mode == "fixture":
        return [
            {
                **base,
                "daily": {d: 70 if i == 1 else 10 for i, d in enumerate(days)},
                "reason": "Synthetic forecast for plumbing tests",
            }
        ]
    lat, lon, zone, _ = CITIES[trip["destination"]]
    own = reader is None
    reader = reader or Reader()
    try:
        data = reader.request(
            "GET",
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "timezone": zone,
                "forecast_days": 16,
                "daily": "precipitation_probability_max",
            },
        )["daily"]
    finally:
        if own:
            reader.close()
    # Exact requested dates only. Never shift an out-of-horizon trip to today's forecast.
    return [
        {
            **base,
            "daily": {
                d: value
                for d, value in zip(
                    data["time"], data["precipitation_probability_max"], strict=True
                )
                if d in days
            },
            "url": "https://open-meteo.com/",
            "reason": "Rain risk only; not official alerts",
        }
    ]


def serve(domain):
    # Bootstrap is application-owned, never accepted from an LLM tool argument.
    context = json.loads(os.environ["TRIPRADAR_MCP_CONTEXT"])
    trip = TripFields.model_validate(context["trip"]).model_dump(mode="json", exclude_none=True)
    mode = context["mode"]
    server = FastMCP("tripradar-" + domain, log_level="ERROR")

    def invoke(function):
        reader = Reader(limit=context.get("read_limit", 20), deadline=context.get("deadline"))
        try:
            result = function(reader)
            return {
                "payload": result,
                "read_attempts": max(1, reader.attempts),
                "provider_events": reader.events,
                "error": None,
            }
        except Exception as exc:
            return {
                "payload": None,
                "read_attempts": max(1, reader.attempts),
                "provider_events": reader.events,
                "error": type(exc).__name__,
            }
        finally:
            reader.close()

    if domain == "destination":

        @server.tool()
        def search_guide(query: str) -> dict:
            """Return source passages for the application-bound destination."""
            if not 1 <= len(query) <= 500:
                raise ValueError("Invalid query")
            return invoke(lambda reader: guide_records(trip, mode, query))
    elif domain == "pricing":

        @server.tool()
        def search_prices() -> dict:
            """Return compatible pricing evidence, or explicit unavailable evidence."""
            return invoke(lambda reader: prices(trip, mode, reader, context.get("hotel_dates")))
    elif domain == "weather":

        @server.tool()
        def get_forecast() -> dict:
            """Return date-aligned rain probabilities, leaving uncovered dates unknown."""
            return invoke(lambda reader: forecast(trip, mode, reader))
    elif domain == "currency":

        @server.tool()
        def calculate_budget(evidence_ids: list[str]) -> dict:
            """Resolve offer amounts by ID from the application-owned evidence snapshot."""
            return invoke(
                lambda reader: calculate(
                    trip,
                    context.get("evidence", {}),
                    evidence_ids,
                    context.get("allowances", []),
                    reader,
                )
            )
    else:
        raise ValueError("Unsupported MCP domain")
    server.run(transport="stdio")


if __name__ == "__main__":
    serve(sys.argv[1])
