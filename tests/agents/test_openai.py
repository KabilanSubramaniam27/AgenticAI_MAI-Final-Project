import asyncio
import json

import httpx2 as httpx
import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from pydantic import SecretStr

from tripradar_agents.config import Settings
from tripradar_agents.llm import create_model, run_agent
from tripradar_agents.observability import Trace
from tripradar_agents.security import Budget


def test_existing_openai_env_key_is_used(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-syntheticOpenAIKey123456")
    s = Settings(_env_file=None, provider="openai", mode="live")
    assert s.openai_api_key.get_secret_value() == "sk-syntheticOpenAIKey123456"
    assert s.readiness() == []
    assert s.input_usd_per_million == 2 and s.output_usd_per_million == 8
    assert create_model("orchestrator", s).model_name == "gpt-4.1"
    assert create_model("price_watcher", s).model_name == "gpt-4.1-mini"


def test_custom_models_require_explicit_rates():
    s = Settings(
        _env_file=None,
        provider="openai",
        model="custom-model",
        openai_api_key=SecretStr("sk-synthetic"),
    )
    assert "TRIPRADAR_AGENT_INPUT_USD_PER_MILLION" in s.readiness()


@pytest.mark.parametrize(
    "role,stage,expected",
    [
        ("orchestrator", "extract", {"facts": {}}),
        ("itinerary_builder", "specialist", {"activities": []}),
        ("price_watcher", "specialist", {"evidence_ids": []}),
        ("weather_risk", "specialist", {"evidence_ids": []}),
        ("grounding_verifier", "verify", {"supported": []}),
    ],
)
def test_provider_graph_uses_json_and_no_unapproved_tools(
    tmp_path, monkeypatch, role, stage, expected
):

    s = Settings(
        _env_file=None,
        provider="openai",
        mode="live",
        openai_api_key=SecretStr("sk-syntheticOpenAIKey123456"),
        input_usd_per_million=3,
        output_usd_per_million=15,
    )
    trace = Trace(tmp_path / "application.log")
    artifacts, requests = {}, []

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 1,
                "model": "gpt-4.1",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": json.dumps(expected)},
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )

    model = create_model(role, s)

    async def execute():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as transport:
            model.root_async_client._client = transport
            monkeypatch.setattr("tripradar_agents.llm.create_model", lambda *args: model)
            return await run_agent(
                role,
                {"stage": stage, "message": "Plan a trip"},
                s,
                Budget(s),
                trace,
                "test",
                artifacts,
            )

    assert asyncio.run(execute()) == expected
    assert requests[0]["model"] == model.model_name
    assert requests[0]["response_format"] == {"type": "json_object"}
    assert "strict" not in requests[0]
    assert "parallel_tool_calls" not in requests[0]
    assert not requests[0].get("tools")
    trace.close()
    assert "syntheticOpenAIKey" not in (tmp_path / "application.log").read_text()


def test_provider_planning_delegates_with_serial_tools(tmp_path, monkeypatch):
    settings = Settings(
        _env_file=None,
        provider="openai",
        mode="live",
        model="gpt-4o-mini",
        openai_api_key=SecretStr("sk-syntheticOpenAIKey123456"),
        input_usd_per_million=3,
        output_usd_per_million=15,
    )
    roles = ["itinerary_builder", "price_watcher", "weather_risk"]
    requests, delegated, artifacts = [], [], {}
    trace = Trace(tmp_path / "application.log")

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        completed = sum(m["role"] == "tool" for m in body["messages"])
        message = {"role": "assistant", "content": '{"done":true}'}
        if completed < len(roles):
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": f"call-{completed}",
                        "type": "function",
                        "function": {
                            "name": "task",
                            "arguments": json.dumps(
                                {
                                    "subagent_type": roles[completed],
                                    "description": "Use the application-bound trip.",
                                }
                            ),
                        },
                    }
                ],
            }
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 1,
                "model": "gpt-4o-mini",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls" if completed < len(roles) else "stop",
                        "message": message,
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )

    subagents = []
    for role in roles:

        async def specialist(state, role=role):
            delegated.append(role)
            return {"messages": [AIMessage(content="Specialist completed.")]}

        subagents.append(
            {
                "name": role,
                "description": f"Run {role} on the validated trip.",
                "runnable": RunnableLambda(specialist),
            }
        )
    model = create_model("orchestrator", settings)

    async def execute():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as transport:
            model.root_async_client._client = transport
            monkeypatch.setattr("tripradar_agents.llm.create_model", lambda *args: model)
            return await run_agent(
                "orchestrator",
                {"stage": "plan", "trip": {"city": "Lisbon"}},
                settings,
                Budget(settings),
                trace,
                "planning-test",
                artifacts,
                subagents=subagents,
            )

    try:
        assert asyncio.run(execute()) == {"done": True}
        assert delegated == roles
        assert len(requests) == 4
        for body in requests:
            assert body["response_format"] == {"type": "json_object"}
            assert body["parallel_tool_calls"] is False
            assert len(body["tools"]) == 1
            function = body["tools"][0]["function"]
            assert function["name"] == "task"
            assert function["strict"] is True
            params = function["parameters"]
            assert params["additionalProperties"] is False
            assert set(params["required"]) == set(params["properties"])
        assert all("output" in call for call in artifacts["model_calls"])
    finally:
        trace.close()


def test_shared_llm_settings_apply_to_all_roles(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "LLM_PROVIDER=openai\nLLM_MODEL=gpt-4o-mini\n"
        "LLM_BASE_URL=https://api.openai.com/v1\nOPENAI_API_KEY=sk-synthetic\n"
    )
    s = Settings(_env_file=env)
    assert s.provider == "openai"
    assert s.model == s.specialist_model == "gpt-4o-mini"
    assert s.readiness() == []
    assert s.input_usd_per_million == 0.15
    assert s.output_usd_per_million == 0.60
    for role in (
        "orchestrator",
        "grounding_verifier",
        "itinerary_builder",
        "price_watcher",
        "weather_risk",
    ):
        model = create_model(role, s)
        assert model.model_name == "gpt-4o-mini"
        assert str(model.root_async_client.base_url).rstrip("/") == s.base_url


def test_role_overrides_win_without_overriding_shared_specialist_model(tmp_path):
    env = tmp_path / ".env"
    env.write_text("LLM_PROVIDER=openai\nLLM_MODEL=gpt-4o-mini\nTRIPRADAR_AGENT_MODEL=gpt-4.1\n")
    s = Settings(_env_file=env)
    assert s.model == "gpt-4.1"
    assert s.specialist_model == "gpt-4o-mini"
    assert s.input_usd_per_million == 2
    env.write_text(env.read_text() + "TRIPRADAR_AGENT_SPECIALIST_MODEL=gpt-4.1-mini\n")
    assert Settings(_env_file=env).specialist_model == "gpt-4.1-mini"


def test_custom_base_url_does_not_assume_openai_prices():
    s = Settings(_env_file=None, base_url="https://proxy.example/v1", model="gpt-4o-mini")
    assert "TRIPRADAR_AGENT_INPUT_USD_PER_MILLION" in s.readiness()
    model = create_model(
        "orchestrator", s.model_copy(update={"openai_api_key": SecretStr("synthetic")})
    )
    assert str(model.root_async_client.base_url) == "https://proxy.example/v1/"


def test_non_openai_provider_is_rejected():
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="provider"):
        Settings(_env_file=None, provider="anthropic")
