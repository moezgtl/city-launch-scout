"""Venue discovery.

Two backends behind one interface:
  - `FixtureBackend` reads synthetic JSON. No key, no network, deterministic.
    This is what the eval harness runs against and what a reviewer can run.
  - `PlacesBackend` calls the Google Places API (New) searchText endpoint.

Keeping these behind one interface means the rest of the pipeline never knows
or cares which one it got, and the whole thing is testable without a key.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import requests

from .config import ROOT, get_env

PLACES_ENDPOINT = "https://places.googleapis.com/v1/places:searchText"

# Only ask for the fields we actually use. Places bills by field mask, so this
# is a cost decision as much as a hygiene one.
FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.location",
        "places.rating",
        "places.userRatingCount",
        "places.priceLevel",
        "places.businessStatus",
        "places.reservable",
        "places.primaryType",
        "places.editorialSummary",
        "places.reviews",
        "places.websiteUri",
        "places.nationalPhoneNumber",
        "places.addressComponents",
    ]
)

_PRICE_LEVEL_MAP = {
    "PRICE_LEVEL_FREE": 0,
    "PRICE_LEVEL_INEXPENSIVE": 1,
    "PRICE_LEVEL_MODERATE": 2,
    "PRICE_LEVEL_EXPENSIVE": 3,
    "PRICE_LEVEL_VERY_EXPENSIVE": 4,
}


@dataclass
class Venue:
    """Normalised venue. Everything downstream speaks this, not raw API JSON."""

    id: str
    name: str
    address: str
    latitude: float
    longitude: float
    rating: float | None
    review_count: int | None
    price_level: int | None
    business_status: str
    reservable: bool | None
    primary_type: str | None
    summary: str | None
    reviews: list[dict[str, Any]] = field(default_factory=list)
    website: str | None = None
    phone: str | None = None
    country: str | None = None

    # Filled in later by the pipeline.
    distance_m: float | None = None

    def review_text(self, limit: int = 8) -> str:
        """Flatten reviews into the block of text the scorer reads."""
        parts = []
        if self.summary:
            parts.append(f"Editorial summary: {self.summary}")
        for r in self.reviews[:limit]:
            stars = r.get("rating", "?")
            parts.append(f"[{stars}/5] {r.get('text', '').strip()}")
        return "\n".join(parts) if parts else "(no review text available)"


@dataclass
class Zone:
    city: str
    name: str
    latitude: float
    longitude: float
    country: str = ""


class Backend(Protocol):
    def search(self, zone: Zone, query: str, max_results: int) -> list[Venue]: ...


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in metres. Good enough at neighbourhood scale."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _normalise(raw: dict[str, Any]) -> Venue:
    """Map a Places payload (or a fixture in the same shape) onto Venue."""
    name = raw.get("displayName")
    if isinstance(name, dict):  # live API returns {"text": ..., "languageCode": ...}
        name = name.get("text")

    summary = raw.get("editorialSummary")
    if isinstance(summary, dict):
        summary = summary.get("text")

    price = raw.get("priceLevel")
    if isinstance(price, str):
        price = _PRICE_LEVEL_MAP.get(price)

    reviews = []
    for r in raw.get("reviews", []) or []:
        text = r.get("text")
        if isinstance(text, dict):
            text = text.get("text")
        reviews.append({"rating": r.get("rating"), "text": text or ""})

    loc = raw.get("location", {}) or {}

    # Extract country from address components if available
    country = None
    for comp in raw.get("addressComponents", []) or []:
        if "country" in (comp.get("types") or []):
            country = comp.get("longText") or comp.get("shortText")
            break

    return Venue(
        id=raw.get("id", ""),
        name=name or "(unnamed)",
        address=raw.get("formattedAddress", ""),
        latitude=loc.get("latitude", 0.0),
        longitude=loc.get("longitude", 0.0),
        rating=raw.get("rating"),
        review_count=raw.get("userRatingCount"),
        price_level=price,
        business_status=raw.get("businessStatus", "UNKNOWN"),
        reservable=raw.get("reservable"),
        primary_type=raw.get("primaryType"),
        summary=summary,
        reviews=reviews,
        website=raw.get("websiteUri"),
        phone=raw.get("nationalPhoneNumber"),
        country=country,
    )


class FixtureBackend:
    """Offline backend. Reads a hand-written JSON file."""

    def __init__(self, path: Path | str):
        self.path = Path(path)

    def search(self, zone: Zone, query: str, max_results: int) -> list[Venue]:
        with open(self.path) as f:
            data = json.load(f)
        venues = [_normalise(p) for p in data["places"]]
        return venues[:max_results]

    @staticmethod
    def zone_from_fixture(path: Path | str) -> Zone:
        with open(path) as f:
            data = json.load(f)
        z = data["zone"]
        return Zone(
            city=z["city"],
            name=z["name"],
            latitude=z["centroid"]["latitude"],
            longitude=z["centroid"]["longitude"],
            country=z.get("country", ""),
        )


class PlacesBackend:
    """Live Google Places API (New)."""

    def __init__(self, api_key: str | None = None, timeout: int = 20):
        self.api_key = api_key or get_env("GOOGLE_PLACES_API_KEY", required=True)
        self.timeout = timeout

    def search(self, zone: Zone, query: str, max_results: int) -> list[Venue]:
        body = {
            "textQuery": f"{query} in {zone.name}, {zone.city}",
            "maxResultCount": min(max_results, 20),
            "locationBias": {
                "circle": {
                    "center": {
                        "latitude": zone.latitude,
                        "longitude": zone.longitude,
                    },
                    "radius": 1500.0,
                }
            },
        }
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": FIELD_MASK,
        }

        # Retry on transient failures only. A 4xx is our bug, not theirs, and
        # retrying it just burns quota.
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                resp = requests.post(
                    PLACES_ENDPOINT, json=body, headers=headers, timeout=self.timeout
                )
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise requests.HTTPError(f"transient {resp.status_code}")
                resp.raise_for_status()
                return [_normalise(p) for p in resp.json().get("places", [])]
            except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as e:
                last_error = e
                time.sleep(2**attempt)
        raise RuntimeError(f"Places search failed after 3 attempts: {last_error}")


def build_backend(mock: bool, fixture: str | None = None) -> tuple[Backend, Zone | None]:
    if mock:
        path = Path(fixture) if fixture else ROOT / "data" / "fixtures" / "lisbon_principe_real.json"
        return FixtureBackend(path), FixtureBackend.zone_from_fixture(path)
    return PlacesBackend(), None
