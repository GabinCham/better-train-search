import json
import os
from config import Config


def load_seen() -> set[str]:
    path = Config.SEEN_OFFERS_FILE
    if not os.path.exists(path):
        return set()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return set(data) if isinstance(data, list) else set()
    except Exception:
        return set()


def mark_seen(offer_id: str):
    seen = load_seen()
    seen.add(offer_id)
    directory = os.path.dirname(Config.SEEN_OFFERS_FILE)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(Config.SEEN_OFFERS_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f)