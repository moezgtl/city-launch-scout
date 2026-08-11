"""City Launch Scout — entry point.

    python -m src.run --mock
    python -m src.run --city Lisbon --zone "Principe Real" --lat 38.7167 --lng -9.15

Pipeline:
    discover  →  hard filter (code)  →  score (LLM)  →  draft outreach  →  report
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from pathlib import Path

from .config import ROOT, load_rubric, get_env
from .hard_filters import partition
from .llm import DEFAULT_MODEL, DEFAULT_SCORING_MODEL, build_llm
from .outreach import draft_for_shortlist
from .places import PlacesBackend, Zone, build_backend
from .report import build_payload, now_iso, write_emails, write_html, write_json
from .score import score_all
from .stats import RunStats


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Scout candidate venues for a Timeleft city launch.")
    p.add_argument("--mock", action="store_true",
                   help="Run offline against synthetic fixtures. No API keys needed.")
    p.add_argument("--fixture", help="Path to a fixture JSON file (implies --mock behaviour).")
    p.add_argument("--city", help="City name, e.g. Lisbon.")
    p.add_argument("--zone", help="Neighbourhood, e.g. 'Principe Real'.")
    p.add_argument("--country", default="", help="Country name, e.g. France.")
    p.add_argument("--lat", type=float, help="Zone centroid latitude.")
    p.add_argument("--lng", type=float, help="Zone centroid longitude.")
    p.add_argument("--query", default="restaurant", help="Search query passed to Places.")
    p.add_argument("--max-results", type=int, default=20)
    p.add_argument("--model", default=DEFAULT_MODEL,
                   help="Model for outreach email drafting.")
    p.add_argument("--scoring-model", default=DEFAULT_SCORING_MODEL,
                   help="Model for venue scoring. Defaults to Haiku (cheaper). Use --model value to match outreach quality.")
    p.add_argument("--sender", default="Maja", help="Name to sign outreach drafts with.")
    p.add_argument("--no-outreach", action="store_true", help="Skip email drafting.")
    p.add_argument("--out", default=str(ROOT / "out"))
    p.add_argument("--rubric", default=str(ROOT / "config" / "rubric.yaml"))
    return p.parse_args(argv)


def resolve_zone(args: argparse.Namespace, fixture_zone: Zone | None) -> Zone:
    if fixture_zone and not args.city:
        return fixture_zone
    missing = [f for f in ("city", "zone", "lat", "lng") if getattr(args, f) is None]
    if missing:
        raise SystemExit(
            f"Live runs need --{', --'.join(missing)}. "
            "Or use --mock to run against the bundled fixture."
        )
    return Zone(city=args.city, name=args.zone, latitude=args.lat, longitude=args.lng, country=getattr(args, "country", "") or "")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    mock = args.mock or bool(args.fixture)
    stats = RunStats()

    # Check keys up front so we fail loudly before doing any work.
    if not mock:
        missing = [k for k in ("ANTHROPIC_API_KEY", "GOOGLE_PLACES_API_KEY") if not get_env(k)]
        if missing:
            print("\n  ERROR: missing API keys:", ", ".join(missing))
            print("  Make sure your .env file exists in the project folder and contains:")
            for k in missing:
                print(f"    {k}=your-key-here")
            print("  Or run with --mock to test without keys.\n")
            return 1

    rubric = load_rubric(args.rubric)
    backend, fixture_zone = build_backend(mock, args.fixture)
    zone = resolve_zone(args, fixture_zone)
    scoring_llm = build_llm(mock, rubric.dimension_names, model=args.scoring_model)
    outreach_llm = build_llm(mock, rubric.dimension_names, model=args.model)
    stats.model = f"scoring={args.scoring_model} · outreach={args.model}"

    print(f"→ Scouting {zone.name}, {zone.city}" + ("  [offline stub]" if mock else ""))

    # Step 1: Discover
    t = stats.start_step("discover")
    venues = backend.search(zone, args.query, args.max_results)
    t.stop()
    stats.n_found = len(venues)
    stats.google_api_calls = getattr(backend, "_call_count", 1) if not mock else 0
    print(f"  found {len(venues)} candidates")

    # Step 2: Hard filters
    t = stats.start_step("hard filters")
    eligible, rejected = partition(venues, zone, rubric)
    t.stop()
    stats.n_passed_filters = len(eligible)
    stats.n_rejected_filters = len(rejected)
    print(f"  {len(eligible)} passed hard filters, {len(rejected)} rejected")
    if not eligible:
        print("  nothing to score — widen the zone or relax config/rubric.yaml")

    # Step 3: Score
    t = stats.start_step("score (LLM)")
    scored = score_all([r.venue for r in eligible], rubric, scoring_llm)
    t.stop()
    stats.n_scored = len(scored)
    stats.n_errors = sum(1 for s in scored if s.verdict == "error")
    stats.n_shortlisted = sum(1 for s in scored if s.verdict == "shortlist")
    stats.n_backup = sum(1 for s in scored if s.verdict == "backup")
    print(f"  scored {len(scored)} venues  ({stats.n_errors} errors)")

    # Step 4: Outreach
    emails = {}
    if scored and not args.no_outreach:
        t = stats.start_step("outreach (LLM)")
        emails = draft_for_shortlist(scored, zone, outreach_llm, args.sender)
        t.stop()
        stats.n_emails_drafted = len(emails)
        print(f"  drafted {len(emails)} outreach emails")

    # Collect final LLM usage (combined from both LLMs)
    combined_calls   = scoring_llm.usage.calls   + outreach_llm.usage.calls
    combined_input   = scoring_llm.usage.input_tokens  + outreach_llm.usage.input_tokens
    combined_output  = scoring_llm.usage.output_tokens + outreach_llm.usage.output_tokens
    combined_seconds = scoring_llm.usage.seconds + outreach_llm.usage.seconds
    combined_cost    = scoring_llm.usage.cost_usd + outreach_llm.usage.cost_usd
    stats.llm_calls    = combined_calls
    stats.input_tokens = combined_input
    stats.output_tokens = combined_output
    stats.llm_seconds  = combined_seconds
    stats.cost_usd     = round(combined_cost, 6)

    # Step 5: Write outputs
    t = stats.start_step("write outputs")
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    payload = build_payload(
        scored, rejected, zone, emails,
        run_meta={
            "run_id": uuid.uuid4().hex[:8],
            "generated_at": now_iso(),
            "rubric_version": rubric.version,
            "mock": mock,
            "n_found": len(venues),
            "usage": {
                "calls": combined_calls,
                "input_tokens": combined_input,
                "output_tokens": combined_output,
                "seconds": round(combined_seconds, 1),
                "cost_usd": round(combined_cost, 6),
            },
            "runtime_seconds": stats.runtime_seconds,
            "stats": stats.as_dict(),
        },
    )

    json_path = write_json(payload, out_dir)
    html_path = write_html(payload, out_dir)
    email_path = write_emails(payload, out_dir)
    t.stop()

    print(f"\n  {json_path}")
    print(f"  {html_path}")
    if email_path:
        print(f"  {email_path}")

    stats.print_summary()
    return 0


if __name__ == "__main__":
    sys.exit(main())
