import json
import os
import sys
import time
from contextlib import AsyncExitStack
from datetime import timedelta

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .config import ROOT
from .security import GuardrailError

ALLOW = {
    "itinerary_builder": {"destination": "search_guide"},
    "price_watcher": {"pricing": "search_prices"},
    "weather_risk": {"weather": "get_forecast"},
    "orchestrator": {"currency": "calculate_budget"},
}


async def call_mcp(role, domain, arguments, context, budget, trace, rid):
    name = ALLOW.get(role, {}).get(domain)
    if not name:
        raise GuardrailError("MCP capability denied")
    budget.check()
    remaining_reads = budget.settings.max_reads - budget.reads
    if remaining_reads <= 0:
        raise GuardrailError("Tool budget exhausted")
    trace.event(
        "tool.start", request_id=rid, agent=role, domain=domain, tool=name, arguments=arguments
    )
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(ROOT / "src"),
        "TRIPRADAR_MCP_CONTEXT": json.dumps(
            {
                **context,
                "read_limit": remaining_reads,
                "deadline": budget.started + budget.settings.deadline_seconds,
            }
        ),
        # Suppress raw framework/LangSmith tracing in domain subprocesses.
        "LANGSMITH_TRACING": "false",
        "LANGCHAIN_TRACING_V2": "false",
    }
    # Explicit environment overrides, without copying all host secrets into children.
    for key, value in os.environ.items():
        if key.startswith(
            ("CHROMA_", "TRIPRADAR_AGENT_CHROMA_", "AMADEUS_", "TRIPRADAR_AGENT_AMADEUS_")
        ):
            env[key] = value
    accounted = False
    try:
        async with AsyncExitStack() as stack:
            read, write = await stack.enter_async_context(
                stdio_client(
                    StdioServerParameters(
                        command=sys.executable,
                        args=["-m", "tripradar_agents.mcp_server", domain],
                        env=env,
                        cwd=str(ROOT),
                    )
                )
            )
            session = await stack.enter_async_context(
                ClientSession(
                    read,
                    write,
                    read_timeout_seconds=timedelta(
                        seconds=max(
                            1,
                            budget.settings.deadline_seconds - (time.monotonic() - budget.started),
                        )
                    ),
                )
            )
            await session.initialize()
            catalog = await session.list_tools()
            if {t.name for t in catalog.tools} != {name}:
                raise GuardrailError("Unexpected MCP tool catalog")
            response = await session.call_tool(name, arguments)
            if response.isError:
                raise GuardrailError("MCP domain returned an error")
            structured = response.structuredContent
            if structured is None:
                structured = json.loads(
                    "".join(c.text for c in response.content if c.type == "text")
                )
            if isinstance(structured, dict) and set(structured) == {"result"}:
                structured = structured["result"]
            if isinstance(structured, dict) and "read_attempts" in structured:
                attempts = structured["read_attempts"]
                if type(attempts) is not int or not 0 <= attempts <= remaining_reads:
                    raise GuardrailError("Invalid MCP usage")
                budget.reads += attempts
                accounted = True
                for event in structured.get("provider_events", []):
                    trace.event("provider.read", request_id=rid, agent=role, domain=domain, **event)
                if structured.get("error"):
                    raise GuardrailError("MCP provider unavailable: " + structured["error"])
                structured = structured["payload"]
            else:
                budget.read()
                accounted = True
            trace.event(
                "tool.end",
                request_id=rid,
                agent=role,
                tool=name,
                evidence_ids=[r.get("id") for r in structured]
                if isinstance(structured, list)
                else [],
            )
            if domain == "destination":
                trace.event(
                    "rag.end",
                    agent=role,
                    request_id=rid,
                    query=arguments["query"],
                    evidence_ids=[r["id"] for r in structured],
                )
            return structured
    except Exception:
        if not accounted:
            # A broken transport leaves remote attempt usage unknown; retain the full reservation.
            budget.reads = budget.settings.max_reads
        trace.event("tool.error", request_id=rid, agent=role, tool=name)
        raise
