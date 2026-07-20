# tests/test_extract.py
import json
from pathlib import Path
from unittest.mock import MagicMock

from app.ai import extract
from app.ai.llm import LLMUnavailable

FIXTURE_DIR = Path(__file__).parent / "fixtures"
VALID_JSON = (FIXTURE_DIR / "extraction_valid.json").read_text()


def test_valid_fixture_json_is_parsed(monkeypatch):
    monkeypatch.setattr(extract, "vision_completion", MagicMock(return_value=VALID_JSON))

    outcome = extract.extract_panels(b"fake-image-bytes")

    assert outcome.needs_manual is False
    assert outcome.result.panels[0].label == "W1"
    assert outcome.result.panels[0].width_mm == 1200
    assert outcome.result.panels[0].glass_type == "toughened"


def test_malformed_json_repairs_successfully_on_retry(monkeypatch):
    calls = [MagicMock(return_value="not json"), MagicMock(return_value=VALID_JSON)]
    mock = MagicMock(side_effect=[c.return_value for c in calls])
    monkeypatch.setattr(extract, "vision_completion", mock)

    outcome = extract.extract_panels(b"fake-image-bytes")

    assert mock.call_count == 2
    assert outcome.needs_manual is False
    assert outcome.result.panels[0].label == "W1"


def test_malformed_json_twice_marks_needs_manual(monkeypatch):
    mock = MagicMock(side_effect=["not json", "still not json"])
    monkeypatch.setattr(extract, "vision_completion", mock)

    outcome = extract.extract_panels(b"fake-image-bytes")

    assert mock.call_count == 2
    assert outcome.needs_manual is True
    assert outcome.reason == "unparseable_extraction"
    assert outcome.result is None


def test_llm_unavailable_marks_needs_manual(monkeypatch):
    monkeypatch.setattr(extract, "vision_completion", MagicMock(side_effect=LLMUnavailable("down")))

    outcome = extract.extract_panels(b"fake-image-bytes")

    assert outcome.needs_manual is True
    assert outcome.reason == "llm_unavailable"
    assert outcome.result is None


def test_low_confidence_panel_marks_needs_manual(monkeypatch):
    payload = json.loads(VALID_JSON)
    payload["panels"][0]["confidence"] = 0.4
    monkeypatch.setattr(extract, "vision_completion", MagicMock(return_value=json.dumps(payload)))

    outcome = extract.extract_panels(b"fake-image-bytes")

    assert outcome.needs_manual is True
    assert outcome.reason == "low_confidence_panel"


def test_unknown_glass_type_defaults_to_clear_float_and_flagged(monkeypatch):
    payload = json.loads(VALID_JSON)
    payload["panels"][0]["glass_type"] = "unknown"
    monkeypatch.setattr(extract, "vision_completion", MagicMock(return_value=json.dumps(payload)))

    outcome = extract.extract_panels(b"fake-image-bytes")

    panel = outcome.result.panels[0]
    assert panel.glass_type == "clear_float"
    assert panel.glass_type_flagged is True
