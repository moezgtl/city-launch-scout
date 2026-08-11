"""City Launch Scout — MCP Server

Exposes three tools to Claude:
  scout_venues   — run the full pipeline for a city/zone
  list_runs      — list previous scout runs saved in out/
  get_shortlist  — read the shortlist from a previous run

Once this server is running, a city manager can open Claude Desktop and type:
  "Scout restaurants in Oberkampf, Paris, France"
  "Show me the shortlist from my last run"
  "What venues did we find in Lisbon?"

Claude will call the right tool, run the pipeline, and show the results
directly in the conversation — no Terminal needed.

Usage:
  pip install "mcp[cli]" fastmcp
  python mcp_server/server.py          # stdio mode (for Claude Desktop)

Claude Desktop config (~/.claude/claude_desktop_config.json):
  {
    "mcpServers": {
      "city-launch-scout": {
        "command": "python3",
        "args": ["/full/path/to/city-launch-scout/mcp_server/server.py"]
      }
    }
  }
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path

# Add the project root to sys.path so we can import src.*
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Load .env from project root (Claude Desktop doesn't inherit shell env vars)
_env_file = ROOT / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            import os as _os
            _os.environ.setdefault(_k.strip(), _v.strip())

from mcp.server.fastmcp import FastMCP

from src.config import load_rubric
from src.hard_filters import partition
from src.llm import build_llm
from src.outreach import draft_for_shortlist
from src.places import Zone, build_backend
from src.report import build_payload, now_iso, write_html, write_json

mcp = FastMCP(
    name="city-launch-scout",
    instructions="""
You help Timeleft city managers find and vet candidate restaurants for dinners.

A Timeleft dinner is six strangers at one table for roughly two hours on a
weeknight. A good venue lets them hear each other, feeds everyone (including
vegetarians), and handles a group reservation without friction.

When someone asks you to scout venues:
1. Ask for city, neighbourhood, and country if not provided
2. If they don't know the coordinates, tell them to right-click the centre of
   the neighbourhood on Google Maps — the numbers that appear are lat/lng
3. Call scout_venues with those details
4. Summarise the top 3 shortlisted venues in plain language
5. Mention any venues flagged for manual review

