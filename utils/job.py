import json
from datetime import datetime, timezone
from pathlib import Path

from config import Config


def _job_path() -> Path:
    return Path(getattr(Config, "JOB_FILE", "./job.json"))


def _worker_path() -> Path:
    return Path(getattr(Config, "WORKER_HEARTBEAT_FILE", "./worker.json"))


def load_job() -> dict:
    path = _job_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {"id": None, "state": "idle"}


def save_job(data: dict):
    path = _job_path()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def queue_remote_job() -> bool:
    job = load_job()
    if job.get("state") in ("queued", "running"):
        return False
    save_job({
        "id": datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
        "state": "queued",
        "queued_at": datetime.now().isoformat(timespec="seconds"),
    })
    return True


def worker_is_online(max_age_seconds: int = 20) -> bool:
    path = _worker_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        seen = datetime.fromisoformat(data["seen_at"])
        return (datetime.now() - seen).total_seconds() <= max_age_seconds
    except (OSError, ValueError, KeyError, TypeError):
        return False


def touch_worker():
    path = _worker_path()
    path.write_text(
        json.dumps({"seen_at": datetime.now().isoformat(timespec="seconds")}),
        encoding="utf-8",
    )
