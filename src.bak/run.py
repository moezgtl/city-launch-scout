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
from .llm import DEFAULT_MODEL, build_llm
from .outreach import draft_for_shortlist
from .places import PlacesBackend, Zone, build_backend
from .report import build_payload, now_iso, write_emails, write_html, write_json
from .score import score_all


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
    p.add_argument("--model", default=DEFAULT_MODEL)
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
    started = time.time()

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
    llm = build_llm(mock, rubric.dimension_names, model=args.model)

    print(f"→ Scouting {zone.name}, {zone.city}" + ("  [offline stub]" if mock else ""))

    venues = backend.search(zone, args.query, args.max_results)
    print(f"  found {len(venues)} candidates")

    eligible, rejected = partition(venues, zone, rubric)
    print(f"  {len(eligible)} passed hard filters, {len(rejected)} rejected")
    if not eligible:
        print("  nothing to score — widen the zone or relax config/rubric.yaml")

    scored = score_all([r.venue for r in eligible], rubric, llm)
    print(f"  scored {len(scored)} venues")

    emails = {}
    if scored and not args.no_outreach:
        emails = draft_for_shortlist(scored, zone, llm, args.sender)
        print(f"  drafted {len(emails)} outreach emails")

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
            "usage": llm.usage.as_dict(),
            "runtime_seconds": round(time.time() - started, 1),
        },
    )

    json_path = write_json(payload, out_dir)
    html_path = write_html(payload, out_dir)
    email_path = write_emails(payload, out_dir)

    print(f"\n  {json_path}")
    print(f"  {html_path}")
    if email_path:
        print(f"  {email_path}")
    u = payload["usage"]
    print(f"\n  {payload['runtime_seconds']}s · {u['calls']} model calls · "
          f"{u['input_tokens'] + u['output_tokens']} tokens")
    return 0


if __name__ == "__main__":
    sys.exit(main())
