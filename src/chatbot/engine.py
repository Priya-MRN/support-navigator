"""Conversation engine: the reliable, UI-agnostic state machine.

The engine drives the full support flow described in the product vision:

    INTAKE -> GREETING -> CHOOSE_TYPE -> SHOW_INSTRUCTIONS [-> SUBTOPIC]
           -> ASK_SATISFIED -> (CLOSE | ESCALATE -> COLLECT_CONTACT -> TICKET_CREATED)

The conversation opens on an *intake gate*: we ask who we're helping (name and
email) so that, if the chat later escalates, an expert can follow up without
asking twice. The gate is skippable — ``skip_intake`` jumps straight to the
greeting and the escalation form collects the details instead.

It is pure logic: it returns structured :class:`BotResponse` objects (message
text, a list of selectable options, and the expected input type) so the same
engine powers both the CLI and the web UI. A :class:`Session` object holds
per-conversation state and history.

Free-text input is mapped to a query type via :mod:`matcher`. When matching is
not confident, the engine tries the optional AI fallback (:mod:`ai`) and, if
that's unavailable, offers human escalation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from . import ai, tickets
from .knowledge import get_query_type, get_query_types, get_sub_topic
from .matcher import match


class State(str, Enum):
    """Conversation states."""

    INTAKE = "intake"
    GREETING = "greeting"
    CHOOSE_TYPE = "choose_type"
    SHOW_INSTRUCTIONS = "show_instructions"
    SUBTOPIC = "subtopic"
    ASK_SATISFIED = "ask_satisfied"
    COLLECT_CONTACT = "collect_contact"
    TICKET_CREATED = "ticket_created"
    CLOSED = "closed"


class InputType(str, Enum):
    """What kind of input the UI should collect next."""

    OPTIONS = "options"          # choose from buttons (free text also allowed)
    TEXT = "text"               # free text expected
    CONTACT_FORM = "contact_form"  # name/email/message form
    INTAKE_FORM = "intake_form"  # name/email gate shown before the chat opens
    NONE = "none"               # terminal / informational


@dataclass
class Option:
    """A selectable quick-reply option / button."""

    id: str
    label: str
    icon: str = ""


@dataclass
class BotResponse:
    """A structured response from the engine to render in any UI.

    ``message`` is the lead paragraph. ``steps`` and ``tail`` are kept separate
    from it so a rich UI can render numbered instructions as real list items
    (rather than parsing markdown out of the message), while the CLI can simply
    join them back together via :meth:`plain_text`.
    """

    message: str
    options: list[Option] = field(default_factory=list)
    input_type: InputType = InputType.OPTIONS
    state: State = State.CHOOSE_TYPE
    # Numbered instruction steps, rendered as a list by rich UIs.
    steps: list[str] = field(default_factory=list)
    # A closing line shown after the steps (e.g. "Did this solve your issue?").
    tail: str = ""
    # Extra payload (e.g. created ticket id) for UIs that want it.
    meta: dict[str, Any] = field(default_factory=dict)

    def plain_text(self) -> str:
        """Flatten message + steps + tail into one text block (CLI/transcript)."""
        parts = [self.message]
        if self.steps:
            parts.append("")
            parts += [f"{i}. {s}" for i, s in enumerate(self.steps, start=1)]
        if self.tail:
            parts.append("")
            parts.append(self.tail)
        return "\n".join(parts)


@dataclass
class Session:
    """Per-conversation state and history."""

    state: State = State.INTAKE
    current_query_id: str | None = None
    history: list[dict[str, str]] = field(default_factory=list)
    # Partially collected contact info during escalation.
    contact: dict[str, str] = field(default_factory=dict)
    # Identity captured at the intake gate (empty when the gate was skipped).
    user: dict[str, str] = field(default_factory=dict)

    def log(self, sender: str, text: str) -> None:
        """Append a line to the running transcript."""
        self.history.append({"sender": sender, "text": text})

    def transcript_text(self) -> str:
        """Render the conversation history as plain text."""
        return "\n".join(f"{m['sender']}: {m['text']}" for m in self.history)


# Special option ids reused across states.
_OPT_MENU = "__menu__"
_OPT_YES = "__yes__"
_OPT_NO = "__no__"
_OPT_HUMAN = "__human__"
_OPT_DONE = "__done__"
_OPT_SKIP = "__skip_intake__"


def _query_type_options() -> list[Option]:
    """Build the main menu options from the knowledge base."""
    return [
        Option(id=qt["id"], label=qt["label"], icon=qt.get("icon", ""))
        for qt in get_query_types()
    ]


_GREETING_TAIL = (
    "Pick a topic from the list, or just type your question — I'll walk you "
    "through it step by step."
)


def start(session: Session) -> BotResponse:
    """Reset the session and open on the intake gate.

    This is the true entry point of a conversation. The UI shows a small
    name/email form; the user may submit it (:func:`submit_intake`) or bypass
    it (:func:`skip_intake`).
    """
    session.state = State.INTAKE
    session.current_query_id = None
    session.contact = {}
    session.user = {}
    session.history = []
    msg = (
        "Hi — I'm your support assistant. Before we dig in, tell me who I'm "
        "helping so an expert can follow up if we need one."
    )
    session.log("bot", msg)
    return BotResponse(
        message=msg,
        options=[],
        input_type=InputType.INTAKE_FORM,
        state=State.INTAKE,
    )


def submit_intake(session: Session, name: str, email: str) -> BotResponse:
    """Validate the intake gate and open the chat.

    On success the identity is stored on the session, pre-fills any later
    escalation form, and is attached to tickets created from this conversation.
    On failure the state stays at ``INTAKE`` so the UI can show the error.
    """
    name = (name or "").strip()
    email = (email or "").strip()

    if not name:
        return BotResponse(
            message="Please add your name so I know who I'm helping.",
            options=[],
            input_type=InputType.INTAKE_FORM,
            state=State.INTAKE,
            meta={"error": True},
        )
    if not tickets.is_valid_email(email):
        return BotResponse(
            message="That email doesn't look right — please double-check it.",
            options=[],
            input_type=InputType.INTAKE_FORM,
            state=State.INTAKE,
            meta={"error": True},
        )

    session.user = {"name": name, "email": email}
    session.state = State.CHOOSE_TYPE
    first_name = name.split()[0]
    msg = f"Thanks, {first_name}. {_GREETING_TAIL}"
    session.log("bot", msg)
    return BotResponse(
        message=msg,
        options=_query_type_options(),
        input_type=InputType.OPTIONS,
        state=State.CHOOSE_TYPE,
    )


def skip_intake(session: Session) -> BotResponse:
    """Bypass the intake gate and open the chat without an identity."""
    session.user = {}
    session.state = State.CHOOSE_TYPE
    msg = (
        "No problem — we can add your details later if we need a human. "
        + _GREETING_TAIL
    )
    session.log("bot", msg)
    return BotResponse(
        message=msg,
        options=_query_type_options(),
        input_type=InputType.OPTIONS,
        state=State.CHOOSE_TYPE,
    )


def greeting(session: Session) -> BotResponse:
    """Produce the greeting + main menu, past the intake gate.

    Kept as the post-intake entry point so existing callers (and the CLI) can
    reach the menu directly without going through the gate.
    """
    session.state = State.CHOOSE_TYPE
    session.current_query_id = None
    session.contact = {}
    msg = "Hi! 👋 I'm your support assistant. What can I help you with today?"
    session.log("bot", msg)
    return BotResponse(
        message=msg,
        options=_query_type_options(),
        input_type=InputType.OPTIONS,
        state=State.CHOOSE_TYPE,
        tail=_GREETING_TAIL,
    )


def _instructions_response(session: Session, qt: dict[str, Any]) -> BotResponse:
    """Render a query type's steps plus sub-topic / satisfaction options."""
    session.state = State.SHOW_INSTRUCTIONS
    session.current_query_id = qt["id"]

    steps = list(qt.get("steps", []))
    msg = f"Happy to help with {qt['label']}. Here are the steps:"

    options: list[Option] = []
    for sub in qt.get("sub_topics", []):
        options.append(Option(id=f"sub:{sub['id']}", label=sub["label"]))

    options.append(Option(id=_OPT_YES, label="Yes, that solved it"))
    options.append(Option(id=_OPT_NO, label="No, I need more help"))

    session.state = State.ASK_SATISFIED
    tail = "Did this solve your issue?"
    resp = BotResponse(
        message=msg,
        options=options,
        input_type=InputType.OPTIONS,
        state=State.ASK_SATISFIED,
        steps=steps,
        tail=tail,
    )
    session.log("bot", resp.plain_text())
    return resp


