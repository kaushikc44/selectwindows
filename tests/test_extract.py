# tests/test_extract.py
# The fixture below represents a worker photo with an iPhone LiDAR overlay
# reading "1.2m x 0.9m" that the model has already converted to integer mm
# (1200 x 900), plus an email body of "bi-fold window, aluminium, laundry".
import json
from pathlib import Path
from unittest.mock import MagicMock

from app.ai import extract
from app.ai.llm import LLMUnavailable

FIXTURE_DIR = Path(__file__).parent / "fixtures"
VALID_JSON = (FIXTURE_DIR / "extraction_valid.json").read_text()

IMAGES = [(b"fake-image-bytes", "image/jpeg")]
BODY_TEXT = "bi-fold window, aluminium, laundry"


def test_valid_fixture_json_is_parsed(monkeypatch):
    monkeypatch.setattr(extract, "vision_completion", MagicMock(return_value=VALID_JSON))

    outcome = extract.extract_quote(IMAGES, BODY_TEXT)

    assert outcome.needs_manual is False
    assert outcome.result.items[0].room == "Laundry"
    assert outcome.result.items[0].height_mm == 1200
    assert outcome.result.items[0].product_type == "bi_fold"


def test_malformed_json_repairs_successfully_on_retry(monkeypatch):
    mock = MagicMock(side_effect=["not json", VALID_JSON])
    monkeypatch.setattr(extract, "vision_completion", mock)

    outcome = extract.extract_quote(IMAGES, BODY_TEXT)

    assert mock.call_count == 2
    assert outcome.needs_manual is False
    assert outcome.result.items[0].product_type == "bi_fold"


def test_malformed_json_twice_marks_needs_manual(monkeypatch):
    mock = MagicMock(side_effect=["not json", "still not json"])
    monkeypatch.setattr(extract, "vision_completion", mock)

    outcome = extract.extract_quote(IMAGES, BODY_TEXT)

    assert mock.call_count == 2
    assert outcome.needs_manual is True
    assert outcome.reason == "unparseable_extraction"
    assert outcome.result is None


def test_llm_unavailable_marks_needs_manual(monkeypatch):
    monkeypatch.setattr(extract, "vision_completion", MagicMock(side_effect=LLMUnavailable("down")))

    outcome = extract.extract_quote(IMAGES, BODY_TEXT)

    assert outcome.needs_manual is True
    assert outcome.reason == "llm_unavailable"
    assert outcome.result is None


def test_low_confidence_item_marks_needs_manual(monkeypatch):
    payload = json.loads(VALID_JSON)
    payload["items"][0]["confidence"] = 0.4
    monkeypatch.setattr(extract, "vision_completion", MagicMock(return_value=json.dumps(payload)))

    outcome = extract.extract_quote(IMAGES, BODY_TEXT)

    assert outcome.needs_manual is True


def test_unreadable_fields_marks_needs_manual(monkeypatch):
    payload = json.loads(VALID_JSON)
    payload["unreadable_fields"] = ["height_mm"]
    monkeypatch.setattr(extract, "vision_completion", MagicMock(return_value=json.dumps(payload)))

    outcome = extract.extract_quote(IMAGES, BODY_TEXT)

    assert outcome.needs_manual is True


def test_unknown_product_type_is_accepted_not_guessed(monkeypatch):
    payload = json.loads(VALID_JSON)
    payload["items"][0]["product_type"] = "unknown"
    payload["items"][0]["material"] = "unknown"
    monkeypatch.setattr(extract, "vision_completion", MagicMock(return_value=json.dumps(payload)))

    outcome = extract.extract_quote(IMAGES, BODY_TEXT)

    assert outcome.result.items[0].product_type == "unknown"
    assert outcome.result.items[0].material == "unknown"


def test_json_with_literal_newline_in_string_field_still_parses(monkeypatch):
    # Models sometimes echo multi-line email text into a string field (e.g.
    # notes) with a raw newline instead of an escaped \n; strict JSON would
    # otherwise reject this outright even though the structure is fine.
    payload = json.loads(VALID_JSON)
    payload["installation"]["notes"] = "line one\nline two"
    raw_with_literal_newline = json.dumps(payload).replace("line one\\nline two", "line one\nline two")
    monkeypatch.setattr(extract, "vision_completion", MagicMock(return_value=raw_with_literal_newline))

    outcome = extract.extract_quote(IMAGES, BODY_TEXT)

    assert outcome.result is not None
    assert "line one" in outcome.result.installation.notes


def test_prompt_includes_body_text(monkeypatch):
    mock = MagicMock(return_value=VALID_JSON)
    monkeypatch.setattr(extract, "vision_completion", mock)

    extract.extract_quote(IMAGES, "sliding door, timber, kitchen")

    sent_prompt = mock.call_args.args[1]
    assert "sliding door, timber, kitchen" in sent_prompt
