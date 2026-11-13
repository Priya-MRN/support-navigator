"""Colored terminal chatbot built on the conversation engine.

Run with ``python -m chatbot`` (or the ``support-bot`` console script). The CLI
presents numbered menu choices AND accepts free-text input at every prompt.
"""

from __future__ import annotations

import sys

from colorama import Fore, Style
from colorama import init as colorama_init

from . import __version__, ai, engine
from .engine import BotResponse, InputType, Option, Session


def _c(text: str, color: str) -> str:
    """Wrap text in a color and reset."""
    return f"{color}{text}{Style.RESET_ALL}"


def _print_bot(resp: BotResponse) -> None:
    """Render a bot response: message, steps, tail, then numbered options."""
    # ``plain_text`` re-joins the structured steps/tail the web UI renders
    # as real list items. Strip any legacy **bold** markers for the terminal.
    message = resp.plain_text().replace("**", "")
    print()
    for line in message.splitlines():
        print(_c("  bot ", Fore.CYAN + Style.BRIGHT) + _c("│ ", Fore.CYAN) + line)

    if resp.meta.get("ticket_title"):
        print(
            _c("  bot ", Fore.CYAN + Style.BRIGHT)
            + _c("│ ", Fore.CYAN)
            + _c(f"✅ {resp.meta['ticket_title']}", Fore.GREEN + Style.BRIGHT)
        )
        print(
            _c("  bot ", Fore.CYAN + Style.BRIGHT)
            + _c("│ ", Fore.CYAN)
            + _c(f"   {resp.meta.get('ticket_meta', '')}", Fore.GREEN)
        )

    if resp.options:
        print()
        for idx, opt in enumerate(resp.options, start=1):
            icon = f"{opt.icon} " if opt.icon else ""
            print(
                "       "
                + _c(f"[{idx}] ", Fore.YELLOW + Style.BRIGHT)
                + f"{icon}{opt.label}"
            )


def _resolve_choice(user_input: str, options: list[Option]) -> str | None:
    """Map a numeric choice to an option id; return ``None`` for free text."""
    stripped = user_input.strip()
    if stripped.isdigit() and options:
        n = int(stripped)
        if 1 <= n <= len(options):
            return options[n - 1].id
    return None


def _prompt(label: str = "you") -> str:
    """Read a line of input from the user."""
    return input(_c(f"  {label} ", Fore.GREEN + Style.BRIGHT) + _c("│ ", Fore.GREEN))


def _collect_contact(session: Session) -> BotResponse:
    """Interactively collect name/email/message, re-prompting on errors."""
    while True:
        name = _prompt("name").strip()
        email = _prompt("email").strip()
        message = _prompt("issue").strip()
        session.log("user", f"[contact] {name} / {email} / {message}")
        resp = engine.submit_contact(session, name, email, message)
        # If validation failed, the engine returns the contact form again.
        if resp.input_type == InputType.CONTACT_FORM:
            _print_bot(resp)
            continue
        return resp


def _run_intake(session: Session) -> BotResponse:
    """Show the intake gate and collect name/email, re-prompting on errors.

    Leaving both fields blank skips the gate, mirroring the web UI's
    "Skip for now" button.
    """
    _print_bot(engine.start(session))
    print()
    print(_c("       (press Enter twice to skip)", Fore.YELLOW))

    while True:
        name = _prompt("name").strip()
        email = _prompt("email").strip()
        if not name and not email:
            session.log("user", "[intake] skipped")
            return engine.skip_intake(session)
        session.log("user", f"[intake] {name} / {email}")
        resp = engine.submit_intake(session, name, email)
        if resp.input_type == InputType.INTAKE_FORM:
            _print_bot(resp)  # validation error — ask again
            continue
        return resp


def run() -> None:
    """Run the interactive CLI loop."""
    colorama_init()

    banner = _c("=" * 58, Fore.MAGENTA)
    print(banner)
    print(_c(f"  Customer Support Chatbot  v{__version__}", Fore.MAGENTA + Style.BRIGHT))
    ai_state = "ON ✨" if ai.is_available() else "off (rule-based)"
    print(_c(f"  AI fallback: {ai_state}", Fore.MAGENTA))
    print(_c("  Type a number to pick an option, or just type your question.", Fore.MAGENTA))
    print(_c("  Type 'quit' to exit.", Fore.MAGENTA))
    print(banner)

    session = Session()
    resp = _run_intake(session)
    _print_bot(resp)

    while True:
        try:
            user_input = _prompt()
        except (EOFError, KeyboardInterrupt):
            print()
            print(_c("  Goodbye! 👋", Fore.MAGENTA))
            return

        if user_input.strip().lower() in {"quit", "exit", "bye"}:
            print(_c("\n  Goodbye! 👋", Fore.MAGENTA))
            return

        session.log("user", user_input)

        # The contact form is handled with its own multi-field prompt.
        if resp.input_type == InputType.CONTACT_FORM:
            # The single line already read becomes the name; gather the rest.
            email = _prompt("email").strip()
            message = _prompt("issue").strip()
            resp = engine.submit_contact(session, user_input.strip(), email, message)
            if resp.input_type == InputType.CONTACT_FORM:
                _print_bot(resp)
                resp = _collect_contact(session)
            _print_bot(resp)
            continue

        # If the user picked an option by number, dispatch it; else free text.
        choice = _resolve_choice(user_input, resp.options)
        if choice is not None:
            resp = engine.handle_option(session, choice)
            # Selecting "Talk to a human" / "No" leads to the contact form.
            if resp.input_type == InputType.CONTACT_FORM:
                _print_bot(resp)
                resp = _collect_contact(session)
        else:
            resp = engine.handle_free_text(session, user_input)
            if resp.input_type == InputType.CONTACT_FORM:
                _print_bot(resp)
                resp = _collect_contact(session)

        _print_bot(resp)

        if resp.state == engine.State.CLOSED:
            return


def main() -> int:
    """Entry point for the console script."""
    try:
        run()
    except Exception as exc:  # pragma: no cover - top-level safety net
        print(f"Unexpected error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
