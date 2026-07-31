# tests/test_enrich_materials.py
import json
from unittest.mock import MagicMock

from app.ai import enrich_materials
from app.ai.enrich_materials import generate_material_estimate
from app.ai.llm import LLMUnavailable


def _response(**overrides):
    base = {
        "glass_spec": "6mm single toughened",
        "frame_components": ["aluminium frame extrusion", "corner brackets"],
        "hardware": ["multi-point lock", "hinges"],
        "sealant_and_fixings": ["silicone sealant", "packers"],
        "notes": "interim estimate only",
    }
    base.update(overrides)
    return json.dumps(base)


def test_successful_estimate_parsed(monkeypatch):
    monkeypatch.setattr(enrich_materials, "chat_completion", MagicMock(return_value=_response()))

    estimate = generate_material_estimate("bi_fold", "aluminium", "medium", "single toughened")

    assert estimate is not None
    assert estimate.glass_spec == "6mm single toughened"
    assert "hinges" in estimate.hardware
    assert "silicone sealant" in estimate.sealant_and_fixings
    assert estimate.notes == "interim estimate only"


def test_malformed_json_repairs_on_retry(monkeypatch):
    mock = MagicMock(side_effect=["not json", _response()])
    monkeypatch.setattr(enrich_materials, "chat_completion", mock)

    estimate = generate_material_estimate("awning", "timber", "small")

    assert mock.call_count == 2
    assert estimate is not None
    assert estimate.glass_spec == "6mm single toughened"


def test_malformed_json_twice_returns_none(monkeypatch):
    mock = MagicMock(side_effect=["not json", "still not json"])
    monkeypatch.setattr(enrich_materials, "chat_completion", mock)

    estimate = generate_material_estimate("awning", "timber", "small")

    assert mock.call_count == 2
    assert estimate is None


def test_llm_unavailable_returns_none_not_crash(monkeypatch):
    monkeypatch.setattr(enrich_materials, "chat_completion", MagicMock(side_effect=LLMUnavailable("down")))

    estimate = generate_material_estimate("bi_fold", "aluminium", "medium")

    assert estimate is None


def test_missing_optional_lists_default_empty(monkeypatch):
    monkeypatch.setattr(
        enrich_materials,
        "chat_completion",
        MagicMock(return_value=json.dumps({"glass_spec": "6mm single toughened"})),
    )

    estimate = generate_material_estimate("bi_fold", "aluminium", "medium")

    assert estimate is not None
    assert estimate.frame_components == []
    assert estimate.hardware == []
    assert estimate.sealant_and_fixings == []
    assert estimate.notes is None
