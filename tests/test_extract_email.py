# tests/test_extract_email.py
import json
from unittest.mock import MagicMock

from app.ai import extract_email
from app.ai.extract_email import extract_email_fields
from app.ai.llm import LLMUnavailable


def test_fields_present_in_body_are_tagged_email_body(monkeypatch):
    monkeypatch.setattr(
        extract_email,
        "chat_completion",
        MagicMock(
            return_value=json.dumps(
                {
                    "client_name": "Sarah Nguyen",
                    "room": "laundry",
                    "product_hint": "bi-fold window, aluminium",
                    "site_notes": "asbestos in eaves",
                }
            )
        ),
    )

    fields = extract_email_fields("Sarah Nguyen, laundry, bi-fold window aluminium, asbestos in eaves")

    assert fields["client_name"].value == "Sarah Nguyen"
    assert fields["client_name"].source == "email_body"
    assert fields["site_notes"].value == "asbestos in eaves"


def test_absent_fields_tagged_missing(monkeypatch):
    monkeypatch.setattr(
        extract_email,
        "chat_completion",
        MagicMock(return_value=json.dumps({"client_name": None, "room": None, "product_hint": None, "site_notes": None})),
    )

    fields = extract_email_fields("just a photo, no details")

    assert fields["client_name"].source == "missing"
    assert fields["client_name"].value is None


def test_empty_body_text_short_circuits_without_llm_call(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr(extract_email, "chat_completion", mock)

    fields = extract_email_fields("")

    mock.assert_not_called()
    assert all(fv.source == "missing" for fv in fields.values())


def test_llm_unavailable_returns_all_missing_not_crash(monkeypatch):
    monkeypatch.setattr(extract_email, "chat_completion", MagicMock(side_effect=LLMUnavailable("down")))

    fields = extract_email_fields("Sarah Nguyen, laundry")

    assert all(fv.source == "missing" for fv in fields.values())


def test_malformed_json_returns_all_missing_not_crash(monkeypatch):
    monkeypatch.setattr(extract_email, "chat_completion", MagicMock(return_value="not json"))

    fields = extract_email_fields("Sarah Nguyen, laundry")

    assert all(fv.source == "missing" for fv in fields.values())


def test_typed_dimensions_extracted_with_raw_value_and_unit(monkeypatch):
    monkeypatch.setattr(
        extract_email,
        "chat_completion",
        MagicMock(
            return_value=json.dumps(
                {
                    "client_name": None,
                    "room": None,
                    "product_hint": None,
                    "site_notes": None,
                    "width_value": 2400,
                    "width_unit": "mm",
                    "height_value": 2.1,
                    "height_unit": "m",
                }
            )
        ),
    )

    fields = extract_email_fields("Width: 2400 mm\nHeight: 2.1m")

    assert fields["width"].source == "email_body"
    assert fields["width"].value.raw_value == 2400
    assert fields["width"].value.raw_unit == "mm"
    assert fields["height"].value.raw_value == 2.1
    assert fields["height"].value.raw_unit == "m"


def test_no_typed_dimensions_stated_tagged_missing(monkeypatch):
    monkeypatch.setattr(
        extract_email,
        "chat_completion",
        MagicMock(
            return_value=json.dumps(
                {
                    "client_name": "Sarah Nguyen",
                    "room": None,
                    "product_hint": None,
                    "site_notes": None,
                    "width_value": None,
                    "width_unit": None,
                    "height_value": None,
                    "height_unit": None,
                }
            )
        ),
    )

    fields = extract_email_fields("Sarah Nguyen wants a bi-fold window")

    assert fields["width"].source == "missing"
    assert fields["width"].value is None
    assert fields["height"].source == "missing"


def test_dimension_value_without_unit_treated_as_missing(monkeypatch):
    # a bare number with no unit is too ambiguous to treat as a real reading
    monkeypatch.setattr(
        extract_email,
        "chat_completion",
        MagicMock(
            return_value=json.dumps(
                {
                    "client_name": None,
                    "room": None,
                    "product_hint": None,
                    "site_notes": None,
                    "width_value": 2400,
                    "width_unit": None,
                    "height_value": None,
                    "height_unit": None,
                }
            )
        ),
    )

    fields = extract_email_fields("some text with a stray number 2400")

    assert fields["width"].source == "missing"
