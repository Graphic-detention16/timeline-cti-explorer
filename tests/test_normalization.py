from timeline_cti.normalization import normalize_text, query_terms, refang_text


def test_unicode_normalization_is_stable() -> None:
    assert normalize_text("  İSTANBUL\nCVE-2026-4242  ") == "i̇stanbul cve-2026-4242"


def test_refangs_common_ioc_notation() -> None:
    assert refang_text("hxxps://evil[.]example/path") == "https://evil.example/path"


def test_query_terms_collapses_whitespace() -> None:
    assert query_terms(" malware   campaign ") == ["malware", "campaign"]
