"""Image OCR for drawing sheets.

Runs in the serve container, where the RapidOCR/ONNX models are installed. The
task container has no OCR stack; the harness reads image bytes over the
protocol and writes the recognized text back to the task's scratch directory so
the model can read it without building its own OCR pipeline.
"""

from __future__ import annotations

import tempfile

try:
    from rapidocr_onnxruntime import RapidOCR
except Exception:  # pragma: no cover - optional dependency
    RapidOCR = None

_ENGINE = None


def available() -> bool:
    """Returns whether the OCR engine is installed."""
    return RapidOCR is not None


def _engine():
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = RapidOCR()
    return _ENGINE


def ocr_image(data: bytes, suffix: str) -> list[str]:
    """OCR an image and return its text lines, or an empty list on failure."""
    if RapidOCR is None or not data:
        return []
    path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix or ".png", delete=False) as fh:
            fh.write(data)
            path = fh.name
        result, _ = _engine()(path)
        return [str(line[1]) for line in (result or []) if len(line) > 1]
    except Exception:
        return []
    finally:
        if path:
            try:
                import os

                os.unlink(path)
            except OSError:
                pass
