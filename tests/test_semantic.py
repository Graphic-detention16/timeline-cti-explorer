from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from timeline_cti.semantic import verify_model_artifact


def write_artifact(path: Path, revision: str, content: bytes = b"onnx-fixture") -> str:
    model = path / "model_quantized.onnx"
    model.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    (path / "manifest.json").write_text(
        json.dumps({"revision": revision, "sha256": digest}),
        encoding="utf-8",
    )
    return digest


def test_model_artifact_requires_matching_revision_and_hash(tmp_path: Path) -> None:
    digest = write_artifact(tmp_path, "pinned-revision")
    assert verify_model_artifact(tmp_path, "pinned-revision", digest).name == (
        "model_quantized.onnx"
    )

    with pytest.raises(ValueError, match="revision"):
        verify_model_artifact(tmp_path, "other-revision", digest)


def test_model_artifact_rejects_tampering(tmp_path: Path) -> None:
    digest = write_artifact(tmp_path, "pinned-revision")
    (tmp_path / "model_quantized.onnx").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="artifact checksum"):
        verify_model_artifact(tmp_path, "pinned-revision", digest)
