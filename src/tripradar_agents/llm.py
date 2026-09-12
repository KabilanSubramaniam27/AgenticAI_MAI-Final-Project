"""Every model dispatch goes through deterministic context/tool/budget checks."""

import asyncio
import json
import time
from uuid import uuid4

from deepagents import create_deep_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from .config import ROOT
from .security import GuardrailError, checked_text, digest, redact


def prompt(role):
    return (
        (ROOT / "config/prompts/common_policy.md").read_text()
        + "\n"
        + (ROOT / f"config/prompts/{role}.md").read_text()
    )


class FixtureModel(BaseChatModel):
    """Explicit scripted model for protocol tests, never a substitute for a live model."""

    role: str

    @property
    def _llm_type(self):
        return "tripradar-scripted-fixture"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        context = json.loads(
            next(m.content for m in reversed(messages) if isinstance(m, HumanMessage))
        )
        if context["stage"] == "extract":
            value = {"facts": {}}
        elif self.role == "orchestrator":
            completed = sum(isinstance(m, ToolMessage) for m in messages)
            roles = ["itinerary_builder", "price_watcher", "weather_risk"]
            if completed < len(roles):
                return ChatResult(
                    generations=[
                        ChatGeneration(
                            message=AIMessage(
                                content="",
                                tool_calls=[
                                    {
                                        "name": "task",
                                        "args": {
                                            "subagent_type": roles[completed],
                                            "description": "Use the application-bound trip.",
                                        },
                                        "id": uuid4().hex,
                                        "type": "tool_call",
                                    }
                                ],
                            )
                        )
                    ]
                )
            value = {"done": True}
        elif self.role == "itinerary_builder":
            from .models import trip_days

            rows = context["evidence"]
            value = {"activities": []}
            if rows:
                quote = rows[0]["text"].split("\n")[0][:300]
                value["activities"] = [
                    {
                        "date": trip_days(context["trip"])[0],
                        "claim": quote,
                        "quote": quote,
                        "evidence_id": rows[0]["id"],
                    }
                ]
        elif self.role == "grounding_verifier":
            if "claims" in context:
                value = {
                    "results": [
                        {
                            "claim_id": c["claim_id"],
                            "claim_hash": c["claim_hash"],
                            "source_hash": c["source_hash"],
                            "status": "supported"
                            if c["activity"]["claim"] == c["activity"]["quote"]
                            else "insufficient_evidence",
                            "quote": c["activity"]["quote"],
                            "reason": "Scripted exact-copy fixture check",
                        }
                        for c in context["claims"]
                    ]
                }
            else:
                value = {
                    "supported": [
                        i for i, a in enumerate(context["activities"]) if a["claim"] == a["quote"]
                    ]
                }
        else:
            value = {
                "evidence_ids": [
                    r["id"] for r in context["evidence"] if r["kind"] in ("price", "weather")
                ]
            }
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=json.dumps(value)))]
        )


