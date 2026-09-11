"""Section-bound chunks with exact normalized-text offsets."""

from __future__ import annotations

import re

from .config import Settings
from .models import Chunk, Section
from .utils import digest

VERSION = "chunker-v2"


def chunk_section(section: Section, embedder, settings: Settings) -> list[Chunk]:
    text = section.text
    prefix = f"{section.page.title} | {' > '.join(section.section_path)}\n"
    # Avoid a very long heading consuming the entire input budget.
    while embedder.count(prefix) > 48:
        prefix = prefix[: max(1, len(prefix) // 2)].rstrip() + "\n"
    base_prefix = prefix
    listing_spans = []
    for listing in section.listings:
        position = text.find(listing["text"])
        if position >= 0 and listing["text"]:
            listing_spans.append((position, position + len(listing["text"]), listing))
    chunks: list[Chunk] = []
    start = 0
    words = list(re.finditer(r"\S+", text))
    while start < len(text):
        while start < len(text) and text[start].isspace():
            start += 1
        if start == len(text):
            break
        prefix = base_prefix
        for left, right, listing in listing_spans:
            if left < start < right:
                name = listing["fields"].get("name", "Listing")
                label = f"{name} (continued)\n"
                while embedder.count(label) > 32:
                    label = label[: max(1, len(label) // 2)]
                prefix += label
                break
        candidates = [m.end() for m in words if m.end() > start]
        end = start
        for stop in candidates:
            if embedder.count(prefix + text[start:stop]) > settings.chunk_target_tokens:
                break
            end = stop
        if end == start:
            # A single extremely long word: cut by characters without losing coverage.
            end = start + 1
            while (
                end < len(text)
                and embedder.count(prefix + text[start : end + 1]) <= settings.chunk_target_tokens
            ):
                end += 1
        for left, right, _listing in listing_spans:
            if start < left < end < right:
                end = left
                break
        # Prefer paragraph/listing and sentence boundaries when reasonably close to the budget.
        segment = text[start:end]
        boundaries = [m.end() for m in re.finditer(r"\n\n|(?<=[.!?])\s+", segment)]
        if boundaries and boundaries[-1] >= len(segment) * 0.55:
            end = start + boundaries[-1]
        while end > start and text[end - 1].isspace():
            end -= 1
        content = text[start:end]
        embedding_input = prefix + content
        count = embedder.count(embedding_input)
        if count > settings.chunk_max_input_tokens:
            raise ValueError("Chunk exceeds model budget")
        page = section.page
        metadata = {
            key: value
            for key, value in page.model_dump().items()
            if key not in {"wikitext"} and isinstance(value, (str, int, float, bool))
        }
        metadata.update(
            section=section.section,
            section_path=" > ".join(section.section_path),
            document_id=section.document_id,
            chunker_version=VERSION,
            start=start,
            end=end,
        )
        overlapping = [
            listing for left, right, listing in listing_spans if left < end and right > start
        ]
        if overlapping:
            metadata["listing_ids"] = ",".join(item["listing_id"] for item in overlapping)
            metadata["listing_names"] = " | ".join(
                item["fields"].get("name", "Listing") for item in overlapping
            )
        chunk_id = digest([section.document_id, VERSION, len(chunks), content])
        chunks.append(
            Chunk(
                chunk_id=chunk_id,
                document_id=section.document_id,
                text=content,
                embedding_input=embedding_input,
                start=start,
                end=end,
                ordinal=len(chunks),
                token_count=count,
                content_hash=digest(content),
                metadata={**metadata, "chunk_id": chunk_id, "content_hash": digest(content)},
            )
        )
        if end >= len(text):
            break
        # Don't overlap across paragraphs/listings; overlap only within split prose.
        next_start = end
        if not text[end:].startswith("\n\n") and settings.chunk_overlap_tokens:
            for match in reversed(words):
                if match.start() <= start or match.start() >= end:
                    continue
                if embedder.count(text[match.start() : end]) > settings.chunk_overlap_tokens:
                    break
                next_start = match.start()
        start = max(start + 1, next_start)
    return chunks
