# tests/test_pipeline.py
import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai import classify, extract_ar, extract_email, extract_form
from app.ingest.poller import PolledImage
from app.models import Base, Item, Material, ProductType, Quote, QuoteStatus
from app.workers.pipeline import (
    process_quote_pipeline,
    process_reply_pipeline,
    recompute_pricing_and_flags,
    run_enrichment_and_flags,
    send_for_approval,
)

FIXTURE_JSON = (Path(__file__).parent / "fixtures" / "extraction_valid.json").read_text()
BODY_TEXT = "bi-fold window, aluminium, laundry"


@pytest.fixture(autouse=True)
def _mock_needs_manual_notice(monkeypatch):
    # Every needs_manual path now sends an internal owner notice; mock it
    # globally so tests exercising that path don't hit real SMTP.
    monkeypatch.setattr("app.workers.pipeline.send_needs_manual_notice", MagicMock())


@pytest.fixture(autouse=True)
def _mock_material_estimate_unavailable(monkeypatch):
    # Enrichment now tries an interim LLM material estimate first; default it
    # to "unavailable" so existing tests keep exercising the deterministic
    # enrich_item() fallback (source="default") unless a test explicitly
    # overrides this mock to exercise the llm_estimate path.
    monkeypatch.setattr("app.workers.pipeline.generate_material_estimate", MagicMock(return_value=None))


def _grouped_response(items):
    return json.dumps({"items": items})


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture()
def fixture_images(tmp_path):
    path = tmp_path / "opening.jpg"
    path.write_bytes(b"\xff\xd8\xff\xe0fakejpegbytes")
    return [PolledImage(filename="opening.jpg", content_type="image/jpeg", storage_path=str(path))]


def _mock_form_path(monkeypatch, form_json=FIXTURE_JSON):
    monkeypatch.setattr(classify, "vision_completion", MagicMock(return_value=json.dumps({"label": "form_page1"})))
    monkeypatch.setattr(extract_form, "vision_completion", MagicMock(return_value=form_json))


def test_full_chain_reaches_pending_approval_with_correct_gst(monkeypatch, db_session, fixture_images):
    _mock_form_path(monkeypatch)
    monkeypatch.setattr("app.workers.pipeline.generate_quote_pdf", MagicMock(return_value=b"%PDF-fake"))
    mock_send_email = MagicMock()
    monkeypatch.setattr("app.workers.pipeline.send_approval_email", mock_send_email)

    quote_id = process_quote_pipeline(
        db_session,
        from_address="fieldworker@example.com",
        email_message_id="<msg-1@example.com>",
        body_text=BODY_TEXT,
        images=fixture_images,
    )
    db_session.commit()

    quote = db_session.get(Quote, quote_id)
    assert quote.status == QuoteStatus.pending_approval
    assert len(quote.items) == 1
    assert quote.items[0].height_mm == 1200
    assert quote.header.glass == "double glazed"
    assert quote.attachments[0].kind.value == "form_page1"

    # Golden maths for 1x bi_fold/aluminium/medium/double_glazed + no installation detail:
    # base 900.00 * medium 1.0 * double_glazed 1.3 = 1170.00 item; + 150.00 install base fee;
    # subtotal 1320.00; GST 10% = 132.00; total 1452.00
    assert quote.items[0].unit_price == Decimal("1170.00")
    assert quote.items_subtotal == Decimal("1170.00")
    assert quote.installation_subtotal == Decimal("150.00")
    assert quote.gst_amount == Decimal("132.00")
    assert quote.total == Decimal("1452.00")

    flags = json.loads(quote.flags)
    assert any(f["code"] == "default_spec" for f in flags)

    assert mock_send_email.call_count == 1
    assert quote.approve_token is not None

    enrichment = json.loads(quote.items[0].enrichment_json)
    assert enrichment["source"] == "default"
    assert enrichment["glass_spec"] == "double_glazed"


