from __future__ import annotations

import re
import unicodedata

WHITESPACE_RE = re.compile(r"\s+")


def refang_text(value: str) -> str:
    """Yaygın IOC etkisizleştirme biçimlerini analiz için geri çevirir."""

    replacements = {
        "hxxps://": "https://",
        "hxxp://": "http://",
        "[.]": ".",
        "(.)": ".",
        "[:]": ":",
        "[@]": "@",
    }
    prepared = value
    for source, target in replacements.items():
        prepared = prepared.replace(source, target)
    return prepared


def normalize_text(value: str) -> str:
    """İndeks ve sorgu tarafında aynı Unicode dönüşümünü uygular."""

    normalized = unicodedata.normalize("NFKC", value).casefold()
    return WHITESPACE_RE.sub(" ", normalized).strip()


def query_terms(value: str) -> list[str]:
    return [term for term in normalize_text(value).split(" ") if term]
