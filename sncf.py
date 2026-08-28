import hashlib
import re
from datetime import date
from urllib.parse import urljoin

from browser.behavior import human_delay


MONTHS_FR = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)
WEEKDAYS_FR = (
    "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche",
)


def parse_price(text: str) -> float | None:
    if not text:
        return None
    normalized = text.replace("\xa0", " ").replace("\u202f", " ")
    matches = re.findall(r"(\d[\d ]*)(?:[,.](\d{1,2}))?\s*€", normalized)
    if not matches:
        return None
    prices = [
        float(f"{euros.replace(' ', '')}.{cents or '0'}")
        for euros, cents in matches
    ]
    return min(prices)


def _first_visible(locators, timeout: int = 800):
    for locator in locators:
        try:
            if locator.first.is_visible(timeout=timeout):
                return locator.first
        except Exception:
            continue
    return None


def _station_input(page, kind: str):
    if kind == "origin":
        names = re.compile(r"d['’]où partez-vous|gare de départ|départ|origine", re.I)
        french_selectors = (
            'input[placeholder*="départ" i], input[aria-label*="départ" i], '
            'input[placeholder*="origine" i], input[aria-label*="origine" i]'
        )
    else:
        names = re.compile(r"où allez-vous|gare d'arrivée|arrivée|destination", re.I)
        french_selectors = (
            'input[placeholder*="arrivée" i], input[aria-label*="arrivée" i], '
            'input[placeholder*="destination" i], input[aria-label*="destination" i]'
        )

    return _first_visible([
        page.get_by_role("combobox", name=names),
        page.get_by_role("textbox", name=names),
        page.locator(
            f'input[placeholder*="{kind}" i], input[name*="{kind}" i], '
            f'input[aria-label*="{kind}" i], [data-test*="{kind}" i] input, '
            f'[data-testid*="{kind}" i] input'
        ),
        page.locator(french_selectors),
    ])


def _open_search_form(page):
    if _station_input(page, "origin"):
        return
    trigger = _first_visible([
        page.get_by_role(
            "button",
            name=re.compile(
                r"où voulez-vous partir|rechercher(?: un trajet)?|acheter un billet",
                re.I,
            ),
        ),
        page.get_by_text(re.compile(r"où voulez-vous partir|^rechercher$", re.I)),
    ], timeout=1200)
    if trigger:
        trigger.click()
        human_delay(400, 800)


def _choose_station(page, kind: str, value: str):
    field = _station_input(page, kind)
    if not field:
        label = "départ" if kind == "origin" else "destination"
        raise RuntimeError(f"Champ de {label} SNCF introuvable")

    field.click()
    field.fill(value)
    human_delay(500, 900)

    option = _first_visible([
        page.get_by_role("option").filter(has_text=re.compile(re.escape(value), re.I)),
        page.get_by_role("listbox").get_by_text(
            re.compile(re.escape(value), re.I)
        ),
        page.locator('[role="option"], [data-test*="suggestion"], [data-testid*="suggestion"]')
            .filter(has_text=re.compile(re.escape(value), re.I)),
    ], timeout=1800)
    if option:
        option.click()
    else:
        field.press("ArrowDown")
        field.press("Enter")
    human_delay(300, 650)


def _date_labels(iso_date: str) -> list[str]:
    value = date.fromisoformat(iso_date)
    weekday = WEEKDAYS_FR[value.weekday()]
    month = MONTHS_FR[value.month - 1]
    return [
        iso_date,
        value.strftime("%d/%m/%Y"),
        f"{value.day} {month} {value.year}",
        f"{weekday} {value.day} {month} {value.year}",
    ]


