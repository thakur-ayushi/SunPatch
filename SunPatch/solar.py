# solar.py
from math import sin, cos, tan, asin, acos, atan2, radians, degrees
from datetime import datetime, timezone

def _julian_day(dt_utc):
    # Meeus approximation
    y = dt_utc.year; m = dt_utc.month; D = dt_utc.day
    H = dt_utc.hour + dt_utc.minute/60 + dt_utc.second/3600
    if m <= 2:
        y -= 1; m += 12
    A = y // 100
    B = 2 - A + (A // 4)
    jd = int(365.25*(y + 4716)) + int(30.6001*(m + 1)) + D + B - 1524.5 + H/24
    return jd

def solar_position(lat_deg, lon_deg, dt_utc=None):
    """Return solar elevation and azimuth (degrees) for UTC time.
       Simple SPA approximation good enough for demo."""
    if dt_utc is None:
        dt_utc = datetime.now(timezone.utc)

    jd = _julian_day(dt_utc)
    n = jd - 2451545.0  # days since J2000.0

    # Mean longitude, anomaly (deg)
    L = (280.460 + 0.9856474*n) % 360
    g = (357.528 + 0.9856003*n) % 360
    g_rad = radians(g)

    # Ecliptic longitude (deg)
    lam = L + 1.915*sin(g_rad) + 0.020*sin(2*g_rad)

    # Obliquity (deg)
    eps = 23.439 - 0.0000004*n

    # Right ascension/declination
    lam_rad = radians(lam)
    eps_rad = radians(eps)
    alpha = degrees(atan2(cos(eps_rad)*sin(lam_rad), cos(lam_rad)))
    delta = degrees(asin(sin(eps_rad)*sin(lam_rad)))

    # Sidereal time (deg)
    GMST = (280.46061837 + 360.98564736629*n) % 360
    LST = (GMST + lon_deg) % 360

    # Hour angle
    H = (LST - alpha + 540) % 360 - 180  # wrap to [-180,180]
    lat = radians(lat_deg)
    Hrad = radians(H)
    deltar = radians(delta)

    # Elevation
    sin_el = sin(lat)*sin(deltar) + cos(lat)*cos(deltar)*cos(Hrad)
    el = degrees(asin(sin_el))

    # Azimuth (from North, clockwise)
    y = -sin(Hrad)*cos(deltar)
    x = cos(lat)*sin(deltar) - sin(lat)*cos(deltar)*cos(Hrad)
    az = (degrees(atan2(y, x)) + 360) % 360

    return el, az
