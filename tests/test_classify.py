# tests/test_classify.py
import json
from unittest.mock import MagicMock

import pytest

from app.ai import classify
from app.ai.classify import VALID_LABELS, classify_attachment
from app.ai.llm import LLMUnavailable


@pytest.mark.parametrize("label", sorted(VALID_LABELS))
def test_each_valid_label_is_returned(monkeypatch, label):
    monkeypatch.setattr(classify, "vision_completion", MagicMock(return_value=json.dumps({"label": label})))

    assert classify_attachment(b"fake-bytes", "image/jpeg") == label


def test_unrecognized_label_defaults_to_other(monkeypatch):
    monkeypatch.setattr(classify, "vision_completion", MagicMock(return_value=json.dumps({"label": "spam"})))

    assert classify_attachment(b"fake-bytes", "image/jpeg") == "other"


def test_malformed_json_defaults_to_other(monkeypatch):
    monkeypatch.setattr(classify, "vision_completion", MagicMock(return_value="not json"))

    assert classify_attachment(b"fake-bytes", "image/jpeg") == "other"


def test_llm_unavailable_defaults_to_other(monkeypatch):
    monkeypatch.setattr(classify, "vision_completion", MagicMock(side_effect=LLMUnavailable("down")))

    assert classify_attachment(b"fake-bytes", "image/jpeg") == "other"


def test_passes_single_image_to_vision_completion(monkeypatch):
    mock = MagicMock(return_value=json.dumps({"label": "ar_measure"}))
    monkeypatch.setattr(classify, "vision_completion", mock)

    classify_attachment(b"img-bytes", "image/png")

    images_arg = mock.call_args.args[0]
    assert images_arg == [(b"img-bytes", "image/png")]
