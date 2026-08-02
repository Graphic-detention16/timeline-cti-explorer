from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, cast

PROTOTYPES: dict[str, tuple[str, ...]] = {
    "malware": (
        "Technical malware analysis with hashes, command and control domains and behavior.",
        "Hash, komuta kontrol alan adı ve davranış içeren zararlı yazılım analizi.",
    ),
    "phishing": (
        "Phishing campaign stealing credentials through malicious links and fake login pages.",
        "Kötü amaçlı bağlantılar ve sahte giriş sayfaları kullanan oltalama kampanyası.",
    ),
    "ransomware": (
        "Ransomware intrusion, data encryption, extortion and victim infrastructure.",
        "Fidye yazılımı saldırısı, veri şifreleme ve tehdit altyapısı.",
    ),
    "vulnerability": (
        "Critical vulnerability exploitation, CVE, proof of concept and remote code execution.",
        "Kritik zafiyet istismarı, CVE, PoC ve uzaktan kod çalıştırma.",
    ),
    "apt_campaign": (
        "Nation state threat actor or APT campaign with tactics, techniques and procedures.",
        "APT tehdit aktörü kampanyası ve taktik teknik prosedür analizi.",
    ),
    "ioc_sharing": (
        "Cyber threat intelligence indicators including IP, domain, URL and file hash.",
        "IP, alan adı, URL ve dosya özeti içeren siber tehdit istihbaratı göstergeleri.",
    ),
}


class NullSemanticScorer:
    available = False
    revision: str | None = None

    def score(self, text: str) -> tuple[None, list[str]]:
        return None, []


class OnnxSemanticScorer:
    """Sabit ONNX modelini yalnız çıkarım için yükler; eğitim yapmaz."""

    def __init__(self, model_path: Path, revision: str, expected_sha256: str = "") -> None:
        self.available = False
        self.revision: str | None = revision
        self._session: Any = None
        self._tokenizer: Any = None
        self._numpy: Any = None
        self._prototype_vectors: dict[str, list[list[float]]] = {}
        try:
            import numpy as np
            import onnxruntime as ort
            from transformers import AutoTokenizer

            model_file = verify_model_artifact(model_path, revision, expected_sha256)
            self._numpy = np
            # Model ağdan burada alınmaz; model-init revision ve SHA-256 doğrulaması yapar.
            self._tokenizer = AutoTokenizer.from_pretrained(  # nosec B615
                model_path, local_files_only=True
            )
            self._session = ort.InferenceSession(
                str(model_file),
                providers=["CPUExecutionProvider"],
            )
            for category, values in PROTOTYPES.items():
                self._prototype_vectors[category] = [self._embed(value) for value in values]
            self.available = True
        except (ImportError, OSError, RuntimeError, ValueError):
            self.available = False

    def _embed(self, text: str) -> list[float]:
        np = self._numpy
        tokens = self._tokenizer(
            text,
            return_tensors="np",
            truncation=True,
            max_length=256,
            padding=True,
        )
        inputs = {
            name: value for name, value in tokens.items() if name in {"input_ids", "attention_mask"}
        }
        output = self._session.run(None, inputs)[0]
        mask = tokens["attention_mask"][..., None].astype(np.float32)
        pooled = (output * mask).sum(axis=1) / np.clip(mask.sum(axis=1), 1e-9, None)
        vector = pooled[0]
        vector = vector / np.clip(np.linalg.norm(vector), 1e-9, None)
        return cast(list[float], vector.astype(float).tolist())

    @staticmethod
    def _cosine(first: list[float], second: list[float]) -> float:
        return sum(a * b for a, b in zip(first, second, strict=True)) / max(
            math.sqrt(sum(a * a for a in first)) * math.sqrt(sum(b * b for b in second)),
            1e-9,
        )

    def score(self, text: str) -> tuple[float | None, list[str]]:
        if not self.available:
            return None, []
        vector = self._embed(text)
        similarities = {
            category: max(self._cosine(vector, prototype) for prototype in prototypes)
            for category, prototypes in self._prototype_vectors.items()
        }
        best_similarity = max(similarities.values(), default=0.0)
        calibrated = max(0.0, min(100.0, (best_similarity - 0.25) / 0.55 * 100))
        categories = sorted(
            category for category, similarity in similarities.items() if similarity >= 0.55
        )
        return round(calibrated, 2), categories


def verify_model_artifact(model_path: Path, revision: str, expected_sha256: str = "") -> Path:
    """Manifest, revision ve dosya özetini inference başlamadan doğrular."""

    model_file = model_path / "model_quantized.onnx"
    if not model_file.exists():
        model_file = model_path / "model.onnx"
    manifest_file = model_path / "manifest.json"
    if not model_file.is_file() or not manifest_file.is_file():
        raise ValueError("model artifact or manifest is missing")

    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("revision") != revision:
        raise ValueError("model revision does not match the manifest")
    manifest_sha = str(manifest.get("sha256", "")).lower()
    configured_sha = expected_sha256.lower().strip()
    if configured_sha and manifest_sha != configured_sha:
        raise ValueError("configured model checksum does not match the manifest")

    digest = hashlib.sha256()
    with model_file.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if not manifest_sha or digest.hexdigest() != manifest_sha:
        raise ValueError("model artifact checksum does not match the manifest")
    return model_file
