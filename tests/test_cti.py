from __future__ import annotations

from timeline_cti.cti import CtiEngine, ScoreThresholds, extract_indicators


class SemanticStub:
    available = True
    revision = "test-revision"

    def score(self, text: str) -> tuple[float, list[str]]:
        return (80.0, ["vulnerability"]) if "CVE" in text else (10.0, [])


class MissingSemanticStub:
    available = False
    revision = None

    def score(self, text: str) -> tuple[None, list[str]]:
        return None, []


def test_extracts_refanged_iocs() -> None:
    indicators = extract_indicators(
        "APT42 shared hxxps://evil[.]example/a and 203.0.113.9 for CVE-2026-4242 T1059.001"
    )
    assert indicators.urls == ["https://evil.example/a"]
    assert "evil.example" in indicators.domains
    assert indicators.ipv4 == ["203.0.113.9"]
    assert indicators.cves == ["CVE-2026-4242"]
    assert indicators.attack_techniques == ["T1059.001"]
    assert indicators.threat_actors == ["APT42"]


def test_hybrid_assessment_is_explainable() -> None:
    engine = CtiEngine(
        SemanticStub(),
        trusted_handles={"trusted"},
        thresholds=ScoreThresholds(),
    )
    result = engine.assess(
        "Critical CVE-2026-4242 exploit at hxxps://evil[.]example",
        username="trusted",
        metrics={"likes": 1000},
    )
    assert result.scoring_mode == "hybrid"
    # 0.65 × 37 kural + 0.35 × 80 semantik skor = 52.
    assert result.rule_score == 37
    assert result.score == 52
    assert result.model_revision == "test-revision"
    assert any(reason.startswith("ioc_evidence") for reason in result.reasons)


def test_missing_model_never_silently_returns_hybrid() -> None:
    engine = CtiEngine(MissingSemanticStub(), set(), ScoreThresholds())
    result = engine.assess("ordinary engineering update")
    assert result.scoring_mode == "rules_only"
    assert result.semantic_score is None
    assert "semantic_model:unavailable" in result.reasons
