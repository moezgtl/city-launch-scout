"""Deterministic eligibility gate.

This module exists to keep the LLM out of decisions that have a right answer.
Rating, review count, price band, distance and operational status are facts. A
language model asked to apply them will occasionally get them wrong, and when a
city manager asks "why was this rejected" the answer needs to be a number, not
a vibe.

Everything here is pure and unit-testable. No network, no model, no surprises.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import Rubric
from .places import Venue, Zone, haversine_m


@dataclass
class FilterResult:
    venue: Venue
    passed: bool
    failures: list[str]

    @property
    def reason(self) -> str:
        return "; ".join(self.failures) if self.failures else "eligible"


def apply(venue: Venue, zone: Zone, rubric: Rubric) -> FilterResult:
    hf = rubric.hard_filters
    failures: list[str] = []

    venue.distance_m = haversine_m(
        zone.latitude, zone.longitude, venue.latitude, venue.longitude
    )

    if hf.get("require_operational", True) and venue.business_status != "OPERATIONAL":
        failures.append(f"not operational ({venue.business_status})")

    if venue.rating is None:
        failures.append("no rating available")
    elif venue.rating < hf["min_rating"]:
        failures.append(f"rating {venue.rating} below {hf['min_rating']}")

    if venue.review_count is None:
        failures.append("no review count available")
    elif venue.review_count < hf["min_review_count"]:
        failures.append(
            f"only {venue.review_count} reviews, floor is {hf['min_review_count']}"
        )

    allowed = hf["allowed_price_levels"]
    if venue.price_level is None:
        # Unknown price is not disqualifying, but it is worth surfacing. We let
        # it through and flag it in the report rather than silently dropping a
        # venue that might be perfect.
        pass
    elif venue.price_level not in allowed:
        failures.append(f"price level {venue.price_level} outside {allowed}")

    max_d = hf["max_distance_from_zone_m"]
    if venue.distance_m is not None and venue.distance_m > max_d:
        failures.append(f"{venue.distance_m:.0f}m from zone centre, limit {max_d}m")

    if hf.get("require_reservations", False) and venue.reservable is False:
        failures.append("does not take reservations")

    return FilterResult(venue=venue, passed=not failures, failures=failures)


def partition(
    venues: list[Venue], zone: Zone, rubric: Rubric
) -> tuple[list[FilterResult], list[FilterResult]]:
    """Split into (eligible, rejected). Rejected venues are kept, not discarded —
    a city manager needs to see what was thrown away and why, otherwise the tool
    is a black box and nobody trusts it."""
    results = [apply(v, zone, rubric) for v in venues]
    return [r for r in results if r.passed], [r for r in results if not r.passed]
