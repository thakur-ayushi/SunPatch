# backend/app.py
import os
import time
from collections import deque
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv
from flask import (
    Flask,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

# ---- local modules (you already have these) ----
# solar.solar_position(lat, lon, when_utc) -> (elevation_deg, azimuth_deg)
# energy_model.predict_kwh(panel_kw, elevation_deg, target_tilt_deg, cloud_pct, aqi) -> daily_kwh
# energy_model.annual_co2_savings(annual_kwh) -> tonnes
from solar import solar_position
from energy_model import predict_kwh, annual_co2_savings


# -------------------- config --------------------
load_dotenv()  # reads backend/.env
OWM_KEY = os.getenv("WEATHER_API_KEY", "")  # OpenWeatherMap key
AQI_KEY = os.getenv("AQI_API_KEY", "")      # World Air Quality Index token

# Default Flask layout: looks in ./templates and ./static automatically
app = Flask(__name__, template_folder="templates", static_folder="static")


# -------------------- in-memory state --------------------
STATE = {
    "auto": True,        # if True -> track sun; else use tilt/az below
    "lat": 28.6139,      # default: New Delhi
    "lon": 77.2090,
    "tilt": 30.0,        # degrees
    "az": 180.0,         # degrees (0=N, 90=E, 180=S, 270=W)
    "panel_kw": 1.0,     # kW
    "cloud_pct": 20,     # %
    "aqi": 60,
    "temp_c": None,
    "humidity": None,
    "weather_desc": None,
    "_last_fetch": 0,    # epoch seconds
}

HISTORY = deque(maxlen=2000)  # tiny time-series buffer


# -------------------- helpers --------------------
def fetch_weather(lat: float, lon: float):
    """Return weather dict or None."""
    if not OWM_KEY:
        return None
    try:
        url = (
            "https://api.openweathermap.org/data/2.5/weather"
            f"?lat={lat}&lon={lon}&units=metric&appid={OWM_KEY}"
        )
        r = requests.get(url, timeout=6)
        j = r.json()
        return {
            "temp_c": j.get("main", {}).get("temp"),
            "humidity": j.get("main", {}).get("humidity"),
            "cloud_pct": j.get("clouds", {}).get("all"),
            "weather_desc": (j.get("weather") or [{}])[0].get("description", "").title(),
        }
    except Exception:
        return None


def fetch_aqi(lat: float, lon: float):
    """Return AQI int or None."""
    if not AQI_KEY:
        return None
    try:
        url = f"https://api.waqi.info/feed/geo:{lat};{lon}/?token={AQI_KEY}"
        r = requests.get(url, timeout=6)
        j = r.json()
        if j.get("status") == "ok":
            return int(j.get("data", {}).get("aqi", 0))
        return None
    except Exception:
        return None


def refresh_weather_if_stale(force: bool = False):
    """Refresh weather/AQI no more than every 10 minutes unless forced."""
    now = time.time()
    if not force and (now - STATE["_last_fetch"] < 600):
        return

    lat, lon = STATE["lat"], STATE["lon"]

    w = fetch_weather(lat, lon)
    if w:
        if w.get("cloud_pct") is not None:
            STATE["cloud_pct"] = int(w["cloud_pct"])
        STATE["temp_c"] = w.get("temp_c")
        STATE["humidity"] = w.get("humidity")
        STATE["weather_desc"] = w.get("weather_desc")

    aqi_val = fetch_aqi(lat, lon)
    if aqi_val is not None and aqi_val > 0:
        STATE["aqi"] = aqi_val

    STATE["_last_fetch"] = now


def _push_history(el, az, tilt, kwh, cloud_pct, aqi):
    HISTORY.append({
        "ts": int(time.time() * 1000),
        "elevation": round(el, 2),
        "azimuth": round(az, 2),
        "tilt": round(tilt, 2),
        "cloud_pct": int(cloud_pct),
        "aqi": int(aqi),
        "power_w": max(0, kwh * 1000),    # toy instantaneous value
        "energy_kwh": max(0, kwh / 60.0), # pretend this sample is 1 minute
    })


# -------------------- pages --------------------
@app.route("/")
def index():
    # No separate index.html — send users to the dashboard
    return redirect(url_for("legacy"))


@app.route("/legacy")
def legacy():
    # Renders templates/legacy.html
    return render_template("legacy.html")


# -------------------- APIs --------------------
@app.get("/api/state")
def api_state():
    """Current system state + computed targets + energy."""
    refresh_weather_if_stale(force=False)

    el, az = solar_position(STATE["lat"], STATE["lon"], datetime.now(timezone.utc))

    # pick target angles
    target_tilt = el if STATE["auto"] else STATE["tilt"]
    target_az = az if STATE["auto"] else STATE["az"]

    # daily energy estimate
    daily_kwh = predict_kwh(
        STATE["panel_kw"], el, target_tilt, STATE["cloud_pct"], STATE["aqi"]
    )
    annual_kwh = round(daily_kwh * 365.0, 1)
    co2_tonnes = annual_co2_savings(annual_kwh)

    _push_history(el, az, target_tilt, daily_kwh, STATE["cloud_pct"], STATE["aqi"])

    return jsonify({
        "auto": STATE["auto"],
        "lat": STATE["lat"],
        "lon": STATE["lon"],
        "now_utc": datetime.now(timezone.utc).isoformat(),
        "solar": {"elevation": round(el, 2), "azimuth": round(az, 2)},
        "target": {"tilt": round(target_tilt, 2), "az": round(target_az, 2)},
        "panel_kw": STATE["panel_kw"],
        "weather": {
            "cloud_pct": STATE["cloud_pct"],
            "aqi": STATE["aqi"],
            "temp_c": STATE["temp_c"],
            "humidity": STATE["humidity"],
            "desc": STATE["weather_desc"],
        },
        "energy": {
            "daily_kwh": daily_kwh,
            "annual_kwh": annual_kwh,
            "co2_tonnes": co2_tonnes,
        },
    })


@app.post("/api/config")
def api_config():
    """Update config values (auto/lat/lon/panel_kw/cloud_pct/aqi/tilt/az)."""
    data = request.get_json(silent=True) or {}
    for key in ["auto", "lat", "lon", "panel_kw", "cloud_pct", "aqi", "tilt", "az"]:
        if key in data and data[key] is not None:
            STATE[key] = data[key]

    # Weather might depend on new lat/lon
    refresh_weather_if_stale(force=True)
    return jsonify({"ok": True, "state": STATE})


@app.route("/api/refresh_weather", methods=["POST", "GET"])
def api_refresh_weather():
    """Force-refresh weather and AQI now."""
    refresh_weather_if_stale(force=True)
    return jsonify({
        "ok": True,
        "state": {
            "cloud_pct": STATE["cloud_pct"],
            "aqi": STATE["aqi"],
            "temp_c": STATE["temp_c"],
            "humidity": STATE["humidity"],
            "desc": STATE["weather_desc"],
        },
    })


@app.get("/api/series")
def api_series():
    """Return recent time-series samples (toy analytics)."""
    pts = list(HISTORY)
    total_kwh = sum(p["energy_kwh"] for p in pts)
    return jsonify({"ok": True, "total_kwh": round(total_kwh, 3), "points": pts})


# -------------------- main --------------------
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