def _subtopic_response(session: Session, qt: dict[str, Any], sub: dict[str, Any]) -> BotResponse:
    """Render a sub-topic's steps plus satisfaction options."""
    msg = f"Here's exactly what to do — {sub['label'].lower()}:"
    options = [
        Option(id=_OPT_YES, label="Yes, that solved it"),
        Option(id=_OPT_NO, label="No, I need more help"),
    ]
    session.state = State.ASK_SATISFIED
    resp = BotResponse(
        message=msg,
        options=options,
        input_type=InputType.OPTIONS,
        state=State.ASK_SATISFIED,
        steps=list(sub.get("steps", [])),
        tail="Did this resolve your issue?",
    )
    session.log("bot", resp.plain_text())
    return resp


def _ask_satisfied_close(session: Session) -> BotResponse:
    """Friendly close after a 'yes'."""
    session.state = State.CHOOSE_TYPE
    session.current_query_id = None
    msg = (
        "Wonderful — glad that sorted it. I'll leave the topics below in case "
        "anything else comes up. Have a great day!"
    )
    options = _query_type_options()
    options.append(Option(id=_OPT_DONE, label="No, I'm all set"))
    session.log("bot", msg)
    return BotResponse(
        message=msg,
        options=options,
        input_type=InputType.OPTIONS,
        state=State.CHOOSE_TYPE,
    )


