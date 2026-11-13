"""Flask web app: a responsive chat widget + an agent (expert) inbox.

Routes:
    GET  /            -> the chat widget UI
    POST /api/message -> drive the engine (send session id + input/option)
    POST /api/reset   -> reset a session
    GET  /agent       -> read-only inbox of open escalation tickets

Sessions are kept in memory keyed by a client-supplied session id. This is a
demo/portfolio app; for production you'd back sessions with a store like Redis.
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request

# Make the package importable when running this file directly (python web/app.py).
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from chatbot import __version__, ai, engine, knowledge, tickets  # noqa: E402
from chatbot.engine import BotResponse, Session  # noqa: E402

app = Flask(__name__)

# In-memory session registry: {session_id: Session}.
_SESSIONS: dict[str, Session] = {}


def _get_session(session_id: str | None) -> tuple[str, Session]:
    """Fetch or create a session for the given id."""
    if session_id and session_id in _SESSIONS:
        return session_id, _SESSIONS[session_id]
    new_id = session_id or uuid.uuid4().hex
    session = Session()
    _SESSIONS[new_id] = session
    return new_id, session


def _serialize(resp: BotResponse) -> dict[str, Any]:
    """Convert a BotResponse into a JSON-friendly dict."""
    return {
        "message": resp.message,
        "steps": list(resp.steps),
        "tail": resp.tail,
        "options": [
            {"id": o.id, "label": o.label, "icon": o.icon} for o in resp.options
        ],
        "input_type": resp.input_type.value,
        "state": resp.state.value,
        "meta": resp.meta,
    }


@app.template_filter("topic_label")
def topic_label(query_type: str) -> str:
    """Render a query type id as its human-readable label."""
    qt = knowledge.get_query_type(query_type)
    return qt["label"] if qt else query_type.replace("_", " ").title()


@app.template_filter("nice_date")
def nice_date(iso: str) -> str:
    """Format a stored ISO timestamp for display (e.g. '27 Jul 2026, 17:09')."""
    try:
        return datetime.fromisoformat(iso).strftime("%d %b %Y, %H:%M")
    except (TypeError, ValueError):
        return iso


@app.get("/")
def index() -> str:
    """Render the chat widget page."""
    return render_template(
        "chat.html",
        version=__version__,
        ai_enabled=ai.is_available(),
        topics=knowledge.get_query_types(),
    )


@app.post("/api/message")
def api_message() -> Any:
    """Drive the conversation engine.

    Request JSON may contain:
        session_id: existing session id (optional on first call)
        action:     "start" | "intake" | "skip_intake" | "option" | "text"
                    | "contact"
        option_id:  for action == "option"
        text:       for action == "text"
        name/email:         for action == "intake"
        name/email/message: for action == "contact"
    """
    data = request.get_json(silent=True) or {}
    session_id, session = _get_session(data.get("session_id"))
    action = data.get("action", "start")

    if action == "start":
        resp = engine.start(session)
    elif action == "intake":
        name = data.get("name", "")
        email = data.get("email", "")
        session.log("user", f"[intake] {name} / {email}")
        resp = engine.submit_intake(session, name, email)
    elif action == "skip_intake":
        session.log("user", "[intake] skipped")
        resp = engine.skip_intake(session)
    elif action == "option":
        option_id = data.get("option_id", "")
        session.log("user", f"[option] {option_id}")
        resp = engine.handle_option(session, option_id)
    elif action == "text":
        text = (data.get("text") or "").strip()
        session.log("user", text)
        resp = engine.handle_free_text(session, text)
    elif action == "contact":
        name = data.get("name", "")
        email = data.get("email", "")
        message = data.get("message", "")
        session.log("user", f"[contact] {name} / {email} / {message}")
        resp = engine.submit_contact(session, name, email, message)
    else:
        resp = engine.start(session)

    payload = _serialize(resp)
    payload["session_id"] = session_id
    return jsonify(payload)


@app.post("/api/reset")
def api_reset() -> Any:
    """Reset (or create) a session and return a fresh intake gate."""
    data = request.get_json(silent=True) or {}
    session_id, session = _get_session(data.get("session_id"))
    # Drop any prior state so a restart genuinely starts over.
    _SESSIONS[session_id] = Session()
    resp = engine.start(_SESSIONS[session_id])
    payload = _serialize(resp)
    payload["session_id"] = session_id
    return jsonify(payload)


@app.get("/agent")
def agent_inbox() -> str:
    """Render the experts' inbox of open tickets."""
    open_tickets = tickets.list_tickets(status="open")
    return render_template("agent.html", tickets=open_tickets, version=__version__)


def main() -> None:
    """Run the development server."""
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)


if __name__ == "__main__":
    main()
