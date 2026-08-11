"""Measure the scorer against human labels.

    python eval/run_eval.py --run out/shortlist.json

This is the part of the project that turns "it seems to work" into a number.
Two numbers matter, and they are not the same:

  Dimension agreement — how often the scorer picks the same 0-3 as the human.
  Verdict agreement   — how often the scorer reaches the same shortlist /
                        backup / reject decision. This is the one that changes
                        what a city manager actually does, so it is the one to
                        quote.

A scorer can be mediocre on dimensions and still be useful if the verdicts land,
because the verdict is what gets acted on. Report both and be honest about the gap.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import load_rubric  # noqa: E402

DIMENSIONS = ["dietary_range", "conversation_fit", "group_readiness", "service_quality", "atmosphere"]


def read_labels(path: Path) -> dict[str, dict]:
    rows = {}
    with open(path) as f:
        lines = [ln for ln in f if not ln.startswith(">")]
    for row in csv.DictReader(lines):
        rows[row["venue_id"]] = row
    return rows


def human_verdict(label: dict, rubric) -> tuple[float, str]:
    """Apply the exact same aggregation to the human labels, so we compare
    verdicts on equal footing rather than comparing a model verdict to a
    human gut call."""
    weights = {d: rubric.scored_dimensions[d]["weight"] for d in DIMENSIONS}
    scores = {d: int(label[d]) for d in DIMENSIONS}
    raw = sum((scores[d] / 3.0) * weights[d] for d in DIMENSIONS)
    weighted = raw * 100
    for d in DIMENSIONS:
        if scores[d] == 0 and weights[d] >= 0.2:
            return weighted, "reject"
    if weighted >= rubric.verdict_thresholds["shortlist"]:
        return weighted, "shortlist"
    if weighted >= rubric.verdict_thresholds["backup"]:
        return weighted, "backup"
    return weighted, "reject"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=str(ROOT / "out" / "shortlist.json"))
    ap.add_argument("--labels", default=str(ROOT / "eval" / "labels.csv"))
    ap.add_argument("--rubric", default=str(ROOT / "config" / "rubric.yaml"))
    args = ap.parse_args()

    rubric = load_rubric(args.rubric)
    labels = read_labels(Path(args.labels))
    run = json.loads(Path(args.run).read_text())
    scored = {s["id"]: s for s in run["scored"]}

    overlap = [vid for vid in labels if vid in scored]
    if not overlap:
        print("No overlap between labels and run output. Did you run the scout first?")
        return 1

    backend = "offline stub" if run.get("mock") else "live model"
    print(f"\nEvaluating {len(overlap)} labelled venues  ·  backend: {backend}\n")

    per_dim = {d: {"exact": 0, "within1": 0, "abs_err": 0, "n": 0} for d in DIMENSIONS}
    disagreements = []

    for vid in overlap:
        label, pred = labels[vid], scored[vid]
        pred_dims = {d["name"]: d["score"] for d in pred["dimensions"]}
        for d in DIMENSIONS:
            truth = int(label[d])
            got = pred_dims.get(d)
            if got is None:
                continue
            per_dim[d]["n"] += 1
            err = abs(got - truth)
            per_dim[d]["abs_err"] += err
            per_dim[d]["exact"] += err == 0
            per_dim[d]["within1"] += err <= 1
            if err >= 2:
                disagreements.append((label["venue_name"], d, truth, got))

    print(f"{'dimension':<18}{'exact':>8}{'±1':>8}{'mean err':>10}")
    print("-" * 44)
    tot_exact = tot_within = tot_n = tot_err = 0
    for d in DIMENSIONS:
        s = per_dim[d]
        if not s["n"]:
            continue
        tot_exact += s["exact"]; tot_within += s["within1"]; tot_n += s["n"]; tot_err += s["abs_err"]
        print(f"{d:<18}{s['exact']/s['n']:>7.0%}{s['within1']/s['n']:>8.0%}{s['abs_err']/s['n']:>10.2f}")
    print("-" * 44)
    print(f"{'ALL':<18}{tot_exact/tot_n:>7.0%}{tot_within/tot_n:>8.0%}{tot_err/tot_n:>10.2f}")

    # Verdict agreement — the number that matters operationally.
    v_match = 0
    v_rows = []
    for vid in overlap:
        _, truth_v = human_verdict(labels[vid], rubric)
        pred_v = scored[vid]["verdict"]
        v_match += truth_v == pred_v
        v_rows.append((labels[vid]["venue_name"], truth_v, pred_v))

    print(f"\nVerdict agreement: {v_match}/{len(overlap)} = {v_match/len(overlap):.0%}\n")
    print(f"{'venue':<24}{'human':<12}{'scorer':<12}")
    print("-" * 48)
    for name, t, p in v_rows:
        mark = "" if t == p else "   <-- differs"
        print(f"{name:<24}{t:<12}{p:<12}{mark}")

    # False shortlists are the expensive error: a city manager wastes an
    # outreach email and possibly a real dinner on a bad room. Track separately.
    false_shortlist = sum(1 for _, t, p in v_rows if p == "shortlist" and t != "shortlist")
    missed = sum(1 for _, t, p in v_rows if t == "shortlist" and p != "shortlist")
    print(f"\nFalse shortlists (costly): {false_shortlist}")
    print(f"Missed good venues (cheap): {missed}")

    if disagreements:
        print("\nWorst dimension disagreements (off by 2 or more):")
        for name, d, truth, got in disagreements:
            print(f"  {name:<22} {d:<18} human {truth}  scorer {got}")
        print("\nThese are where to look first when improving the prompt.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
