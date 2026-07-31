# tests/test_extract_ar.py
import json
from unittest.mock import MagicMock

from app.ai import extract_ar
from app.ai.extract_ar import extract_ar_readings, extract_grouped_readings
from app.ai.llm import LLMUnavailable

IMAGES = [(b"photo1", "image/jpeg"), (b"photo2", "image/jpeg")]


def _mock_response(readings: list[dict]) -> str:
    return json.dumps({"readings": readings})


def test_pairs_overlay_values_and_normalises_units_to_mm(monkeypatch):
    monkeypatch.setattr(
        extract_ar,
        "vision_completion",
        MagicMock(
            return_value=_mock_response(
                [
                    {"raw_value": 79, "raw_unit": "cm", "axis": "width", "confidence": 0.8},
                    {"raw_value": 1.48, "raw_unit": "m", "axis": "height", "confidence": 0.85},
                ]
            )
        ),
    )

    readings = extract_ar_readings(b"fake-bytes", "image/jpeg")

    assert len(readings) == 2
    assert readings[0].value_mm == 790
    assert readings[0].axis == "width"
    assert readings[0].confidence == 0.8
    assert readings[1].value_mm == 1480
    assert readings[1].axis == "height"


def test_unlabelled_axis_preserved_not_guessed(monkeypatch):
    monkeypatch.setattr(
        extract_ar,
        "vision_completion",
        MagicMock(return_value=_mock_response([{"raw_value": 79, "raw_unit": "cm", "confidence": 0.7}])),
    )

    readings = extract_ar_readings(b"fake-bytes", "image/jpeg")

    assert readings[0].axis == "unlabelled"


def test_unrecognized_unit_is_skipped_not_crashed(monkeypatch, caplog):
    monkeypatch.setattr(
        extract_ar,
        "vision_completion",
        MagicMock(
            return_value=_mock_response(
                [
                    {"raw_value": 79, "raw_unit": "furlongs", "axis": "width", "confidence": 0.5},
                    {"raw_value": 900, "raw_unit": "mm", "axis": "height", "confidence": 0.9},
                ]
            )
        ),
    )

    with caplog.at_level("WARNING"):
        readings = extract_ar_readings(b"fake-bytes", "image/jpeg")

    assert len(readings) == 1
    assert readings[0].value_mm == 900
    assert any("unrecognized unit" in r.message for r in caplog.records)


def test_llm_unavailable_returns_empty_list_not_crash(monkeypatch):
    monkeypatch.setattr(extract_ar, "vision_completion", MagicMock(side_effect=LLMUnavailable("down")))

    assert extract_ar_readings(b"fake-bytes", "image/jpeg") == []


def test_malformed_json_returns_empty_list_not_crash(monkeypatch):
    monkeypatch.setattr(extract_ar, "vision_completion", MagicMock(return_value="not json"))

    assert extract_ar_readings(b"fake-bytes", "image/jpeg") == []


def test_no_readings_in_image_returns_empty_list(monkeypatch):
    monkeypatch.setattr(extract_ar, "vision_completion", MagicMock(return_value=_mock_response([])))

    assert extract_ar_readings(b"fake-bytes", "image/jpeg") == []


def _grouped_response(items: list[dict]) -> str:
    return json.dumps({"items": items})


def test_grouped_extraction_groups_multiple_photos_into_two_items(monkeypatch):
    monkeypatch.setattr(
        extract_ar,
        "vision_completion",
        MagicMock(
            return_value=_grouped_response(
                [
                    {
                        "room": None,
                        "description": "large glass window",
                        "readings": [
                            {"raw_value": 3.47, "raw_unit": "m", "axis": "width", "confidence": 0.9},
                            {"raw_value": 2.26, "raw_unit": "m", "axis": "height", "confidence": 0.9},
                        ],
                    },
                    {
                        "room": None,
                        "description": "hinged door",
                        "readings": [
                            {"raw_value": 2.59, "raw_unit": "m", "axis": "unlabelled", "confidence": 0.85}
                        ],
                    },
                ]
            )
        ),
    )

    result = extract_grouped_readings(IMAGES, "sliding window aluminium panels")

    assert len(result.items) == 2
    assert result.items[0].description == "large glass window"
    assert len(result.items[0].readings) == 2
    assert result.items[1].description == "hinged door"
    assert len(result.items[1].readings) == 1


def test_grouped_extraction_room_field_populated_from_text(monkeypatch):
    monkeypatch.setattr(
        extract_ar,
        "vision_completion",
        MagicMock(
            return_value=_grouped_response(
                [{"room": "laundry", "description": "bi-fold window", "readings": []}]
            )
        ),
    )

    result = extract_grouped_readings(IMAGES, "laundry: bi-fold window")

    assert result.items[0].room == "laundry"


def test_grouped_extraction_source_kind_defaults_to_ar_overlay(monkeypatch):
    monkeypatch.setattr(
        extract_ar,
        "vision_completion",
        MagicMock(return_value=_grouped_response([{"room": None, "description": "x", "readings": []}])),
    )

    result = extract_grouped_readings(IMAGES, "text")

    assert result.items[0].source_kind == "ar_overlay"


def test_grouped_extraction_source_kind_sketch_annotation_recognized(monkeypatch):
    monkeypatch.setattr(
        extract_ar,
        "vision_completion",
        MagicMock(
            return_value=_grouped_response(
                [{"room": None, "description": "x", "source_kind": "sketch_annotation", "readings": []}]
            )
        ),
    )

    result = extract_grouped_readings(IMAGES, "text")

    assert result.items[0].source_kind == "sketch_annotation"


def test_grouped_extraction_room_null_when_not_stated(monkeypatch):
    monkeypatch.setattr(
        extract_ar,
        "vision_completion",
        MagicMock(return_value=_grouped_response([{"room": None, "description": "a window", "readings": []}])),
    )

    result = extract_grouped_readings(IMAGES, "no room mentioned here")

    assert result.items[0].room is None


def test_grouped_extraction_empty_images_returns_no_items_without_calling_llm(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr(extract_ar, "vision_completion", mock)

    result = extract_grouped_readings([], "some text")

    assert result.items == []
    mock.assert_not_called()


def test_grouped_extraction_malformed_json_repairs_on_retry(monkeypatch):
    mock = MagicMock(
        side_effect=["not json", _grouped_response([{"room": None, "description": "x", "readings": []}])]
    )
    monkeypatch.setattr(extract_ar, "vision_completion", mock)

    result = extract_grouped_readings(IMAGES, "text")

    assert mock.call_count == 2
    assert len(result.items) == 1


def test_grouped_extraction_malformed_json_twice_returns_no_items(monkeypatch):
    mock = MagicMock(side_effect=["not json", "still not json"])
    monkeypatch.setattr(extract_ar, "vision_completion", mock)

    result = extract_grouped_readings(IMAGES, "text")

    assert mock.call_count == 2
    assert result.items == []


def test_grouped_extraction_llm_unavailable_returns_no_items_not_crash(monkeypatch):
    monkeypatch.setattr(extract_ar, "vision_completion", MagicMock(side_effect=LLMUnavailable("down")))

    result = extract_grouped_readings(IMAGES, "text")

    assert result.items == []


def test_grouped_extraction_sends_all_images_in_one_call(monkeypatch):
    mock = MagicMock(return_value=_grouped_response([]))
    monkeypatch.setattr(extract_ar, "vision_completion", mock)

    extract_grouped_readings(IMAGES, "text")

    assert mock.call_count == 1
    images_arg = mock.call_args.args[0]
    assert images_arg == IMAGES
