# tests/test_routing.py
import json
from pathlib import Path
from unittest.mock import MagicMock

from app.ai import classify, extract_ar, extract_email, extract_form
from app.workers.routing import classify_images, extract_from_attachments

FIXTURE_DIR = Path(__file__).parent / "fixtures"
FORM_JSON = (FIXTURE_DIR / "extraction_valid.json").read_text()


def _grouped_response(items):
    return json.dumps({"items": items})


def _mock_email_fields(
    monkeypatch,
    client_name=None,
    site_notes=None,
    width_value=None,
    width_unit=None,
    height_value=None,
    height_unit=None,
):
    monkeypatch.setattr(
        extract_email,
        "chat_completion",
        MagicMock(
            return_value=json.dumps(
                {
                    "client_name": client_name,
                    "room": None,
                    "product_hint": None,
                    "site_notes": site_notes,
                    "width_value": width_value,
                    "width_unit": width_unit,
                    "height_value": height_value,
                    "height_unit": height_unit,
                }
            )
        ),
    )


def test_classify_images_returns_one_label_per_image(monkeypatch):
    monkeypatch.setattr(
        classify, "vision_completion", MagicMock(side_effect=[json.dumps({"label": "ar_measure"}), json.dumps({"label": "site_photo"})])
    )

    kinds = classify_images([(b"img1", "image/jpeg"), (b"img2", "image/jpeg")])

    assert kinds == ["ar_measure", "site_photo"]


def test_form_images_route_to_extract_form(monkeypatch):
    monkeypatch.setattr(extract_form, "vision_completion", MagicMock(return_value=FORM_JSON))

    outcome = extract_from_attachments(
        [(b"form-bytes", "image/jpeg")], ["form_page1"], "bi-fold window, aluminium, laundry"
    )

    assert outcome.needs_manual is False
    assert outcome.result.items[0].product_type == "bi_fold"


def test_ar_only_single_item_builds_from_grouped_call(monkeypatch):
    monkeypatch.setattr(
        extract_ar,
        "vision_completion",
        MagicMock(
            return_value=_grouped_response(
                [
                    {
                        "room": "backyard",
                        "description": "alum bifold replacing french doors",
                        "readings": [
                            {"raw_value": 79, "raw_unit": "cm", "axis": "width", "confidence": 0.8},
                            {"raw_value": 148, "raw_unit": "cm", "axis": "height", "confidence": 0.85},
                        ],
                    }
                ]
            )
        ),
    )
    _mock_email_fields(monkeypatch, client_name="Sarah Nguyen", site_notes="asbestos in eaves")

    outcome = extract_from_attachments(
        [(b"ar-bytes", "image/jpeg")],
        ["ar_measure"],
        "Sarah Nguyen, backyard, alum bifold replacing french doors, asbestos in eaves",
    )

    assert outcome.result is not None
    item = outcome.result.items[0]
    assert item.width_mm == 790
    assert item.height_mm == 1480
    assert item.room == "backyard"
    assert item.product_type == "bi_fold"
    assert item.material == "aluminium"
    assert outcome.result.header.client_name == "Sarah Nguyen"
    assert outcome.result.installation.asbestos == "yes"
    assert any(r.source == "ar_overlay" for r in item.width_readings)


