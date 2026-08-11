"""Thin Anthropic client.

Deliberately built on `requests` rather than the SDK so the repo has one fewer
dependency and so the offline stub can stand in without any monkeypatching.
Swap in the official SDK if you prefer — the interface is one method.

Tracks tokens and wall time per call because "this run cost 4 cents and took
90 seconds" is a number the ops team will ask for on day one.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import requests

from .config import get_env

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-4-6"


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0

    def add(self, input_tokens: int, output_tokens: int, seconds: float) -> None:
        self.calls += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.seconds += seconds

    def as_dict(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "seconds": round(self.seconds, 1),
        }


class LLM(Protocol):
    usage: Usage

    def complete_json(self, system: str, user: str, max_tokens: int) -> dict[str, Any]: ...
    def complete_text(self, system: str, user: str, max_tokens: int) -> str: ...


def _extract_json(text: str) -> dict[str, Any]:
    """Models sometimes wrap JSON in prose or fences despite instructions.
    Strip the common cases rather than failing the whole run over a backtick."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


class AnthropicLLM:
    def __init__(self, model: str = DEFAULT_MODEL, api_key: str | None = None, timeout: int = 60):
        self.model = model
        self.api_key = api_key or get_env("ANTHROPIC_API_KEY", required=True)
        self.timeout = timeout
        self.usage = Usage()

    def _call(self, system: str, user: str, max_tokens: int) -> str:
        headers = {
            "content-type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": API_VERSION,
        }
        body = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }

        last_error: Exception | None = None
        for attempt in range(3):
            started = time.time()
            try:
                resp = requests.post(API_URL, json=body, headers=headers, timeout=self.timeout)
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise requests.HTTPError(f"transient {resp.status_code}")
                resp.raise_for_status()
                data = resp.json()
                usage = data.get("usage", {})
                self.usage.add(
                    usage.get("input_tokens", 0),
                    usage.get("output_tokens", 0),
                    time.time() - started,
                )
                return "".join(
                    b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"
                )
            except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as e:
                last_error = e
                time.sleep(2**attempt)
        raise RuntimeError(f"Anthropic call failed after 3 attempts: {last_error}")

    def complete_json(self, system: str, user: str, max_tokens: int = 1500) -> dict[str, Any]:
        return _extract_json(self._call(system, user, max_tokens))

    def complete_text(self, system: str, user: str, max_tokens: int = 800) -> str:
        return self._call(system, user, max_tokens).strip()


class StubLLM:
    """Offline stand-in.

    This is NOT a model. It is a crude keyword heuristic that returns
    correctly-shaped output so the pipeline runs end to end with no key and no
    network. Scores from this backend are not meaningful — the eval harness
    exists precisely to show you the difference between this and the real thing.
    """

    NEGATIVE = {
        "conversation_fit": ["shout", "loud", "noisy", "dj", "nightclub", "music so loud", "echo"],
        "dietary_range": ["only thing she could order", "meat heavy", "nothing for veg", "basically nothing"],
        "group_readiness": ["impossible for a group", "no bookings", "no reservation", "mostly standing", "gave up"],
        "service_quality": ["forgot", "waited forty", "chaotic", "slow to notice"],
        "atmosphere": ["canteen", "processed", "nothing special"],
    }
    POSITIVE = {
        "conversation_fit": ["actually have a conversation", "quiet", "well spaced", "easy to talk", "never becomes a problem", "acoustics are good"],
        "dietary_range": ["vegetarian", "vegan", "clearly marked", "clearly labelled", "half the menu"],
        "group_readiness": ["big table", "communal table", "merged two tables", "split the bill", "large table", "group of six"],
        "service_quality": ["attentive", "warm", "patient", "looked after", "could not have been kinder"],
        "atmosphere": ["warm", "beautiful", "charming", "welcome", "lovely"],
    }

    def __init__(self, dimensions: list[str]):
        self.dimensions = dimensions
        self.usage = Usage()

    def complete_json(self, system: str, user: str, max_tokens: int = 1500) -> dict[str, Any]:
        started = time.time()
        blob = user.lower()
        scores: dict[str, Any] = {}
        for dim in self.dimensions:
            neg = sum(1 for k in self.NEGATIVE.get(dim, []) if k in blob)
            pos = sum(1 for k in self.POSITIVE.get(dim, []) if k in blob)
            if neg == 0 and pos == 0:
                score, why = None, "stub found no keywords either way"
            else:
                score = max(0, min(3, 2 + pos - neg))
                why = f"stub heuristic: {pos} positive and {neg} negative keyword hits"
            scores[dim] = {"score": score, "justification": why, "evidence": "(stub backend, no evidence extracted)"}
        self.usage.add(len(user) // 4, 200, time.time() - started)
        return {"dimensions": scores, "summary": "Generated by the offline stub backend. Not a real assessment."}

    def complete_text(self, system: str, user: str, max_tokens: int = 800) -> str:
        started = time.time()
        self.usage.add(len(user) // 4, 150, time.time() - started)
        return (
            "[STUB OUTREACH DRAFT — the offline backend does not write real emails. "
            "Run without --mock to generate these.]"
        )


def build_llm(mock: bool, dimensions: list[str], model: str = DEFAULT_MODEL) -> LLM:
    return StubLLM(dimensions) if mock else AnthropicLLM(model=model)