def test_llm_material_estimate_success_flags_as_ai_estimate_not_default(monkeypatch, db_session, fixture_images):
    from app.ai.enrich_materials import MaterialEstimate

    _mock_form_path(monkeypatch)
    monkeypatch.setattr(
        "app.workers.pipeline.generate_material_estimate",
        MagicMock(
            return_value=MaterialEstimate(
                glass_spec="6mm single toughened",
                frame_components=["aluminium frame extrusion"],
                hardware=["multi-point lock"],
                sealant_and_fixings=["silicone sealant"],
                notes="interim estimate only",
            )
        ),
    )
    monkeypatch.setattr("app.workers.pipeline.generate_quote_pdf", MagicMock(return_value=b"%PDF-fake"))
    monkeypatch.setattr("app.workers.pipeline.send_approval_email", MagicMock())

    quote_id = process_quote_pipeline(
        db_session,
        from_address="fieldworker@example.com",
        email_message_id="<msg-llm-estimate@example.com>",
        body_text=BODY_TEXT,
        images=fixture_images,
    )
    db_session.commit()

    quote = db_session.get(Quote, quote_id)
    assert quote.status == QuoteStatus.pending_approval

    flags = json.loads(quote.flags)
    assert any(f["code"] == "llm_material_estimate" and "AI ESTIMATE" in f["message"] for f in flags)
    assert not any(f["code"] == "default_spec" for f in flags)

    # regression: the materials breakdown used to be computed then thrown
    # away, so the PDF (rendered later) had nothing to show beyond the flag.
    enrichment = json.loads(quote.items[0].enrichment_json)
    assert enrichment["source"] == "llm_estimate"
    assert enrichment["glass_spec"] == "6mm single toughened"
    assert "multi-point lock" in enrichment["hardware"]


def test_extraction_failure_marks_needs_manual_not_crash(monkeypatch, db_session, fixture_images):
    from app.ai.llm import LLMUnavailable

    monkeypatch.setattr(classify, "vision_completion", MagicMock(return_value=json.dumps({"label": "form_page1"})))
    monkeypatch.setattr(extract_form, "vision_completion", MagicMock(side_effect=LLMUnavailable("down")))

    quote_id = process_quote_pipeline(
        db_session,
        from_address="fieldworker@example.com",
        email_message_id="<msg-2@example.com>",
        body_text=BODY_TEXT,
        images=fixture_images,
    )
    db_session.commit()

    quote = db_session.get(Quote, quote_id)
    assert quote.status == QuoteStatus.needs_manual


def test_needs_manual_sends_owner_notice_not_silent(monkeypatch, db_session, fixture_images):
    from app.ai.llm import LLMUnavailable

    monkeypatch.setattr(classify, "vision_completion", MagicMock(return_value=json.dumps({"label": "form_page1"})))
    monkeypatch.setattr(extract_form, "vision_completion", MagicMock(side_effect=LLMUnavailable("down")))
    mock_notice = MagicMock()
    monkeypatch.setattr("app.workers.pipeline.send_needs_manual_notice", mock_notice)

    quote_id = process_quote_pipeline(
        db_session,
        from_address="fieldworker@example.com",
        email_message_id="<msg-notice@example.com>",
        body_text=BODY_TEXT,
        images=fixture_images,
    )
    db_session.commit()

    quote = db_session.get(Quote, quote_id)
    assert quote.status == QuoteStatus.needs_manual
    assert mock_notice.call_count == 1
    assert mock_notice.call_args.args[0].id == quote_id


def test_needs_manual_notice_failure_does_not_change_status_or_crash(monkeypatch, db_session, fixture_images):
    from app.ai.llm import LLMUnavailable

    monkeypatch.setattr(classify, "vision_completion", MagicMock(return_value=json.dumps({"label": "form_page1"})))
    monkeypatch.setattr(extract_form, "vision_completion", MagicMock(side_effect=LLMUnavailable("down")))
    monkeypatch.setattr(
        "app.workers.pipeline.send_needs_manual_notice", MagicMock(side_effect=RuntimeError("smtp down"))
    )

    quote_id = process_quote_pipeline(
        db_session,
        from_address="fieldworker@example.com",
        email_message_id="<msg-notice-fail@example.com>",
        body_text=BODY_TEXT,
        images=fixture_images,
    )
    db_session.commit()

    quote = db_session.get(Quote, quote_id)
    assert quote.status == QuoteStatus.needs_manual  # unchanged despite notice failure


def test_pending_approval_quote_does_not_trigger_needs_manual_notice(monkeypatch, db_session, fixture_images):
    _mock_form_path(monkeypatch)
    monkeypatch.setattr("app.workers.pipeline.generate_quote_pdf", MagicMock(return_value=b"%PDF-fake"))
    monkeypatch.setattr("app.workers.pipeline.send_approval_email", MagicMock())
    mock_notice = MagicMock()
    monkeypatch.setattr("app.workers.pipeline.send_needs_manual_notice", mock_notice)

    process_quote_pipeline(
        db_session,
        from_address="fieldworker@example.com",
        email_message_id="<msg-ok@example.com>",
        body_text=BODY_TEXT,
        images=fixture_images,
    )
    db_session.commit()

    mock_notice.assert_not_called()


