# tests/test_site_conditions.py
from pathlib import Path

from app.engine.site_conditions import detect_asbestos_mention


def test_detects_asbestos_mention_case_insensitive():
    assert detect_asbestos_mention("Asbestos in eaves") is True
    assert detect_asbestos_mention("possible ASBESTOS sheeting") is True


def test_no_mention_returns_false():
    assert detect_asbestos_mention("brick veneer, 2nd floor") is False


def test_none_or_empty_returns_false():
    assert detect_asbestos_mention(None) is False
    assert detect_asbestos_mention("") is False


def test_explicit_negation_returns_false():
    # regression: a real rep reply literally said this and got flagged anyway
    assert detect_asbestos_mention("Ground Floor, No asbestos present, front driveway access") is False
    assert detect_asbestos_mention("Site is asbestos-free") is False
    assert detect_asbestos_mention("Confirmed asbestos free throughout") is False
    assert detect_asbestos_mention("No known asbestos on site") is False


def test_negation_does_not_suppress_a_real_positive_mention_elsewhere():
    # the negation check is a substring match, not a full-sentence parse —
    # this documents the known limit rather than claiming perfect NLU
    assert detect_asbestos_mention("Asbestos confirmed in ceiling, ground floor is clear") is True


def test_module_never_imports_openai():
    text = Path(__file__).parent.parent.joinpath("app/engine/site_conditions.py").read_text()
    assert "openai" not in text.lower()
