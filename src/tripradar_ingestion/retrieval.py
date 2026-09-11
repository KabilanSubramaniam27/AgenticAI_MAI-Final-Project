from .config import Settings
from .embeddings import LocalEmbedder
from .observability import Observer
from .registry import load_registry, resolve_destination
from .vectorstore import VectorStore


def search_guide(
    destination: str,
    section: str | None = None,
    query: str = "",
    k: int = 5,
    *,
    settings: Settings | None = None,
    observer: Observer | None = None,
) -> list[dict]:
    """Retrieve actual guide passages; an empty result is a coverage failure."""
    from uuid import uuid4

    if not query.strip() or not 1 <= k <= 50:
        raise ValueError("A nonempty query and k between 1 and 50 are required")
    settings = settings or Settings.load()
    city = resolve_destination(load_registry(settings.root), destination)
    obs = observer or Observer(settings, uuid4().hex)
    try:
        with obs.span("tripradar.search"):
            return VectorStore(settings, LocalEmbedder(settings)).search(
                city.id, query, section, k, obs
            )
    finally:
        if observer is None:
            obs.close()