def _begin_escalation(session: Session) -> BotResponse:
    """Offer / start human escalation after a 'no'."""
    session.state = State.COLLECT_CONTACT
    # Pre-fill from the intake gate so the customer isn't asked twice.
    session.contact = dict(session.user)
    msg = (
        "No problem — let me connect you with a human support expert. Share "
        "your details below and someone will follow up by email."
    )
    session.log("bot", msg)
    qt = get_query_type(session.current_query_id or "")
    return BotResponse(
        message=msg,
        options=[],
        input_type=InputType.CONTACT_FORM,
        state=State.COLLECT_CONTACT,
        meta={
            "prefill": dict(session.user),
            "topic": qt["label"] if qt else "General",
        },
    )


def _closed(session: Session) -> BotResponse:
    """Terminal goodbye."""
    session.state = State.CLOSED
    msg = "Thanks for chatting with us. Have a great day! 👋"
    session.log("bot", msg)
    return BotResponse(
        message=msg,
        options=[Option(id=_OPT_MENU, label="Start over 🔄")],
        input_type=InputType.NONE,
        state=State.CLOSED,
    )


def handle_free_text(session: Session, text: str) -> BotResponse:
    """Route free text via keyword matching, then optional AI, then escalation."""
    result = match(text)

    if result.confident and result.query_id:
        qt = get_query_type(result.query_id)
        if qt:
            resp = _instructions_response(session, qt)
            resp.message = f"That sounds like {qt['label']} — here's what to do:"
            return resp

    # Not confident — try optional AI fallback.
    ai_answer = ai.maybe_ai_answer(text)
    if ai_answer:
        session.state = State.ASK_SATISFIED
        options = [
            Option(id=_OPT_YES, label="Yes, that solved it"),
            Option(id=_OPT_NO, label="No, I need more help"),
        ]
        resp = BotResponse(
            message=ai_answer,
            options=options,
            input_type=InputType.OPTIONS,
            state=State.ASK_SATISFIED,
            tail="Did that help?",
        )
        session.log("bot", resp.plain_text())
        return resp

    # No confident match and no AI — show the menu and offer a human.
    session.state = State.CHOOSE_TYPE
    msg = (
        "I want to get this right rather than guess. Pick the closest topic "
        "below, or I can hand you straight to a human expert."
    )
    options = _query_type_options()
    options.append(Option(id=_OPT_HUMAN, label="Talk to a human"))
    session.log("bot", msg)
    return BotResponse(
        message=msg,
        options=options,
        input_type=InputType.OPTIONS,
        state=State.CHOOSE_TYPE,
    )


