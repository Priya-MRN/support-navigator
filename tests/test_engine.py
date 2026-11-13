"""Tests for the conversation engine state machine."""

from chatbot import engine
from chatbot.engine import InputType, Session, State


def test_start_opens_on_intake_gate():
    session = Session()
    resp = engine.start(session)
    assert resp.state == State.INTAKE
    assert resp.input_type == InputType.INTAKE_FORM
    assert resp.options == []


def test_intake_requires_a_name():
    session = Session()
    engine.start(session)
    resp = engine.submit_intake(session, "", "alex@example.com")
    assert resp.state == State.INTAKE
    assert resp.input_type == InputType.INTAKE_FORM
    assert resp.meta.get("error")
    assert session.user == {}


def test_intake_rejects_a_bad_email():
    session = Session()
    engine.start(session)
    resp = engine.submit_intake(session, "Alex Morgan", "not-an-email")
    assert resp.state == State.INTAKE
    assert resp.meta.get("error")
    assert session.user == {}


def test_intake_success_opens_the_menu_and_stores_identity():
    session = Session()
    engine.start(session)
    resp = engine.submit_intake(session, "Alex Morgan", "alex@example.com")
    assert resp.state == State.CHOOSE_TYPE
    assert resp.input_type == InputType.OPTIONS
    assert "Alex" in resp.message
    assert session.user == {"name": "Alex Morgan", "email": "alex@example.com"}
    ids = {opt.id for opt in resp.options}
    assert {"billing", "orders", "returns", "account", "technical"} <= ids


def test_skip_intake_opens_the_menu_without_identity():
    session = Session()
    engine.start(session)
    resp = engine.skip_intake(session)
    assert resp.state == State.CHOOSE_TYPE
    assert session.user == {}
    assert resp.options


def test_skip_intake_via_option_id():
    session = Session()
    engine.start(session)
    resp = engine.handle_option(session, "__skip_intake__")
    assert resp.state == State.CHOOSE_TYPE
    assert session.user == {}


def test_intake_identity_prefills_the_escalation_form():
    session = Session()
    engine.start(session)
    engine.submit_intake(session, "Alex Morgan", "alex@example.com")
    engine.handle_option(session, "billing")
    resp = engine.handle_option(session, "__no__")
    assert resp.state == State.COLLECT_CONTACT
    assert resp.meta["prefill"] == {
        "name": "Alex Morgan",
        "email": "alex@example.com",
    }
    assert resp.meta["topic"] == "Billing & Payments"


def test_instructions_return_structured_steps():
    session = Session()
    engine.greeting(session)
    resp = engine.handle_option(session, "returns")
    # Steps are structured data, not markdown baked into the message.
    assert len(resp.steps) >= 3
    assert all(isinstance(s, str) for s in resp.steps)
    assert not any(line.startswith("1. ") for line in resp.message.splitlines())
    assert resp.tail
    # plain_text() re-joins them for the CLI / transcript.
    assert "1. " in resp.plain_text()


def test_greeting_offers_menu():
    session = Session()
    resp = engine.greeting(session)
    assert resp.state == State.CHOOSE_TYPE
    assert resp.input_type == InputType.OPTIONS
    # Should include all the main query types.
    ids = {opt.id for opt in resp.options}
    assert {"billing", "orders", "returns", "account", "technical"} <= ids


def test_choose_type_shows_instructions_and_satisfaction():
    session = Session()
    engine.greeting(session)
    resp = engine.handle_option(session, "returns")
    assert resp.state == State.ASK_SATISFIED
    # Steps should be in the message.
    assert "Return" in resp.message or "return" in resp.message
    option_ids = {opt.id for opt in resp.options}
    assert "__yes__" in option_ids
    assert "__no__" in option_ids


def test_satisfied_yes_closes_friendly():
    session = Session()
    engine.greeting(session)
    engine.handle_option(session, "billing")
    resp = engine.handle_option(session, "__yes__")
    assert resp.state == State.CHOOSE_TYPE
    assert "glad" in resp.message.lower() or "anything else" in resp.message.lower()


def test_satisfied_no_starts_escalation():
    session = Session()
    engine.greeting(session)
    engine.handle_option(session, "technical")
    resp = engine.handle_option(session, "__no__")
    assert resp.state == State.COLLECT_CONTACT
    assert resp.input_type == InputType.CONTACT_FORM


def test_full_escalation_creates_ticket(tmp_path):
    db = tmp_path / "tickets.db"
    session = Session()
    engine.greeting(session)
    engine.handle_option(session, "account")
    engine.handle_option(session, "__no__")  # not satisfied -> escalate
    resp = engine.submit_contact(
        session,
        name="Alice Example",
        email="alice@example.com",
        message="Locked out of my account.",
        db_path=str(db),
    )
    assert resp.state == State.TICKET_CREATED
    assert resp.meta.get("ticket_id") == 1
    # The ticket confirmation is structured so the UI can render a success card.
    assert "ticket" in resp.meta.get("ticket_title", "").lower()
    assert "alice@example.com" in resp.meta.get("ticket_meta", "")
    assert "Alice" in resp.message


def test_submit_contact_invalid_email_stays_on_form(tmp_path):
    db = tmp_path / "tickets.db"
    session = Session()
    engine.greeting(session)
    engine.handle_option(session, "other")
    engine.handle_option(session, "__no__")
    resp = engine.submit_contact(
        session,
        name="Bob",
        email="not-an-email",
        message="Help me",
        db_path=str(db),
    )
    assert resp.state == State.COLLECT_CONTACT
    assert resp.input_type == InputType.CONTACT_FORM
    assert "⚠️" in resp.message


def test_subtopic_navigation():
    session = Session()
    engine.greeting(session)
    engine.handle_option(session, "returns")
    resp = engine.handle_option(session, "sub:damaged_item")
    assert resp.state == State.ASK_SATISFIED
    assert "damaged" in resp.message.lower()


def test_free_text_routes_to_instructions():
    session = Session()
    engine.greeting(session)
    resp = engine.handle_free_text(session, "I need a refund for a broken item")
    assert session.current_query_id == "returns"
    assert resp.state == State.ASK_SATISFIED
