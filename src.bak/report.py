"""Outputs.

Two artefacts per run:
  shortlist.json  — machine-readable, feeds Sheets/Notion or the eval harness
  shortlist.html  — a standalone page a city manager opens and works from

The HTML is a single file with no build step and no server. That matters: the
person who needs it works in Slack and Notion, and "open this file" is a much
lower bar than "run this locally".
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ROOT, Rubric
from .hard_filters import FilterResult
from .places import Zone
from .score import ScoredVenue

TEMPLATE = ROOT / "src" / "templates" / "report.html"

MOCK_DISCLAIMER = (
    "This run used the offline stub backend. Venue data is synthetic and the scores "
    "come from a keyword heuristic, not a language model. Nothing here is a real "
    "assessment — it exists to show the pipeline working end to end."
)
LIVE_DISCLAIMER = (
    "Scores are model judgements from public review text and are a starting point for "
    "a human decision, not a substitute for one. Hard filters (rating, review count, "
    "price, distance) were applied in code and are exact."
)


def build_payload(
    scored: list[ScoredVenue],
    rejected: list[FilterResult],
    zone: Zone,
    emails: dict[str, str],
    run_meta: dict[str, Any],
) -> dict[str, Any]:
    return {
        "run_id": run_meta["run_id"],
        "generated_at": run_meta["generated_at"],
        "city": zone.city,
        "zone": zone.name,
        "country": zone.country,
        "rubric_version": run_meta["rubric_version"],
        "mock": run_meta["mock"],
        "counts": {
            "found": run_meta["n_found"],
            "eligible": len(scored),
            "rejected_by_filters": len(rejected),
            "shortlist": sum(1 for s in scored if s.verdict == "shortlist"),
        },
        "usage": run_meta["usage"],
        "runtime_seconds": run_meta["runtime_seconds"],
        "scored": [s.as_dict() for s in scored],
        "rejected": [
            {"id": r.venue.id, "name": r.venue.name, "reason": r.reason} for r in rejected
        ],
        "outreach_drafts": emails,
    }


def write_json(payload: dict[str, Any], out_dir: Path) -> Path:
    path = out_dir / "shortlist.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return path


def write_html(payload: dict[str, Any], out_dir: Path) -> Path:
    html = TEMPLATE.read_text()
    replacements = {
        "{{RUN_ID}}": payload["run_id"],
        "{{ZONE}}": payload["zone"],
        "{{COUNTRY_LINE}}": (f", {payload['country']}" if payload.get("country") else ""),
        "{{CITY}}": payload["city"],
        "{{N_FOUND}}": str(payload["counts"]["found"]),
        "{{N_ELIGIBLE}}": str(payload["counts"]["eligible"]),
        "{{N_SHORTLIST}}": str(payload["counts"]["shortlist"]),
        "{{RUNTIME}}": str(payload["runtime_seconds"]),
        "{{TOKENS}}": str(payload["usage"]["input_tokens"] + payload["usage"]["output_tokens"]),
        "{{RUBRIC_VERSION}}": payload["rubric_version"],
        "{{DISCLAIMER}}": MOCK_DISCLAIMER if payload["mock"] else LIVE_DISCLAIMER,
        "{{DATA}}": json.dumps(payload, ensure_ascii=False),
    }
    for key, value in replacements.items():
        html = html.replace(key, value)
    path = out_dir / "shortlist.html"
    path.write_text(html)
    return path


def write_emails(payload: dict[str, Any], out_dir: Path) -> Path | None:
    if not payload["outreach_drafts"]:
        return None
    by_id = {s["id"]: s["name"] for s in payload["scored"]}
    lines = [f"# Outreach drafts — {payload['zone']}, {payload['city']}", ""]
    lines.append("Drafts only. Read each one before sending.\n")
    for vid, body in payload["outreach_drafts"].items():
        lines += [f"## {by_id.get(vid, vid)}", "", "```", body, "```", ""]
    path = out_dir / "outreach_drafts.md"
    path.write_text("\n".join(lines))
    return path


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
