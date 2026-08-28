#!/usr/bin/env python3
"""Polls the public site and runs SNCF searches on this computer."""

import base64
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from config import Config


ROOT = Path(__file__).resolve().parent


def _request(method: str, path: str, payload: dict | None = None, timeout: int = 20):
    if not Config.WORKER_HUB or not Config.WORKER_TOKEN:
        raise RuntimeError(
            "Configure WORKER_HUB et WORKER_TOKEN dans le fichier .env de ce Mac."
        )
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{Config.WORKER_HUB}{path}",
        data=data,
        method=method,
        headers={"X-Worker-Token": Config.WORKER_TOKEN},
    )
    if payload is not None:
        request.add_header("Content-Type", "application/json")
    if Config.WORKER_BASIC_USER:
        credentials = base64.b64encode(
            f"{Config.WORKER_BASIC_USER}:{Config.WORKER_BASIC_PASSWORD}".encode()
        ).decode()
        request.add_header("Authorization", f"Basic {credentials}")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
        if not body:
            return {}
        return json.loads(body)


def _load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def run_job(instructions_yaml: str):
    Path(Config.INSTRUCTIONS_FILE).write_text(instructions_yaml, encoding="utf-8")
    log_path = ROOT / "bot-run.log"
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"\n--- worker {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
        result = subprocess.run(
            [sys.executable, str(ROOT / "main.py")],
            cwd=ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
    dashboard = _load_json(Path(Config.DASHBOARD_FILE))
    offers = _load_json(Path(Config.OFFERS_FILE))
    try:
        _request(
            "POST",
            "/worker/results",
            {"dashboard": dashboard, "offers": offers},
            timeout=30,
        )
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        print(f"[!] Impossible d'envoyer les résultats : {error}")
    try:
        _request("POST", "/worker/finished", {})
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        print(f"[!] Impossible de clôturer le job : {error}")
    if result.returncode != 0:
        print(f"[!] La recherche s'est terminée avec le code {result.returncode}")
    else:
        print("[+] Recherche terminée, résultats envoyés au site.")


def main():
    print("Robot prêt. Laisse cette fenêtre ouverte.")
    print(f"Site : {Config.WORKER_HUB or '(WORKER_HUB manquant)'}")
    print("Tes amis lancent une recherche sur le site ; Chrome s'ouvrira ici.")
    while True:
        try:
            _request("POST", "/worker/ping", {})
            job = _request("GET", "/worker/next")
        except (OSError, urllib.error.URLError, json.JSONDecodeError, RuntimeError) as error:
            print(f"[!] Site injoignable : {error}")
            time.sleep(5)
            continue
        instructions = (job or {}).get("instructions")
        if instructions:
            print("[+] Recherche reçue, Chrome va s'ouvrir…")
            run_job(instructions)
        else:
            time.sleep(2)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nRobot arrêté.")