def test_two_visually_distinct_photo_groups_become_two_independent_items(monkeypatch):
    # regression: previously all photos in one email were pooled into a
    # single item, so a large window (3470x2260mm) and a separate hinged
    # door (2590mm) produced a spurious cross-item dimension conflict.
    monkeypatch.setattr(
        extract_ar,
        "vision_completion",
        MagicMock(
            return_value=_grouped_response(
                [
                    {
                        "room": None,
                        "description": "sliding window aluminium",
                        "source_kind": "ar_overlay",
                        "readings": [
                            {"raw_value": 3.47, "raw_unit": "m", "axis": "width", "confidence": 1.0},
                            {"raw_value": 2.26, "raw_unit": "m", "axis": "height", "confidence": 1.0},
                        ],
                    },
                    {
                        "room": None,
                        "description": "hinged door",
                        "source_kind": "ar_overlay",
                        "readings": [
                            {"raw_value": 2.59, "raw_unit": "m", "axis": "unlabelled", "confidence": 1.0},
                            {"raw_value": 2.10, "raw_unit": "m", "axis": "unlabelled", "confidence": 1.0},
                        ],
                    },
                ]
            )
        ),
    )
    _mock_email_fields(monkeypatch, client_name="ingrity")

    outcome = extract_from_attachments(
        [(b"img1", "image/jpeg")] * 5, ["ar_measure"] * 5, "Product type sliding window aluminium panels"
    )

    assert outcome.needs_manual is False
    assert len(outcome.result.items) == 2
    window, door = outcome.result.items
    assert window.width_mm == 3470
    assert window.height_mm == 2260
    assert window.product_type == "sliding"
    assert door.width_mm == 2590
    assert door.height_mm == 2100
    assert door.product_type == "hinged"


def test_partial_width_segments_are_summed_not_conflict_checked(monkeypatch):
    # regression: a wide sliding door opening split into a glazed section
    # (2.26m) and a solid infill panel (2.59m), sharing the same height,
    # is ONE item whose total width is the SUM of the sections (4.85m) —
    # not two conflicting width readings of the same edge.
    monkeypatch.setattr(
        extract_ar,
        "vision_completion",
        MagicMock(
            return_value=_grouped_response(
                [
                    {
                        "room": None,
                        "description": "sliding door with glazed and solid panel sections",
                        "product_type_hint": "sliding",
                        "readings": [
                            {"raw_value": 3.47, "raw_unit": "m", "axis": "height", "segment": "full", "confidence": 1.0},
                            {"raw_value": 3.47, "raw_unit": "m", "axis": "height", "segment": "full", "confidence": 1.0},
                            {"raw_value": 2.26, "raw_unit": "m", "axis": "width", "segment": "partial", "confidence": 1.0},
                            {"raw_value": 2.59, "raw_unit": "m", "axis": "width", "segment": "partial", "confidence": 1.0},
                        ],
                    }
                ]
            )
        ),
    )
    _mock_email_fields(monkeypatch)

    outcome = extract_from_attachments([(b"img1", "image/jpeg")] * 5, ["ar_measure"] * 5, "sliding door")

    assert outcome.needs_manual is False
    assert len(outcome.result.items) == 1
    item = outcome.result.items[0]
    assert item.width_mm == 4850
    assert item.height_mm == 3470


def test_summed_partial_segments_can_exceed_old_6000mm_single_window_cap(monkeypatch):
    # regression: a large commercial opening's sections can sum past 6000mm
    # (e.g. 3470mm + 2590mm = 6060mm) even though no *single* window/door
    # ever does — this used to raise an uncaught pydantic ValidationError
    # deep inside dimension merging and crash the whole pipeline run.
    monkeypatch.setattr(
        extract_ar,
        "vision_completion",
        MagicMock(
            return_value=_grouped_response(
                [
                    {
                        "room": None,
                        "description": "large commercial glazed partition",
                        "readings": [
                            {"raw_value": 3470, "raw_unit": "mm", "axis": "height", "segment": "full", "confidence": 1.0},
                            {"raw_value": 3470, "raw_unit": "mm", "axis": "width", "segment": "partial", "confidence": 1.0},
                            {"raw_value": 2590, "raw_unit": "mm", "axis": "width", "segment": "partial", "confidence": 1.0},
                        ],
                    }
                ]
            )
        ),
    )
    _mock_email_fields(monkeypatch)

    outcome = extract_from_attachments([(b"img1", "image/jpeg")] * 5, ["ar_measure"] * 5, "sliding door")

    assert outcome.needs_manual is False
    assert outcome.result.items[0].width_mm == 6060


