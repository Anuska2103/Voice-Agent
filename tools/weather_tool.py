from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import List

import httpx
from redis import asyncio as aioredis
from logger import get_logger

from tools.geocoding import geocode_location_async

LOGGER = get_logger(__name__)


CURRENT_WEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"
FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"


@dataclass
class WeatherForecastDay:
    date: str
    min_temp_c: float
    max_temp_c: float
    condition: str
    humidity: int = 0
    rain_chance: float = 0.0


@dataclass
class WeatherReport:
    temp_c: float
    feels_like_c: float
    humidity: int
    description: str
    wind_kph: float
    city_name: str
    forecast: List[WeatherForecastDay] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "temp_c": self.temp_c,
            "feels_like_c": self.feels_like_c,
            "humidity": self.humidity,
            "description": self.description,
            "wind_kph": self.wind_kph,
            "city_name": self.city_name,
            "forecast": [
                {
                    "date": d.date,
                    "min_temp_c": d.min_temp_c,
                    "max_temp_c": d.max_temp_c,
                    "condition": d.condition,
                    "humidity": d.humidity,
                    "rain_chance": d.rain_chance,
                }
                for d in self.forecast
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WeatherReport":
        forecast = [WeatherForecastDay(**day) for day in data.get("forecast", [])]
        return cls(
            temp_c=data["temp_c"],
            feels_like_c=data["feels_like_c"],
            humidity=data["humidity"],
            description=data["description"],
            wind_kph=data["wind_kph"],
            city_name=data["city_name"],
            forecast=forecast,
        )


async def fetch_weather_report(
    redis_client: aioredis.Redis,
    api_key: str,
    location_query: str,
) -> WeatherReport:
    lat, lon, canonical_name = await geocode_location_async(location_query)

    if lat is None or lon is None:
        raise RuntimeError(f"Could not geocode location: '{location_query}'")

    cache_key = f"owm_weather:{lat:.4f}:{lon:.4f}"

    try:
        cached = await redis_client.get(cache_key)
        if cached:
            LOGGER.info("Weather cache hit for %s", canonical_name)
            return WeatherReport.from_dict(json.loads(cached))
    except Exception as e:
        LOGGER.warning("Redis weather cache read failed: %s", e)

    LOGGER.info("Fetching weather for %s (lat=%s, lon=%s)", canonical_name, lat, lon)

    async with httpx.AsyncClient(timeout=10.0) as client:
        current_resp = await client.get(
            CURRENT_WEATHER_URL,
            params={"lat": lat, "lon": lon, "appid": api_key, "units": "metric"},
        )
        if current_resp.status_code >= 400:
            raise RuntimeError(
                f"OpenWeatherMap current weather error: {current_resp.status_code} – {current_resp.text}"
            )
        current_data = current_resp.json()

        forecast_resp = await client.get(
            FORECAST_URL,
            params={"lat": lat, "lon": lon, "appid": api_key, "units": "metric", "cnt": 24},
        )
        if forecast_resp.status_code >= 400:
            raise RuntimeError(
                f"OpenWeatherMap forecast error: {forecast_resp.status_code} – {forecast_resp.text}"
            )
        forecast_data = forecast_resp.json()

    main = current_data.get("main", {})
    wind = current_data.get("wind", {})
    weather_desc = current_data.get("weather", [{}])[0].get("description", "Unknown")
    city_name = current_data.get("name", canonical_name)

    daily: dict[str, dict] = {}
    for slot in forecast_data.get("list", []):
        date_str = slot.get("dt_txt", "")[:10]
        slot_main = slot.get("main", {})
        slot_weather = slot.get("weather", [{}])[0]
        pop = slot.get("pop", 0.0)

        if date_str not in daily:
            daily[date_str] = {"temps": [], "conditions": [], "humidities": [], "pops": []}

        daily[date_str]["temps"].append(slot_main.get("temp", 0))
        daily[date_str]["conditions"].append(slot_weather.get("description", "Unknown"))
        daily[date_str]["humidities"].append(slot_main.get("humidity", 0))
        daily[date_str]["pops"].append(pop)

    forecast_days: list[WeatherForecastDay] = []
    for date_str, day_data in sorted(daily.items())[:3]:
        temps = day_data["temps"]
        condition = max(set(day_data["conditions"]), key=day_data["conditions"].count)
        forecast_days.append(
            WeatherForecastDay(
                date=date_str,
                min_temp_c=round(min(temps), 1),
                max_temp_c=round(max(temps), 1),
                condition=condition.title(),
                humidity=round(sum(day_data["humidities"]) / len(day_data["humidities"])),
                rain_chance=round(max(day_data["pops"]) * 100),
            )
        )

    report = WeatherReport(
        temp_c=round(main.get("temp", 0), 1),
        feels_like_c=round(main.get("feels_like", 0), 1),
        humidity=int(main.get("humidity", 0)),
        description=weather_desc.title(),
        wind_kph=round(wind.get("speed", 0) * 3.6, 1),
        city_name=city_name,
        forecast=forecast_days,
    )

    try:
        await redis_client.setex(cache_key, 15 * 60, json.dumps(report.to_dict()))
    except Exception as e:
        LOGGER.warning("Redis weather cache write failed: %s", e)

    return report


def format_weather_for_voice(report: WeatherReport) -> str:
    lines = [
        f"Current weather in {report.city_name}:",
        f"  Temperature: {report.temp_c}°C (feels like {report.feels_like_c}°C)",
        f"  Condition: {report.description}",
        f"  Humidity: {report.humidity}%",
        f"  Wind: {report.wind_kph} km/h",
    ]

    if report.forecast:
        lines.append("3-day forecast:")
        for day in report.forecast:
            lines.append(
                f"  {day.date}: {day.min_temp_c}–{day.max_temp_c}°C, "
                f"{day.condition}, Rain chance: {day.rain_chance}%"
            )

    return "\n".join(lines)