# tests/test_extract_sketch.py
import json
from unittest.mock import MagicMock

from app.ai import extract_sketch
from app.ai.extract_sketch import extract_sketch_annotations
from app.ai.llm import LLMUnavailable


def _mock_response(readings: list[dict]) -> str:
    return json.dumps({"readings": readings})


def test_reads_written_numbers_and_normalises_to_mm(monkeypatch):
    monkeypatch.setattr(
        extract_sketch,
        "vision_completion",
        MagicMock(return_value=_mock_response([{"raw_value": 1.2, "raw_unit": "m", "confidence": 0.6}])),
    )

    annotations = extract_sketch_annotations(b"fake-bytes", "image/jpeg")

    assert len(annotations) == 1
    assert annotations[0].value_mm == 1200
    assert annotations[0].confidence == 0.6


def test_no_annotations_on_sketch_returns_empty_list(monkeypatch):
    monkeypatch.setattr(extract_sketch, "vision_completion", MagicMock(return_value=_mock_response([])))

    assert extract_sketch_annotations(b"fake-bytes", "image/jpeg") == []


def test_unrecognized_unit_is_skipped_not_crashed(monkeypatch):
    monkeypatch.setattr(
        extract_sketch,
        "vision_completion",
        MagicMock(return_value=_mock_response([{"raw_value": 5, "raw_unit": "cubits", "confidence": 0.3}])),
    )

    assert extract_sketch_annotations(b"fake-bytes", "image/jpeg") == []


def test_llm_unavailable_returns_empty_list_not_crash(monkeypatch):
    monkeypatch.setattr(extract_sketch, "vision_completion", MagicMock(side_effect=LLMUnavailable("down")))

    assert extract_sketch_annotations(b"fake-bytes", "image/jpeg") == []


def test_malformed_json_returns_empty_list_not_crash(monkeypatch):
    monkeypatch.setattr(extract_sketch, "vision_completion", MagicMock(return_value="not json"))

    assert extract_sketch_annotations(b"fake-bytes", "image/jpeg") == []
