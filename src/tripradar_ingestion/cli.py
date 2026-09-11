from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated

import typer
from rich.console import Console

from .config import Settings
from .embeddings import LocalEmbedder
from .manifest import Manifest
from .pipeline import Pipeline
from .registry import load_registry, resolve_destination
from .reporting import statistics
from .retrieval import search_guide
from .utils import read_json, write_json, writer_lock
from .vectorstore import VectorStore

app = typer.Typer(
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
    help="Collect and index source-attributed Wikivoyage guides.",
)
sources = typer.Typer(no_args_is_help=True)
app.add_typer(sources, name="sources")
console = Console()


def output(value) -> None:
    console.print_json(json.dumps(value, ensure_ascii=False, default=str))


@app.command("setup-model")
def setup_model():
    """Explicitly download and verify Chroma's local MiniLM assets."""
    settings = Settings.load()
    with writer_lock(settings.data):
        output(LocalEmbedder(settings).setup())


@app.command()
def health(check_embeddings: bool = False):
    """Check local readiness; optionally execute one cached local embedding."""
    settings = Settings.load()
    embedder = LocalEmbedder(settings)
    result: dict = {
        "root": str(settings.root),
        "model": settings.embedding_model,
        "dimension": 384,
        "langsmith_enabled": settings.langsmith_tracing,
        "chroma_path": str(settings.resolve(settings.chroma_persist_directory)),
    }
    try:
        embedder.ensure_ready()
        result["model_cache"] = "verified"
        if check_embeddings:
            embedder.encode(["Destination guide readiness check"])
            result["local_inference"] = "passed"
    except (ValueError, RuntimeError) as exc:
        result["model_cache"] = str(exc)
    pointer = settings.data / "manifests/active_collection.json"
    if pointer.exists():
        try:
            result["collection"] = VectorStore(settings, embedder).active().name
        except (RuntimeError, ValueError) as exc:
            result["collection_error"] = str(exc)
    else:
        result["collection"] = "not_published"
    output(result)


@sources.command("list")
def source_list():
    output([d.model_dump() for d in load_registry(Settings.load().root)])


@sources.command()
def stale(days: int = 30):
    settings = Settings.load()
    path = settings.data / "manifests/ingestion.sqlite3"
    rows = []
    if path.exists():
        manifest = Manifest(settings.data)
        rows = manifest.checks()
        manifest.close()
    by_city = {r["destination"]: r for r in rows}
    output(
        [
            {"destination": d.id, **by_city.get(d.id, {"status": "never_collected"})}
            for d in load_registry(settings.root)
            if d.id not in by_city
            or by_city[d.id]["status"] != "success"
            or (datetime.now(UTC) - datetime.fromisoformat(by_city[d.id]["checked_at"])).days
            >= days
        ]
    )


def stage_command(stage: str):
    def run(
        destination: Annotated[str | None, typer.Option("--destination")] = None,
        all_cities: Annotated[bool, typer.Option("--all")] = False,
        root_only: bool = False,
        resume: bool = False,
        force: bool = False,
        dry_run: bool = False,
    ):
        settings = Settings.load()
        cities = load_registry(settings.root)
        if destination and all_cities:
            raise typer.BadParameter("Choose --destination or --all")
        if destination:
            cities = [resolve_destination(cities, destination)]
        elif not all_cities:
            raise typer.BadParameter("Specify --destination CITY or --all")
        if dry_run:
            output(
                {
                    "stage": stage,
                    "destinations": [d.id for d in cities],
                    "root_only": root_only,
                    "max_district_pages": settings.max_district_pages,
                    "writes": False,
                    "model_ready": (settings.data / "models/verified.json").exists(),
                }
            )
            return
        report = Pipeline(settings).run(cities, stage, root_only, resume, force)
        output(
            {
                **{k: v for k, v in report.items() if k not in {"stage_summaries", "statistics"}},
                "report_path": str(settings.data / "reports" / (report["run_id"] + ".json")),
            }
        )
        if report["errors"]:
            raise typer.Exit(1)

    run.__name__ = stage
    return run


for _stage in ("collect", "parse", "normalize", "chunk", "embed", "index", "ingest"):
    app.command(_stage)(stage_command(_stage))


@app.command()
def stats():
    output(statistics(Settings.load()))


@app.command()
def validate():
    """Validate the published snapshot's vectors, documents, and provenance."""
    settings = Settings.load()
    output(VectorStore(settings, LocalEmbedder(settings)).validate_active())


@app.command()
def search(query: str, destination: str, section: str | None = None, top_k: int = 5):
    results = search_guide(destination, section, query, top_k)
    output({"status": "results" if results else "not_covered", "results": results})


@app.command()
def evaluate(dataset: str = "tests/fixtures/retrieval_queries.json"):
    """Evaluate human-labeled expected guide passages (no generated answers)."""
    settings = Settings.load()
    rows = read_json(settings.resolve(dataset))
    results = []
    for row in rows:
        hits = search_guide(
            row["destination"], row.get("section"), row["query"], 5, settings=settings
        )
        passed = any(
            any(term.casefold() in hit["text"].casefold() for term in row["expected"])
            for hit in hits
        )
        results.append(
            {"query": row["query"], "passed": passed, "sources": [h["revision_url"] for h in hits]}
        )
    report = {
        "passed": sum(r["passed"] for r in results),
        "total": len(results),
        "results": results,
    }
    write_json(settings.data / "reports/retrieval_evaluation.json", report)
    output(report)


if __name__ == "__main__":
    app()
