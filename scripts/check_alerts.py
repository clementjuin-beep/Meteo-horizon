#!/usr/bin/env python3
"""Météo Horizon — alertes + récap de demain pour plusieurs villes, envoyés via ntfy.sh.
Sans dépendance externe. Dédoublonnage sans état : on relit l'historique du topic ntfy."""
import json, os, sys, urllib.request

TOPIC = os.environ["NTFY_TOPIC"]
NTFY = "https://ntfy.sh"
SUMMARY_HOUR = int(os.environ.get("SUMMARY_HOUR", "19"))  # heure de Paris du récap de demain
SITE = "https://clementjuin-beep.github.io/Meteo-horizon/"

# Villes surveillées : (slug, nom, latitude, longitude). Ajoutes-en ici si besoin.
CITIES = [
    ("labrede", "La Brède", 44.6814, -0.5278),
    ("paris", "Paris", 48.8566, 2.3522),
]

WMO = {0: "Ciel dégagé", 1: "Plutôt dégagé", 2: "Partiellement nuageux", 3: "Couvert",
       45: "Brouillard", 48: "Brouillard givrant", 51: "Bruine légère", 53: "Bruine", 55: "Bruine dense",
       61: "Pluie faible", 63: "Pluie", 65: "Pluie forte", 66: "Pluie verglaçante", 67: "Pluie verglaçante forte",
       71: "Neige faible", 73: "Neige", 75: "Neige forte", 77: "Grains de neige",
       80: "Averses faibles", 81: "Averses", 82: "Averses violentes", 85: "Averses de neige",
       86: "Averses de neige fortes", 95: "Orage", 96: "Orage et grêle", 99: "Orage et forte grêle"}


def http_text(url, data=None):
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")


def forecast(lat, lon):
    url = (f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
           "&current=temperature_2m"
           "&hourly=precipitation_probability,precipitation,weather_code,wind_gusts_10m"
           "&daily=weather_code,temperature_2m_max,temperature_2m_min,uv_index_max,"
           "precipitation_sum,precipitation_probability_max,wind_gusts_10m_max"
           "&timezone=Europe%2FParis&forecast_days=3")
    return json.loads(http_text(url))


def compute_alerts(slug, name, d):
    now = d["current"]["time"]                      # ex. 2026-11-26T14:45
    h = d["hourly"]
    i = next((k for k, t in enumerate(h["time"]) if t >= now[:13]), 0)
    day, hour = now[:10], int(now[11:13])
    out = []

    rain, pop = h["precipitation"][i] or 0, h["precipitation_probability"][i] or 0
    if rain >= 0.3 or pop >= 70:
        out.append((f"{slug}-rain1h-{day}-{hour // 3}", "🌧️ Pluie attendue dans l'heure",
                    f"{rain:.1f} mm, prob. {pop} % à {name}.", 3))

    tmin1 = d["daily"]["temperature_2m_min"][1]
    if tmin1 is not None and tmin1 <= 0:
        out.append((f"{slug}-frost-{day}", "❄️ Gel prévu demain matin",
                    f"Minimale de {round(tmin1)} °C demain à {name}.", 4))

    if any(c in (95, 96, 99) for c in h["weather_code"][i:i + 12]):
        out.append((f"{slug}-storm-{day}", "⛈️ Risque d'orage",
                    f"Épisode orageux prévu dans les 12 h à {name}.", 4))

    gust = max(h["wind_gusts_10m"][i:i + 12])
    if gust >= 60:
        out.append((f"{slug}-wind-{day}", "💨 Fortes rafales",
                    f"Rafales jusqu'à {round(gust)} km/h à {name}.", 4))

    tmax0, tmin0 = d["daily"]["temperature_2m_max"][0], d["daily"]["temperature_2m_min"][0]
    if tmax0 >= 33:
        out.append((f"{slug}-heat-{day}", "🌡️ Pic de chaleur", f"Max de {round(tmax0)} °C aujourd'hui à {name}.", 4))
    elif tmin0 <= -3:
        out.append((f"{slug}-cold-{day}", "🥶 Grand froid", f"Min de {round(tmin0)} °C aujourd'hui à {name}.", 4))

    uv = d["daily"]["uv_index_max"][0]
    if uv is not None and uv >= 6:
        out.append((f"{slug}-uv-{day}", f"☀️ Indice UV élevé ({uv:.1f})",
                    f"Protection solaire recommandée à {name}.", 3))
    return out


def tomorrow_block(name, d):
    dl = d["daily"]
    desc = WMO.get(dl["weather_code"][1], "Temps variable")
    tmin, tmax = round(dl["temperature_2m_min"][1]), round(dl["temperature_2m_max"][1])
    rain, pop = dl["precipitation_sum"][1] or 0, dl["precipitation_probability_max"][1] or 0
    gust, uv = round(dl["wind_gusts_10m_max"][1] or 0), dl["uv_index_max"][1] or 0
    return (f"📍 {name} : {desc}, {tmin}° / {tmax}°\n"
            f"   Pluie {rain:.1f} mm ({pop} %) · rafales {gust} km/h · UV {uv:.0f}")


def already_sent():
    """Clés déjà envoyées sur les 24 dernières heures (lues dans l'historique ntfy)."""
    try:
        raw = http_text(f"{NTFY}/{TOPIC}/json?poll=1&since=24h")
    except Exception as e:
        print("Lecture historique impossible:", e)
        return set()
    keys = set()
    for line in raw.splitlines():
        try:
            keys.update(json.loads(line).get("tags", []))
        except ValueError:
            continue
    return keys


def publish(title, message, key, priority):
    payload = {"topic": TOPIC, "title": title, "message": message,
               "tags": [key], "priority": priority, "click": SITE}
    http_text(NTFY, json.dumps(payload).encode("utf-8"))
    print("envoyée:", key)


def main():
    sent = already_sent()
    data = {}
    for slug, name, lat, lon in CITIES:
        data[slug] = forecast(lat, lon)
        alerts = compute_alerts(slug, name, data[slug])
        if not alerts:
            print(f"{name} : aucune alerte active.")
        for key, title, body, prio in alerts:
            if key in sent:
                print("déjà envoyée:", key)
            else:
                publish(f"{title} ({name})", body, key, prio)

    # Récap de demain (toutes les villes dans une seule notification), une fois par soir
    first = data[CITIES[0][0]]
    if SUMMARY_HOUR <= int(first["current"]["time"][11:13]) < 23:
        key = f"tomorrow-{first['daily']['time'][1]}"
        if key in sent:
            print("récap déjà envoyé:", key)
        else:
            body = "\n".join(tomorrow_block(name, data[slug]) for slug, name, _, _ in CITIES)
            publish("📅 Météo de demain", body, key, 3)


if __name__ == "__main__":
    sys.exit(main())
    