def _choose_date(page, iso_date: str):
    date_input = _first_visible([
        page.locator('input[type="date"]'),
        page.locator('input[name*="date" i]'),
        page.get_by_role("textbox", name=re.compile(r"date|aller", re.I)),
    ])
    if date_input:
        input_type = (date_input.get_attribute("type") or "").lower()
        value = iso_date if input_type == "date" else date.fromisoformat(iso_date).strftime("%d/%m/%Y")
        date_input.fill(value)
        date_input.press("Tab")
        human_delay(300, 600)
        return

    opener = _first_visible([
        page.get_by_role("button", name=re.compile(r"date|aller", re.I)),
        page.locator('[data-test*="date"], [data-testid*="date"]'),
    ], timeout=1200)
    if not opener:
        raise RuntimeError("Sélecteur de date SNCF introuvable")
    opener.click()
    human_delay(300, 600)

    labels = _date_labels(iso_date)
    day = _first_visible([
        page.get_by_role("button", name=re.compile(re.escape(label), re.I))
        for label in labels
    ], timeout=500)
    if not day:
        day = _first_visible([
            page.locator(f'[data-date="{iso_date}"]'),
            page.locator(f'time[datetime="{iso_date}"]').locator("xpath=ancestor::button[1]"),
        ])
    if not day:
        raise RuntimeError(
            f"La date {iso_date} n'est pas visible dans le calendrier SNCF"
        )
    day.click()
    human_delay(1000, 1400)

    confirm = _first_visible([
        page.get_by_role("button", name=re.compile(r"valider|confirmer|appliquer", re.I)),
    ], timeout=1600)
    if confirm:
        confirm.click()
        try:
            page.get_by_role("dialog").wait_for(state="hidden", timeout=5000)
        except Exception:
            pass


def search_journeys(page, search: dict):
    _open_search_form(page)
    _choose_station(page, "origin", search["origin"])
    _choose_station(page, "destination", search["destination"])
    _choose_date(page, search["date"])

    submit = _first_visible([
        page.get_by_role(
            "button",
            name=re.compile(r"voir les prix|rechercher|afficher les prix", re.I),
        ),
        page.locator('[data-test*="search"][type="submit"], [data-testid*="search"][type="submit"]'),
    ], timeout=1600)
    if not submit:
        raise RuntimeError("Bouton de recherche SNCF introuvable")
    submit.click()
    page.wait_for_load_state("domcontentloaded", timeout=60000)
    page.wait_for_function(
        "() => document.body.innerText.includes('€') "
        "|| /aucun trajet|indisponible/i.test(document.body.innerText)",
        timeout=60000,
    )
    human_delay(800, 1400)


def _offer_id(search: dict, departure: str, arrival: str, operator: str) -> str:
    raw = "|".join([
        search["date"],
        search["origin"].casefold(),
        search["destination"].casefold(),
        departure,
        arrival,
        operator.casefold(),
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def collect_offers(page, search: dict, site: str) -> list[dict]:
    offers = []
    seen = set()
    cards = page.locator(
        '[data-test="proposal-card"], [data-testid="proposal-card"]'
    )

    for index in range(cards.count()):
        container = cards.nth(index)
        try:
            text = " ".join(container.inner_text().split())
            price = parse_price(text)
            if price is None:
                continue

            times = re.findall(r"\b(?:[01]?\d|2[0-3])[:h]\d{2}\b", text)
            departure = times[0].replace("h", ":") if times else "—"
            arrival = times[1].replace("h", ":") if len(times) > 1 else "—"
            duration_match = re.search(r"\b\d+\s*h(?:\s*\d{1,2}(?:\s*min)?)?\b", text, re.I)
            operator_match = re.search(
                r"\b(TGV\s*INOUI|OUIGO(?:\s+Train Classique)?|INTERCIT[EÉ]S|TER|"
                r"EUROSTAR|TGV\s*LYRIA|RENFE|TRENITALIA)\b",
                text,
                re.I,
            )
            operator = operator_match.group(1) if operator_match else "Train"
            offer_id = _offer_id(search, departure, arrival, operator)
            if offer_id in seen:
                continue

            link = container.locator("a[href]").first
            href = link.get_attribute("href") if link.count() else ""
            offers.append({
                "id": offer_id,
                "price": price,
                "origin": search["origin"],
                "destination": search["destination"],
                "date": search["date"],
                "departure_time": departure,
                "arrival_time": arrival,
                "duration": duration_match.group(0) if duration_match else "—",
                "operator": operator,
                "url": urljoin(f"{site}/", href) if href else page.url,
            })
            seen.add(offer_id)
        except Exception:
            continue

    return sorted(offers, key=lambda offer: (offer["price"], offer["departure_time"]))
