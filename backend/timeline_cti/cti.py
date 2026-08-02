from __future__ import annotations

import ipaddress
import math
import re
from dataclasses import dataclass
from typing import Literal, Protocol
from urllib.parse import urlparse

from .models import CtiAssessment, CtiLevel, IndicatorSet
from .normalization import normalize_text, refang_text

URL_RE = re.compile(r"\bhttps?://[^\s<>\"']+", re.IGNORECASE)
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,63}\b", re.IGNORECASE)
IP_CANDIDATE_RE = re.compile(r"(?<![\w:])(?:[A-F0-9:.]{3,45})(?![\w:])", re.IGNORECASE)
DOMAIN_RE = re.compile(r"\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}\b", re.I)
MD5_RE = re.compile(r"\b[a-fA-F0-9]{32}\b")
SHA1_RE = re.compile(r"\b[a-fA-F0-9]{40}\b")
SHA256_RE = re.compile(r"\b[a-fA-F0-9]{64}\b")
SHA512_RE = re.compile(r"\b[a-fA-F0-9]{128}\b")
CVE_RE = re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.IGNORECASE)
ATTACK_RE = re.compile(r"\bT\d{4}(?:\.\d{3})?\b", re.IGNORECASE)
FILENAME_RE = re.compile(
    r"\b[\w.-]+\.(?:exe|dll|sys|ps1|bat|cmd|js|vbs|jar|apk|docm|xlsm|zip|rar|7z)\b",
    re.IGNORECASE,
)
HASHTAG_RE = re.compile(r"(?<!\w)#([\w-]{2,64})", re.UNICODE)
ACTOR_RE = re.compile(r"\b(?:APT\d{1,3}|UNC\d{2,6}|FIN\d{1,3}|TA\d{3,6})\b", re.I)

THREAT_TERMS = {
    "malware": ("malware", "zararlı yazılım", "trojan", "backdoor", "stealer", "botnet"),
    "phishing": ("phishing", "oltalama", "credential theft", "kimlik avı"),
    "ransomware": ("ransomware", "fidye yazılımı", "encryptor", "extortion"),
    "vulnerability": ("vulnerability", "zafiyet", "exploit", "zero-day", "0day", "rce"),
    "apt_campaign": ("threat actor", "campaign", "apt", "tehdit aktörü", "ioc", "indicator"),
}


class SemanticScorer(Protocol):
    available: bool
    revision: str | None

    def score(self, text: str) -> tuple[float | None, list[str]]: ...


@dataclass(frozen=True)
class ScoreThresholds:
    medium: int = 40
    high: int = 70
    critical: int = 85


