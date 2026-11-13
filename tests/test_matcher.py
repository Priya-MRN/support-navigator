"""Tests for the free-text -> query type matcher."""

from chatbot import matcher


def test_refund_maps_to_returns():
    result = matcher.match("I want a refund")
    assert result.query_id == "returns"
    assert result.confident


def test_billing_question():
    result = matcher.match("I was charged twice on my credit card")
    assert result.query_id == "billing"
    assert result.confident


def test_track_order():
    result = matcher.match("where is my order, I need to track my package")
    assert result.query_id == "orders"
    assert result.confident


def test_password_reset_maps_to_account():
    result = matcher.match("I forgot my password and can't log in")
    assert result.query_id == "account"
    assert result.confident


def test_technical_issue():
    result = matcher.match("the app keeps crashing with an error")
    assert result.query_id == "technical"
    assert result.confident


def test_fuzzy_typo_tolerance():
    # "refnud" is a typo for "refund".
    result = matcher.match("can i get a refnud please")
    assert result.query_id == "returns"


def test_gibberish_is_not_confident():
    result = matcher.match("zxqwv plover blicket")
    assert not result.confident
