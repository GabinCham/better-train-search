import argparse
import os
import random
import re
import time
import webbrowser

from tenacity import retry, stop_after_attempt, wait_exponential

from browser.behavior import human_delay, human_scroll
from browser.launcher import BrowserManager
from config import Config
from local_links import (
    ensure_link_server,
    offer_url,
    reset_dashboard,
    save_offers,
    update_dashboard,
)
from proxy.rotator import ProxyRotator
from sncf import collect_offers, search_journeys
from utils.discord import send_challenge_alert, send_train_alert
from utils.instructions import load_instructions
from utils.status import set_search_status


LAST_CHALLENGE_ALERT_AT = 0.0


def is_challenged(page) -> bool:
    """Détecte les pages anti-bot bloquantes, notamment DataDome."""
    title = (page.title() or "").lower()
    url = page.url.lower()
    if "just a moment" in title or "attention required" in title:
        return True
    if any(part in url for part in (
        "cdn-cgi/challenge",
        "captcha-delivery.com",
        "/sorry/",
        "/captcha/",
        "/challenge/",
    )):
        return True

    blockers = [
        page.locator("#cf-challenge-running"),
        page.locator("#challenge-form"),
        page.locator("#cf-browser-verification"),
        page.locator('iframe[title*="captcha" i]'),
        page.locator('script[src*="captcha-delivery.com"]'),
        page.get_by_role("heading", name="Just a moment"),
        page.get_by_role("heading", name=re.compile("access denied", re.I)),
        page.get_by_role("heading", name=re.compile("verify.*human", re.I)),
        page.get_by_text("Checking your browser", exact=False),
    ]
    for blocker in blockers:
        try:
            if blocker.first.is_visible(timeout=400) or blocker.first.count():
                return True
        except Exception:
            continue
    return False


CHALLENGE_MESSAGE = (
    "SNCF a demandé une vérification anti-robot. Réessaie dans quelques minutes."
)


def wait_for_challenge_resolution(page, timeout_seconds: int = 120):
    if not is_challenged(page):
        return
    alert_challenge(page, CHALLENGE_MESSAGE)
    if Config.HEADLESS or Config.PUBLIC_BASE_URL:
        raise RuntimeError(CHALLENGE_MESSAGE)

    print(
        "[!] Challenge DataDome affiché dans Chrome. "
        f"Validez-le manuellement sous {timeout_seconds} secondes..."
    )
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        time.sleep(2)
        if not is_challenged(page):
            print("[+] Challenge validé, reprise de la recherche")
            human_delay(600, 1000)
            return
    raise RuntimeError(CHALLENGE_MESSAGE)


def alert_challenge(page, reason: str):
    global LAST_CHALLENGE_ALERT_AT
    now = time.monotonic()
    if (
        LAST_CHALLENGE_ALERT_AT
        and now - LAST_CHALLENGE_ALERT_AT < Config.CHALLENGE_ALERT_COOLDOWN_SECONDS
    ):
        print("[!] Alerte challenge déjà envoyée récemment")
        return

    LAST_CHALLENGE_ALERT_AT = now
    try:
        url = page.url
        title = page.title()
    except Exception:
        url, title = "", ""
    send_challenge_alert(url, title, reason)


def next_watch_interval(failed: bool) -> tuple[int, str]:
    if failed:
        minimum = Config.ERROR_BACKOFF_MIN_SECONDS
        maximum = Config.ERROR_BACKOFF_MAX_SECONDS
        reason = "Pause après erreur"
    else:
        minimum = Config.WATCH_INTERVAL_MIN_SECONDS
        maximum = Config.WATCH_INTERVAL_MAX_SECONDS
        reason = "Prochaine recherche"
    low, high = sorted((max(1, minimum), max(1, maximum)))
    return random.randint(low, high), reason


def accept_cookies(page):
    buttons = [
        page.locator(".didomi-continue-without-agreeing"),
        page.locator("#onetrust-accept-btn-handler"),
        page.get_by_role("button", name="Accepter et fermer"),
        page.get_by_role("button", name="Tout accepter"),
        page.get_by_role("button", name="J'accepte"),
        page.get_by_role("button", name="Accepter"),
    ]
    for button in buttons:
        try:
            if button.first.is_visible(timeout=1200):
                button.first.click()
                human_delay(300, 600)
                return
        except Exception:
            continue


def display_offers(offers: list[dict]):
    if not offers:
        print("[-] Aucun billet avec un prix exploitable")
        return
    print("[+] Billets classés du moins cher au plus cher :")
    for rank, offer in enumerate(offers, start=1):
        print(
            f"    {rank:>2}. {offer['price']:>7.2f} € · "
            f"{offer['date']} · "
            f"{offer['departure_time']} → {offer['arrival_time']} · "
            f"{offer['duration']} · {offer['operator']}"
        )


def select_cheapest(
    offers: list[dict],
    max_price: float | None,
    max_results: int = 0,
) -> list[dict]:
    selected = [
        offer
        for offer in offers
        if max_price is None or offer["price"] <= max_price
    ]
    selected.sort(
        key=lambda offer: (
            offer["price"],
            offer["date"],
            offer["departure_time"],
        )
    )
    return selected[:max_results] if max_results else selected


def notify_new_offers(offers: list[dict], max_alerts: int) -> list[dict]:
    if max_alerts <= 0:
        return []
    if not offers:
        return []

    sent = []
    for offer in offers[:max_alerts]:
        if send_train_alert(offer) or not Config.DISCORD_WEBHOOK_URL:
            sent.append(offer)
    return sent


