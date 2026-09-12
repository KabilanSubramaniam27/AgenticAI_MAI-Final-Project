"""Explicit startup account/model probes; never log keys or provider error bodies."""

import asyncio

from .llm import create_model


async def probe_models(settings, trace):
    if settings.mode == "fixture":
        return {"status": "fixture", "models": {}}
    if settings.readiness():
        return {"status": "configuration_incomplete", "models": {}}
    results = {}
    for role in ("orchestrator", "itinerary_builder"):
        name = settings.model if role == "orchestrator" else settings.specialist_model
        if name in results:
            continue
        model = create_model(role, settings)
        try:
            # Read-only model visibility, not a paid completion or a proof of answer quality.
            reply = await asyncio.wait_for(
                model.root_async_client.models.retrieve(model.model_name), 5
            )
            results[model.model_name] = "available" if reply.id else "unconfirmed"
        except Exception as exc:
            results[model.model_name] = type(exc).__name__
        finally:
            await model.root_async_client.close()
            model.root_client.close()
        trace.event(
            "provider.model_probe", model=model.model_name, status=results[model.model_name]
        )
    return {
        "status": "available" if all(v == "available" for v in results.values()) else "unavailable",
        "models": results,
    }