def test_approval_email_failure_marks_needs_manual_not_crash(monkeypatch, db_session, fixture_images):
    _mock_form_path(monkeypatch)
    monkeypatch.setattr("app.workers.pipeline.generate_quote_pdf", MagicMock(return_value=b"%PDF-fake"))
    monkeypatch.setattr(
        "app.workers.pipeline.send_approval_email", MagicMock(side_effect=RuntimeError("smtp down"))
    )

    quote_id = process_quote_pipeline(
        db_session,
        from_address="fieldworker@example.com",
        email_message_id="<msg-3@example.com>",
        body_text=BODY_TEXT,
        images=fixture_images,
    )
    db_session.commit()

    quote = db_session.get(Quote, quote_id)
    assert quote.status == QuoteStatus.needs_manual
    assert "pipeline error" in quote.notes


def test_low_confidence_extraction_marks_needs_manual_and_skips_pricing(monkeypatch, db_session, fixture_images):
    payload = json.loads(FIXTURE_JSON)
    payload["items"][0]["confidence"] = 0.3
    _mock_form_path(monkeypatch, json.dumps(payload))
    mock_send_email = MagicMock()
    monkeypatch.setattr("app.workers.pipeline.send_approval_email", mock_send_email)

    quote_id = process_quote_pipeline(
        db_session,
        from_address="fieldworker@example.com",
        email_message_id="<msg-4@example.com>",
        body_text=BODY_TEXT,
        images=fixture_images,
    )
    db_session.commit()

    quote = db_session.get(Quote, quote_id)
    assert quote.status == QuoteStatus.needs_manual
    assert quote.total is None
    assert mock_send_email.call_count == 0
    # regression: notes used to get silently overwritten with just the
    # installation notes, so the needs_manual notice never said why.
    assert "needs_manual" in quote.notes
    assert "item 1 confidence 0.30" in quote.notes


def test_ar_screenshot_plus_body_reaches_pending_approval(monkeypatch, db_session, fixture_images):
    monkeypatch.setattr(classify, "vision_completion", MagicMock(return_value=json.dumps({"label": "ar_measure"})))
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
    monkeypatch.setattr(
        extract_email,
        "chat_completion",
        MagicMock(
            return_value=json.dumps(
                {
                    "client_name": "Sarah Nguyen",
                    "room": "backyard",
                    "product_hint": "alum bifold replacing french doors",
                    "site_notes": "asbestos in eaves",
                }
            )
        ),
    )
    monkeypatch.setattr("app.workers.pipeline.generate_quote_pdf", MagicMock(return_value=b"%PDF-fake"))
    mock_send_email = MagicMock()
    monkeypatch.setattr("app.workers.pipeline.send_approval_email", mock_send_email)

    quote_id = process_quote_pipeline(
        db_session,
        from_address="fieldworker@example.com",
        email_message_id="<msg-ar@example.com>",
        body_text="Sarah Nguyen, backyard, alum bifold replacing french doors, asbestos in eaves",
        images=fixture_images,
    )
    db_session.commit()

    quote = db_session.get(Quote, quote_id)
    assert quote.status == QuoteStatus.pending_approval
    assert quote.items[0].width_mm == 790
    assert quote.items[0].height_mm == 1480
    assert quote.items[0].product_type == ProductType.bi_fold
    assert quote.header.client_name == "Sarah Nguyen"

    flags = json.loads(quote.flags)
    codes = {f["code"] for f in flags}
    assert "ar_measurement" in codes
    assert "asbestos" in codes
    assert mock_send_email.call_count == 1


