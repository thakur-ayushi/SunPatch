SunPatch is a web app that shows a 3D solar panel you can tilt/rotate and an info panel fed by a Python (Flask/FastAPI) backend. The backend computes sun position, optimal tilt suggestions, and basic energy/geometry metrics for your location and time. Frontend renders an interactive 3D scene and displays the numbers in real time

Features

🛰️ Sun position: elevation & azimuth for any lat/lon/time.

📐 Smart tilt suggestions: annual / seasonal / monthly / solar-noon modes.

⚡ Instant metrics (on the info panel):

Panel tilt & azimuth

Sun elevation & azimuth

Incidence angle (θᵢ) and cosine loss

Simple plane-of-array irradiance estimate (POA, W/m²)

🖥️ 3D viewer: interactive solar panel model (Orbit controls; tilt/azimuth sliders).

🌐 Clean API: stateless JSON endpoints your UI can call.

Tech Stack

Frontend: React + Three.js (or React Three Fiber) + Vite

Backend: Python (Flask or FastAPI), numpy, astral/pvlib for sun position

Build/Dev: Node 18+, Python 3.11+
