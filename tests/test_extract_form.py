# tests/test_extract_form.py
import json
from pathlib import Path
from unittest.mock import MagicMock

from app.ai import extract_form
from app.ai.extract_form import extract_form as run_extract_form
from app.ai.llm import LLMUnavailable

FIXTURE_DIR = Path(__file__).parent / "fixtures"
VALID_JSON = (FIXTURE_DIR / "extraction_valid.json").read_text()

IMAGES = [(b"fake-form-page-bytes", "image/jpeg")]
BODY_TEXT = "bi-fold window, aluminium, laundry"


def test_valid_fixture_json_is_parsed(monkeypatch):
    monkeypatch.setattr(extract_form, "vision_completion", MagicMock(return_value=VALID_JSON))

    outcome = run_extract_form(IMAGES, BODY_TEXT)

    assert outcome.needs_manual is False
    assert outcome.result.items[0].height_mm == 1200
    assert outcome.result.items[0].product_type == "bi_fold"


def test_resolved_dimensions_stamped_as_form_field_reading(monkeypatch):
    monkeypatch.setattr(extract_form, "vision_completion", MagicMock(return_value=VALID_JSON))

    outcome = run_extract_form(IMAGES, BODY_TEXT)

    item = outcome.result.items[0]
    assert len(item.height_readings) == 1
    assert item.height_readings[0].value_mm == item.height_mm
    assert item.height_readings[0].source == "form_field"
    assert len(item.width_readings) == 1
    assert item.width_readings[0].source == "form_field"


def test_config_code_field_is_parsed_when_present(monkeypatch):
    payload = json.loads(VALID_JSON)
    payload["items"][0]["config_code"] = "BFW-3"
    monkeypatch.setattr(extract_form, "vision_completion", MagicMock(return_value=json.dumps(payload)))

    outcome = run_extract_form(IMAGES, BODY_TEXT)

    assert outcome.result.items[0].config_code == "BFW-3"


def test_malformed_json_repairs_successfully_on_retry(monkeypatch):
    mock = MagicMock(side_effect=["not json", VALID_JSON])
    monkeypatch.setattr(extract_form, "vision_completion", mock)

    outcome = run_extract_form(IMAGES, BODY_TEXT)

    assert mock.call_count == 2
    assert outcome.needs_manual is False


def test_malformed_json_twice_marks_needs_manual(monkeypatch):
    mock = MagicMock(side_effect=["not json", "still not json"])
    monkeypatch.setattr(extract_form, "vision_completion", mock)

    outcome = run_extract_form(IMAGES, BODY_TEXT)

    assert mock.call_count == 2
    assert outcome.needs_manual is True
    assert outcome.reason == "unparseable_extraction"
    assert outcome.result is None


def test_llm_unavailable_marks_needs_manual(monkeypatch):
    monkeypatch.setattr(extract_form, "vision_completion", MagicMock(side_effect=LLMUnavailable("down")))

    outcome = run_extract_form(IMAGES, BODY_TEXT)

    assert outcome.needs_manual is True
    assert outcome.reason == "llm_unavailable"
    assert outcome.result is None


def test_circled_option_unmarked_is_never_guessed(monkeypatch):
    monkeypatch.setattr(extract_form, "vision_completion", MagicMock(return_value=VALID_JSON))

    outcome = run_extract_form(IMAGES, BODY_TEXT)

    assert outcome.result.header.wind_rating == "unmarked"
