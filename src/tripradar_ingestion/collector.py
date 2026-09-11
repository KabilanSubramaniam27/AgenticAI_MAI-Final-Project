"""Revision-pinned MediaWiki collection; no arbitrary outbound crawling."""

from __future__ import annotations

import random
import time
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import httpx
import mwparserfromhell as mw

from .config import Settings
from .models import Destination, Page
from .observability import Observer
from .utils import atomic_bytes, file_hash, now, read_json, write_json

API = "https://en.wikivoyage.org/w/api.php"


class SourceError(RuntimeError):
    pass


def retry_after(value: str | None) -> float:
    if not value:
        return 0
    try:
        return max(0, float(value))
    except ValueError:
        try:
            return max(0, parsedate_to_datetime(value).timestamp() - time.time())
        except (ValueError, TypeError):
            return 0


class Collector:
    def __init__(self, settings: Settings, observer: Observer):
        self.settings, self.obs = settings, observer
        self.client = httpx.Client(
            timeout=settings.http_timeout_seconds,
            headers={"User-Agent": settings.scraper_user_agent},
            follow_redirects=False,
        )
        self.last_request = 0.0

    def close(self) -> None:
        self.client.close()

    def request(self, params: dict) -> tuple[dict, bytes, dict]:
        for attempt in range(self.settings.http_max_retries + 1):
            time.sleep(
                max(0, self.settings.http_interval_seconds - (time.monotonic() - self.last_request))
            )
            delay = 0.0
            with self.obs.span("wikivoyage.request", attempt=attempt + 1) as result:
                self.last_request = time.monotonic()
                try:
                    response = self.client.get(
                        API, params={"format": "json", "formatversion": 2, "maxlag": 5, **params}
                    )
                    result.update(http_status=response.status_code, bytes=len(response.content))
                    delay = retry_after(response.headers.get("Retry-After"))
                    transient = response.status_code in (408, 429, 500, 502, 503, 504)
                    if not transient:
                        response.raise_for_status()
                        payload = response.json()
                        code = payload.get("error", {}).get("code")
                        transient = code in ("maxlag", "ratelimited", "readonly")
                        if code and not transient:
                            raise SourceError(f"MediaWiki API error: {code}")
                        if not transient:
                            headers = {
                                k: response.headers[k]
                                for k in ("etag", "last-modified", "content-type")
                                if k in response.headers
                            }
                            return payload, response.content, headers
                    result.update(outcome="retry", retry_after_seconds=delay)
                except (httpx.TimeoutException, httpx.NetworkError):
                    result.update(outcome="retry", error_type="network")
            if attempt == self.settings.http_max_retries:
                raise SourceError("MediaWiki request exhausted retries")
            # Long Retry-After is not ignored or shortened into an early request.
            time.sleep(max(delay, min(30, 2**attempt + random.random())))
        raise AssertionError("unreachable")

    def page(self, destination: Destination, title: str) -> Page:
        if ":" in title or "#" in title:
            raise SourceError("Only article namespace page titles are permitted")
        with self.obs.span(
            "wikivoyage.collect", destination_id=destination.id, requested_title=title
        ) as summary:
            info, info_raw, info_headers = self.request(
                {
                    "action": "query",
                    "titles": title,
                    "redirects": 1,
                    "prop": "info|revisions",
                    "inprop": "url",
                    "rvprop": "ids|timestamp",
                    "rvlimit": 1,
                }
            )
            rows = info.get("query", {}).get("pages", [])
            if len(rows) != 1 or rows[0].get("missing") or rows[0].get("ns") != 0:
                raise SourceError(f"Missing or non-article page: {title}")
            row = rows[0]
            rev = row["revisions"][0]
            base = (
                self.settings.data
                / "raw/wikivoyage"
                / destination.id
                / str(row["pageid"])
                / str(rev["revid"])
            )
            cached = base / "page.json"
            if cached.exists():
                page = Page.model_validate(read_json(cached))
                text_path = base / "source.wiki"
                if text_path.is_file() and file_hash(text_path) == page.raw_hash:
                    summary.update(outcome="reused", revision_id=page.revision_id)
                    self.obs.event(
                        "wikivoyage.checked",
                        page_id=page.page_id,
                        revision_id=page.revision_id,
                        checked_at=now(),
                    )
                    return page
            parsed, raw, headers = self.request(
                {"action": "parse", "oldid": rev["revid"], "prop": "wikitext|revid"}
            )
            data = parsed["parse"]
            if data["revid"] != rev["revid"]:
                raise SourceError("Parse/revision identity mismatch")
            wikitext = data["wikitext"]
            if not isinstance(wikitext, str) or not wikitext.strip():
                raise SourceError("Empty wikitext")
            atomic_bytes(base / "query.json", info_raw)
            atomic_bytes(base / "parse.json", raw)
            atomic_bytes(base / "source.wiki", wikitext.encode())
            canonical = "https://en.wikivoyage.org/wiki/" + quote(
                row["title"].replace(" ", "_"), safe="/"
            )
            page = Page(
                destination_id=destination.id,
                country=destination.country,
                requested_title=title,
                title=row["title"],
                page_id=row["pageid"],
                revision_id=rev["revid"],
                revision_time=rev["timestamp"],
                retrieved_at=now(),
                source_url=canonical,
                revision_url=f"https://en.wikivoyage.org/w/index.php?oldid={rev['revid']}",
                history_url=canonical + "?action=history",
                raw_path=str(base / "source.wiki"),
                raw_hash=file_hash(base / "source.wiki"),
                wikitext=wikitext,
            )
            write_json(cached, page.model_dump())
            write_json(
                base / "retrieval.json",
                {
                    "retrieved_at": page.retrieved_at,
                    "api_url": API,
                    "query_headers": info_headers,
                    "parse_headers": headers,
                    "parse_sha256": file_hash(base / "parse.json"),
                },
            )
            summary.update(
                page_id=page.page_id,
                revision_id=page.revision_id,
                raw_artifact=str(base / "source.wiki"),
            )
            return page


def district_candidates(page: Page) -> list[str]:
    """Only links explicitly named by region/district hierarchy templates."""
    found: set[str] = set()
    for template in mw.parse(page.wikitext).filter_templates():
        name = str(template.name).strip().casefold().replace("_", " ")
        if name in {"regionlist", "region list", "districtlist", "district list"}:
            for param in template.params:
                key = str(param.name).strip().casefold()
                if key.endswith(("name", "items")):
                    found.update(
                        str(link.title).split("#")[0].strip()
                        for link in mw.parse(str(param.value)).filter_wikilinks()
                    )
    return sorted(t for t in found if t and ":" not in t and t != page.title)