def run_one_search(
    page,
    search: dict,
    site: str,
) -> list[dict]:
    page.goto(f"{site}/home/search/od", wait_until="domcontentloaded", timeout=60000)
    human_delay(800, 1400)
    wait_for_challenge_resolution(page)

    accept_cookies(page)
    set_search_status(
        "searching",
        f"Recherche du {search['date']} : {search['origin']} → {search['destination']}",
        step=2,
    )
    search_journeys(page, search)
    wait_for_challenge_resolution(page)

    by_id = {}
    unchanged_rounds = 0
    for _ in range(12):
        current = collect_offers(page, search, site)
        previous_count = len(by_id)
        by_id.update({offer["id"]: offer for offer in current})
        unchanged_rounds = unchanged_rounds + 1 if len(by_id) == previous_count else 0

        next_button = page.get_by_role(
            "button",
            name=re.compile(r"afficher les trajets suivants", re.I),
        )
        try:
            if (
                next_button.count() == 0
                or not next_button.first.is_visible(timeout=700)
                or not next_button.first.is_enabled()
                or unchanged_rounds >= 2
            ):
                break
            next_button.first.click()
            human_delay(1200, 1800)
        except Exception:
            break

    offers = sorted(
        by_id.values(),
        key=lambda offer: (offer["price"], offer["departure_time"]),
    )
    return offers


@retry(
    stop=stop_after_attempt(Config.MAX_RETRIES),
    wait=wait_exponential(multiplier=5, min=5, max=120),
)
def run_session(instructions: dict, profile_id: str | None = None):
    proxy = ProxyRotator().next()
    site = instructions["site"]
    print(f"[+] Proxy : {proxy or 'aucun'}")
    for search in instructions["searches"]:
        ceiling = (
            f" · maximum {search['max_price']:.2f} €"
            if search["max_price"] is not None
            else " · sans prix maximum"
        )
        print(
            f"[+] Trajet : {search['origin']} → {search['destination']} "
            f"les {', '.join(search['dates'])}{ceiling}"
        )

    manager = BrowserManager(proxy=proxy, profile_id=profile_id)
    set_search_status("opening", "Ouverture de SNCF Connect", step=1)
    page = manager.start()
    try:
        reset_dashboard()
        all_offers = []
        for search in instructions["searches"]:
            route_offers = []
            for travel_date in search["dates"]:
                dated_search = {**search, "date": travel_date}
                print(
                    f"[+] Recherche du {travel_date} : "
                    f"{search['origin']} → {search['destination']}"
                )
                set_search_status(
                    "searching",
                    f"Recherche du {travel_date} : "
                    f"{search['origin']} → {search['destination']}",
                    step=2,
                )
                route_offers.extend(run_one_search(page, dated_search, site))

            set_search_status(
                "ranking",
                f"Comparaison des prix · {search['origin']} → {search['destination']}",
                step=3,
            )

            selected = select_cheapest(
                route_offers,
                search["max_price"],
                instructions["max_results"],
            )
            display_offers(selected)
            if selected:
                save_offers(selected)
                update_dashboard(selected)
            # if Config.DISCORD_WEBHOOK_URL and selected:
            #     for offer in selected:
            #         offer["url"] = offer_url(offer["id"])
            # notify_new_offers(selected, instructions["max_alerts"])
            all_offers.extend(selected)
        print(f"[+] Session réussie · {len(all_offers)} billet(s) trouvé(s)")
        set_search_status(
            "done",
            (
                f"{len(all_offers)} train(s) trouvé(s)"
                if all_offers
                else "Aucun train trouvé pour ces critères"
            ),
            step=4,
            offer_count=len(all_offers),
        )
        return all_offers
    except Exception as error:
        print(f"[!] Erreur session : {type(error).__name__}: {error}")
        set_search_status(
            "error",
            "La recherche n'a pas pu aboutir",
            error=str(error),
        )
        text = str(error).lower()
        challenged = any(
            part in text for part in ("challenge", "datadome", "anti-robot")
        )
        if not challenged:
            try:
                challenged = is_challenged(page)
            except Exception:
                challenged = False
        if challenged:
            alert_challenge(page, str(error))
        raise
    finally:
        manager.close()


def main():
    parser = argparse.ArgumentParser(
        description="Recherche les billets SNCF Connect les moins chers"
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Relance les recherches en boucle et alerte sur Discord",
    )
    args = parser.parse_args()

    links_ready = ensure_link_server()
    if links_ready:
        print(
            f"[+] Interface locale : "
            f"http://127.0.0.1:{Config.LINK_SERVER_PORT}/"
        )
    else:
        print("[!] Impossible de démarrer l'interface locale")

    set_search_status("starting", "Démarrage de la recherche", step=0, pid=os.getpid())

    if not Config.DISCORD_WEBHOOK_URL:
        print("[!] Discord non configuré : pas d'alerte si SNCF détecte le bot")

    while True:
        failed = False
        try:
            run_session(
                load_instructions(),
                profile_id="sncf-watch" if args.watch else "sncf-main",
            )
        except Exception as error:
            failed = True
            print(f"[-] Échec après retries : {error}")
            set_search_status(
                "error",
                "La recherche n'a pas pu aboutir",
                error=str(error),
            )

        if not args.watch:
            if not failed and links_ready:
                dashboard = Config.PUBLIC_BASE_URL or f"http://127.0.0.1:{Config.LINK_SERVER_PORT}"
                print(f"[+] Résultats : {dashboard}/")
                if not Config.PUBLIC_BASE_URL:
                    webbrowser.open(f"{dashboard}/")
            break
        interval, reason = next_watch_interval(failed)
        print(f"[+] {reason} dans {interval // 60} min {interval % 60:02d}s")
        time.sleep(interval)


if __name__ == "__main__":
    main()
