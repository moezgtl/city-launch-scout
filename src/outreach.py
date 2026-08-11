"""Drafts a first-contact email per shortlisted venue.

Drafts only. Nothing here sends anything. A human reads every one before it
goes out — partly because a bad first email burns a venue permanently, and
partly because a tool that emails strangers on your behalf without review is
not a tool anybody should deploy.
"""

from __future__ import annotations

from .config import ROOT
from .llm import LLM
from .places import Zone
from .score import ScoredVenue

PROMPT_PATH = ROOT / "prompts" / "outreach_email.md"


def draft_email(scored: ScoredVenue, zone: Zone, llm: LLM, sender_name: str) -> str:
    rationale_lines = [
        f"- {d.name}: {d.score}/3 — {d.justification}"
        for d in scored.dimensions
        if d.score is not None
    ]
    prompt = (
        PROMPT_PATH.read_text()
        .replace("{NAME}", scored.venue.name)
        .replace("{TYPE}", scored.venue.primary_type or "restaurant")
        .replace("{ZONE}", zone.name)
        .replace("{CITY}", zone.city)
        .replace("{SENDER_NAME}", sender_name)
        .replace("{RATIONALE}", "\n".join(rationale_lines) or "(none)")
        .replace("{MATERIAL}", scored.venue.review_text(limit=5))
    )
    try:
        return llm.complete_text(
            system="You write short, specific, unfussy emails. You return only the email.",
            user=prompt,
        )
    except Exception as e:
        return f"[Draft failed: {type(e).__name__}. Write this one by hand or rerun.]"


def draft_for_shortlist(
    scored: list[ScoredVenue], zone: Zone, llm: LLM, sender_name: str
) -> dict[str, str]:
    """Only drafts for venues we would actually contact. Drafting emails for
    rejected venues is spend with no purpose."""
    return {
        s.venue.id: draft_email(s, zone, llm, sender_name)
        for s in scored
        if s.verdict in ("shortlist", "backup")
    }
