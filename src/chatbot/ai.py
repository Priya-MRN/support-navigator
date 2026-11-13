"""Optional AI fallback powered by the Anthropic Claude API.

This module is *entirely optional*. The chatbot works fully without it via
the rule-based menu and keyword matcher. When an ``ANTHROPIC_API_KEY`` is
present in the environment, free-text questions that the matcher can't confidently
handle are sent to Claude for a helpful, support-scoped answer.

The ``anthropic`` import is lazy so the package imports and runs even if the
SDK isn't installed. Any error (missing key, missing SDK, network failure)
results in ``None`` being returned so the caller can gracefully escalate.
"""

from __future__ import annotations

import os

# Recommended current model per the claude-api skill (latest Opus tier).
_MODEL = "claude-opus-4-8"

# Keep the assistant tightly scoped to polite customer support.
_SYSTEM_PROMPT = (
    "You are a friendly, concise customer support assistant for a generic "
    "online store / SaaS product. Answer the customer's question helpfully in "
    "2-5 short sentences. Give practical, step-by-step guidance when relevant. "
    "Never invent account-specific details, order numbers, or policies you "
    "cannot know. If the request needs human action (refunds, account access, "
    "billing disputes), say so and suggest contacting a human support expert. "
    "Stay polite and professional."
)


def is_available() -> bool:
    """Return ``True`` if an Anthropic API key is configured."""
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


def maybe_ai_answer(question: str) -> str | None:
    """Try to answer a free-text question with Claude.

    Returns ``None`` if no API key is set, the SDK is unavailable, or any
    error occurs — the caller should then fall back to escalation.

    Args:
        question: The customer's free-text question.

    Returns:
        A short support answer string, or ``None`` on any failure.
    """
    if not is_available():
        return None

    question = (question or "").strip()
    if not question:
        return None

    try:
        # Lazy import so the package works without the SDK installed.
        import anthropic  # type: ignore

        client = anthropic.Anthropic()
        response = client.messages.create(
            model=_MODEL,
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            # Adaptive thinking is recommended for 4.6+ models.
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": question}],
        )

        # response.content is a list of blocks; collect the text blocks.
        parts = [
            block.text
            for block in response.content
            if getattr(block, "type", None) == "text"
        ]
        answer = "\n".join(p for p in parts if p).strip()
        return answer or None
    except Exception:
        # Missing SDK, auth error, network failure, refusal, etc.
        # Stay graceful: the engine will escalate to a human instead.
        return None
