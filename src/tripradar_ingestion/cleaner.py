import html
import re
import unicodedata


def clean_text(text: str) -> str:
    text = unicodedata.normalize("NFC", html.unescape(text))
    lines = [
        re.sub(r"[\t \u00a0]+", " ", line).strip().lstrip("*#;:").strip()
        for line in text.splitlines()
    ]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def deduplicate(text: str) -> tuple[str, int]:
    blocks, seen, count = [], set(), 0
    for block in re.split(r"\n\s*\n", text):
        if block and block not in seen:
            seen.add(block)
            blocks.append(block)
        elif block:
            count += 1
    return "\n\n".join(blocks), count