class Boundary(AgentMiddleware):
    def __init__(self, role, budget, trace, rid, artifacts, allowed, system):
        self.role, self.budget, self.trace = role, budget, trace
        self.rid, self.artifacts, self.allowed, self.system = rid, artifacts, allowed, system

    async def awrap_model_call(self, request, handler):
        # Remove all DeepAgents default filesystem/shell/planning/general-purpose capabilities.
        tools = [t for t in request.tools if getattr(t, "name", None) in self.allowed]
        model_settings = dict(request.model_settings)
        if tools and request.model._llm_type == "openai-chat":
            # JSON-mode parsing in the OpenAI SDK requires strict function tools.
            # Preserve the executable tools; LangChain applies strict schemas when binding.
            model_settings.update(strict=True, parallel_tool_calls=False)
        messages = []
        for message in request.messages:
            if isinstance(message, SystemMessage):
                raise GuardrailError("Unexpected system role in conversational context")
            content = message.content
            if isinstance(content, str):
                content = checked_text(content, 40000)
            else:
                content = redact(content)
            messages.append(message.model_copy(update={"content": content}))
        payload = {
            "system": self.system,
            "messages": [m.model_dump() for m in messages],
            "tools": [{"name": t.name, "schema": t.args} for t in tools],
            "model_settings": model_settings,
        }
        self.budget.model(json.dumps(payload), max_output=output_limit(self.role))
        call_id = uuid4().hex
        item = {
            "id": call_id,
            "agent": self.role,
            "model": getattr(request.model, "model_name", request.model._llm_type),
            "input": redact(payload),
            "prompt_hash": digest(self.system),
        }
        self.artifacts.setdefault("model_calls", []).append(item)
        self.trace.event(
            "llm.input", request_id=self.rid, call_id=call_id, agent=self.role, **payload
        )
        try:
            dispatched = time.monotonic()
            for attempt in range(2):
                try:
                    result = await asyncio.wait_for(
                        handler(
                            request.override(
                                messages=messages,
                                tools=tools,
                                system_message=SystemMessage(self.system),
                                model_settings=model_settings,
                            )
                        ),
                        min(
                            45,
                            max(
                                0.001,
                                self.budget.settings.deadline_seconds
                                - (time.monotonic() - self.budget.started),
                            ),
                        ),
                    )
                    break
                except Exception as exc:
                    transient = getattr(exc, "status_code", None) in {
                        429,
                        500,
                        502,
                        503,
                        504,
                    } or type(exc).__name__ in {"APIConnectionError", "APITimeoutError"}
                    if attempt or not transient:
                        raise
                    self.budget.model(json.dumps(payload), max_output=output_limit(self.role))
                    item["transport_retry"] = type(exc).__name__
                    self.trace.event(
                        "llm.retry",
                        request_id=self.rid,
                        call_id=call_id,
                        agent=self.role,
                        attempt=2,
                    )
            item["latency_ms"] = round((time.monotonic() - dispatched) * 1000)
            output = [m.model_dump() for m in result.result]
            item["usage"] = [getattr(m, "usage_metadata", None) for m in result.result]
            item["output"] = redact(output)
            self.trace.event(
                "llm.output", request_id=self.rid, call_id=call_id, agent=self.role, output=output
            )
            for message in result.result:
                for call in getattr(message, "tool_calls", []):
                    self.check_tool(call)
            return result
        except BaseException as exc:
            item["error"] = type(exc).__name__
            self.trace.event(
                "llm.error",
                request_id=self.rid,
                call_id=call_id,
                agent=self.role,
                error=type(exc).__name__,
            )
            raise

    def check_tool(self, call):
        if call["name"] not in self.allowed:
            raise GuardrailError("Tool not allowed for this stage")
        if call["name"] == "task" and call["args"].get("subagent_type") not in {
            "itinerary_builder",
            "price_watcher",
            "weather_risk",
        }:
            raise GuardrailError("Specialist not allowed")

    async def awrap_tool_call(self, request, handler):
        self.check_tool(request.tool_call)
        return await handler(request)


def output_limit(role):
    return (
        4000
        if role in {"itinerary_builder", "repair"}
        else 3000
        if role == "grounding_verifier"
        else 1000
    )


def create_model(role, settings):
    if settings.mode == "fixture":
        return FixtureModel(role=role)
    model_id = (
        settings.model
        if role in {"orchestrator", "grounding_verifier", "judge"}
        else settings.specialist_model
    )
    common = {
        "model": model_id,
        "temperature": 0,
        "max_tokens": output_limit(role),
        "max_retries": 0,
        "timeout": 45,
    }
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        api_key=settings.openai_api_key.get_secret_value(),
        base_url=settings.base_url,
        model_kwargs={"response_format": {"type": "json_object"}},
        **common,
    )


async def run_agent(role, context, settings, budget, trace, rid, artifacts, subagents=None):
    # Raw framework tracing stays disabled; Trace exports sanitized spans explicitly.
    # This context prevents inherited environment tracing from leaking model payloads.
    from langsmith import tracing_context

    model = create_model(role, settings)
    system = prompt(role)
    boundary = Boundary(
        role, budget, trace, rid, artifacts, {"task"} if subagents else set(), system
    )
    agent = create_deep_agent(
        model=model,
        system_prompt=system,
        subagents=subagents or [],
        middleware=[boundary],
        name=role,
    )
    with tracing_context(enabled=False):
        result = await agent.ainvoke(
            {"messages": [HumanMessage(json.dumps(context))]}, config={"recursion_limit": 20}
        )
    content = result["messages"][-1].content
    if isinstance(content, list):
        content = "".join(b.get("text", "") for b in content if isinstance(b, dict))
    return json.loads(content)
