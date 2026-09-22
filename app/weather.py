"""Deterministic Open-Meteo client.

No LLM involvement anywhere in this file. Every number the bot ever reports to
a user has to have come from here -- the graph's compose step is only allowed
to interpolate values out of the dict this module returns, never to invent or
"recall" a number itself.
"""
from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass

import requests

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

CURRENT_FIELDS = "temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m,wind_gusts_10m,uv_index"
HOURLY_FIELDS = "temperature_2m,precipitation,precipitation_probability,wind_speed_10m,wind_gusts_10m,uv_index,visibility"
DAILY_FIELDS = "precipitation_sum,precipitation_probability_max,uv_index_max,wind_speed_10m_max,wind_gusts_10m_max"

REQUEST_TIMEOUT_SECONDS = 10
REQUEST_HEADERS = {"User-Agent": "weather-advisory-support-bot/1.0 (+https://github.com/Stavan-Pandya/Weather-Advisory-Bot)"}
RETRY_ATTEMPTS = 3

# Open-Meteo's geocoding data indexes several major Indian cities only under
# their official post-renaming name, not the colloquial English name still in
# everyday use -- e.g. searching "Bangalore" returns a small unrelated town in
# Pakistan's Sindh province, because Bengaluru simply isn't aliased under it.
# Found via live testing, not theoretical: this is a small, explicit patch for
# the handful of cases most likely to come up, not a general solution -- an
# unlisted colloquial name still falls through to Open-Meteo's raw top result.
COLLOQUIAL_NAME_ALIASES = {
    "bangalore": "Bengaluru",
    "bombay": "Mumbai",
    "calcutta": "Kolkata",
    "madras": "Chennai",
    "trivandrum": "Thiruvananthapuram",
    "poona": "Pune",
    "cochin": "Kochi",
    "mysore": "Mysuru",
    "gurgaon": "Gurugram",
    "baroda": "Vadodara",
}
RETRY_BACKOFF_SECONDS = 1.5


def _get_with_retry(url: str, params: dict) -> requests.Response:
    """A 429 from Open-Meteo's free tier is often a shared-IP burst limit on
    hosting platforms (many unrelated tenants sharing one egress IP), not our
    own request volume -- worth a couple of short retries before giving up,
    since the bucket can clear within seconds."""
    last_exc: Exception | None = None
    for attempt in range(RETRY_ATTEMPTS):
        try:
            resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS, headers=REQUEST_HEADERS)
            if resp.status_code == 429 and attempt < RETRY_ATTEMPTS - 1:
                time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
                continue
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < RETRY_ATTEMPTS - 1:
                time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
    raise last_exc


class WeatherLookupError(Exception):
    """Raised for any failure resolving a location or fetching a forecast.

    Deliberately one exception type for both geocoding and forecast failures:
    the spec treats "location can't be resolved" and "weather API is down" as
    the same class of problem for the user -- an honest "we don't know" -- so
    the graph only needs one failure branch to handle both.
    """


@dataclass(frozen=True)
class ResolvedLocation:
    name: str
    admin1: str | None
    country: str | None
    latitude: float
    longitude: float

    @property
    def display_name(self) -> str:
        parts = [self.name]
        if self.admin1 and self.admin1 != self.name:
            parts.append(self.admin1)
        if self.country:
            parts.append(self.country)
        return ", ".join(parts)


def geocode(city_name: str) -> ResolvedLocation:
    lookup_name = COLLOQUIAL_NAME_ALIASES.get(city_name.strip().lower(), city_name)
    try:
        resp = _get_with_retry(
            GEOCODING_URL,
            params={"name": lookup_name, "count": 5, "language": "en", "format": "json"},
        )
        data = resp.json()
    except requests.RequestException as exc:
        raise WeatherLookupError(f"Geocoding request failed for '{city_name}': {exc}") from exc

    results = data.get("results")
    if not results:
        raise WeatherLookupError(f"Could not resolve a location for '{city_name}' (no geocoding results).")

    top = results[0]
    return ResolvedLocation(
        name=top["name"],
        admin1=top.get("admin1"),
        country=top.get("country"),
        latitude=top["latitude"],
        longitude=top["longitude"],
    )


def fetch_forecast(latitude: float, longitude: float) -> dict:
    """Returns a distilled forecast dict. Raises WeatherLookupError on failure."""
    try:
        resp = _get_with_retry(
            FORECAST_URL,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "current": CURRENT_FIELDS,
                "hourly": HOURLY_FIELDS,
                "daily": DAILY_FIELDS,
                "timezone": "auto",
                "forecast_days": 2,
            },
        )
        data = resp.json()
    except requests.RequestException as exc:
        raise WeatherLookupError(f"Forecast request failed: {exc}") from exc

    if "current" not in data or "hourly" not in data:
        raise WeatherLookupError("Forecast response was missing expected fields.")

    current = data["current"]
    hourly = data["hourly"]
    daily = data.get("daily", {})

    # Slice the next 24 hourly entries starting at (or after) "now" per the API's own clock.
    hourly_times = hourly.get("time", [])
    now = current.get("time")
    start_idx = 0
    if now in hourly_times:
        start_idx = hourly_times.index(now)
    else:
        now_dt = dt.datetime.fromisoformat(now) if now else None
        for i, t in enumerate(hourly_times):
            if now_dt and dt.datetime.fromisoformat(t) >= now_dt:
                start_idx = i
                break

    def hourly_slice(field: str, count: int = 24) -> list:
        values = hourly.get(field, [])
        return values[start_idx:start_idx + count]

    next_24h = []
    times = hourly_slice("time")
    for i, t in enumerate(times):
        next_24h.append({
            "time": t,
            "temperature_2m": _at(hourly, "temperature_2m", start_idx + i),
            "precipitation": _at(hourly, "precipitation", start_idx + i),
            "precipitation_probability": _at(hourly, "precipitation_probability", start_idx + i),
            "wind_speed_10m": _at(hourly, "wind_speed_10m", start_idx + i),
            "wind_gusts_10m": _at(hourly, "wind_gusts_10m", start_idx + i),
            "uv_index": _at(hourly, "uv_index", start_idx + i),
            "visibility": _at(hourly, "visibility", start_idx + i),
        })

    def daily_entry(idx: int) -> dict:
        return {
            "date": _at(daily, "time", idx),
            "precipitation_sum": _at(daily, "precipitation_sum", idx),
            "precipitation_probability_max": _at(daily, "precipitation_probability_max", idx),
            "uv_index_max": _at(daily, "uv_index_max", idx),
            "wind_speed_10m_max": _at(daily, "wind_speed_10m_max", idx),
            "wind_gusts_10m_max": _at(daily, "wind_gusts_10m_max", idx),
        }

    return {
        "timezone": data.get("timezone"),
        "current": {
            "time": current.get("time"),
            "temperature_2m": current.get("temperature_2m"),
            "relative_humidity_2m": current.get("relative_humidity_2m"),
            "precipitation": current.get("precipitation"),
            "wind_speed_10m": current.get("wind_speed_10m"),
            "wind_gusts_10m": current.get("wind_gusts_10m"),
            "uv_index": current.get("uv_index"),
        },
        "next_24h": next_24h,
        "today": daily_entry(0),
        "tomorrow": daily_entry(1) if len(daily.get("time", [])) > 1 else None,
    }


def _at(container: dict, field: str, idx: int):
    values = container.get(field, [])
    if 0 <= idx < len(values):
        return values[idx]
    return None
