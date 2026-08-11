"""Judgement layer.

The LLM scores each venue on the rubric's soft dimensions. Aggregation into a
final number happens in Python, not in the prompt — asking a model to do
weighted arithmetic is a way to introduce errors you cannot see.

Every score carries a justification and the evidence behind it. If a city
manager cannot audit a rejection in ten seconds, they will stop using the tool.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import ROOT, Rubric
from .llm import LLM
from .places import Venue

PROMPT_PATH = ROOT / "prompts" / "venue_score.md"


@dataclass
class DimensionScore:
    name: str
    score: int | None
    justification: str
    evidence: str | None


@dataclass
class ScoredVenue:
    venue: Venue
    dimensions: list[DimensionScore]
    weighted_score: float
    verdict: str
    summary: str
    flags: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.venue.id,
            "name": self.venue.name,
            "address": self.venue.address,
            "latitude": self.venue.latitude,
            "longitude": self.venue.longitude,
            "rating": self.venue.rating,
            "review_count": self.venue.review_count,
            "price_level": self.venue.price_level,
            "distance_m": round(self.venue.distance_m) if self.venue.distance_m else None,
            "website": self.venue.website,
            "phone": self.venue.phone,
            "country": self.venue.country,
            "weighted_score": round(self.weighted_score, 1),
            "verdict": self.verdict,
            "summary": self.summary,
            "flags": self.flags,
            "dimensions": [
                {
                    "name": d.name,
                    "score": d.score,
                    "justification": d.justification,
                    "evidence": d.evidence,
                }
                for d in self.dimensions
            ],
        }


def _build_prompt(venue: Venue, rubric: Rubric) -> str:
    template = PROMPT_PATH.read_text()
    dimensions = "\n".join(
        f"### {name}\n{spec['question'].strip()}"
        for name, spec in rubric.scored_dimensions.items()
    )
    scale = "\n".join(f"- **{k}** — {v}" for k, v in sorted(rubric.score_scale.items()))
    return (
        template.replace("{DIMENSIONS}", dimensions)
        .replace("{SCALE}", scale)
        .replace("{NAME}", venue.name)
        .replace("{TYPE}", venue.primary_type or "unknown")
        .replace("{ADDRESS}", venue.address)
        .replace("{MATERIAL}", venue.review_text())
    )


def _aggregate(dimensions: list[DimensionScore], rubric: Rubric) -> tuple[float, list[str]]:
    """Weighted score out of 100, renormalised over the dimensions that were
    actually scored. A venue with two nulls is not penalised for the nulls — it
    is flagged instead, which is the honest treatment."""
    flags: list[str] = []
    scored = [d for d in dimensions if d.score is not None]
    unscored = [d for d in dimensions if d.score is None]

    if unscored:
        flags.append(f"no evidence for: {', '.join(d.name for d in unscored)}")
    if len(unscored) > rubric.max_unscored_dimensions:
        flags.append("too little evidence to score reliably — needs manual review")
    if not scored:
        return 0.0, flags + ["nothing could be scored"]

    weight_total = sum(rubric.scored_dimensions[d.name]["weight"] for d in scored)
    raw = sum(
        (d.score / 3.0) * rubric.scored_dimensions[d.name]["weight"] for d in scored
    )
    normalised = (raw / weight_total) * 100 if weight_total else 0.0

    # A zero on a heavily weighted dimension should not be averaged away.
    for d in scored:
        if d.score == 0 and rubric.scored_dimensions[d.name]["weight"] >= 0.2:
            flags.append(f"disqualifying score on {d.name}")

    return normalised, flags


def _verdict(weighted: float, flags: list[str], rubric: Rubric) -> str:
    if any(f.startswith("disqualifying") for f in flags):
        return "reject"
    if any("manual review" in f for f in flags):
        return "review"
    if weighted >= rubric.verdict_thresholds["shortlist"]:
        return "shortlist"
    if weighted >= rubric.verdict_thresholds["backup"]:
        return "backup"
    return "reject"


def score_venue(venue: Venue, rubric: Rubric, llm: LLM) -> ScoredVenue:
    prompt = _build_prompt(venue, rubric)
    system = "You are a careful venue scout. You return only valid JSON."

    try:
        raw = llm.complete_json(system=system, user=prompt)
    except Exception as e:
        # One venue failing to score must not kill a run over twenty venues.
        return ScoredVenue(
            venue=venue,
            dimensions=[],
            weighted_score=0.0,
            verdict="error",
            summary=f"Scoring failed: {type(e).__name__}",
            flags=["scoring error — retry this venue individually"],
        )

    payload = raw.get("dimensions", {})
    dimensions: list[DimensionScore] = []
    for name in rubric.dimension_names:
        entry = payload.get(name) or {}
        score = entry.get("score")
        if isinstance(score, (int, float)) and score is not None:
            score = max(0, min(3, int(round(score))))
        else:
            score = None
        dimensions.append(
            DimensionScore(
                name=name,
                score=score,
                justification=entry.get("justification") or "(none returned)",
                evidence=entry.get("evidence"),
            )
        )

    weighted, flags = _aggregate(dimensions, rubric)
    return ScoredVenue(
        venue=venue,
        dimensions=dimensions,
        weighted_score=weighted,
        verdict=_verdict(weighted, flags, rubric),
        summary=raw.get("summary") or "",
        flags=flags,
    )


def score_all(venues: list[Venue], rubric: Rubric, llm: LLM) -> list[ScoredVenue]:
    results = [score_venue(v, rubric, llm) for v in venues]
    return sorted(results, key=lambda s: s.weighted_score, reverse=True)