def test_multiple_photo_groups_become_two_priced_items_one_approval_email(monkeypatch, db_session, fixture_images):
    # regression: a large window + a separate door sent as 5 photos in one
    # email previously got pooled into a single item and spuriously
    # conflicted; now each photo group is its own item and both price fine.
    monkeypatch.setattr(classify, "vision_completion", MagicMock(return_value=json.dumps({"label": "ar_measure"})))
    monkeypatch.setattr(
        extract_ar,
        "vision_completion",
        MagicMock(
            return_value=_grouped_response(
                [
                    {
                        "room": None,
                        "description": "sliding window aluminium",
                        "readings": [
                            {"raw_value": 3.47, "raw_unit": "m", "axis": "width", "confidence": 1.0},
                            {"raw_value": 2.26, "raw_unit": "m", "axis": "height", "confidence": 1.0},
                        ],
                    },
                    {
                        "room": None,
                        "description": "hinged door",
                        "readings": [
                            {"raw_value": 2.59, "raw_unit": "m", "axis": "unlabelled", "confidence": 1.0},
                            {"raw_value": 2.10, "raw_unit": "m", "axis": "unlabelled", "confidence": 1.0},
                        ],
                    },
                ]
            )
        ),
    )
    monkeypatch.setattr(
        extract_email,
        "chat_completion",
        MagicMock(
            return_value=json.dumps(
                {"client_name": "ingrity", "room": None, "product_hint": None, "site_notes": None}
            )
        ),
    )
    monkeypatch.setattr("app.workers.pipeline.generate_quote_pdf", MagicMock(return_value=b"%PDF-fake"))
    mock_send_email = MagicMock()
    monkeypatch.setattr("app.workers.pipeline.send_approval_email", mock_send_email)

    quote_id = process_quote_pipeline(
        db_session,
        from_address="fieldworker@example.com",
        email_message_id="<msg-multi@example.com>",
        body_text="Product type sliding window aluminium panels",
        images=fixture_images,
    )
    db_session.commit()

    quote = db_session.get(Quote, quote_id)
    assert quote.status == QuoteStatus.pending_approval
    assert len(quote.items) == 2
    window, door = quote.items
    assert window.width_mm == 3470 and window.height_mm == 2260
    assert door.width_mm == 2590 and door.height_mm == 2100
    assert window.unit_price is not None
    assert door.unit_price is not None
    assert quote.total is not None
    assert mock_send_email.call_count == 1


def test_sketch_plus_body_reaches_pending_approval(monkeypatch, db_session, fixture_images):
    monkeypatch.setattr(classify, "vision_completion", MagicMock(return_value=json.dumps({"label": "hand_sketch"})))
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
                            {"raw_value": 900, "raw_unit": "mm", "axis": "width", "confidence": 0.8},
                            {"raw_value": 1200, "raw_unit": "mm", "axis": "height", "confidence": 0.85},
                        ],
                    }
                ]
            )
        ),
    )
    monkeypatch.setattr(
        extract_email,
        "chat_completion",
        MagicMock(
            return_value=json.dumps(
                {"client_name": "Tom Lee", "room": "kitchen", "product_hint": "sliding door timber", "site_notes": None}
            )
        ),
    )
    monkeypatch.setattr("app.workers.pipeline.generate_quote_pdf", MagicMock(return_value=b"%PDF-fake"))
    mock_send_email = MagicMock()
    monkeypatch.setattr("app.workers.pipeline.send_approval_email", mock_send_email)

    quote_id = process_quote_pipeline(
        db_session,
        from_address="fieldworker@example.com",
        email_message_id="<msg-sketch@example.com>",
        body_text="sliding door timber, kitchen, Tom Lee",
        images=fixture_images,
    )
    db_session.commit()

    quote = db_session.get(Quote, quote_id)
    assert quote.status == QuoteStatus.pending_approval
    assert quote.items[0].product_type == ProductType.sliding
    assert mock_send_email.call_count == 1


def test_missing_product_type_and_client_name_goes_to_awaiting_info(monkeypatch, db_session, fixture_images):
    monkeypatch.setattr(classify, "vision_completion", MagicMock(return_value=json.dumps({"label": "ar_measure"})))
    monkeypatch.setattr(
        extract_ar,
        "vision_completion",
        MagicMock(
            return_value=_grouped_response(
                [
                    {
                        "room": None,
                        "description": None,
                        "readings": [
                            {"raw_value": 900, "raw_unit": "mm", "axis": "width", "confidence": 0.8},
                            {"raw_value": 1200, "raw_unit": "mm", "axis": "height", "confidence": 0.8},
                        ],
                    }
                ]
            )
        ),
    )
    monkeypatch.setattr(
        extract_email,
        "chat_completion",
        MagicMock(return_value=json.dumps({"client_name": None, "room": None, "product_hint": None, "site_notes": None})),
    )
    mock_send_missing_info = MagicMock(return_value="<clarify-1@select.example.com>")
    monkeypatch.setattr("app.workers.pipeline.send_missing_info_request", mock_send_missing_info)

    quote_id = process_quote_pipeline(
        db_session,
        from_address="rep@fieldcrew.example.com",
        email_message_id="<msg-noinfo@example.com>",
        body_text="just a measurement, no details",
        images=fixture_images,
    )
    db_session.commit()

    quote = db_session.get(Quote, quote_id)
    assert quote.status == QuoteStatus.awaiting_info
    assert quote.awaiting_info_message_id == "<clarify-1@select.example.com>"
    missing = json.loads(quote.awaiting_info_fields)
    assert set(missing) == {"product_type", "client_name"}
    assert mock_send_missing_info.call_count == 1