def test_partial_segments_confidence_uses_minimum_of_sections(monkeypatch):
    monkeypatch.setattr(
        extract_ar,
        "vision_completion",
        MagicMock(
            return_value=_grouped_response(
                [
                    {
                        "room": None,
                        "description": "sliding door",
                        "readings": [
                            {"raw_value": 900, "raw_unit": "mm", "axis": "height", "confidence": 0.9},
                            {"raw_value": 1000, "raw_unit": "mm", "axis": "width", "segment": "partial", "confidence": 0.9},
                            {"raw_value": 1200, "raw_unit": "mm", "axis": "width", "segment": "partial", "confidence": 0.4},
                        ],
                    }
                ]
            )
        ),
    )
    _mock_email_fields(monkeypatch)

    outcome = extract_from_attachments([(b"img1", "image/jpeg")], ["ar_measure"], "")

    item = outcome.result.items[0]
    assert item.width_mm == 2200
    assert any(r.confidence == 0.4 for r in item.width_readings)


def test_conflict_in_one_item_does_not_use_other_items_readings(monkeypatch):
    monkeypatch.setattr(
        extract_ar,
        "vision_completion",
        MagicMock(
            return_value=_grouped_response(
                [
                    {
                        "room": None,
                        "description": "window",
                        "readings": [
                            {"raw_value": 900, "raw_unit": "mm", "axis": "width", "confidence": 0.9},
                            {"raw_value": 1200, "raw_unit": "mm", "axis": "height", "confidence": 0.9},
                        ],
                    },
                    {
                        "room": None,
                        "description": "door with conflicting readings",
                        "readings": [
                            {"raw_value": 790, "raw_unit": "mm", "axis": "width", "confidence": 0.9},
                            {"raw_value": 2000, "raw_unit": "mm", "axis": "width", "confidence": 0.9},
                        ],
                    },
                ]
            )
        ),
    )
    _mock_email_fields(monkeypatch)

    outcome = extract_from_attachments([(b"img1", "image/jpeg")] * 2, ["ar_measure"] * 2, "")

    assert outcome.needs_manual is True
    assert outcome.reason == "dimension_conflict_item_2_width"
    assert outcome.result is None
    assert outcome.conflict_readings is not None
    assert {r.value_mm for r in outcome.conflict_readings} == {790, 2000}


def test_readings_within_tolerance_resolve_to_minimum_and_flagged_not_conflicted(monkeypatch):
    # regression: two real AR-overlay photos of the same edge came back
    # 2700mm/2470mm (~8.5% apart) and used to raise a spurious conflict —
    # now resolved to the minimum, with dimensions_multi_reading set so
    # it's still visible (never a silent average or max).
    monkeypatch.setattr(
        extract_ar,
        "vision_completion",
        MagicMock(
            return_value=_grouped_response(
                [
                    {
                        "room": None,
                        "description": "sliding window",
                        "readings": [
                            {"raw_value": 2700, "raw_unit": "mm", "axis": "height", "confidence": 0.9},
                            {"raw_value": 2470, "raw_unit": "mm", "axis": "height", "confidence": 0.9},
                            {"raw_value": 1900, "raw_unit": "mm", "axis": "width", "confidence": 0.9},
                        ],
                    }
                ]
            )
        ),
    )
    _mock_email_fields(monkeypatch)

    outcome = extract_from_attachments([(b"img1", "image/jpeg")] * 2, ["ar_measure"] * 2, "")

    assert outcome.needs_manual is False
    item = outcome.result.items[0]
    assert item.height_mm == 2470  # min(2700, 2470)
    assert item.dimensions_multi_reading is True


def test_product_type_hint_takes_priority_over_description(monkeypatch):
    # regression: an item's visual description ("large multi-pane glass
    # window partition") often doesn't contain Select's taxonomy words even
    # when product_type_hint correctly does — hint must win when present.
    monkeypatch.setattr(
        extract_ar,
        "vision_completion",
        MagicMock(
            return_value=_grouped_response(
                [
                    {
                        "room": None,
                        "description": "large multi-pane glass window partition",
                        "product_type_hint": "sliding",
                        "readings": [
                            {"raw_value": 3470, "raw_unit": "mm", "axis": "width", "confidence": 1.0},
                            {"raw_value": 2260, "raw_unit": "mm", "axis": "height", "confidence": 1.0},
                        ],
                    }
                ]
            )
        ),
    )
    _mock_email_fields(monkeypatch)

    outcome = extract_from_attachments([(b"img1", "image/jpeg")], ["ar_measure"], "sliding window aluminium panels")

    assert outcome.result.items[0].product_type == "sliding"


