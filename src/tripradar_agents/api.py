import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from .config import Settings
from .diagnostics import probe_models
from .models import ChatRequest
from .observability import Trace
from .runtime import Runtime
from .security import GuardrailError, checked_text
from .store import Store
from .tracking import profile, work


def create_app(settings=None):
    settings = settings or Settings()
    judge_problem = None
    try:
        judge_profile = profile(settings)
    except (ValueError, OSError, KeyError) as exc:
        judge_profile = None
        judge_problem = type(exc).__name__
    store = Store(settings.database, judge_profile)
    trace = Trace(settings.database.parent / "logs/application.log", settings)
    runtime = Runtime(settings, trace)
    probes = {"status": "not_run"}
    tasks = set()
    semaphore = asyncio.Semaphore(2)

    @asynccontextmanager
    async def lifespan(app):
        store.restart()
        if settings.startup_model_probes:
            probes.update(await probe_models(settings, trace))
        if judge_profile:
            tasks.add(asyncio.create_task(work(store, settings, trace)))
        yield
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        trace.close()

    app = FastAPI(title="TripRadar", lifespan=lifespan)
    app.state.store, app.state.runtime = store, runtime

    @app.middleware("http")
    async def bounds(request: Request, call_next):
        if request.method == "POST":
            body = bytearray()
            async for piece in request.stream():
                body.extend(piece)
                if len(body) > 64000:
                    return JSONResponse({"detail": "Request body too large"}, status_code=413)
            request._body = bytes(body)
        return await call_next(request)

    @app.exception_handler(PermissionError)
    async def unauthorized(request, exc):
        return JSONResponse({"detail": "Session unavailable"}, status_code=403)

    @app.exception_handler(LookupError)
    async def missing(request, exc):
        return JSONResponse({"detail": "Request unavailable"}, status_code=404)

    @app.get("/health")
    async def health():
        return {"status": "ok", "environment": settings.mode}

    @app.get("/ready")
    async def ready():
        problems = settings.readiness()
        if probes["status"] == "unavailable":
            problems.append("OPENAI_MODEL_ACCESS")
        return JSONResponse(
            {
                "ready": not problems,
                "missing_settings": problems,
                "environment": settings.mode,
                "pricing": "fixture"
                if settings.mode == "fixture"
                else settings.amadeus_environment + "_configured_unverified"
                if settings.amadeus_client_id.get_secret_value()
                and settings.amadeus_client_secret.get_secret_value()
                else "credentials_missing",
                "scope": "provisional itinerary slice",
                "langsmith": trace.telemetry,
                "background_judge": "accepted_enabled"
                if judge_profile
                else "blocked_invalid_acceptance"
                if judge_problem
                else "disabled_pending_acceptance",
                "provider": settings.provider,
                "model_probes": probes,
                "model": settings.model,
                "specialist_model": settings.specialist_model,
            },
            status_code=503 if problems else 200,
        )

    @app.post("/sessions")
    async def session():
        return store.session()

    @app.get("/sessions/{sid}")
    async def history(sid: str, authorization: str = Header()):
        result = store.history(sid, authorization)
        return {"messages": result["messages"], "trip": result["trip"]}

    @app.delete("/sessions/{sid}")
    async def delete(sid: str, authorization: str = Header()):
        store.delete(sid, authorization)
        return {"deleted": True}

    @app.get("/requests/{rid}")
    async def result(rid: str, authorization: str = Header()):
        return store.get(rid, authorization)

    async def execute(rid, payload, token):
        artifacts = {}
        trace.begin(rid, payload)
        terminal = {"status": "interrupted"}
        error = None
        try:
            await asyncio.wait_for(semaphore.acquire(), timeout=30)
            try:
                if not store.start(rid):
                    return
                session = store.history(payload["thread_id"], token)
                payload["_prior_allowances"] = session.get("allowances", [])
                response, trip = await runtime.run(
                    rid, payload, session["model_history"], session["trip"], artifacts
                )
                if store.finish(rid, response, artifacts, trip):
                    terminal = response
            finally:
                semaphore.release()
        except asyncio.CancelledError:
            error = "CancelledError"
            store.finish(
                rid,
                {"answer": "Request interrupted. Submit a new request to retry."},
                artifacts,
                {},
                "interrupted",
            )
            raise
        except Exception as exc:
            error = type(exc).__name__
            terminal = {"status": "failed", "error_code": error}
            trace.event("request.error", request_id=rid, error=type(exc).__name__)
            store.finish(
                rid,
                {
                    "status": "failed",
                    "answer": "Could not produce a validated response. Check provider configuration or try a simpler request.",
                    "error_code": type(exc).__name__,
                    "environment": settings.mode,
                },
                artifacts,
                {},
                "failed",
            )

        finally:
            trace.finish(rid, terminal, error)

    @app.post("/chat", status_code=202)
    async def chat(body: ChatRequest, authorization: str = Header()):
        if settings.readiness():
            raise HTTPException(503, "Agent configuration incomplete; inspect /ready")
        try:
            payload = body.model_dump(mode="json")
            # Validate before admission/model dispatch. Persist only permitted redacted input.
            payload["message"] = checked_text(payload["message"])
            rid, admitted = store.admit(payload, authorization)
        except GuardrailError as exc:
            raise HTTPException(422, str(exc)) from exc
        except OverflowError as exc:
            raise HTTPException(429, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        if admitted:
            task = asyncio.create_task(execute(rid, payload, authorization))
            tasks.add(task)
            task.add_done_callback(tasks.discard)
        return {"request_id": rid, "status_url": "/requests/" + rid}

    return app
