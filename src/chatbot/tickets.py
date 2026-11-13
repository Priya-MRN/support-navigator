"""SQLite-backed support ticket store for human escalations.

When a customer is not satisfied and asks to talk to a human expert, the
engine collects their name, email, and a short message and creates a ticket
here. The ``/agent`` web page (the "experts inbox") reads from this store.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# Default location of the SQLite database (next to the package data dir).
_DEFAULT_DB_PATH = Path(__file__).resolve().parent / "data" / "tickets.db"

# Pragmatic email validation: good enough to catch obvious mistakes without
# trying to fully implement RFC 5322.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_valid_email(email: str) -> bool:
    """Return ``True`` if ``email`` looks like a valid address."""
    return bool(_EMAIL_RE.match(email.strip())) if email else False


@dataclass
class Ticket:
    """A single support escalation ticket."""

    id: int
    name: str
    email: str
    query_type: str
    message: str
    transcript: str
    created_at: str
    status: str


def _connect(db_path: str | Path) -> sqlite3.Connection:
    """Open a SQLite connection with row access by column name."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str | Path = _DEFAULT_DB_PATH) -> None:
    """Create the tickets table if it does not already exist."""
    with _connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tickets (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL,
                email       TEXT NOT NULL,
                query_type  TEXT NOT NULL,
                message     TEXT NOT NULL,
                transcript  TEXT NOT NULL DEFAULT '',
                created_at  TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'open'
            )
            """
        )
        conn.commit()


def create_ticket(
    name: str,
    email: str,
    query_type: str,
    message: str,
    transcript: str = "",
    db_path: str | Path = _DEFAULT_DB_PATH,
) -> Ticket:
    """Create and persist a new support ticket.

    Args:
        name: Customer's name.
        email: Customer's email address (validated).
        query_type: The query type label/id this escalation relates to.
        message: Short description of the issue from the customer.
        transcript: Optional captured conversation transcript.
        db_path: Database location (overridable for tests).

    Returns:
        The created :class:`Ticket` including its assigned id.

    Raises:
        ValueError: If name/message are empty or the email is invalid.
    """
    name = (name or "").strip()
    email = (email or "").strip()
    message = (message or "").strip()

    if not name:
        raise ValueError("Name is required.")
    if not is_valid_email(email):
        raise ValueError("A valid email address is required.")
    if not message:
        raise ValueError("A short message describing the issue is required.")

    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    init_db(db_path)
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO tickets
                (name, email, query_type, message, transcript, created_at, status)
            VALUES (?, ?, ?, ?, ?, ?, 'open')
            """,
            (name, email, query_type, message, transcript, created_at),
        )
        conn.commit()
        ticket_id = int(cur.lastrowid)

    return Ticket(
        id=ticket_id,
        name=name,
        email=email,
        query_type=query_type,
        message=message,
        transcript=transcript,
        created_at=created_at,
        status="open",
    )


def list_tickets(
    status: str | None = None, db_path: str | Path = _DEFAULT_DB_PATH
) -> list[Ticket]:
    """Return tickets, newest first, optionally filtered by status."""
    init_db(db_path)
    with _connect(db_path) as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM tickets WHERE status = ? ORDER BY id DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM tickets ORDER BY id DESC"
            ).fetchall()

    return [
        Ticket(
            id=row["id"],
            name=row["name"],
            email=row["email"],
            query_type=row["query_type"],
            message=row["message"],
            transcript=row["transcript"],
            created_at=row["created_at"],
            status=row["status"],
        )
        for row in rows
    ]
