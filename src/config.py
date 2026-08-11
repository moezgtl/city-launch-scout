"""Configuration loading. The rubric lives in YAML so a non-engineer can change
the thresholds without touching Python."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RUBRIC = ROOT / "config" / "rubric.yaml"


@dataclass
class Rubric:
    version: str
    hard_filters: dict[str, Any]
    scored_dimensions: dict[str, dict[str, Any]]
    score_scale: dict[int, str]
    verdict_thresholds: dict[str, int]
    max_unscored_dimensions: int

    @property
    def dimension_names(self) -> list[str]:
        return list(self.scored_dimensions.keys())

    def validate(self) -> None:
        total = sum(d["weight"] for d in self.scored_dimensions.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"Dimension weights must sum to 1.0, got {total:.4f}. "
                "Fix config/rubric.yaml."
            )
        if self.verdict_thresholds["shortlist"] <= self.verdict_thresholds["backup"]:
            raise ValueError("shortlist threshold must be above backup threshold.")


def load_rubric(path: Path | str = DEFAULT_RUBRIC) -> Rubric:
    with open(path) as f:
        raw = yaml.safe_load(f)
    rubric = Rubric(
        version=raw["version"],
        hard_filters=raw["hard_filters"],
        scored_dimensions=raw["scored_dimensions"],
        score_scale=raw["score_scale"],
        verdict_thresholds=raw["verdict_thresholds"],
        max_unscored_dimensions=raw["max_unscored_dimensions"],
    )
    rubric.validate()
    return rubric


def load_dotenv(path: Path | str = ROOT / ".env") -> None:
    """Read a .env file into the environment.

    Hand-rolled rather than pulling in python-dotenv, because one fewer thing to
    install is one fewer thing to go wrong on someone else's machine. Real
    environment variables always win, so this never clobbers a value you set
    deliberately in your shell.
    """
    path = Path(path)
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


def get_env(name: str, required: bool = False) -> str | None:
    load_dotenv()
    value = os.environ.get(name)
    if required and not value:
        raise RuntimeError(
            f"Missing required environment variable {name}. "
            "Copy .env.example to .env and fill it in, or run with --mock."
        )
    return value