class CtiEngine:
    VERSION = "rules-1.0.0"

    def __init__(
        self,
        semantic_scorer: SemanticScorer,
        trusted_handles: set[str],
        thresholds: ScoreThresholds,
    ) -> None:
        self.semantic_scorer = semantic_scorer
        self.trusted_handles = trusted_handles
        self.thresholds = thresholds

    def assess(
        self,
        text: str,
        username: str = "",
        metrics: dict[str, int] | None = None,
    ) -> CtiAssessment:
        indicators = extract_indicators(text)
        normalized = normalize_text(text)
        reasons: list[str] = []
        categories: set[str] = set()

        indicator_score = min(45, self._indicator_score(indicators))
        if indicator_score:
            reasons.append(f"ioc_evidence:{indicator_score}")
            categories.add("ioc_sharing")

        cve_attack_score = min(
            20,
            len(indicators.cves) * 8 + len(indicators.attack_techniques) * 6,
        )
        if cve_attack_score:
            reasons.append(f"cve_attack_reference:{cve_attack_score}")
            categories.add("vulnerability")

        matched_categories = {
            category
            for category, terms in THREAT_TERMS.items()
            if any(term in normalized for term in terms)
        }
        context_score = min(20, len(matched_categories) * 6)
        if context_score:
            reasons.append(f"threat_context:{context_score}")
            categories.update(matched_categories)

        trust_score = 10 if username.lower().lstrip("@") in self.trusted_handles else 0
        if trust_score:
            reasons.append("trusted_source:10")

        engagement = sum(max(0, int(value)) for value in (metrics or {}).values())
        engagement_score = min(5, int(math.log10(engagement + 1))) if engagement else 0
        if engagement_score:
            reasons.append(f"engagement_signal:{engagement_score}")

        rule_score = min(
            100,
            indicator_score + cve_attack_score + context_score + trust_score + engagement_score,
        )
        semantic_score, semantic_categories = self.semantic_scorer.score(text)
        categories.update(semantic_categories)

        if semantic_score is None:
            final_score = rule_score
            scoring_mode: Literal["hybrid", "rules_only"] = "rules_only"
            model_revision = None
            reasons.append("semantic_model:unavailable")
        else:
            final_score = round(0.65 * rule_score + 0.35 * semantic_score)
            scoring_mode = "hybrid"
            model_revision = self.semantic_scorer.revision
            reasons.append(f"semantic_relevance:{semantic_score:.1f}")

        return CtiAssessment(
            score=max(0, min(100, final_score)),
            level=self._level(final_score),
            rule_score=rule_score,
            semantic_score=semantic_score,
            scoring_mode=scoring_mode,
            categories=sorted(categories),
            indicators=indicators,
            reasons=reasons,
            scorer_version=self.VERSION,
            model_revision=model_revision,
        )

    @staticmethod
    def _indicator_score(indicators: IndicatorSet) -> int:
        hashes = len(indicators.md5 + indicators.sha1 + indicators.sha256 + indicators.sha512)
        network = len(indicators.ipv4 + indicators.ipv6 + indicators.domains + indicators.urls)
        supporting = len(indicators.emails + indicators.filenames + indicators.threat_actors)
        return min(45, hashes * 15 + network * 5 + supporting * 3)

    def _level(self, score: int) -> CtiLevel:
        if score >= self.thresholds.critical:
            return CtiLevel.CRITICAL
        if score >= self.thresholds.high:
            return CtiLevel.HIGH
        if score >= self.thresholds.medium:
            return CtiLevel.MEDIUM
        return CtiLevel.LOW


def extract_indicators(text: str) -> IndicatorSet:
    prepared = refang_text(text)
    urls = sorted({match.rstrip(".,);]") for match in URL_RE.findall(prepared)})
    emails = sorted(set(EMAIL_RE.findall(prepared)))

    ipv4: set[str] = set()
    ipv6: set[str] = set()
    for candidate in IP_CANDIDATE_RE.findall(prepared):
        try:
            address = ipaddress.ip_address(candidate.strip(".[]()"))
        except ValueError:
            continue
        (ipv4 if address.version == 4 else ipv6).add(str(address))

    domains = set(DOMAIN_RE.findall(prepared))
    domains.difference_update(email.split("@", 1)[-1] for email in emails)
    for url in urls:
        hostname = urlparse(url).hostname
        if hostname:
            try:
                ipaddress.ip_address(hostname)
            except ValueError:
                domains.add(hostname.lower())

    return IndicatorSet(
        ipv4=sorted(ipv4),
        ipv6=sorted(ipv6),
        domains=sorted(domain.lower() for domain in domains),
        urls=urls,
        emails=emails,
        md5=sorted(set(MD5_RE.findall(prepared))),
        sha1=sorted(set(SHA1_RE.findall(prepared))),
        sha256=sorted(set(SHA256_RE.findall(prepared))),
        sha512=sorted(set(SHA512_RE.findall(prepared))),
        cves=sorted({value.upper() for value in CVE_RE.findall(prepared)}),
        attack_techniques=sorted({value.upper() for value in ATTACK_RE.findall(prepared)}),
        filenames=sorted(set(FILENAME_RE.findall(prepared))),
        hashtags=sorted({value.lower() for value in HASHTAG_RE.findall(prepared)}),
        threat_actors=sorted({value.upper() for value in ACTOR_RE.findall(prepared)}),
    )