def handle_option(session: Session, option_id: str) -> BotResponse:
    """Process a selected option id based on the current state."""
    # Global options usable from most states.
    if option_id == _OPT_SKIP:
        return skip_intake(session)
    if option_id == _OPT_MENU:
        return greeting(session)
    if option_id == _OPT_DONE:
        return _closed(session)
    if option_id == _OPT_HUMAN:
        return _begin_escalation(session)

    if option_id == _OPT_YES:
        return _ask_satisfied_close(session)
    if option_id == _OPT_NO:
        return _begin_escalation(session)

    # Sub-topic selection (e.g. "sub:reset_password").
    if option_id.startswith("sub:") and session.current_query_id:
        sub_id = option_id.split(":", 1)[1]
        sub = get_sub_topic(session.current_query_id, sub_id)
        qt = get_query_type(session.current_query_id)
        if sub and qt:
            return _subtopic_response(session, qt, sub)

    # Main-menu query type selection.
    qt = get_query_type(option_id)
    if qt:
        return _instructions_response(session, qt)

    # Unknown option — fall back to the menu.
    return greeting(session)


def submit_contact(
    session: Session,
    name: str,
    email: str,
    message: str,
    *,
    create_ticket: Callable[..., Any] = tickets.create_ticket,
    db_path: Any = None,
) -> BotResponse:
    """Validate contact details and create an escalation ticket.

    Args:
        session: The active session.
        name: Customer name.
        email: Customer email.
        message: Short description of the issue.
        create_ticket: Injectable ticket factory (defaults to the real store);
            tests can pass a fake or a custom ``db_path``.
        db_path: Optional database path forwarded to the ticket store.

    Returns:
        A :class:`BotResponse`. On a validation error the state stays at
        ``COLLECT_CONTACT`` and the error message is returned.
    """
    query_type = session.current_query_id or "other"
    kwargs: dict[str, Any] = {}
    if db_path is not None:
        kwargs["db_path"] = db_path

    try:
        ticket = create_ticket(
            name=name,
            email=email,
            query_type=query_type,
            message=message,
            transcript=session.transcript_text(),
            **kwargs,
        )
    except ValueError as exc:
        # Stay on the form so the user can correct their input.
        session.state = State.COLLECT_CONTACT
        msg = f"⚠️ {exc} Please try again."
        session.log("bot", msg)
        return BotResponse(
            message=msg,
            options=[],
            input_type=InputType.CONTACT_FORM,
            state=State.COLLECT_CONTACT,
        )

    session.state = State.TICKET_CREATED
    # Remember the identity so a follow-up escalation doesn't ask again.
    session.user = {"name": ticket.name, "email": ticket.email}
    first_name = ticket.name.split()[0] if ticket.name.split() else ticket.name
    qt = get_query_type(query_type)
    topic_label = qt["label"] if qt else "General"
    msg = f"All set, {first_name} — your request is with our experts now."
    options = _query_type_options()
    options.append(Option(id=_OPT_DONE, label="No, I'm all set"))
    resp = BotResponse(
        message=msg,
        options=options,
        input_type=InputType.OPTIONS,
        state=State.TICKET_CREATED,
        tail="Anything else I can help with in the meantime?",
        meta={
            "ticket_id": ticket.id,
            "ticket_title": f"Support ticket #{ticket.id} created",
            "ticket_meta": f"{topic_label} · a human will email {ticket.email}",
        },
    )
    session.log("bot", resp.plain_text())
    return resp
