import base64
import json
import os
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from config import Config


SEARCH_STEPS = (
    "Préparation",
    "Connexion à SNCF",
    "Recherche des trains",
    "Comparaison des prix",
    "Résultats prêts",
)


def process_is_alive(pid) -> bool:
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _status_path() -> Path:
    return Path(getattr(Config, "SEARCH_STATUS_FILE", "./search_status.json"))


def set_search_status(
    state: str,
    label: str,
    step: int | None = None,
    error: str | None = None,
    offer_count: int | None = None,
    pid: int | None = None,
    skip_hub_push: bool = False,
):
    path = _status_path()
    current = load_search_status()
    resolved_step = current.get("step", 0) if step is None else step
    payload = {
        "state": state,
        "step": max(0, min(int(resolved_step), len(SEARCH_STEPS) - 1)),
        "steps": list(SEARCH_STEPS),
        "label": label,
        "error": error,
        "pid": pid if pid is not None else current.get("pid"),
        "offer_count": (
            offer_count
            if offer_count is not None
            else current.get("offer_count", 0)
        ),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if not skip_hub_push:
        _push_status_to_hub(payload)


def load_search_status() -> dict:
    path = _status_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {
        "state": "idle",
        "step": 0,
        "steps": list(SEARCH_STEPS),
        "label": "Aucune recherche en cours",
        "error": None,
        "pid": None,
        "offer_count": 0,
        "updated_at": "",
    }


def _push_status_to_hub(payload: dict):
    hub = getattr(Config, "WORKER_HUB", "")
    token = getattr(Config, "WORKER_TOKEN", "")
    if not hub or not token:
        return
    try:
        request = urllib.request.Request(
            f"{hub}/worker/status",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Worker-Token": token,
            },
        )
        user = getattr(Config, "WORKER_BASIC_USER", "")
        password = getattr(Config, "WORKER_BASIC_PASSWORD", "")
        if user:
            credentials = base64.b64encode(f"{user}:{password}".encode()).decode()
            request.add_header("Authorization", f"Basic {credentials}")
        urllib.request.urlopen(request, timeout=5)
    except (OSError, urllib.error.URLError):
        pass
