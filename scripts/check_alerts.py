#!/usr/bin/env python3
"""Météo Horizon — vérifie les règles d'alerte et envoie une notif via ntfy.sh.
Sans dépendance externe. Dédoublonnage sans état : on relit l'historique du topic ntfy."""
import json, os, sys, urllib.request

TOPIC = os.environ["NTFY_TOPIC"]
NAME = os.environ.get("CITY_NAME", "La Brède")
LAT = float(os.environ.get("CITY_LAT", "44.6814"))
LON = float(os.environ.get("CITY_LON", "-0.5278"))
NTFY = "https://ntfy.sh"


def http_json(url, data=None):
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")


def forecast():
    url = (f"https://api.open-meteo.com/v1/forecast?latitude={LAT}&longitude={LON}"
           "&current=temperature_2m"
           "&hourly=precipitation_probability,precipitation,weather_code,wind_gusts_10m"
           "&daily=temperature_2m_max,temperature_2m_min,uv_index_max"
           "&timezone=Europe%2FParis&forecast_days=3")
    return json.loads(http_json(url))


def compute_alerts(d):
    now = d["current"]["time"]                      # ex. 2026-11-26T14:45
    h = d["hourly"]
    i = next((k for k, t in enumerate(h["time"]) if t >= now[:13]), 0)
    day, hour = now[:10], int(now[11:13])
    out = []

    rain, pop = h["precipitation"][i] or 0, h["precipitation_probability"][i] or 0
    if rain >= 0.3 or pop >= 70:
        out.append(("rain1h", f"rain1h-{day}-{hour // 3}", "🌧️ Pluie attendue dans l'heure",
                    f"{rain:.1f} mm, prob. {pop} % à {NAME}.", "default"))

    tmin1 = d["daily"]["temperature_2m_min"][1]
    if tmin1 is not None and tmin1 <= 0:
        out.append(("frost", f"frost-{day}", "❄️ Gel prévu demain matin",
                    f"Minimale de {round(tmin1)} °C demain à {NAME}.", "high"))

    if any(c in (95, 96, 99) for c in h["weather_code"][i:i + 12]):
        out.append(("storm", f"storm-{day}", "⛈️ Risque d'orage",
                    f"Épisode orageux prévu dans les 12 h à {NAME}.", "high"))

    gust = max(h["wind_gusts_10m"][i:i + 12])
    if gust >= 60:
        out.append(("wind", f"wind-{day}", "💨 Fortes rafales",
                    f"Rafales jusqu'à {round(gust)} km/h à {NAME}.", "high"))

    tmax0, tmin0 = d["daily"]["temperature_2m_max"][0], d["daily"]["temperature_2m_min"][0]
    if tmax0 >= 33:
        out.append(("heat", f"heat-{day}", "🌡️ Pic de chaleur", f"Max de {round(tmax0)} °C aujourd'hui.", "high"))
    elif tmin0 <= -3:
        out.append(("cold", f"cold-{day}", "🥶 Grand froid", f"Min de {round(tmin0)} °C aujourd'hui.", "high"))

    uv = d["daily"]["uv_index_max"][0]
    if uv is not None and uv >= 6:
        out.append(("uv", f"uv-{day}", f"☀️ Indice UV élevé ({uv:.1f})", "Protection solaire recommandée.", "default"))
    return out


def already_sent():
    """Clés déjà envoyées sur les 24 dernières heures (lues dans l'historique ntfy)."""
    try:
        raw = http_json(f"{NTFY}/{TOPIC}/json?poll=1&since=24h")
    except Exception as e:
        print("Lecture historique impossible:", e)
        return set()
    keys = set()
    for line in raw.splitlines():
        try:
            m = json.loads(line)
        except ValueError:
            continue
        keys.update(m.get("tags", []))
    return keys


def main():
    alerts = compute_alerts(forecast())
    sent = already_sent()
    for _id, key, title, body, prio in alerts:
        if key in sent:
            print("déjà envoyée:", key)
            continue
        payload = {"topic": TOPIC, "title": f"{title} ({NAME})", "message": body,
                   "tags": [key], "priority": {"high": 4}.get(prio, 3),
                   "click": "https://clementjuin-beep.github.io/Meteo-horizon/"}
        http_json(NTFY, json.dumps(payload).encode("utf-8"))
        print("envoyée:", key)
    if not alerts:
        print("Aucune alerte active.")


if __name__ == "__main__":
    sys.exit(main())
  