def test_single_item_material_found_in_body_text_even_when_description_present(monkeypatch):
    # regression: the vision model's description ("large multi-pane glass
    # window partition") almost always exists and doesn't mention material,
    # so an either/or fallback chain (hint -> description -> body_text)
    # permanently shadowed body-text material info like "Aluminium Sliding
    # Door" that only the client's email actually stated.
    monkeypatch.setattr(
        extract_ar,
        "vision_completion",
        MagicMock(
            return_value=_grouped_response(
                [
                    {
                        "room": None,
                        "description": "large multi-pane glass window/door with black mullions",
                        "product_type_hint": None,
                        "readings": [
                            {"raw_value": 2260, "raw_unit": "mm", "axis": "width", "confidence": 1.0},
                            {"raw_value": 3470, "raw_unit": "mm", "axis": "height", "confidence": 1.0},
                        ],
                    }
                ]
            )
        ),
    )
    _mock_email_fields(monkeypatch)

    outcome = extract_from_attachments(
        [(b"img1", "image/jpeg")], ["ar_measure"], "Product: Aluminium Sliding Door"
    )

    item = outcome.result.items[0]
    assert item.product_type == "sliding"
    assert item.material == "aluminium"


def test_multi_item_material_not_cross_contaminated_from_body_text(monkeypatch):
    monkeypatch.setattr(
        extract_ar,
        "vision_completion",
        MagicMock(
            return_value=_grouped_response(
                [
                    {
                        "room": None,
                        "description": "window",
                        "product_type_hint": "sliding",
                        "readings": [
                            {"raw_value": 900, "raw_unit": "mm", "axis": "width", "confidence": 1.0},
                            {"raw_value": 1200, "raw_unit": "mm", "axis": "height", "confidence": 1.0},
                        ],
                    },
                    {
                        "room": None,
                        "description": "door, no material stated for this one",
                        "product_type_hint": "hinged",
                        "readings": [
                            {"raw_value": 800, "raw_unit": "mm", "axis": "width", "confidence": 1.0},
                            {"raw_value": 2000, "raw_unit": "mm", "axis": "height", "confidence": 1.0},
                        ],
                    },
                ]
            )
        ),
    )
    _mock_email_fields(monkeypatch)

    outcome = extract_from_attachments(
        [(b"img1", "image/jpeg")] * 2, ["ar_measure"] * 2, "aluminium throughout, sliding window in lounge"
    )

    assert outcome.result.items[0].material == "unknown"  # "window" description never mentions aluminium
    assert outcome.result.items[1].material == "unknown"  # never guessed from shared body text either


def test_single_item_falls_back_to_body_text_when_no_hint_or_description(monkeypatch):
    monkeypatch.setattr(
        extract_ar,
        "vision_completion",
        MagicMock(
            return_value=_grouped_response(
                [
                    {
                        "room": None,
                        "description": None,
                        "product_type_hint": None,
                        "readings": [
                            {"raw_value": 900, "raw_unit": "mm", "axis": "width", "confidence": 1.0},
                            {"raw_value": 1200, "raw_unit": "mm", "axis": "height", "confidence": 1.0},
                        ],
                    }
                ]
            )
        ),
    )
    _mock_email_fields(monkeypatch)

    outcome = extract_from_attachments([(b"img1", "image/jpeg")], ["ar_measure"], "bi-fold window aluminium")

    assert outcome.result.items[0].product_type == "bi_fold"


