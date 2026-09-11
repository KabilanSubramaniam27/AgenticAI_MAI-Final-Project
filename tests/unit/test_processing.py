from tripradar_ingestion.chunker import chunk_section
from tripradar_ingestion.collector import district_candidates
from tripradar_ingestion.normalizer import normalize
from tripradar_ingestion.parser import parse_page


def test_nested_sections_listing_and_unknown_template(page):
    page.wikitext = """Lead.
== See ==
Museum overview.
=== Old town ===
{{see|name=City Museum|content=Not open on Mondays.|price=€5|hours=10–18|url=https://example.org}}
{{odd|Useful unexpected content}}
[[File:Photo.jpg|caption should disappear]]
== Stay safe ==
Do not swim here.
"""
    sections = parse_page(page)
    assert len(sections) == 4
    parent, child = sections[1:3]
    assert "City Museum" not in parent.text
    assert child.section == "see"
    assert child.section_path == ["See", "Old town"]
    assert "Not open on Mondays." in child.text
    assert "Guide price: €5" in child.text
    assert child.listings[0]["guide_price_text"] == "€5"
    assert child.listings[0]["environment"] == "unknown"
    assert child.diagnostics[0]["name"] == "odd"
    assert "Useful unexpected content" in child.text
    assert "Photo.jpg" not in child.text
    assert "Do not swim" in sections[-1].text


def test_district_discovery_hierarchy_not_arbitrary_prefix(page):
    page.wikitext = """{{Regionlist|region1name=Central|region1items=[[Lisbon/Baixa]]
|region1description=Visit [[Lisbon/Unrelated]]}}
[[Paris]] [[Lisbon/Other]]"""
    assert district_candidates(page) == ["Lisbon/Baixa"]


def test_chunks_cover_text_without_truncation(page, settings, embedder):
    page.wikitext = "== See ==\n" + " ".join(f"word{i}" for i in range(1500))
    section, _ = normalize(parse_page(page)[1])
    chunks = chunk_section(section, embedder, settings)
    assert len(chunks) > 5
    covered = set()
    for chunk in chunks:
        assert section.text[chunk.start : chunk.end] == chunk.text
        assert chunk.token_count <= settings.chunk_max_input_tokens
        covered.update(range(chunk.start, chunk.end))
    assert all(i in covered for i, c in enumerate(section.text) if not c.isspace())
    assert [c.chunk_id for c in chunks] == [
        c.chunk_id for c in chunk_section(section, embedder, settings)
    ]


def test_short_warning_and_dedup(page, settings, embedder):
    page.wikitext = "== Stay safe ==\nDo not swim.\n\nDo not swim."
    section, removed = normalize(parse_page(page)[1])
    assert removed == 1
    assert chunk_section(section, embedder, settings)[0].text == "Do not swim."


def test_region_description_is_kept(page):
    page.wikitext = "{{Regionlist|region1name=Downtown|region1description=Many museums here.}}"
    assert "Many museums here." in parse_page(page)[0].text


def test_oversized_listing_keeps_fragment_identity(page, settings, embedder):
    page.wikitext = "== See ==\n{{see|name=City Museum|content=" + "art " * 600 + "}}"
    section, _ = normalize(parse_page(page)[1])
    chunks = chunk_section(section, embedder, settings)
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.metadata["listing_names"] == "City Museum"
        assert chunk.metadata["listing_ids"] == section.listings[0]["listing_id"]
        assert "City Museum" in chunk.embedding_input


def test_real_attributed_listing_fixture(page):
    import json
    from pathlib import Path

    fixture = json.loads(
        (Path(__file__).parents[1] / "fixtures/wikivoyage/lisbon_listing.json").read_text()
    )
    page.wikitext = "== See ==\n" + fixture["wikitext"]
    page.revision_id = fixture["revision_id"]
    section = parse_page(page)[1]
    assert fixture["expected_name"] in section.text
    assert section.page.revision_id == fixture["revision_id"]
    assert section.listings
