"""Tests for the SQLite ticket store and email validation."""

import pytest

from chatbot import tickets


def test_email_validation():
    assert tickets.is_valid_email("user@example.com")
    assert tickets.is_valid_email("a.b-c@sub.domain.co")
    assert not tickets.is_valid_email("no-at-sign")
    assert not tickets.is_valid_email("missing@domain")
    assert not tickets.is_valid_email("")
    assert not tickets.is_valid_email("spaces in@email.com")


def test_create_and_list_ticket(tmp_path):
    db = tmp_path / "tickets.db"
    ticket = tickets.create_ticket(
        name="Carol",
        email="carol@example.com",
        query_type="billing",
        message="Double charged this month.",
        transcript="bot: hi\nuser: help",
        db_path=str(db),
    )
    assert ticket.id == 1
    assert ticket.status == "open"

    all_tickets = tickets.list_tickets(db_path=str(db))
    assert len(all_tickets) == 1
    assert all_tickets[0].name == "Carol"
    assert all_tickets[0].query_type == "billing"


def test_list_filters_by_status(tmp_path):
    db = tmp_path / "tickets.db"
    tickets.create_ticket("A", "a@x.com", "orders", "msg", db_path=str(db))
    open_tickets = tickets.list_tickets(status="open", db_path=str(db))
    assert len(open_tickets) == 1
    closed_tickets = tickets.list_tickets(status="closed", db_path=str(db))
    assert closed_tickets == []


def test_create_ticket_rejects_bad_input(tmp_path):
    db = tmp_path / "tickets.db"
    with pytest.raises(ValueError):
        tickets.create_ticket("", "a@x.com", "orders", "msg", db_path=str(db))
    with pytest.raises(ValueError):
        tickets.create_ticket("Name", "bad-email", "orders", "msg", db_path=str(db))
    with pytest.raises(ValueError):
        tickets.create_ticket("Name", "a@x.com", "orders", "", db_path=str(db))
