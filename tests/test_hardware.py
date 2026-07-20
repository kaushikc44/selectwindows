# tests/test_hardware.py
import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

from app.ai import hardware
from app.ai.hardware import load_catalog, predict_hardware
from app.ai.llm import LLMUnavailable
from app.schemas import PanelIn

CATALOG_PATH = Path(__file__).parent.parent / "app" / "engine" / "catalog.yaml"


def _catalog():
    return load_catalog(CATALOG_PATH)


def _panels():
    return [PanelIn(label="W1", width_mm=1200, height_mm=900, qty=1, glass_type="toughened", confidence=0.9)]


def test_valid_codes_priced_from_catalog_not_llm(monkeypatch):
    # LLM output includes a rogue unit_price which must be ignored entirely.
    llm_output = json.dumps({"items": [{"code": "SIL-CLEAR", "qty": 2, "unit_price": "999.99"}]})
    monkeypatch.setattr(hardware, "chat_completion", MagicMock(return_value=llm_output))

    lines = predict_hardware(_panels(), _catalog())

    assert len(lines) == 1
    assert lines[0].code == "SIL-CLEAR"
    assert lines[0].unit_price == Decimal("8.50")
    assert lines[0].qty == 2
    assert lines[0].estimated is True


def test_unknown_code_is_dropped_and_logged(monkeypatch, caplog):
    llm_output = json.dumps(
        {"items": [{"code": "MADE-UP-CODE", "qty": 1}, {"code": "PACKER-3MM", "qty": 4}]}
    )
    monkeypatch.setattr(hardware, "chat_completion", MagicMock(return_value=llm_output))

    with caplog.at_level("WARNING"):
        lines = predict_hardware(_panels(), _catalog())

    assert [line.code for line in lines] == ["PACKER-3MM"]
    assert any("MADE-UP-CODE" in record.message for record in caplog.records)


def test_qty_is_capped_at_sane_maximum(monkeypatch, caplog):
    llm_output = json.dumps({"items": [{"code": "FIX-SCREW-50", "qty": 100000}]})
    monkeypatch.setattr(hardware, "chat_completion", MagicMock(return_value=llm_output))

    with caplog.at_level("WARNING"):
        lines = predict_hardware(_panels(), _catalog())

    assert lines[0].qty == hardware.MAX_QTY_PER_LINE
    assert any("Capping qty" in record.message for record in caplog.records)


def test_non_positive_or_non_int_qty_dropped(monkeypatch):
    llm_output = json.dumps(
        {"items": [{"code": "BEAD-CLIP", "qty": 0}, {"code": "SETTING-BLOCK", "qty": "four"}]}
    )
    monkeypatch.setattr(hardware, "chat_completion", MagicMock(return_value=llm_output))

    lines = predict_hardware(_panels(), _catalog())

    assert lines == []


def test_llm_unavailable_returns_empty_list_not_crash(monkeypatch):
    monkeypatch.setattr(hardware, "chat_completion", MagicMock(side_effect=LLMUnavailable("down")))

    lines = predict_hardware(_panels(), _catalog())

    assert lines == []


def test_malformed_json_returns_empty_list_not_crash(monkeypatch):
    monkeypatch.setattr(hardware, "chat_completion", MagicMock(return_value="not json at all"))

    lines = predict_hardware(_panels(), _catalog())

    assert lines == []


def test_catalog_loads_five_items():
    catalog = _catalog()
    assert len(catalog) == 5
    assert catalog["SIL-CLEAR"].unit_price == Decimal("8.50")
