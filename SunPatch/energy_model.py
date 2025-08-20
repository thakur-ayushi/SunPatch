# energy_model.py
# Predict daily energy (kWh) from panel size, tilt match, weather, AQI.
# Very simple & explainable model for judges.

def clamp(x, lo, hi): return max(lo, min(hi, x))

def predict_kwh(panel_kw, elevation_deg, tilt_deg, cloud_pct=0, aqi=50, hours_sun=5.5):
    # Tilt penalty: difference from elevation hurts yield
    tilt_error = abs(elevation_deg - tilt_deg)
    tilt_factor = clamp(1.0 - (tilt_error/60.0), 0.4, 1.0)  # up to -60° then 40%

    # Clouds penalty (linear for demo)
    cloud_factor = clamp(1.0 - cloud_pct/100.0, 0.2, 1.0)

    # AQI penalty (good→bad reduces irradiance proxy)
    # 50 → 1.0, 300+ → 0.6
    aqi = clamp(aqi, 20, 400)
    aqi_factor = clamp(1.0 - (aqi - 50)/500.0, 0.6, 1.0)

    base = panel_kw * hours_sun  # simplistic daily capacity
    return round(base * tilt_factor * cloud_factor * aqi_factor, 2)

def annual_co2_savings(kwh_year, grid_emission_factor=0.7):
    # 0.7 kg CO2 per kWh (India average-type factor, tunable)
    tonnes = (kwh_year * grid_emission_factor) / 1000.0
    return round(tonnes, 2)