def test_rep_reply_merges_and_completes_pipeline(monkeypatch, db_session, fixture_images):
    monkeypatch.setattr(classify, "vision_completion", MagicMock(return_value=json.dumps({"label": "ar_measure"})))
    monkeypatch.setattr(
        extract_ar,
        "vision_completion",
        MagicMock(
            return_value=_grouped_response(
                [
                    {
                        "room": None,
                        "description": None,
                        "readings": [
                            {"raw_value": 900, "raw_unit": "mm", "axis": "width", "confidence": 0.8},
                            {"raw_value": 1200, "raw_unit": "mm", "axis": "height", "confidence": 0.8},
                        ],
                    }
                ]
            )
        ),
    )
    monkeypatch.setattr(
        extract_email,
        "chat_completion",
        MagicMock(return_value=json.dumps({"client_name": None, "room": None, "product_hint": None, "site_notes": None})),
    )
    monkeypatch.setattr("app.workers.pipeline.send_missing_info_request", MagicMock(return_value="<clarify-1@select.example.com>"))

    quote_id = process_quote_pipeline(
        db_session,
        from_address="rep@fieldcrew.example.com",
        email_message_id="<msg-noinfo2@example.com>",
        body_text="just a measurement",
        images=fixture_images,
    )
    db_session.commit()

    quote = db_session.get(Quote, quote_id)
    assert quote.status == QuoteStatus.awaiting_info

    monkeypatch.setattr(
        extract_email,
        "chat_completion",
        MagicMock(
            return_value=json.dumps(
                {"client_name": "Priya Rao", "room": None, "product_hint": "bi-fold window aluminium", "site_notes": None}
            )
        ),
    )
    monkeypatch.setattr("app.workers.pipeline.generate_quote_pdf", MagicMock(return_value=b"%PDF-fake"))
    mock_send_email = MagicMock()
    monkeypatch.setattr("app.workers.pipeline.send_approval_email", mock_send_email)

    process_reply_pipeline(db_session, quote, "It's a bi-fold window, aluminium. Client is Priya Rao.")
    db_session.commit()

    quote = db_session.get(Quote, quote_id)
    assert quote.status == QuoteStatus.pending_approval
    assert quote.header.client_name == "Priya Rao"
    assert quote.items[0].product_type == ProductType.bi_fold
    assert quote.awaiting_info_message_id is None
    assert mock_send_email.call_count == 1


def _dimension_conflict_grouped_response():
    return _grouped_response(
        [
            {
                "room": None,
                "description": "aluminium sliding door",
                "product_type_hint": "sliding",
                "readings": [
                    {"raw_value": 790, "raw_unit": "mm", "axis": "width", "confidence": 0.9},
                    {"raw_value": 2000, "raw_unit": "mm", "axis": "width", "confidence": 0.9},
                    {"raw_value": 1200, "raw_unit": "mm", "axis": "height", "confidence": 0.9},
                ],
            }
        ]
    )


def _resolved_grouped_response():
    return _grouped_response(
        [
            {
                "room": None,
                "description": "aluminium sliding door",
                "product_type_hint": "sliding",
                "readings": [
                    {"raw_value": 2000, "raw_unit": "mm", "axis": "width", "confidence": 0.9},
                    {"raw_value": 1200, "raw_unit": "mm", "axis": "height", "confidence": 0.9},
                ],
            }
        ]
    )


