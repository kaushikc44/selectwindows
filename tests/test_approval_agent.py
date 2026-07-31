# tests/test_approval_agent.py
import json
from unittest.mock import MagicMock

from app.ai import approval_agent
from app.ai.approval_agent import check_against_lessons
from app.ai.llm import LLMUnavailable
from app.models import Item, LearnedLesson, Material, ProductType, Quote


def _quote(**item_overrides) -> Quote:
    quote = Quote()
    item = Item(
        item_no=1,
        description_raw="aluminium awning window, bathroom",
        product_type=ProductType.awning,
        material=Material.aluminium,
        height_mm=900,
        width_mm=600,
    )
    for key, value in item_overrides.items():
        setattr(item, key, value)
    quote.items = [item]
    return quote


def _lesson(**overrides) -> LearnedLesson:
    base = dict(trigger_summary="low-sill bathroom window with no safety glass", fix_summary="add safety glass")
    base.update(overrides)
    return LearnedLesson(**base)


def _response(notes=None) -> str:
    return json.dumps({"notes": notes or []})


def test_no_lessons_returns_empty_without_calling_the_llm(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr(approval_agent, "chat_completion", mock)

    result = check_against_lessons(_quote(), [])

    assert result == []
    mock.assert_not_called()


def test_matched_lesson_note_returned(monkeypatch):
    monkeypatch.setattr(
        approval_agent, "chat_completion", MagicMock(return_value=_response(["matches a past low-sill correction"]))
    )

    result = check_against_lessons(_quote(sill_height_mm=400), [_lesson()])

    assert result == ["matches a past low-sill correction"]


def test_no_match_returns_empty_list(monkeypatch):
    monkeypatch.setattr(approval_agent, "chat_completion", MagicMock(return_value=_response([])))

    result = check_against_lessons(_quote(), [_lesson()])

    assert result == []


def test_llm_unavailable_returns_empty_not_crash(monkeypatch):
    monkeypatch.setattr(approval_agent, "chat_completion", MagicMock(side_effect=LLMUnavailable("down")))

    assert check_against_lessons(_quote(), [_lesson()]) == []


def test_malformed_json_repairs_on_retry(monkeypatch):
    mock = MagicMock(side_effect=["not json", _response(["fixed on retry"])])
    monkeypatch.setattr(approval_agent, "chat_completion", mock)

    result = check_against_lessons(_quote(), [_lesson()])

    assert mock.call_count == 2
    assert result == ["fixed on retry"]


def test_malformed_json_twice_returns_empty(monkeypatch):
    mock = MagicMock(side_effect=["not json", "still not json"])
    monkeypatch.setattr(approval_agent, "chat_completion", mock)

    result = check_against_lessons(_quote(), [_lesson()])

    assert mock.call_count == 2
    assert result == []


def test_prompt_includes_lesson_and_quote_content(monkeypatch):
    mock = MagicMock(return_value=_response())
    monkeypatch.setattr(approval_agent, "chat_completion", mock)

    check_against_lessons(_quote(sill_height_mm=400), [_lesson(trigger_summary="a low-sill window")])

    prompt = mock.call_args.args[0][0]["content"]
    assert "a low-sill window" in prompt
    assert "awning" in prompt
    assert "400mm" in prompt
