from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .config import get_settings


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as model_file:
        for chunk in iter(lambda: model_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def export_model() -> None:
    settings = get_settings()
    target = settings.CTI_MODEL_PATH
    target.mkdir(parents=True, exist_ok=True)
    quantized = target / "model_quantized.onnx"
    manifest_path = target / "manifest.json"

    if not quantized.exists():
        from optimum.onnxruntime import ORTModelForFeatureExtraction, ORTQuantizer
        from optimum.onnxruntime.configuration import AutoQuantizationConfig
        from transformers import AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(
            settings.CTI_MODEL_ID,
            revision=settings.CTI_MODEL_REVISION,
        )
        model = ORTModelForFeatureExtraction.from_pretrained(
            settings.CTI_MODEL_ID,
            revision=settings.CTI_MODEL_REVISION,
            export=True,
        )
        model.save_pretrained(target)
        tokenizer.save_pretrained(target)
        quantizer = ORTQuantizer.from_pretrained(target)
        quantizer.quantize(
            save_dir=target,
            quantization_config=AutoQuantizationConfig.avx2(is_static=False, per_channel=False),
            file_suffix="quantized",
        )
    elif manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(existing, dict) or (
            existing.get("model_id") != settings.CTI_MODEL_ID
            or existing.get("revision") != settings.CTI_MODEL_REVISION
        ):
            raise RuntimeError("existing model artifact belongs to another model revision")
    else:
        raise RuntimeError("existing model artifact has no integrity manifest")

    actual = sha256_file(quantized)
    expected = settings.CTI_MODEL_SHA256.lower().strip()
    if expected and actual != expected:
        raise RuntimeError("quantized model checksum does not match CTI_MODEL_SHA256")
    manifest_path.write_text(
        json.dumps(
            {
                "model_id": settings.CTI_MODEL_ID,
                "revision": settings.CTI_MODEL_REVISION,
                "sha256": actual,
                "training_on_x_content": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Model ready. SHA256={actual}")


if __name__ == "__main__":
    export_model()