def test_dimension_conflict_sends_retry_request_and_awaits_reply(monkeypatch, db_session, fixture_images):
    monkeypatch.setattr(classify, "vision_completion", MagicMock(return_value=json.dumps({"label": "ar_measure"})))
    monkeypatch.setattr(
        extract_ar, "vision_completion", MagicMock(return_value=_dimension_conflict_grouped_response())
    )
    monkeypatch.setattr(
        extract_email,
        "chat_completion",
        MagicMock(
            return_value=json.dumps(
                {"client_name": "Priya Rao", "room": None, "product_hint": None, "site_notes": None}
            )
        ),
    )
    mock_retry_request = MagicMock(return_value="<conflict-1@select.example.com>")
    monkeypatch.setattr("app.workers.pipeline.send_dimension_conflict_retry_request", mock_retry_request)

    quote_id = process_quote_pipeline(
        db_session,
        from_address="rep@fieldcrew.example.com",
        email_message_id="<msg-conflict@example.com>",
        body_text="Aluminium sliding door",
        images=fixture_images,
    )
    db_session.commit()

    quote = db_session.get(Quote, quote_id)
    assert quote.status == QuoteStatus.awaiting_info
    assert quote.awaiting_info_message_id == "<conflict-1@select.example.com>"
    assert json.loads(quote.awaiting_info_fields) == ["dimension_conflict"]
    assert quote.items == []  # nothing persisted — a dimension conflict aborts before item creation
    assert mock_retry_request.call_count == 1
    conflict_readings_arg = mock_retry_request.call_args[0][1]
    assert {r.value_mm for r in conflict_readings_arg} == {790, 2000}


def test_dimension_conflict_reply_with_correction_completes_pipeline(monkeypatch, db_session, fixture_images):
    monkeypatch.setattr(classify, "vision_completion", MagicMock(return_value=json.dumps({"label": "ar_measure"})))
    monkeypatch.setattr(
        extract_ar,
        "vision_completion",
        MagicMock(side_effect=[_dimension_conflict_grouped_response(), _resolved_grouped_response()]),
    )
    monkeypatch.setattr(
        extract_email,
        "chat_completion",
        MagicMock(
            return_value=json.dumps(
                {"client_name": "Priya Rao", "room": None, "product_hint": None, "site_notes": None}
            )
        ),
    )
    monkeypatch.setattr(
        "app.workers.pipeline.send_dimension_conflict_retry_request",
        MagicMock(return_value="<conflict-1@select.example.com>"),
    )

    quote_id = process_quote_pipeline(
        db_session,
        from_address="rep@fieldcrew.example.com",
        email_message_id="<msg-conflict2@example.com>",
        body_text="Aluminium sliding door",
        images=fixture_images,
    )
    db_session.commit()

    quote = db_session.get(Quote, quote_id)
    assert quote.status == QuoteStatus.awaiting_info

    monkeypatch.setattr("app.workers.pipeline.generate_quote_pdf", MagicMock(return_value=b"%PDF-fake"))
    mock_send_email = MagicMock()
    monkeypatch.setattr("app.workers.pipeline.send_approval_email", mock_send_email)

    process_reply_pipeline(db_session, quote, "Sorry, the width is actually 2000mm.")
    db_session.commit()

    quote = db_session.get(Quote, quote_id)
    assert quote.status == QuoteStatus.pending_approval
    assert quote.items[0].width_mm == 2000
    assert quote.items[0].height_mm == 1200
    assert quote.awaiting_info_message_id is None
    assert quote.awaiting_info_fields is None
    assert mock_send_email.call_count == 1


def test_dimension_conflict_reply_with_new_photo_completes_pipeline(monkeypatch, db_session, fixture_images, tmp_path):
    from app.ingest.poller import PolledImage

    monkeypatch.setattr(classify, "vision_completion", MagicMock(return_value=json.dumps({"label": "ar_measure"})))
    monkeypatch.setattr(
        extract_ar,
        "vision_completion",
        MagicMock(side_effect=[_dimension_conflict_grouped_response(), _resolved_grouped_response()]),
    )
    monkeypatch.setattr(
        extract_email,
        "chat_completion",
        MagicMock(
            return_value=json.dumps(
                {"client_name": "Priya Rao", "room": None, "product_hint": None, "site_notes": None}
            )
        ),
    )
    monkeypatch.setattr(
        "app.workers.pipeline.send_dimension_conflict_retry_request",
        MagicMock(return_value="<conflict-1@select.example.com>"),
    )

    quote_id = process_quote_pipeline(
        db_session,
        from_address="rep@fieldcrew.example.com",
        email_message_id="<msg-conflict3@example.com>",
        body_text="Aluminium sliding door",
        images=fixture_images,
    )
    db_session.commit()
    quote = db_session.get(Quote, quote_id)
    assert quote.status == QuoteStatus.awaiting_info
    assert len(quote.attachments) == 1

    monkeypatch.setattr("app.workers.pipeline.generate_quote_pdf", MagicMock(return_value=b"%PDF-fake"))
    mock_send_email = MagicMock()
    monkeypatch.setattr("app.workers.pipeline.send_approval_email", mock_send_email)

    retake_path = tmp_path / "retake.jpg"
    retake_path.write_bytes(b"\xff\xd8\xff\xe0retakejpegbytes")
    retake_image = PolledImage(filename="retake.jpg", content_type="image/jpeg", storage_path=str(retake_path))

    process_reply_pipeline(db_session, quote, "Here's a clearer photo.", images=[retake_image])
    db_session.commit()

    quote = db_session.get(Quote, quote_id)
    assert quote.status == QuoteStatus.pending_approval
    assert len(quote.attachments) == 2
    assert mock_send_email.call_count == 1


