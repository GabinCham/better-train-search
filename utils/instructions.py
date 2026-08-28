from datetime import date
from pathlib import Path

import yaml
from config import Config


def _parse_date(raw, path: Path) -> str:
    try:
        travel_date = date.fromisoformat(str(raw).strip())
    except (TypeError, ValueError):
        raise ValueError(
            f"Date invalide dans {path} : utilisez le format AAAA-MM-JJ"
        ) from None
    if travel_date < date.today():
        raise ValueError(f"La date {travel_date.isoformat()} est déjà passée")
    return travel_date.isoformat()


def _parse_dates(raw, path: Path) -> list[str]:
    values = raw if isinstance(raw, list) else [raw]
    dates = []
    for value in values:
        parsed = _parse_date(value, path)
        if parsed not in dates:
            dates.append(parsed)
    return dates


def load_instructions() -> dict:
    path = Path(Config.INSTRUCTIONS_FILE)
    if not path.exists():
        raise FileNotFoundError(f"Fichier d'instructions introuvable : {path}")

    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    searches = []
    for raw in data.get("recherches") or []:
        origin = str(raw.get("depart") or "").strip()
        destination = str(raw.get("destination") or "").strip()
        raw_dates = raw.get("dates", raw.get("date"))
        if not origin or not destination or not raw_dates:
            continue
        raw_max_price = raw.get("prix_max")
        searches.append({
            "origin": origin,
            "destination": destination,
            "dates": _parse_dates(raw_dates, path),
            "max_price": (
                float(raw_max_price)
                if raw_max_price is not None and str(raw_max_price).strip()
                else None
            ),
        })

    if not searches:
        raise ValueError(f"Aucune recherche valide dans {path}")

    return {
        "site": (data.get("site") or "https://www.sncf-connect.com").rstrip("/"),
        "max_results": max(0, int(data.get("max_resultats") or 0)),
        "max_alerts": max(0, int(data.get("max_alertes") or 5)),
        "searches": searches,
    }