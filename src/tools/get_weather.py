from typing import Annotated
from langchain_core.tools import tool
import requests
import os

WEATHER_API = "https://api.open-meteo.com/v1/forecast"

@tool
def get_weather(
    city: Annotated[str, "City name, e.g. Chicago"],
    units: Annotated[str, "metric | imperial"] = "metric",
) -> str:
    """Return current weather + 3-day forecast for the given city."""
    geo = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": city, "count": 1},
        timeout=6,
    ).json()["results"][0]
    lat, lon = geo["latitude"], geo["longitude"]

    weather = requests.get(
        WEATHER_API,
        params={
            "latitude": lat,
            "longitude": lon,
            "current_weather": "true",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_mean",
            "timezone": "auto",
        },
        timeout=6,
    ).json()

    cur = weather["current_weather"]
    daily = weather["daily"]
    out = f"**{city}** 目前 {cur['temperature']}°{('C' if units=='metric' else 'F')}，风速 {cur['windspeed']} km/h。\n\n"
    out += "| 日期 | 最高 | 最低 | 概率% |\n|------|------|------|-------|\n"
    for i, day in enumerate(daily["time"][:3]):
        out += f"| {day} | {daily['temperature_2m_max'][i]} | {daily['temperature_2m_min'][i]} | {daily['precipitation_probability_mean'][i]} |\n"
    return out