def test_run_enrichment_and_flags_wires_item_sill_height_into_safety_glass_flag(db_session):
    # Regression test for a real, previously-silent gap: safety_glass_flags()
    # has always accepted a sill_height_mm dict, but nothing ever built one
    # from real data — this confirms Item.sill_height_mm now actually
    # reaches it via run_enrichment_and_flags, not just via direct unit
    # tests of safety_glass_flags() itself (see tests/test_flags.py).
    quote = Quote(status=QuoteStatus.extracted)
    db_session.add(quote)
    db_session.flush()
    item = Item(
        quote_id=quote.id,
        item_no=1,
        description_raw="aluminium awning window, bathroom",
        product_type=ProductType.awning,  # a window, not a door — only the low sill should trigger the flag
        material=Material.aluminium,
        height_mm=900,
        width_mm=600,
        sill_height_mm=400,  # below MIN_SAFETY_GLASS_SILL_MM (500)
    )
    db_session.add(item)
    db_session.commit()

    run_enrichment_and_flags(db_session, quote)

    flags = json.loads(quote.flags)
    assert any(f["code"] == "as1288_safety_glass" for f in flags)


def test_send_for_approval_stores_agent_notes_from_learned_lessons(db_session, monkeypatch):
    quote = Quote(status=QuoteStatus.extracted)
    db_session.add(quote)
    db_session.commit()

    monkeypatch.setattr("app.workers.pipeline.generate_quote_pdf", MagicMock(return_value=b"%PDF-fake"))
    monkeypatch.setattr("app.workers.pipeline.send_approval_email", MagicMock())
    monkeypatch.setattr(
        "app.workers.pipeline.check_against_lessons", MagicMock(return_value=["matches a past low-sill correction"])
    )

    send_for_approval(db_session, quote)

    assert quote.status == QuoteStatus.pending_approval
    assert json.loads(quote.agent_notes) == ["matches a past low-sill correction"]


def test_send_for_approval_agent_check_failure_does_not_block_approval_email(db_session, monkeypatch):
    quote = Quote(status=QuoteStatus.extracted)
    db_session.add(quote)
    db_session.commit()

    monkeypatch.setattr("app.workers.pipeline.generate_quote_pdf", MagicMock(return_value=b"%PDF-fake"))
    mock_send_email = MagicMock()
    monkeypatch.setattr("app.workers.pipeline.send_approval_email", mock_send_email)
    monkeypatch.setattr(
        "app.workers.pipeline.check_against_lessons", MagicMock(side_effect=RuntimeError("boom"))
    )

    send_for_approval(db_session, quote)

    assert quote.status == QuoteStatus.pending_approval  # unaffected by the agent-check failure
    assert mock_send_email.call_count == 1
    assert quote.agent_notes is None


def test_send_for_approval_computes_readiness_score_from_flags(db_session, monkeypatch):
    quote = Quote(status=QuoteStatus.extracted)
    db_session.add(quote)
    db_session.flush()
    db_session.add(
        Item(
            quote_id=quote.id,
            item_no=1,
            description_raw="aluminium awning window",
            product_type=ProductType.awning,
            material=Material.aluminium,
            height_mm=900,
            width_mm=600,
        )
    )
    db_session.commit()

    monkeypatch.setattr("app.workers.pipeline.generate_quote_pdf", MagicMock(return_value=b"%PDF-fake"))
    monkeypatch.setattr("app.workers.pipeline.send_approval_email", MagicMock())
    monkeypatch.setattr("app.workers.pipeline.check_against_lessons", MagicMock(return_value=[]))
    quote.flags = json.dumps([{"code": "ar_measurement", "message": "..."}])

    send_for_approval(db_session, quote)

    assert quote.readiness_score == 90  # 100 - 10 (ar_measurement), no lesson match


