# app.py
from flask import Flask, render_template, request, jsonify
from datetime import datetime, timezone
try:
    from solar import solar_position
    from energy_model import predict_kwh, annual_co2_savings
except Exception as e:
    print("Import error:", e)

import os, time, requests
from dotenv import load_dotenv

print(">>> Starting SunPatch app (debug mode)...")


load_dotenv()
OWM_KEY = os.getenv("WEATHER_API_KEY", "")
AQI_KEY = os.getenv("AQI_API_KEY", "")

app = Flask(__name__)

# In-memory state
STATE = {
    "auto": True,
    "lat": 28.6139,        # default: Delhi
    "lon": 77.2090,
    "tilt": 30.0,
    "az": 180.0,
    "panel_kw": 1.0,
    # Weather/Air (manual fallback values)
    "cloud_pct": 20,
    "aqi": 60,
    "temp_c": None,
    "weather_desc": None,
    "humidity": None,
    # cache timestamp
    "_last_fetch": 0
}

def fetch_weather(lat, lon):
    """OpenWeather: current weather (temp, humidity, clouds, desc)."""
    if not OWM_KEY:
        return None
    try:
        url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&units=metric&appid={OWM_KEY}"
        r = requests.get(url, timeout=6)
        j = r.json()
        return {
            "temp_c": j.get("main", {}).get("temp"),
            "humidity": j.get("main", {}).get("humidity"),
            "cloud_pct": j.get("clouds", {}).get("all"),
            "weather_desc": (j.get("weather") or [{}])[0].get("description", "").title()
        }
    except Exception:
        return None

def fetch_aqi(lat, lon):
    """WAQI (aqicn.org): AQI by geo coordinates."""
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

def refresh_weather_if_stale(force=False):
    # pull at most once every 10 minutes unless force
    now = time.time()
    if not force and (now - STATE["_last_fetch"] < 600):
        return

    lat, lon = STATE["lat"], STATE["lon"]

    w = fetch_weather(lat, lon)
    if w:
        # Only overwrite if API returned sensible values
        if w.get("cloud_pct") is not None:
            STATE["cloud_pct"] = int(w["cloud_pct"])
        STATE["temp_c"] = w.get("temp_c")
        STATE["humidity"] = w.get("humidity")
        STATE["weather_desc"] = w.get("weather_desc")

    aqi_val = fetch_aqi(lat, lon)
    if aqi_val is not None and aqi_val > 0:
        STATE["aqi"] = aqi_val

    STATE["_last_fetch"] = now

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/state", methods=["GET"])
def get_state():
    # Lazy refresh (no error if keys missing)
    refresh_weather_if_stale(force=False)

    el, az = solar_position(STATE["lat"], STATE["lon"], datetime.now(timezone.utc))
    target_tilt = el if STATE["auto"] else STATE["tilt"]
    target_az = az if STATE["auto"] else STATE["az"]

    kwh = predict_kwh(
        STATE["panel_kw"], el, target_tilt,
        STATE["cloud_pct"], STATE["aqi"]
    )
    annual = round(kwh * 365, 1)
    co2 = annual_co2_savings(annual)

    return jsonify({
        "auto": STATE["auto"],
        "lat": STATE["lat"], "lon": STATE["lon"],
        "now_utc": datetime.now(timezone.utc).isoformat(),
        "solar": {"elevation": round(el,2), "azimuth": round(az,2)},
        "target": {"tilt": round(target_tilt,2), "az": round(target_az,2)},
        "panel_kw": STATE["panel_kw"],
        "weather": {
            "cloud_pct": STATE["cloud_pct"],
            "aqi": STATE["aqi"],
            "temp_c": STATE["temp_c"],
            "humidity": STATE["humidity"],
            "desc": STATE["weather_desc"]
        },
        "energy": {"daily_kwh": kwh, "annual_kwh": annual, "co2_tonnes": co2}
    })

@app.route("/api/config", methods=["POST"])
def set_config():
    data = request.json or {}
    for k in ["auto","lat","lon","panel_kw","cloud_pct","aqi","tilt","az"]:
        if k in data and data[k] is not None:
            STATE[k] = data[k]

    # If location changed, refresh weather immediately (non-blocking feel)
    refresh_weather_if_stale(force=True)
    return jsonify({"ok": True, "state": STATE})

@app.route("/api/refresh_weather", methods=["POST","GET"])
def manual_refresh():
    refresh_weather_if_stale(force=True)
    return jsonify({"ok": True, "state": {
        "cloud_pct": STATE["cloud_pct"],
        "aqi": STATE["aqi"],
        "temp_c": STATE["temp_c"],
        "humidity": STATE["humidity"],
        "desc": STATE["weather_desc"]
    }})
    
# Optional hardware hook (keep commented until ESP32 is ready)
# import requests as _req
# ESP32_URL = "http://192.168.0.50"  # your ESP32 IP
# @app.route("/api/hardware/nudge")
# def nudge_hw():
#     t = STATE["tilt"]; a = STATE["az"]
#     try:
#         _req.get(f"{ESP32_URL}/move?tilt={t}&az={a}", timeout=0.5)
#         return jsonify({"ok": True})
#     except Exception as e:
#         return jsonify({"ok": False, "error": str(e)}), 502

if __name__ == "__main__":
    app.run(debug=True)