def test_multi_item_does_not_cross_contaminate_from_shared_body_text(monkeypatch):
    # regression: with 2+ items, falling back to the whole shared body_text
    # for an item with no hint/description risked tagging it with a product
    # type that actually named a DIFFERENT item in the same email.
    monkeypatch.setattr(
        extract_ar,
        "vision_completion",
        MagicMock(
            return_value=_grouped_response(
                [
                    {
                        "room": None,
                        "description": "window",
                        "product_type_hint": "sliding",
                        "readings": [
                            {"raw_value": 900, "raw_unit": "mm", "axis": "width", "confidence": 1.0},
                            {"raw_value": 1200, "raw_unit": "mm", "axis": "height", "confidence": 1.0},
                        ],
                    },
                    {
                        "room": None,
                        "description": None,
                        "product_type_hint": None,
                        "readings": [
                            {"raw_value": 800, "raw_unit": "mm", "axis": "width", "confidence": 1.0},
                            {"raw_value": 2000, "raw_unit": "mm", "axis": "height", "confidence": 1.0},
                        ],
                    },
                ]
            )
        ),
    )
    _mock_email_fields(monkeypatch)

    outcome = extract_from_attachments(
        [(b"img1", "image/jpeg")] * 2, ["ar_measure"] * 2, "sliding window aluminium panels"
    )

    assert outcome.result.items[0].product_type == "sliding"
    assert outcome.result.items[1].product_type == "unknown"  # never guessed from item 1's text


def test_no_dimension_data_at_all_marks_needs_manual(monkeypatch):
    monkeypatch.setattr(extract_ar, "vision_completion", MagicMock(return_value=_grouped_response([])))
    _mock_email_fields(monkeypatch)

    outcome = extract_from_attachments([(b"img1", "image/jpeg")], ["ar_measure"], "")

    assert outcome.needs_manual is True
    assert outcome.reason == "insufficient_dimension_data"


def test_sketch_only_input_tagged_sketch_annotation_source(monkeypatch):
    monkeypatch.setattr(
        extract_ar,
        "vision_completion",
        MagicMock(
            return_value=_grouped_response(
                [
                    {
                        "room": "kitchen",
                        "description": "sliding door timber",
                        "source_kind": "sketch_annotation",
                        "readings": [
                            {"raw_value": 900, "raw_unit": "mm", "axis": "width", "confidence": 0.5},
                            {"raw_value": 1200, "raw_unit": "mm", "axis": "height", "confidence": 0.5},
                        ],
                    }
                ]
            )
        ),
    )
    _mock_email_fields(monkeypatch)

    outcome = extract_from_attachments([(b"sketch-bytes", "image/jpeg")], ["hand_sketch"], "sliding door timber, kitchen")

    assert outcome.result is not None
    item = outcome.result.items[0]
    assert item.product_type == "sliding"
    assert item.material == "timber"
    assert item.room == "kitchen"
    assert all(r.source == "sketch_annotation" for r in item.width_readings + item.height_readings)


def test_grouped_call_receives_all_non_form_images_together(monkeypatch):
    mock = MagicMock(return_value=_grouped_response([]))
    monkeypatch.setattr(extract_ar, "vision_completion", mock)
    _mock_email_fields(monkeypatch)

    extract_from_attachments(
        [(b"img1", "image/jpeg"), (b"img2", "image/jpeg"), (b"img3", "image/jpeg")],
        ["ar_measure", "site_photo", "hand_sketch"],
        "",
    )

    assert mock.call_count == 1
    images_arg = mock.call_args.args[0]
    assert images_arg == [(b"img1", "image/jpeg"), (b"img3", "image/jpeg")]  # site_photo excluded


def test_single_item_typed_dimension_used_when_no_photo_reading_present(monkeypatch):
    # test4-style case: the rep typed "Width: 2400 mm / Height: 2100 mm" in
    # the body and the photos don't independently confirm either axis, so
    # the typed value is the only candidate and should resolve cleanly.
    monkeypatch.setattr(
        extract_ar,
        "vision_completion",
        MagicMock(
            return_value=_grouped_response(
                [
                    {
                        "room": None,
                        "description": "aluminium sliding door",
                        "product_type_hint": "sliding",
                        "readings": [],
                    }
                ]
            )
        ),
    )
    _mock_email_fields(monkeypatch, width_value=2400, width_unit="mm", height_value=2100, height_unit="mm")

    outcome = extract_from_attachments(
        [(b"img1", "image/jpeg")], ["ar_measure"], "Product: Aluminium Sliding Door\nWidth: 2400 mm\nHeight: 2100 mm"
    )

    assert outcome.needs_manual is False
    item = outcome.result.items[0]
    assert item.width_mm == 2400
    assert item.height_mm == 2100
    assert any(r.source == "email_body" for r in item.width_readings)
    assert any(r.source == "email_body" for r in item.height_readings)