Always remind the city manager that outreach emails are drafts — a human
should read each one before sending.
""",
)


@mcp.tool()
def scout_venues(
    city: str,
    zone: str,
    latitude: float,
    longitude: float,
    country: str = "",
    sender_name: str = "Maja",
    max_results: int = 20,
    mock: bool = False,
) -> str:
    """
    Scout candidate restaurants for a Timeleft dinner in a given neighbourhood.

    Runs the full pipeline: discover → hard filter → score → draft outreach.
    Returns a plain-language summary of the results plus the path to the
    full HTML report the city manager can open in their browser.

    Args:
        city:         City name, e.g. "Paris"
        zone:         Neighbourhood name, e.g. "Oberkampf"
        latitude:     Zone centroid latitude (right-click on Google Maps)
        longitude:    Zone centroid longitude (right-click on Google Maps)
        country:      Country name, e.g. "France" (used for email language)
        sender_name:  Name to sign outreach drafts with (default: Maja)
        max_results:  How many venues to fetch from Google (default: 20)
        mock:         Use synthetic data instead of real APIs (for testing)
    """
    started = time.time()

    try:
        from src.llm import DEFAULT_MODEL, DEFAULT_SCORING_MODEL
        rubric = load_rubric()
        backend, fixture_zone = build_backend(mock)
        zone_obj = fixture_zone if mock else Zone(
            city=city, name=zone,
            latitude=latitude, longitude=longitude,
            country=country,
        )
        scoring_llm = build_llm(mock, rubric.dimension_names, model=DEFAULT_SCORING_MODEL)
        outreach_llm = build_llm(mock, rubric.dimension_names, model=DEFAULT_MODEL)

        venues = backend.search(zone_obj, "restaurant", max_results)
        eligible, rejected = partition(venues, zone_obj, rubric)

        if not eligible:
            return (
                f"Found {len(venues)} venues in {zone}, {city} but none passed "
                f"the hard filters (rating ≥ {rubric.hard_filters['min_rating']}, "
                f"≥ {rubric.hard_filters['min_review_count']} reviews, "
                f"price level {rubric.hard_filters['allowed_price_levels']}, "
                f"within {rubric.hard_filters['max_distance_from_zone_m']}m). "
                "Try widening the radius or lowering min_review_count in config/rubric.yaml."
            )

        from src.score import score_all
        scored = score_all([r.venue for r in eligible], rubric, scoring_llm)
        emails = draft_for_shortlist(scored, zone_obj, outreach_llm, sender_name)

        out_dir = ROOT / "out"
        out_dir.mkdir(exist_ok=True)

        combined_usage = {
            "calls": scoring_llm.usage.calls + outreach_llm.usage.calls,
            "input_tokens": scoring_llm.usage.input_tokens + outreach_llm.usage.input_tokens,
            "output_tokens": scoring_llm.usage.output_tokens + outreach_llm.usage.output_tokens,
            "seconds": round(scoring_llm.usage.seconds + outreach_llm.usage.seconds, 1),
            "cost_usd": round(scoring_llm.usage.cost_usd + outreach_llm.usage.cost_usd, 6),
        }

        payload = build_payload(
            scored, rejected, zone_obj, emails,
            run_meta={
                "run_id": uuid.uuid4().hex[:8],
                "generated_at": now_iso(),
                "rubric_version": rubric.version,
                "mock": mock,
                "n_found": len(venues),
                "usage": combined_usage,
                "runtime_seconds": round(time.time() - started, 1),
            },
        )

        json_path = write_json(payload, out_dir)
        html_path = write_html(payload, out_dir)

        # Build a plain-language summary for Claude to relay
        shortlisted = [s for s in scored if s.verdict == "shortlist"]
        backup = [s for s in scored if s.verdict == "backup"]
        needs_review = [s for s in scored if s.verdict == "review"]

        lines = [
            f"✅ Scout complete for {zone}, {city}{', ' + country if country else ''}",
            f"",
            f"📊 {len(venues)} venues found → {len(eligible)} passed filters → "
            f"{len(shortlisted)} shortlisted",
            f"",
        ]

        if shortlisted:
            lines.append("🟢 Contact these first:")
            for s in shortlisted[:5]:
                phone = f" · {s.venue.phone}" if s.venue.phone else ""
                lines.append(f"  • {s.venue.name} ({s.weighted_score:.0f}/100){phone}")
                lines.append(f"    {s.summary}")

        if backup:
            lines.append(f"\n🟡 Backup ({len(backup)} venues):")
            for s in backup[:3]:
                lines.append(f"  • {s.venue.name} ({s.weighted_score:.0f}/100)")

        if needs_review:
            lines.append(
                f"\n🟠 {len(needs_review)} venue(s) need manual review "
                f"(not enough evidence to score automatically)"
            )

        if rejected:
            lines.append(f"\n🔴 {len(rejected)} rejected by hard filters")

        lines += [
            f"",
            f"📄 Full report: {html_path}",
            f"   Open this file in your browser to see all details, scores, and draft emails.",
            f"",
            f"⚠️  Outreach emails are drafts — please read each one before sending.",
            f"",
            f"⏱  {payload['runtime_seconds']}s · "
            f"{payload['usage']['input_tokens'] + payload['usage']['output_tokens']} tokens used",
        ]

        return "\n".join(lines)

    except Exception as e:
        return (
            f"❌ Scout failed: {type(e).__name__}: {e}\n\n"
            "Common causes:\n"
            "• Missing API keys in .env\n"
            "• Google Places API not enabled (needs 'Places API (New)')\n"
            "• No Anthropic credit\n"
            "Run with mock=True to test without API keys."
        )


@mcp.tool()
def list_runs() -> str:
    """
    List all previous scout runs saved in the out/ folder.

    Returns a summary of each run: city, zone, date, how many venues
    were shortlisted.
    """
    out_dir = ROOT / "out"
    json_files = sorted(out_dir.glob("shortlist*.json"), reverse=True)

    if not json_files:
        return "No previous runs found in out/. Run scout_venues first."

    lines = [f"Found {len(json_files)} previous run(s):\n"]
    for path in json_files[:10]:
        try:
            data = json.loads(path.read_text())
            shortlisted = sum(1 for s in data.get("scored", []) if s["verdict"] == "shortlist")
            lines.append(
                f"• {data.get('zone')}, {data.get('city')} "
                f"— {data.get('generated_at', '')[:10]} "
                f"— {shortlisted} shortlisted "
                f"(run {data.get('run_id', '?')})"
            )
        except Exception:
            lines.append(f"• {path.name} (could not read)")

    return "\n".join(lines)


@mcp.tool()
def get_shortlist(run_id: str = "") -> str:
    """
    Get the shortlisted venues from a previous scout run.

    Args:
        run_id: The 8-character run ID from list_runs. Leave empty to get
                the most recent run.
    """
    out_dir = ROOT / "out"
    json_files = sorted(out_dir.glob("shortlist*.json"), reverse=True)

    if not json_files:
        return "No previous runs found. Run scout_venues first."

    # Find the right file
    target = None
    if run_id:
        for path in json_files:
            try:
                data = json.loads(path.read_text())
                if data.get("run_id") == run_id:
                    target = data
                    break
            except Exception:
                continue
        if not target:
            return f"Run ID '{run_id}' not found. Use list_runs to see available runs."
    else:
        target = json.loads(json_files[0].read_text())

    shortlisted = [s for s in target.get("scored", []) if s["verdict"] == "shortlist"]
    backup = [s for s in target.get("scored", []) if s["verdict"] == "backup"]

    lines = [
        f"Shortlist for {target.get('zone')}, {target.get('city')} "
        f"(run {target.get('run_id')}, {target.get('generated_at', '')[:10]})",
        "",
    ]

    if shortlisted:
        lines.append("🟢 Contact:")
        for s in shortlisted:
            phone = f"\n    📞 {s['phone']}" if s.get("phone") else ""
            lines.append(f"\n  {s['name']} — {s['weighted_score']:.0f}/100{phone}")
            lines.append(f"  {s['summary']}")
            for d in s.get("dimensions", []):
                if d["score"] is not None:
                    lines.append(f"    {d['name'].replace('_',' ')}: {d['score']}/3 — {d['justification']}")
    else:
        lines.append("No venues shortlisted in this run.")

    if backup:
        lines.append(f"\n🟡 Backup ({len(backup)}):")
        for s in backup:
            lines.append(f"  • {s['name']} ({s['weighted_score']:.0f}/100) — {s['summary']}")

    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="stdio")
