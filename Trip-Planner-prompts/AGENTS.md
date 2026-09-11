# TripRadar — Models & Agent API Contract

Reference for the team split: which model each agent uses, what API/tool it calls, what that API returns, and what the agent is responsible for doing with it. Use this as the starting contract for Day 1's prompt-writing.

## Implemented ingestion boundary

Destination retrieval is implemented in the parent project's `src/tripradar_ingestion/`. The initial city registry is Lisbon, Paris, London, and New York City. Chroma's local default MiniLM embedding function produces 384-dimensional vectors; the validated persistent index is also Chroma. `search_guide` returns revision-linked source passages and attribution. See [README](../README.md) for commands. Agents and MCP wrappers described below remain future work.

## Model Choice

One provider, two tiers — avoids multi-provider complexity on a 2-day build.

| Tier | Model | Used by | Why |
|---|---|---|---|
| Fast/cheap | **Claude Haiku 4.5** (`claude-haiku-4-5-20251001`) | Itinerary-Builder, Price-Watcher, Weather-Risk-Agent | Mostly "call a tool, format/summarize the result" — no deep multi-step reasoning needed, so the cheapest capable model keeps iteration fast |
| Stronger reasoning | **Claude Sonnet 5** (`claude-sonnet-5`) | Trip-Planner | The only agent doing real multi-step reasoning (reconciling 3 agents' outputs, deciding budget trade-offs) — worth the stronger model since a bad trim decision is the most visible failure mode in a demo |

**Alternatives**, if the team already has credits elsewhere: `gpt-4o-mini` / `gemini-2.0-flash` for the fast tier, `gpt-4.1` / `gemini-2.5-pro` for Trip-Planner. For zero LLM cost (not just zero data cost), run locally via Ollama with `qwen2.5:7b` (fast tier) and `qwen2.5:32b` or `llama3.1:70b` (Trip-Planner) — adds local-hardware variance across machines, so only worth it if API cost is a hard blocker.

---

## Per-Agent API Contract

| Agent | Model | MCP Tool Called | What the API Returns | What the Agent Must Do |
|---|---|---|---|---|
| **Itinerary-Builder** | Haiku 4.5 | `destination-search` → `search_guide(destination, section, query)` (queries the Chroma index) | Top-k Wikivoyage text chunks + metadata (section, source, revision date) | Synthesize a day-by-day plan **only** from retrieved chunks, cite the section per day, explicitly state "not covered in the guide" rather than inventing when nothing relevant comes back |
| **Price-Watcher** | Haiku 4.5 | `flight-hotel-pricing` → `search_flights(origin, dest, dates)` / `search_hotels(dest, dates)` (wraps Amadeus Flight Offers Search + Hotel Search) | Raw JSON: carriers, prices, durations, stops / hotel names, price-per-night, ratings | Pick the best 1–2 reasonable options (not blindly cheapest — flag a 2-stop red-eye), return a structured object `{flight_cost, hotel_cost, currency, details}` |
| **Weather-Risk-Agent** | Haiku 4.5 | `weather` → `get_forecast(location, date_range)` (wraps Open-Meteo) | Daily precip probability, temp, weather code per date | Cross-reference against the itinerary's planned activities, output a structured flag list: `{day, conflict: bool, reason}` |
| **Trip-Planner** | Sonnet 5 | `currency` → `convert(amount, from, to)` (wraps Frankfurter); also invokes the other three agents as sub-calls | ECB exchange rate; the three agents' structured outputs | Convert all costs to the user's home currency, total against budget, decide what to trim if over budget (hotel tier before a paid attraction), output final itinerary text **and** a structured verdict `{fits_budget: bool, total, delta}` |

---

## Prompting Rules (apply to every agent)

1. **Structured output, not prose, for anything Trip-Planner has to consume.** Price-Watcher, Weather-Risk-Agent, and Itinerary-Builder should return JSON (or a rigid template), not free-flowing text — loose language is exactly where a 2-day integration breaks on Day 2.
2. **Grounding rule for Itinerary-Builder specifically:** only use retrieved content; say so explicitly when nothing relevant was found. This is the project's one RAG-faithfulness guarantee — state it plainly in the system prompt.
3. **Trip-Planner's trim policy must be explicit in the prompt** — don't leave "what to cut when over budget" to the model's judgment alone; give it an ordered preference (e.g., downgrade hotel tier → reduce trip length → flag as infeasible) so its behavior is predictable and demoable.

---

## Shared Trip-Request Schema (lock this on Day 1)

```json
{
  "destination": "Lisbon",
  "start_date": "2026-10-10",
  "end_date": "2026-10-20",
  "budget": 2000,
  "budget_currency": "USD",
  "interests": ["food", "history", "hiking"]
}
```

Every agent should consume/produce fields consistent with this shape — agree on it in the Day 1 kickoff before anyone writes code.
