# TripRadar — Technical Implementation Guide

Concrete build reference: tech stack, repo layout, exact API endpoints/auth per data source, the MCP tool each one is wrapped in, and the agent call pattern. Pairs with [AGENTS.md](AGENTS.md) (models + prompting contract) and [TRIPRADAR.md](TRIPRADAR.md) (project spec).

## Tech Stack

| Layer | Choice | Notes |
|---|---|---|
| Language | Python 3.11+ | |
| LLM calls | Anthropic Messages API | Haiku 4.5 for 3 agents, Sonnet 5 for Trip-Planner — see AGENTS.md |
| Tool layer | MCP Python SDK | One server per external boundary |
| Vector DB | Chroma (local, embedded) | Zero setup, no server to run |
| Embeddings | `sentence-transformers/all-MiniLM-L6-v2` (local, free) | Swap for Voyage AI (`voyage-3-lite`) later if retrieval quality needs improvement — has a free tier |

## Repo Structure

The implemented ingestion package lives directly under the parent project, not under this reference-document folder. See [README](../README.md), the [ingestion plan](../prompts/DataIngestion.md), and [validation results](../docs/validation.md).

```text
AgenticAI_MAI-Final-Project/
  src/tripradar_ingestion/       # implemented Python ingestion and retrieval package
  config/                       # Lisbon, Paris, London, New York City and settings
  data/                         # raw revisions, sections, chunks, vectors, manifests
  tests/
  docs/
  prompts/DataIngestion.md
  Trip-Planner-prompts/          # these future application/agent reference documents
  pyproject.toml
  uv.lock
```

Future agent/MCP packages also belong under the parent `src/` directory and are not implemented by the ingestion work.

---

## API Details Per MCP Server

### 1. `destination-search` — Wikivoyage

**Ingestion (one-time, offline):**
```
GET https://en.wikivoyage.org/w/api.php?action=parse&page=Lisbon&format=json&prop=wikitext
```
No auth, no key. Returns raw wikitext for the page — parse into sections by header (`== See ==`, `== Do ==`, `== Eat ==`, etc.), strip templates/infobox markup, keep prose.

**MCP tool exposed:**
```
search_guide(destination: str, section: str | None, query: str, k: int = 5)
```
Embeds `query`, runs similarity search against the Chroma collection filtered by `destination` (and `section` if given).

**Returns:**
```json
[{ "text": "...", "section": "Do", "source_url": "https://en.wikivoyage.org/wiki/Lisbon", "score": 0.83 }]
```

---

### 2. `flight-hotel-pricing` — Amadeus (Self-Service test tier)

**Auth (OAuth2 client-credentials):**
```
POST https://test.api.amadeus.com/v1/security/oauth2/token
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials&client_id=<AMADEUS_CLIENT_ID>&client_secret=<AMADEUS_CLIENT_SECRET>
```
Returns a bearer token valid ~30 minutes.

**Flight Offers Search:**
```
GET https://test.api.amadeus.com/v2/shopping/flight-offers
    ?originLocationCode=JFK&destinationLocationCode=LIS
    &departureDate=2026-10-10&returnDate=2026-10-20&adults=1&max=5
Authorization: Bearer <token>
```
Returns an array of flight offers: price, itineraries, segments, carrier, stops.

**Hotel Search (two-step):**
```
GET https://test.api.amadeus.com/v1/reference-data/locations/hotels/by-city?cityCode=LIS
GET https://test.api.amadeus.com/v3/shopping/hotel-offers?hotelIds=<ids>&checkInDate=...&checkOutDate=...
```

**MCP tools exposed:**
```
search_flights(origin, destination, depart_date, return_date) -> { price, currency, carrier, stops, duration }
search_hotels(destination, check_in, check_out) -> { name, price_per_night, currency, rating }
```

---

### 3. `weather` — Open-Meteo

No auth.

**Geocoding (destination name → lat/long), or hardcode a small lookup table for Lisbon/Porto/Athens:**
```
GET https://geocoding-api.open-meteo.com/v1/search?name=Lisbon
```

**Forecast:**
```
GET https://api.open-meteo.com/v1/forecast
    ?latitude=38.72&longitude=-9.14
    &daily=precipitation_probability_max,temperature_2m_max,weathercode
    &timezone=auto&start_date=2026-10-10&end_date=2026-10-20
```

**MCP tool exposed:**
```
get_forecast(location, start_date, end_date) -> [{ date, precip_probability, temp_max, condition }]
```

---

### 4. `currency` — Frankfurter.app

No auth.

```
GET https://api.frankfurter.app/latest?amount=100&from=USD&to=EUR
```

**MCP tool exposed:**
```
convert(amount, from_currency, to_currency) -> { converted_amount, rate, date }
```

---

## Agent Call Pattern

Each agent is a Claude Messages API call with its relevant MCP tool(s) registered as `tools`:

```python
response = client.messages.create(
    model="claude-haiku-4-5-20251001",
    system=ITINERARY_BUILDER_SYSTEM_PROMPT,
    messages=[{"role": "user", "content": trip_request_json}],
    tools=[destination_search_tool_schema],
)
```

**Trip-Planner** additionally orchestrates the other three agents as direct function calls (`itinerary_builder.run(...)`, `price_watcher.run(...)`, `weather_risk.run(...)`) rather than exposing them as Messages API tools — simpler to debug for a 2-day build. It then makes its own Sonnet 5 call with the `currency` tool registered, for the final reconciliation step.

---

## Environment Variables (`.env.example`)

```
ANTHROPIC_API_KEY=
AMADEUS_CLIENT_ID=
AMADEUS_CLIENT_SECRET=
```

Wikivoyage, Open-Meteo, and Frankfurter need no keys.

---

## Implemented destination ingestion

The configured destinations are Lisbon, Paris, London, and New York City, with bounded district/borough discovery. `tripradar-ingest ingest --all` collects revision-pinned Wikivoyage content, preserves listing templates as structured records, cleans/normalizes sections, creates token-limited chunks, calls Chroma's local default MiniLM embedding function (384 dimensions), and publishes a validated persistent Chroma snapshot. Long sections are split to prevent truncation; blindly removing all templates is not the implemented parser behavior.

Run `tripradar-ingest setup-model` once before embedding. Collection uses the public API; the local model and vector store need no API credentials. Optional LangSmith tracing requires `LANGSMITH_*` settings. Ingestion-specific overrides are prefixed `TRIPRADAR_` to coexist with existing agent settings.

The Python retrieval function `tripradar_ingestion.retrieval.search_guide(destination, section, query, k)` is ready for later MCP wrapping. Results include exact passage text, revision/history links, section, stable IDs, timestamps, license/attribution, and clearly labeled cosine distance/similarity. An empty result is a coverage gap. Live prices and forecasts remain outside the corpus.
