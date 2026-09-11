from __future__ import annotations

from pydantic import BaseModel, Field


class Destination(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    title: str
    country: str
    aliases: list[str] = Field(default_factory=list)
    enabled: bool = True
    districts: list[str] = Field(default_factory=list)


class Page(BaseModel):
    source_id: str = "wikivoyage_en"
    source_name: str = "English Wikivoyage"
    language: str = "en"
    destination_id: str
    country: str
    requested_title: str
    title: str
    page_id: int
    revision_id: int
    revision_time: str
    retrieved_at: str
    source_url: str
    revision_url: str
    history_url: str
    raw_path: str
    raw_hash: str
    wikitext: str = ""
    attribution: str = "Wikivoyage contributors"
    license: str = "CC-BY-SA-4.0"
    license_url: str = "https://creativecommons.org/licenses/by-sa/4.0/"
    modifications: str = "Wikitext parsed, cleaned, and chunked; see saved source revision"


class Section(BaseModel):
    document_id: str
    page: Page
    section: str
    section_path: list[str]
    occurrence: int
    text: str
    listings: list[dict] = Field(default_factory=list)
    diagnostics: list[dict] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    content_hash: str = ""


class Chunk(BaseModel):
    chunk_id: str
    document_id: str
    text: str = Field(min_length=1)
    embedding_input: str = Field(min_length=1)
    start: int
    end: int
    ordinal: int
    token_count: int
    content_hash: str
    metadata: dict[str, str | int | float | bool]
