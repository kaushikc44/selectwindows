# tests/test_llm.py
from unittest.mock import MagicMock

import httpx
import pytest
from openai import APIConnectionError

from app.ai import llm
from app.ai.llm import LLMUnavailable, chat_completion, vision_completion


def _fake_request():
    return httpx.Request("POST", "https://example.test/v1/chat/completions")


def _fake_response(content: str):
    message = MagicMock(content=content)
    choice = MagicMock(message=message)
    return MagicMock(choices=[choice])


def test_chat_completion_returns_content_on_success(monkeypatch):
    monkeypatch.setattr(
        llm.client.chat.completions, "create", MagicMock(return_value=_fake_response("hello"))
    )
    assert chat_completion([{"role": "user", "content": "hi"}]) == "hello"


def test_vision_completion_returns_content_on_success(monkeypatch):
    monkeypatch.setattr(
        llm.client.chat.completions, "create", MagicMock(return_value=_fake_response('{"panels": []}'))
    )
    result = vision_completion(b"fake-bytes", "extract panels")
    assert result == '{"panels": []}'


def test_retries_then_raises_llm_unavailable(monkeypatch):
    error = APIConnectionError(request=_fake_request())
    mock_create = MagicMock(side_effect=error)
    monkeypatch.setattr(llm.client.chat.completions, "create", mock_create)
    monkeypatch.setattr(llm.time, "sleep", MagicMock())

    with pytest.raises(LLMUnavailable):
        chat_completion([{"role": "user", "content": "hi"}])

    assert mock_create.call_count == llm.settings.LLM_MAX_RETRIES + 1


def test_succeeds_after_one_retry(monkeypatch):
    error = APIConnectionError(request=_fake_request())
    mock_create = MagicMock(side_effect=[error, _fake_response("recovered")])
    monkeypatch.setattr(llm.client.chat.completions, "create", mock_create)
    monkeypatch.setattr(llm.time, "sleep", MagicMock())

    assert chat_completion([{"role": "user", "content": "hi"}]) == "recovered"
    assert mock_create.call_count == 2