def test_single_item_typed_dimension_agrees_with_photo_reading(monkeypatch):
    monkeypatch.setattr(
        extract_ar,
        "vision_completion",
        MagicMock(
            return_value=_grouped_response(
                [
                    {
                        "room": None,
                        "description": "aluminium sliding door",
                        "readings": [
                            {"raw_value": 2400, "raw_unit": "mm", "axis": "width", "confidence": 0.9},
                            {"raw_value": 2100, "raw_unit": "mm", "axis": "height", "confidence": 0.9},
                        ],
                    }
                ]
            )
        ),
    )
    _mock_email_fields(monkeypatch, width_value=2400, width_unit="mm", height_value=2100, height_unit="mm")

    outcome = extract_from_attachments(
        [(b"img1", "image/jpeg")], ["ar_measure"], "Width: 2400 mm / Height: 2100 mm"
    )

    assert outcome.needs_manual is False
    item = outcome.result.items[0]
    assert item.width_mm == 2400
    assert item.height_mm == 2100


def test_single_item_typed_dimension_conflicting_with_photo_raises_conflict(monkeypatch):
    monkeypatch.setattr(
        extract_ar,
        "vision_completion",
        MagicMock(
            return_value=_grouped_response(
                [
                    {
                        "room": None,
                        "description": "aluminium sliding door",
                        "readings": [
                            {"raw_value": 2400, "raw_unit": "mm", "axis": "width", "confidence": 0.9},
                            {"raw_value": 2100, "raw_unit": "mm", "axis": "height", "confidence": 0.9},
                        ],
                    }
                ]
            )
        ),
    )
    # typed body text disagrees with the photo reading by way more than 5%
    _mock_email_fields(monkeypatch, width_value=1200, width_unit="mm")

    outcome = extract_from_attachments(
        [(b"img1", "image/jpeg")], ["ar_measure"], "Width: 1200 mm / Height: 2100 mm"
    )

    assert outcome.needs_manual is True
    assert outcome.reason == "dimension_conflict_item_1_width"


def test_multi_item_never_pulls_dimension_from_shared_body_text(monkeypatch):
    # with 2+ items, a shared typed dimension in the body can't be safely
    # attributed to either one, so it must never be used as a candidate —
    # each item must resolve strictly from its own photo readings.
    monkeypatch.setattr(
        extract_ar,
        "vision_completion",
        MagicMock(
            return_value=_grouped_response(
                [
                    {
                        "room": None,
                        "description": "window",
                        "product_type_hint": "sliding",
                        "readings": [
                            {"raw_value": 900, "raw_unit": "mm", "axis": "width", "confidence": 1.0},
                            {"raw_value": 1200, "raw_unit": "mm", "axis": "height", "confidence": 1.0},
                        ],
                    },
                    {
                        "room": None,
                        "description": "door",
                        "product_type_hint": "hinged",
                        "readings": [
                            {"raw_value": 800, "raw_unit": "mm", "axis": "width", "confidence": 1.0},
                            {"raw_value": 2000, "raw_unit": "mm", "axis": "height", "confidence": 1.0},
                        ],
                    },
                ]
            )
        ),
    )
    _mock_email_fields(monkeypatch, width_value=5000, width_unit="mm")

    outcome = extract_from_attachments(
        [(b"img1", "image/jpeg")] * 2, ["ar_measure"] * 2, "Width: 5000 mm somewhere in here"
    )

    assert outcome.needs_manual is False
    assert outcome.result.items[0].width_mm == 900
    assert outcome.result.items[1].width_mm == 800
    assert all(r.source != "email_body" for r in outcome.result.items[0].width_readings)
    assert all(r.source != "email_body" for r in outcome.result.items[1].width_readings)
