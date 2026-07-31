# tests/test_extract_ar_field.py
import json
from unittest.mock import MagicMock

from app.ai import extract_ar_field
from app.ai.extract_ar_field import extract_single_reading
from app.ai.llm import LLMUnavailable


def _response(**overrides) -> str:
    base = {"found": True, "raw_value": 79.0, "raw_unit": "cm", "confidence": 0.9}
    base.update(overrides)
    return json.dumps(base)


def test_reads_the_single_pill_and_normalizes_to_mm(monkeypatch):
    monkeypatch.setattr(extract_ar_field, "vision_completion", MagicMock(return_value=_response()))

    reading = extract_single_reading(b"fake-bytes", "image/jpeg", "width")

    assert reading is not None
    assert reading.value_mm == 790
    assert reading.confidence == 0.9


def test_prompt_asks_for_the_axis_it_was_given(monkeypatch):
    mock = MagicMock(return_value=_response())
    monkeypatch.setattr(extract_ar_field, "vision_completion", mock)

    extract_single_reading(b"fake-bytes", "image/jpeg", "height")

    prompt = mock.call_args.args[1]
    assert "height" in prompt


def test_found_false_returns_none(monkeypatch):
    monkeypatch.setattr(
        extract_ar_field, "vision_completion", MagicMock(return_value=_response(found=False, raw_value=None, raw_unit=None))
    )

    assert extract_single_reading(b"fake-bytes", "image/jpeg", "width") is None


def test_unrecognized_unit_returns_none_not_crash(monkeypatch, caplog):
    monkeypatch.setattr(
        extract_ar_field, "vision_completion", MagicMock(return_value=_response(raw_unit="furlongs"))
    )

    with caplog.at_level("WARNING"):
        result = extract_single_reading(b"fake-bytes", "image/jpeg", "width")

    assert result is None
    assert any("unrecognized unit" in r.message for r in caplog.records)


def test_llm_unavailable_returns_none_not_crash(monkeypatch):
    monkeypatch.setattr(extract_ar_field, "vision_completion", MagicMock(side_effect=LLMUnavailable("down")))

    assert extract_single_reading(b"fake-bytes", "image/jpeg", "width") is None


def test_malformed_json_repairs_on_retry(monkeypatch):
    mock = MagicMock(side_effect=["not json", _response()])
    monkeypatch.setattr(extract_ar_field, "vision_completion", mock)

    result = extract_single_reading(b"fake-bytes", "image/jpeg", "width")

    assert mock.call_count == 2
    assert result is not None
    assert result.value_mm == 790


def test_malformed_json_twice_returns_none(monkeypatch):
    mock = MagicMock(side_effect=["not json", "still not json"])
    monkeypatch.setattr(extract_ar_field, "vision_completion", mock)

    result = extract_single_reading(b"fake-bytes", "image/jpeg", "width")

    assert mock.call_count == 2
    assert result is None
