"""Run-level observability.

Collects timing, token usage, cost estimates, and API call counts
so every run is fully auditable. Printed to the terminal and embedded
in the HTML report.

Cost constants are approximate list prices as of mid-2025.
Check https://www.anthropic.com/pricing for the latest figures.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class StepTimer:
    name: str
    started: float = field(default_factory=time.time)
    ended: float | None = None

    def stop(self) -> "StepTimer":
        self.ended = time.time()
        return self

    @property
    def seconds(self) -> float:
        if self.ended is None:
            return time.time() - self.started
        return round(self.ended - self.started, 2)


@dataclass
class RunStats:
    # Timing
    run_started: float = field(default_factory=time.time)
    steps: list[StepTimer] = field(default_factory=list)

    # Counts
    n_found: int = 0
    n_passed_filters: int = 0
    n_rejected_filters: int = 0
    n_scored: int = 0
    n_errors: int = 0
    n_shortlisted: int = 0
    n_backup: int = 0
    n_emails_drafted: int = 0
    google_api_calls: int = 0

    # LLM usage (filled from llm.usage at end of run)
    model: str = ""
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    llm_seconds: float = 0.0
    cost_usd: float = 0.0  # accurate per-model cost, summed from Usage instances

    def start_step(self, name: str) -> StepTimer:
        t = StepTimer(name=name)
        self.steps.append(t)
        return t

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def cost_per_venue(self) -> float | None:
        if self.n_scored == 0:
            return None
        return round(self.cost_usd / self.n_scored, 5)

    @property
    def runtime_seconds(self) -> float:
        return round(time.time() - self.run_started, 1)

    def as_dict(self) -> dict[str, Any]:
        return {
            "runtime_seconds": self.runtime_seconds,
            "steps": [
                {"name": s.name, "seconds": s.seconds} for s in self.steps
            ],
            "counts": {
                "found": self.n_found,
                "passed_filters": self.n_passed_filters,
                "rejected_filters": self.n_rejected_filters,
                "scored": self.n_scored,
                "errors": self.n_errors,
                "shortlisted": self.n_shortlisted,
                "backup": self.n_backup,
                "emails_drafted": self.n_emails_drafted,
            },
            "api_calls": {
                "google_places": self.google_api_calls,
                "anthropic_llm": self.llm_calls,
            },
            "llm": {
                "model": self.model,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "total_tokens": self.total_tokens,
                "llm_seconds": round(self.llm_seconds, 1),
            },
            "cost": {
                "total_usd": self.cost_usd,
                "per_venue_usd": self.cost_per_venue,
                "note": "Approximate list price. Check anthropic.com/pricing for current rates.",
            },
        }

    def print_summary(self) -> None:
        """Print a human-readable summary to stdout."""
        sep = "─" * 52
        print(f"\n  {sep}")
        print(f"  {'RUN SUMMARY':^52}")
        print(f"  {sep}")

        # Pipeline counts
        print(f"  {'PIPELINE':}")
        print(f"    Found          {self.n_found:>6}")
        print(f"    Passed filters {self.n_passed_filters:>6}  ({self.n_rejected_filters} rejected)")
        print(f"    Scored         {self.n_scored:>6}  ({self.n_errors} errors)")
        print(f"    Shortlisted    {self.n_shortlisted:>6}")
        print(f"    Backup         {self.n_backup:>6}")
        print(f"    Emails drafted {self.n_emails_drafted:>6}")

        # Step timings
        if self.steps:
            print(f"\n  {'TIMING':}")
            for s in self.steps:
                bar_len = min(20, int(s.seconds * 2))
                bar = "█" * bar_len
                print(f"    {s.name:<20} {s.seconds:>5.1f}s  {bar}")
            print(f"    {'TOTAL':<20} {self.runtime_seconds:>5.1f}s")

        # API calls
        print(f"\n  {'API CALLS':}")
        print(f"    Google Places  {self.google_api_calls:>6}")
        print(f"    Anthropic LLM  {self.llm_calls:>6}")

        # Tokens & cost
        if self.llm_calls > 0:
            print(f"\n  {'LLM USAGE':}  ({self.model})")
            print(f"    Input tokens   {self.input_tokens:>8,}")
            print(f"    Output tokens  {self.output_tokens:>8,}")
            print(f"    Total tokens   {self.total_tokens:>8,}")
            print(f"    LLM time       {self.llm_seconds:>7.1f}s")
            print(f"\n  {'COST (approx.)':}")
            print(f"    Total          ${self.cost_usd:.4f}")
            if self.cost_per_venue is not None:
                print(f"    Per venue      ${self.cost_per_venue:.5f}")
            print(f"    (list price · claude-sonnet-4-6 · mid-2025)")

        print(f"  {sep}\n")
