from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from . import chunker, normalizer, parser
from .collector import Collector, district_candidates
from .config import Settings
from .embeddings import LocalEmbedder
from .manifest import Manifest
from .models import Chunk, Destination, Page, Section
from .observability import Observer
from .utils import digest, now, read_json, read_jsonl, write_json, write_jsonl, writer_lock
from .vectorstore import VectorStore

STAGES = ["collect", "parse", "normalize", "chunk", "embed", "index"]


class Pipeline:
    def __init__(self, settings: Settings, embedder=None):
        self.settings = settings
        self._embedder = embedder

    @property
    def embedder(self):
        if self._embedder is None:
            self._embedder = LocalEmbedder(self.settings)
        return self._embedder

    def artifact(self, stage: str, city: str) -> Path:
        folder = {
            "collect": "raw",
            "parse": "parsed",
            "normalize": "normalized",
            "chunk": "chunks",
        }[stage]
        return self.settings.data / folder / (city + ".jsonl")

    def collect(
        self,
        city: Destination,
        obs: Observer,
        root_only: bool,
        resume: bool,
        force: bool,
        manifest: Manifest,
    ) -> list[Page]:
        status_path = self.settings.data / "manifests" / (city.id + "-collection.json")
        scope = digest(
            [
                city.model_dump(),
                root_only,
                self.settings.max_district_depth,
                self.settings.max_district_pages,
            ]
        )
        with obs.span("sources.discover", destination_id=city.id) as metrics:
            # Reuse only collection work performed in this logical run and same scope.
            if resume and not force and status_path.exists():
                previous = read_json(status_path)
                if previous.get("run_id") == obs.run_id and previous.get("scope") == scope:
                    if manifest.cached(city.id, "collect", previous.get("fingerprint", "")):
                        metrics["outcome"] = "reused"
                        return [
                            Page.model_validate(r)
                            for r in read_jsonl(self.artifact("collect", city.id))
                        ]
            collector = Collector(self.settings, obs)
            queue = [(city.title, 0), *((t, 1) for t in city.districts if not root_only)]
            pages: list[Page] = []
            seen, page_ids = set(), set()
            excluded: list[dict] = []
            try:
                while queue:
                    title, depth = queue.pop(0)
                    if title in seen:
                        continue
                    seen.add(title)
                    if depth > self.settings.max_district_depth:
                        excluded.append({"title": title, "reason": "depth_limit"})
                        continue
                    if depth and len(pages) >= self.settings.max_district_pages + 1:
                        excluded.append({"title": title, "reason": "page_limit"})
                        continue
                    page = collector.page(city, title)
                    if page.page_id in page_ids:
                        continue
                    page_ids.add(page.page_id)
                    pages.append(page)
                    if not root_only:
                        queue.extend((t, depth + 1) for t in district_candidates(page))
            except Exception:
                write_json(
                    status_path,
                    {
                        "status": "failed",
                        "run_id": obs.run_id,
                        "scope": scope,
                        "collected_raw_pages": len(pages),
                    },
                )
                manifest.checked(city.id, "failed")
                raise
            finally:
                collector.close()
            path = self.artifact("collect", city.id)
            write_jsonl(path, [p.model_dump() for p in pages])
            fingerprint = digest([(p.page_id, p.revision_id, p.raw_hash) for p in pages])
            manifest.record(city.id, "collect", fingerprint, path)
            manifest.checked(city.id, "success")
            write_json(
                status_path,
                {
                    "status": "success",
                    "run_id": obs.run_id,
                    "scope": scope,
                    "fingerprint": fingerprint,
                    "root_only": root_only,
                    "pages": len(pages),
                    "excluded": excluded,
                    "checked_at": now(),
                },
            )
            metrics.update(pages=len(pages), excluded=len(excluded))
            return pages

    def transform(
        self, city: Destination, stage: str, obs: Observer, manifest: Manifest, force: bool
    ) -> None:
        previous = {"parse": "collect", "normalize": "parse", "chunk": "normalize"}[stage]
        source = self.artifact(previous, city.id)
        if not source.is_file():
            raise ValueError(f"Missing {previous} artifacts for {city.id}; run {previous}")
        rows = read_jsonl(source)
        fingerprint = self.stage_fingerprint(stage, rows)
        with obs.span(
            {"parse": "wikitext.parse", "normalize": "content.normalize", "chunk": "content.chunk"}[
                stage
            ],
            destination_id=city.id,
        ) as metrics:
            if not force and manifest.cached(city.id, stage, fingerprint):
                metrics["outcome"] = "reused"
                return
            output: list[dict] = []
            if stage == "parse":
                for row in rows:
                    output.extend(
                        s.model_dump() for s in parser.parse_page(Page.model_validate(row))
                    )
                metrics.update(
                    sections=len(output),
                    listings=sum(len(s["listings"]) for s in output),
                    unknown_templates=sum(len(s["diagnostics"]) for s in output),
                )
            elif stage == "normalize":
                rejected, removed = [], 0
                with obs.span("content.clean", destination_id=city.id) as clean_metrics:
                    for row in rows:
                        section, count = normalizer.normalize(Section.model_validate(row))
                        removed += count
                        if section.text.strip():
                            output.append(section.model_dump())
                        else:
                            rejected.append(
                                {"document_id": section.document_id, "reason": "empty_section"}
                            )
                    clean_metrics.update(
                        input_records=len(rows), output_records=len(output), rejected=len(rejected)
                    )
                with obs.span("content.deduplicate") as dedup_metrics:
                    dedup_metrics["duplicates_removed"] = removed
                write_json(
                    self.settings.data / "reports" / obs.run_id / (city.id + "-rejected.json"),
                    rejected,
                )
            else:
                archive = self.settings.data / "normalized/archive" / (digest(rows) + ".jsonl")
                write_jsonl(archive, rows)
                for row in rows:
                    output.extend(
                        c.model_dump()
                        for c in chunker.chunk_section(
                            Section.model_validate(row), self.embedder, self.settings
                        )
                    )
                for record in output:
                    record["metadata"]["normalized_artifact"] = str(archive)
                    record["metadata"]["normalized_artifact_hash"] = digest(rows)
                metrics.update(
                    chunks=len(output),
                    max_tokens=max((r["token_count"] for r in output), default=0),
                )
            if not output:
                raise ValueError(f"No usable {stage} output for {city.id}")
            path = self.artifact(stage, city.id)
            write_jsonl(path, output)
            manifest.record(city.id, stage, fingerprint, path)

    def stage_fingerprint(self, stage: str, rows: list[dict]) -> str:
        version = {
            "parse": parser.VERSION,
            "normalize": normalizer.VERSION,
            "chunk": chunker.VERSION,
        }[stage]
        extra = (
            [
                self.embedder.fingerprint,
                self.settings.chunk_target_tokens,
                self.settings.chunk_overlap_tokens,
                self.settings.chunk_max_input_tokens,
                "archive-provenance-v1",
            ]
            if stage == "chunk"
            else []
        )
        return digest([rows, version, extra])

    def verify_stage_chain(self, city: Destination, manifest: Manifest) -> None:
        for stage, previous in (
            ("parse", "collect"),
            ("normalize", "parse"),
            ("chunk", "normalize"),
        ):
            source = self.artifact(previous, city.id)
            if not source.exists():
                raise ValueError(f"Missing {previous} input for {city.id}")
            fingerprint = self.stage_fingerprint(stage, read_jsonl(source))
            if not manifest.cached(city.id, stage, fingerprint):
                raise ValueError(
                    f"Stale or modified {stage} artifacts for {city.id}; rerun {stage} and subsequent stages"
                )

    def chunks(self, cities: list[Destination]) -> list[Chunk]:
        result: list[Chunk] = []
        for city in cities:
            path = self.artifact("chunk", city.id)
            if not path.exists():
                raise ValueError(f"Missing chunks for {city.id}")
            result.extend(Chunk.model_validate(r) for r in read_jsonl(path))
        if len({c.chunk_id for c in result}) != len(result):
            raise ValueError("Duplicate chunk IDs")
        return result

    def run(
        self,
        cities: list[Destination],
        stage: str = "ingest",
        root_only: bool = False,
        resume: bool = False,
        force: bool = False,
    ) -> dict:
        with writer_lock(self.settings.data):
            attempt = uuid4().hex
            resume_path = self.settings.data / "manifests/last_run.json"
            scope = {"cities": [c.id for c in cities], "stage": stage, "root_only": root_only}
            previous = read_json(resume_path) if resume and resume_path.exists() else {}
            if previous and previous["scope"] != scope:
                raise ValueError("Resume scope differs; use the original destination/stage options")
            run_id = previous.get("run_id", attempt)
            write_json(resume_path, {"scope": scope, "run_id": run_id, "attempt_id": attempt})
            obs = Observer(self.settings, run_id, attempt)
            manifest = Manifest(self.settings.data)
            report: dict = {
                "run_id": run_id,
                "attempt_id": attempt,
                "scope": scope,
                "started_at": now(),
                "errors": [],
                "cities": {},
                "outcome": "success",
            }
            try:
                with obs.span("tripradar." + stage, cities=scope["cities"]) as root_metrics:
                    steps = STAGES if stage == "ingest" else [stage]
                    for city in cities:
                        with obs.span(
                            "destination.process", destination_id=city.id
                        ) as city_metrics:
                            try:
                                for step in steps:
                                    if step == "collect":
                                        self.collect(city, obs, root_only, resume, force, manifest)
                                    elif step in {"parse", "normalize", "chunk"}:
                                        self.transform(city, step, obs, manifest, force)
                                    elif step == "embed":
                                        self.verify_stage_chain(city, manifest)
                                        with obs.span(
                                            "embeddings.process", destination_id=city.id
                                        ) as metrics:
                                            metrics.update(
                                                self.embedder.embed_chunks(self.chunks([city]), obs)
                                            )
                                            report["cities"][city.id] = dict(metrics)
                            except Exception as exc:
                                report["errors"].append(
                                    {
                                        "destination": city.id,
                                        "type": type(exc).__name__,
                                        "message": str(exc)[:300],
                                    }
                                )
                                city_metrics.update(outcome="failed", error_type=type(exc).__name__)
                    if "index" in steps and not report["errors"]:
                        try:
                            # Never publish stale artifacts after a known failed collection attempt.
                            for city in cities:
                                path = (
                                    self.settings.data
                                    / "manifests"
                                    / (city.id + "-collection.json")
                                )
                                if path.exists() and read_json(path)["status"] != "success":
                                    raise ValueError(
                                        f"Last collection failed for {city.id}; collect successfully before publication"
                                    )
                            for city in cities:
                                self.verify_stage_chain(city, manifest)
                            chunks = self.chunks(cities)
                            selected = {c.id for c in cities}
                            pointer = self.settings.data / "manifests/active_collection.json"
                            if pointer.exists():
                                state = read_json(pointer)
                                chunks += [
                                    Chunk.model_validate(r)
                                    for r in read_json(Path(state["snapshot"]))
                                    if r["metadata"]["destination_id"] not in selected
                                ]
                            report["index"] = VectorStore(self.settings, self.embedder).publish(
                                chunks, obs
                            )
                        except Exception as exc:
                            report["errors"].append(
                                {
                                    "stage": "index",
                                    "type": type(exc).__name__,
                                    "message": str(exc)[:300],
                                }
                            )
                    if report["errors"]:
                        report["outcome"] = "partial_failure"
                    root_metrics.update(outcome=report["outcome"], failures=len(report["errors"]))
                    with obs.span("report.write"):
                        write_json(self.settings.data / "reports" / (run_id + ".json"), report)
            finally:
                manifest.close()
                obs.close()
                report.update(
                    completed_at=now(),
                    telemetry=obs.telemetry,
                    trace_id=obs.trace_id,
                    trace_url=obs.trace_url,
                )
                from .reporting import statistics

                report["stage_summaries"] = [e for e in obs.events if e.get("event") == "finished"]
                report["statistics"] = statistics(self.settings)
                write_json(self.settings.data / "reports" / (run_id + ".json"), report)
            return report
