from pathlib import Path

import yaml

from .models import Destination


def load_registry(root: Path) -> list[Destination]:
    rows = yaml.safe_load((root / "config/destinations.yaml").read_text())["destinations"]
    destinations = [Destination.model_validate(row) for row in rows]
    if len({d.id for d in destinations}) != len(destinations):
        raise ValueError("Duplicate destination IDs")
    return [d for d in destinations if d.enabled]


def resolve_destination(destinations: list[Destination], value: str) -> Destination:
    value = value.casefold().strip()
    matches = [
        d for d in destinations if value in {a.casefold() for a in [d.id, d.title, *d.aliases]}
    ]
    if len(matches) != 1:
        raise ValueError(f"Unsupported or ambiguous destination: {value}")
    return matches[0]
