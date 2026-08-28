import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from config import Config

SNCF_FALLBACK = "https://www.sncf-connect.com"


def _post_webhook(payload: dict, success_message: str) -> bool:
    webhook = Config.DISCORD_WEBHOOK_URL
    if not webhook:
        print("[!] Pas de DISCORD_WEBHOOK_URL → alerte Discord ignorée")
        return False

    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        webhook,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "sncf-price-alert"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            if response.status in (200, 204):
                print(success_message)
                return True
            print(f"[!] Discord HTTP {response.status}")
            return False
    except urllib.error.HTTPError as e:
        print(f"[!] Discord HTTP {e.code}: {e.read()[:200]!r}")
        return False
    except Exception as e:
        print(f"[!] Discord : {e}")
        return False


def send_train_alert(offer: dict) -> bool:
    route = f"{offer.get('origin', '—')} → {offer.get('destination', '—')}"
    price = offer.get("price")
    url = offer.get("url") or SNCF_FALLBACK

    embed = {
        "title": route[:256],
        "url": url,
        "color": 5814783,
        "fields": [
            {"name": "Prix", "value": f"{price:.2f} €", "inline": True},
            {"name": "Date", "value": offer.get("date") or "—", "inline": True},
            {
                "name": "Horaires",
                "value": (
                    f"{offer.get('departure_time', '—')} → "
                    f"{offer.get('arrival_time', '—')}"
                ),
                "inline": True,
            },
            {"name": "Durée", "value": offer.get("duration") or "—", "inline": True},
            {"name": "Train", "value": offer.get("operator") or "—", "inline": True},
        ],
    }

    payload = {
        "content": f"🚆 **{route}** à partir de **{price:.2f} €**",
        "embeds": [embed],
    }
    return _post_webhook(payload, f"[+] Discord envoyé : {route[:60]}")


def send_challenge_alert(url: str, title: str, reason: str) -> bool:
    payload = {
        "content": "🚨 **SNCF a détecté le robot**",
        "embeds": [{
            "title": "Recherche bloquée (anti-bot)",
            "url": url or SNCF_FALLBACK,
            "color": 15158332,
            "fields": [
                {"name": "Raison", "value": reason[:1024], "inline": False},
                {"name": "Titre de la page", "value": (title or "—")[:1024], "inline": False},
                {"name": "URL", "value": (url or "—")[:1024], "inline": False},
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }],
    }
    return _post_webhook(payload, "[+] Alerte challenge envoyée sur Discord")