def test_send_for_approval_readiness_score_penalized_when_lesson_matches(db_session, monkeypatch):
    quote = Quote(status=QuoteStatus.extracted, flags=json.dumps([]))
    db_session.add(quote)
    db_session.commit()

    monkeypatch.setattr("app.workers.pipeline.generate_quote_pdf", MagicMock(return_value=b"%PDF-fake"))
    monkeypatch.setattr("app.workers.pipeline.send_approval_email", MagicMock())
    monkeypatch.setattr(
        "app.workers.pipeline.check_against_lessons", MagicMock(return_value=["matches a past correction"])
    )

    send_for_approval(db_session, quote)

    assert quote.readiness_score == 80  # 100 - 20 lesson-match penalty


def test_recompute_pricing_and_flags_updates_totals_after_dimension_change(db_session):
    quote = Quote(status=QuoteStatus.pending_approval)
    db_session.add(quote)
    db_session.flush()
    item = Item(
        quote_id=quote.id,
        item_no=1,
        description_raw="aluminium awning window",
        product_type=ProductType.awning,
        material=Material.aluminium,
        height_mm=900,
        width_mm=600,
        qty=1,
    )
    db_session.add(item)
    db_session.commit()

    recompute_pricing_and_flags(db_session, quote)
    first_total = quote.total

    item.width_mm = 2400  # much bigger opening — should re-price to a larger total
    recompute_pricing_and_flags(db_session, quote)

    assert quote.total is not None
    assert quote.total > first_total


def test_recompute_pricing_and_flags_preserves_quote_status(db_session):
    # run_pricing has the side effect of setting status=priced — an edited
    # quote must stay in whatever actionable status it was already in.
    quote = Quote(status=QuoteStatus.needs_manual)
    db_session.add(quote)
    db_session.commit()

    recompute_pricing_and_flags(db_session, quote)

    assert quote.status == QuoteStatus.needs_manual


def test_recompute_pricing_and_flags_never_calls_the_materials_llm(db_session, monkeypatch):
    # Critical: re-running flags after an owner edit must never overwrite a
    # manual materials correction with a fresh AI guess.
    mock_estimate = MagicMock()
    monkeypatch.setattr("app.workers.pipeline.generate_material_estimate", mock_estimate)

    quote = Quote(status=QuoteStatus.pending_approval)
    db_session.add(quote)
    db_session.flush()
    db_session.add(
        Item(
            quote_id=quote.id,
            item_no=1,
            description_raw="aluminium awning window",
            product_type=ProductType.awning,
            material=Material.aluminium,
            height_mm=900,
            width_mm=600,
            enrichment_json=json.dumps(
                {
                    "glass_spec": "6mm toughened",
                    "safety_glass_required": False,
                    "hardware": [],
                    "energy_u_value": None,
                    "energy_shgc": None,
                    "labour_hours": 0.0,
                    "men_required": 1,
                    "unrecognized": False,
                    "source": "owner_edit",
                    "frame_components": [],
                    "sealant_and_fixings": [],
                    "notes": None,
                }
            ),
        )
    )
    db_session.commit()

    recompute_pricing_and_flags(db_session, quote)

    mock_estimate.assert_not_called()
    flags = json.loads(quote.flags)
    assert not any(f["code"] in ("llm_material_estimate", "default_spec") for f in flags)


def test_recompute_pricing_and_flags_refreshes_readiness_score_keeping_existing_agent_notes(db_session):
    quote = Quote(status=QuoteStatus.pending_approval, agent_notes=json.dumps(["matches a past correction"]))
    db_session.add(quote)
    db_session.flush()
    db_session.add(
        Item(
            quote_id=quote.id,
            item_no=1,
            description_raw="aluminium awning window",
            product_type=ProductType.awning,
            material=Material.aluminium,
            height_mm=900,
            width_mm=600,
            dimensions_multi_reading=True,
        )
    )
    db_session.commit()

    recompute_pricing_and_flags(db_session, quote)

    # 100 - 10 (dimensions_multi_reading) - 10 (default_spec, no enrichment_json
    # stored on this item) - 20 (existing lesson match, kept as-is)
    assert quote.readiness_score == 60
    assert json.loads(quote.agent_notes) == ["matches a past correction"]  # untouched
