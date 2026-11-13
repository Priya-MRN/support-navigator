"""Tests for the optional AI fallback (no network, no key required)."""

from chatbot import ai


def test_not_available_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert ai.is_available() is False


def test_maybe_ai_answer_returns_none_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert ai.maybe_ai_answer("How do I reset my password?") is None


def test_empty_key_treated_as_unavailable(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "   ")
    assert ai.is_available() is False
    assert ai.maybe_ai_answer("hello") is None


def test_maybe_ai_answer_empty_question_returns_none(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    assert ai.maybe_ai_answer("") is None
