from .cleaner import clean_text, deduplicate
from .models import Section
from .utils import digest

VERSION = "normalizer-v1"


def normalize(section: Section) -> tuple[Section, int]:
    text, removed = deduplicate(clean_text(section.text))
    return section.model_copy(update={"text": text, "content_hash": digest(text)}), removed
