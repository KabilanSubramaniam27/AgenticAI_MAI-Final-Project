"""AST parsing preserves listing content before removing layout templates."""

from __future__ import annotations

from collections import Counter

import mwparserfromhell as mw
from mwparserfromhell.nodes import Heading

from .cleaner import clean_text
from .models import Page, Section
from .utils import digest

VERSION = "parser-v2"
SECTIONS = {
    x.replace("_", " "): x
    for x in (
        "understand",
        "get_in",
        "get_around",
        "see",
        "do",
        "buy",
        "eat",
        "drink",
        "sleep",
        "stay_safe",
        "stay_healthy",
        "connect",
        "cope",
        "go_next",
    )
}
LISTINGS = {"see", "do", "eat", "drink", "sleep", "buy", "go", "marker", "listing"}
LAYOUT = {
    "pagebanner",
    "geo",
    "ispartof",
    "is part of",
    "quickbar",
    "regionlist",
    "region list",
    "mapframe",
    "mapshape",
    "mapshapes",
    "maplink",
    "flag",
    "routebox",
    "printdistricts",
    "dead link",
    "mapmask",
    "usablecity",
    "guidecity",
    "outlinecity",
    "starcity",
    "usable district",
    "outline district",
    "guide district",
    "itinerary",
    "related",
    "stub",
    "style",
    "commons",
    "wikipedia",
    "wikidata",
    "districtlist",
}


def plain(value: str) -> str:
    return clean_text(mw.parse(value).strip_code(normalize=True, collapse=True))


def render(raw: str, document_id: str) -> tuple[str, list[dict], list[dict], list[str]]:
    code = mw.parse(raw)
    listings, diagnostics = [], []
    links = [str(x.title).strip() for x in code.filter_wikilinks()]
    links += [str(x.url).strip() for x in code.filter_external_links()]
    for index, template in enumerate(list(code.filter_templates(recursive=False))):
        name = str(template.name).strip().casefold().replace("_", " ")
        if name in LISTINGS:
            fields = {str(p.name).strip(): plain(str(p.value)) for p in template.params}
            fields = {k: v for k, v in fields.items() if v}
            listing_id = digest([document_id, index, str(template)])
            mapping = {
                "name": "Name",
                "alt": "Alternative name",
                "content": "Description",
                "address": "Address",
                "directions": "Directions",
                "url": "Website",
                "lat": "Latitude",
                "long": "Longitude",
                "hours": "Hours",
                "price": "Guide price",
                "phone": "Phone",
                "lastedit": "Source last edit",
            }
            text = "; ".join(
                f"{label}: {fields[key]}" for key, label in mapping.items() if key in fields
            )
            record = {
                "listing_id": listing_id,
                "kind": name,
                "fields": fields,
                "guide_price_text": fields.get("price"),
                "environment": "unknown",
                "source_template": str(template),
                "text": text,
            }
            listings.append(record)
            code.replace(template, "\n\n" + text + "\n\n")
        elif name in {"regionlist", "region list", "districtlist", "district list"}:
            lines = [
                plain(str(p.value))
                for p in template.params
                if str(p.name).strip().casefold().endswith(("name", "items", "description"))
            ]
            code.replace(template, "\n\n" + "\n".join(lines) + "\n\n")
        elif name in LAYOUT or name.endswith(("city", "district")):
            code.replace(template, "")
        elif name in {"warningbox", "cautionbox", "infobox", "note", "warning"}:
            text = " ".join(plain(str(p.value)) for p in template.params)
            code.replace(template, "\n\n" + text + "\n\n")
        elif name == "convert":
            code.replace(template, " ".join(plain(str(p.value)) for p in template.params[:2]))
        else:
            diagnostics.append({"type": "unknown_template", "name": name, "raw": str(template)})
            # Keep visible parameter values rather than quietly erasing unknown content.
            values = " ".join(plain(str(p.value)) for p in template.params)
            code.replace(template, values)
    for link in list(code.filter_wikilinks(recursive=False)):
        if str(link.title).strip().casefold().startswith(("file:", "image:", "category:")):
            code.remove(link)
    return plain(str(code)), listings, diagnostics, links


def parse_page(page: Page) -> list[Section]:
    stack: list[tuple[int, str]] = []
    path: list[str] = ["Overview"]
    groups: list[tuple[list[str], str]] = []
    buffer: list[str] = []
    for node in mw.parse(page.wikitext).nodes:
        if isinstance(node, Heading):
            groups.append((path, "".join(buffer)))
            buffer = []
            while stack and stack[-1][0] >= node.level:
                stack.pop()
            stack.append((node.level, plain(str(node.title))))
            path = [title for _, title in stack]
        else:
            buffer.append(str(node))
    groups.append((path, "".join(buffer)))
    occurrences: Counter = Counter()
    sections = []
    for path, raw in groups:
        occurrences[tuple(path)] += 1
        document_id = digest([page.source_id, page.page_id, path, occurrences[tuple(path)]])
        text, listings, diagnostics, links = render(raw, document_id)
        key = next(
            (SECTIONS[label.casefold()] for label in path if label.casefold() in SECTIONS),
            "overview" if path == ["Overview"] else "other",
        )
        sections.append(
            Section(
                document_id=document_id,
                page=page.model_copy(update={"wikitext": ""}),
                section=key,
                section_path=path,
                occurrence=occurrences[tuple(path)],
                text=text,
                listings=listings,
                diagnostics=diagnostics,
                links=links,
            )
        )
    return sections
