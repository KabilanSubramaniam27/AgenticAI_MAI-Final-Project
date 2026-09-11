from collections import Counter

import numpy as np

from .config import Settings
from .utils import read_json, read_jsonl


def statistics(settings: Settings) -> dict:
    counts: dict = {}
    tokens: list[int] = []
    for path in sorted((settings.data / "chunks").glob("*.jsonl")):
        chunks = read_jsonl(path)
        counts[path.stem] = {
            "chunks": len(chunks),
            "sections": dict(Counter(c["metadata"]["section"] for c in chunks)),
        }
        tokens.extend(c["token_count"] for c in chunks)
    coverage = {
        path.name: read_json(path)
        for path in (settings.data / "manifests").glob("*-collection.json")
    }
    pointer = settings.data / "manifests/active_collection.json"
    return {
        "cities": counts,
        "coverage": coverage,
        "active": read_json(pointer) if pointer.exists() else None,
        "token_distribution": {str(p): float(np.percentile(tokens, p)) for p in (0, 50, 95, 100)}
        if tokens
        else {},
    }
