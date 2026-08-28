import argparse
import html
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import yaml
from browser.launcher import BrowserManager
from config import Config
from sncf import search_journeys
from utils.instructions import load_instructions
from utils.status import load_search_status, process_is_alive, set_search_status


ROOT = Path(__file__).resolve().parent
SERVER_SIGNATURE = b"sncf-local-links-v8"
RUN_PROCESS = None


def public_base() -> str:
    return Config.PUBLIC_BASE_URL or f"http://127.0.0.1:{Config.LINK_SERVER_PORT}"


def offer_url(offer_id: str) -> str:
    return f"{public_base()}/offer/{offer_id}"


def train_href(offer: dict) -> str:
    if Config.OPEN_OFFERS_IN_CLIENT:
        external = offer.get("sncf_url") or ""
        if external.startswith("http") and "/offer/" not in external:
            return external
        return "https://www.sncf-connect.com"
    return offer_url(offer["id"])


def load_offers() -> dict[str, dict]:
    path = Path(Config.OFFERS_FILE)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_offers(offers: list[dict]):
    path = Path(Config.OFFERS_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    stored = load_offers()
    for offer in offers:
        sncf_url = offer.get("sncf_url") or offer.get("url") or ""
        if "/offer/" in sncf_url:
            sncf_url = offer.get("sncf_url") or ""
        stored[offer["id"]] = {
            **offer,
            "sncf_url": sncf_url,
            "url": offer_url(offer["id"]),
        }
    path.write_text(
        json.dumps(stored, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def reset_dashboard():
    path = Path(Config.DASHBOARD_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"updated_at": datetime.now().isoformat(timespec="seconds"), "offers": []},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def update_dashboard(offers: list[dict]):
    path = Path(Config.DASHBOARD_FILE)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {"updated_at": "", "offers": []}
    current = {
        offer["id"]: offer
        for offer in data.get("offers", [])
        if isinstance(offer, dict) and offer.get("id")
    }
    current.update({offer["id"]: offer for offer in offers})
    data = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "offers": list(current.values()),
    }
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_dashboard() -> dict:
    try:
        data = json.loads(Path(Config.DASHBOARD_FILE).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"offers": []}
    except (OSError, json.JSONDecodeError):
        return {"offers": []}


def _server_is_running() -> bool:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{Config.LINK_SERVER_PORT}/health",
            timeout=1,
        ) as response:
            return response.read() == SERVER_SIGNATURE
    except (OSError, urllib.error.URLError):
        return False


def ensure_link_server() -> bool:
    if _server_is_running():
        return True
    subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "serve"],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    for _ in range(20):
        time.sleep(0.1)
        if _server_is_running():
            return True
    return False


def _html_page(title: str, message: str) -> bytes:
    return f"""<!doctype html>
<html lang="fr"><meta charset="utf-8">
<title>{title}</title>
<style>
body {{ font: 18px system-ui; max-width: 680px; margin: 80px auto; padding: 20px; }}
h1 {{ color: #17233c; }} p {{ line-height: 1.5; }}
</style>
<h1>{title}</h1><p>{message}</p>
</html>""".encode("utf-8")


def _format_day(iso_date: str) -> str:
    days = ("Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche")
    months = (
        "janvier", "février", "mars", "avril", "mai", "juin",
        "juillet", "août", "septembre", "octobre", "novembre", "décembre",
    )
    try:
        value = datetime.fromisoformat(iso_date)
        return f"{days[value.weekday()]} {value.day} {months[value.month - 1]}"
    except ValueError:
        return iso_date


def _duration_minutes(duration: str) -> int:
    match = re.search(r"(?:(\d+)\s*h)?\s*(\d{1,2})?", duration or "")
    if not match:
        return 9999
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    total = hours * 60 + minutes
    return total or 9999


def render_dashboard() -> bytes:
    data = load_dashboard()
    offers = [
        offer for offer in data.get("offers", [])
        if isinstance(offer, dict) and offer.get("price") is not None
    ]
    routes = {}
    for offer in offers:
        route = (offer.get("origin", "—"), offer.get("destination", "—"))
        routes.setdefault(route, {}).setdefault(offer.get("date", "—"), []).append(offer)

    route_sections = []
    for (origin, destination), days in routes.items():
        day_sections = []
        for travel_date, day_offers in sorted(days.items()):
            day_offers.sort(key=lambda item: (
                item["price"],
                _duration_minutes(item.get("duration", "")),
                item.get("departure_time", ""),
            ))
            cheapest = day_offers[0]["price"]
            shortest = min(
                _duration_minutes(offer.get("duration", ""))
                for offer in day_offers
            )
            train_rows = []
            for index, offer in enumerate(day_offers):
                duration_minutes = _duration_minutes(offer.get("duration", ""))
                is_double_winner = (
                    offer["price"] == cheapest
                    and duration_minutes == shortest
                )
                classes = ["train"]
                if index == 0:
                    classes.append("recommended")
                if is_double_winner:
                    classes.append("gold")
                badge = (
                    '<em class="gold-badge">★ Moins cher + plus rapide</em>'
                    if is_double_winner
                    else ""
                )
                train_rows.append(f"""
                <a class="{' '.join(classes)}" href="{html.escape(train_href(offer))}"
                   {"target=\"_blank\" rel=\"noopener\"" if Config.OPEN_OFFERS_IN_CLIENT else ""}
                   data-price="{offer['price']}" data-duration="{duration_minutes}"
                   data-departure="{html.escape(offer.get('departure_time', ''))}">
                  <span class="time">{html.escape(offer.get('departure_time', '—'))}
                    <small>→ {html.escape(offer.get('arrival_time', '—'))}</small>
                  </span>
                  <span class="operator">{html.escape(offer.get('operator', 'Train'))}
                    <small>{html.escape(offer.get('duration', '—'))}</small>{badge}
                  </span>
                  <strong>{offer['price']:.2f}&nbsp;€</strong>
                </a>""")
            day_sections.append(f"""
            <section class="day">
              <header>
                <div><span class="eyebrow">Jour sélectionné</span>
                  <h3>{html.escape(_format_day(travel_date))}</h3></div>
                <div class="best"><span>Meilleur prix</span><b>{cheapest:.2f}&nbsp;€</b></div>
              </header>
              <div class="sorter" role="group" aria-label="Trier les trains">
                <button class="active" data-sort="price">Moins cher</button>
                <button data-sort="duration" title="Trier par durée de trajet">Plus rapide</button>
                <button data-sort="balance">Équilibre</button>
                <button class="anger" data-sort="anger"
                  title="Comparer deux départs proches avec un grand écart de prix">😡 Écart</button>
              </div>
              <div class="anger-explanation" hidden></div>
              <div class="trains">{''.join(train_rows)}</div>
            </section>""")
        route_sections.append(f"""
        <section class="route">
          <div class="route-title"><span>Trajet</span>
            <h2>{html.escape(origin)} <i>→</i> {html.escape(destination)}</h2></div>
          <div class="days">{''.join(day_sections)}</div>
        </section>""")

    content = "".join(route_sections) or """
      <div class="empty"><h2>Aucun résultat pour le moment</h2>
      <p>Lance le bot pour afficher les trains des jours sélectionnés.</p></div>"""
    updated_at = html.escape(data.get("updated_at") or "—")
    return f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="60">
  <title>Comparateur SNCF local</title>
  <style>
    :root {{ --navy:#111a30; --blue:#1674d1; --pale:#eef5ff; --line:#dce4ef;
      --green:#087a55; --green-bg:#e5f7ef; --text:#172033; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; color:var(--text); background:#f5f7fb;
      font-family:Inter,ui-sans-serif,system-ui,-apple-system,sans-serif; }}
    .top {{ position:relative; color:white; background:var(--navy);
      padding:30px max(24px,calc((100% - 1440px)/2)); }}
    .top span,.eyebrow,.route-title>span {{ color:#7f91ad; font-size:12px;
      font-weight:800; letter-spacing:.09em; text-transform:uppercase; }}
    .top h1 {{ margin:5px 0 0; font-size:clamp(26px,4vw,42px); }}
    .top p {{ margin:8px 0 0; color:#b9c6d9; }}
    .settings-link {{ position:absolute; top:32px; right:max(24px,calc((100% - 1440px)/2));
      padding:11px 15px; color:white; border:1px solid #52617b; border-radius:9px;
      text-decoration:none; font-size:13px; font-weight:750; }}
    .settings-link:hover {{ background:#26324a; }}
    main {{ max-width:1440px; margin:auto; padding:28px 24px 60px; }}
    .route {{ margin-bottom:38px; }}
    .route-title {{ margin:0 0 15px; }}
    .route-title h2 {{ margin:4px 0; font-size:24px; }}
    .route-title i {{ color:var(--blue); font-style:normal; }}
    .days {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(320px,1fr)); gap:18px; }}
    .day {{ overflow:hidden; background:white; border:1px solid var(--line);
      border-radius:16px; box-shadow:0 7px 24px rgba(26,44,74,.06); }}
    .day>header {{ display:flex; align-items:center; justify-content:space-between;
      gap:16px; padding:20px; background:var(--pale); border-bottom:1px solid var(--line); }}
    .day h3 {{ margin:4px 0 0; font-size:19px; }}
    .best {{ text-align:right; }}
    .best span {{ display:block; color:#617087; font-size:12px; }}
    .best b {{ color:var(--green); font-size:23px; }}
    .sorter {{ display:grid; grid-template-columns:repeat(4,1fr); gap:5px;
      margin:12px 12px 4px; padding:4px; background:#edf1f6; border-radius:10px; }}
    .sorter button {{ padding:9px 5px; color:#58667a; background:transparent;
      border:0; border-radius:7px; font-family:inherit; font-size:12px;
      font-weight:700; cursor:pointer; }}
    .sorter button:hover {{ color:var(--blue); }}
    .sorter button.active {{ color:var(--navy); background:white;
      box-shadow:0 2px 7px rgba(23,32,51,.11); }}
    .sorter button.anger.active {{ color:#9c251d; background:#fff0ed; }}
    .anger-explanation {{ margin:8px 12px 4px; padding:10px 12px; color:#78221c;
      background:#fff0ed; border:1px solid #ffc9c2; border-radius:9px;
      font-size:12px; font-weight:650; line-height:1.4; }}
    .trains {{ padding:8px; }}
    .train {{ display:grid; grid-template-columns:1.1fr 1.4fr auto; align-items:center;
      gap:10px; min-height:68px; margin:4px 0; padding:12px; color:inherit;
      border:1px solid transparent; border-radius:11px; text-decoration:none; }}
    .train:hover {{ background:#f7faff; border-color:#b9d6f3; }}
    .train.recommended {{ background:var(--green-bg); }}
    .train.gold {{ background:linear-gradient(110deg,#fff3c2,#ffe08a);
      border-color:#e2b638; box-shadow:inset 4px 0 #d6a600; }}
    .train span {{ font-weight:750; }}
    .train small {{ display:block; margin-top:3px; color:#68768a; font-weight:500; }}
    .train strong {{ color:var(--blue); font-size:19px; white-space:nowrap; }}
    .train.recommended strong {{ color:var(--green); }}
    .train.gold strong {{ color:#8a6200; }}
    .train.filtered-out {{ display:none; }}
    .gold-badge {{ display:block; width:max-content; max-width:100%; margin-top:6px;
      padding:3px 6px; color:#6f5100; background:rgba(255,255,255,.58);
      border-radius:5px; font-size:10px; font-style:normal; font-weight:800; }}
    .empty {{ padding:70px 20px; text-align:center; background:white; border-radius:16px; }}
    @media(max-width:520px) {{
      main {{ padding:20px 12px 40px; }} .days {{ grid-template-columns:1fr; }}
      .train {{ grid-template-columns:1fr 1fr; }} .operator {{ display:none; }}
    }}
  </style>
</head>
<body>
  <header class="top"><span>Tableau de bord local</span>
    <h1>Les trains les moins chers</h1>
    <p>Actualisé le {updated_at} · Clique sur un train pour l'ouvrir dans SNCF Connect.</p>
    <a class="settings-link" href="/settings">＋ Nouvelle recherche</a>
  </header>
  <main>{content}</main>
  <script>
    const formatDuration = minutes => {{
      if (!Number.isFinite(minutes) || minutes >= 9999) return "—";
      return `${{Math.floor(minutes / 60)}}h${{String(minutes % 60).padStart(2, "0")}}`;
    }};
    document.querySelectorAll(".day").forEach(day => {{
      const trains = day.querySelector(".trains");
      const rows = [...trains.querySelectorAll(".train")];
      const prices = rows.map(row => Number(row.dataset.price));
      const durations = rows.map(row => Number(row.dataset.duration));
      const minPrice = Math.min(...prices), maxPrice = Math.max(...prices);
      const minDuration = Math.min(...durations), maxDuration = Math.max(...durations);
      const departureMinutes = row => {{
        const match = (row.dataset.departure || "").match(/(\\d{{1,2}}):(\\d{{2}})/);
        return match ? Number(match[1]) * 60 + Number(match[2]) : 9999;
      }};
      const angerPair = () => {{
        let winner = null;
        for (let i = 0; i < rows.length; i++) {{
          for (let j = i + 1; j < rows.length; j++) {{
            const timeGap = Math.abs(departureMinutes(rows[i]) - departureMinutes(rows[j]));
            if (timeGap >= 9999) continue;
            const priceGap = Math.abs(
              Number(rows[i].dataset.price) - Number(rows[j].dataset.price));
            const comparisonScore = priceGap / Math.max(1, timeGap);
            if (!winner || comparisonScore > winner.score ||
                (comparisonScore === winner.score && priceGap > winner.priceGap)) {{
              winner = {{ first:rows[i], second:rows[j], timeGap, priceGap,
                score:comparisonScore }};
            }}
          }}
        }}
        return winner;
      }};

      const score = (row, mode) => {{
        const price = Number(row.dataset.price);
        const duration = Number(row.dataset.duration);
        if (mode === "duration") return duration;
        if (mode === "balance") {{
          const priceScore = (price - minPrice) / Math.max(1, maxPrice - minPrice);
          const durationScore = (duration - minDuration) /
            Math.max(1, maxDuration - minDuration);
          return priceScore + durationScore;
        }}
        return price;
      }};

      day.querySelectorAll(".sorter button").forEach(button => {{
        button.addEventListener("click", () => {{
          const mode = button.dataset.sort;
          day.querySelectorAll(".sorter button").forEach(item =>
            item.classList.toggle("active", item === button));
          rows.forEach(row => row.classList.remove("filtered-out"));
          const explanation = day.querySelector(".anger-explanation");
          explanation.hidden = true;

          if (mode === "anger") {{
            const pair = angerPair();
            if (!pair) return;
            rows.forEach(row => {{
              row.classList.remove("recommended");
              if (row !== pair.first && row !== pair.second)
                row.classList.add("filtered-out");
            }});
            const pairRows = [pair.first, pair.second].sort(
              (a, b) => departureMinutes(a) - departureMinutes(b));
            pairRows.forEach(row => trains.appendChild(row));
            const cheaper = pairRows.reduce((best, row) =>
              Number(row.dataset.price) < Number(best.dataset.price) ? row : best);
            cheaper.classList.add("recommended");
            day.querySelector(".best span").textContent = "Écart le plus surprenant";
            day.querySelector(".best b").textContent =
              `+${{pair.priceGap.toFixed(2)}} € · ${{pair.timeGap}} min`;
            explanation.textContent =
              `😡 Ces deux trains partent à ${{pair.timeGap}} min d'écart, ` +
              `mais le plus cher coûte ${{pair.priceGap.toFixed(2)}} € de plus.`;
            explanation.hidden = false;
            return;
          }}

          rows.sort((a, b) => score(a, mode) - score(b, mode)
            || Number(a.dataset.price) - Number(b.dataset.price)
            || Number(a.dataset.duration) - Number(b.dataset.duration));
          rows.forEach(row => {{
            row.classList.remove("recommended");
            trains.appendChild(row);
          }});
          const best = rows[0];
          best.classList.add("recommended");
          const label = day.querySelector(".best span");
          const value = day.querySelector(".best b");
          if (mode === "duration") {{
            label.textContent = "Trajet le plus rapide";
            value.textContent = formatDuration(Number(best.dataset.duration));
          }} else if (mode === "balance") {{
            label.textContent = "Meilleur équilibre";
            value.textContent = `${{Number(best.dataset.price).toFixed(2)}} € · ${{
              formatDuration(Number(best.dataset.duration))}}`;
          }} else {{
            label.textContent = "Meilleur prix";
            value.textContent = `${{Number(best.dataset.price).toFixed(2)}} €`;
          }}
        }});
      }});
    }});
  </script>
</body>
</html>""".encode("utf-8")


def _date_input(index: int, value: str = "") -> str:
    value_attr = f' value="{html.escape(value)}"' if value else ""
    return (
        f'<div class="date-row"><input type="date" name="dates_{index}"'
        f'{value_attr} required>'
        '<button type="button" class="remove-date" onclick="removeDate(this)"'
        ' aria-label="Retirer ce jour">×</button></div>'
    )


def _route_form(search: dict, index: int) -> str:
    dates = search.get("dates") or [date.today().isoformat()]
    date_inputs = "".join(_date_input(index, value) for value in dates)
    max_price = "" if search.get("max_price") is None else str(search["max_price"])
    return f"""
    <section class="search-card" data-index="{index}">
      <div class="card-head"><h2>Trajet <span>{index + 1}</span></h2>
        <button type="button" class="remove" onclick="removeRoute(this)">Supprimer</button></div>
      <div class="two-cols">
        <label>Gare ou ville de départ
          <input name="origin_{index}" value="{html.escape(search.get('origin', ''))}"
            placeholder="Ex. Le Mans" required>
        </label>
        <label>Destination
          <input name="destination_{index}" value="{html.escape(search.get('destination', ''))}"
            placeholder="Ex. Bordeaux" required>
        </label>
      </div>
      <label>Jours à comparer</label>
      <div class="dates" data-date-name="dates_{index}">{date_inputs}</div>
      <button type="button" class="add-date" onclick="addDate(this)">＋ Ajouter un jour</button>
      <label class="price">Prix maximum <small>(facultatif)</small>
        <div class="price-input"><input type="number" min="0" step="0.01"
          name="max_price_{index}" value="{html.escape(max_price)}"
          placeholder="Aucune limite"><span>€</span></div>
      </label>
    </section>"""


def render_settings(
    message: str = "",
    is_error: bool = False,
    watch_search: bool = False,
) -> bytes:
    try:
        instructions = load_instructions()
    except Exception:
        instructions = {
            "searches": [{
                "origin": "",
                "destination": "",
                "dates": [date.today().isoformat()],
                "max_price": None,
            }],
            "max_results": 0,
            "max_alerts": 1,
        }
    searches = instructions.get("searches") or []
    cards = "".join(_route_form(search, index) for index, search in enumerate(searches))
    notice = ""
    if message and not watch_search:
        notice = (
            f'<div class="notice {"error" if is_error else ""}">{html.escape(message)}</div>'
        )
    return f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Configurer la recherche SNCF</title>
  <style>
    :root {{ --navy:#111a30; --blue:#1674d1; --line:#dce4ef; --text:#172033; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; color:var(--text); background:#f5f7fb;
      font-family:Inter,ui-sans-serif,system-ui,-apple-system,sans-serif; }}
    header {{ color:white; background:var(--navy); padding:28px max(24px,calc((100% - 900px)/2)); }}
    header a {{ color:#bcd5f2; text-decoration:none; font-size:13px; font-weight:700; }}
    header h1 {{ margin:12px 0 5px; font-size:34px; }}
    header p {{ margin:0; color:#b9c6d9; }}
    main {{ max-width:900px; margin:auto; padding:26px 20px 60px; }}
    .notice {{ margin-bottom:18px; padding:13px 15px; color:#075f43;
      background:#e5f7ef; border:1px solid #a7dfca; border-radius:10px; font-weight:700; }}
    .notice.error {{ color:#8d241c; background:#fff0ed; border-color:#ffc9c2; }}
    .search-card,.options {{ margin-bottom:18px; padding:22px; background:white;
      border:1px solid var(--line); border-radius:15px;
      box-shadow:0 7px 24px rgba(26,44,74,.05); }}
    .card-head {{ display:flex; align-items:center; justify-content:space-between; margin-bottom:20px; }}
    .card-head h2 {{ margin:0; font-size:20px; }}
    .card-head h2 span {{ display:inline-grid; place-items:center; width:27px; height:27px;
      color:white; background:var(--blue); border-radius:50%; font-size:13px; }}
    label {{ display:block; color:#344157; font-size:13px; font-weight:750; }}
    label small {{ color:#7b8799; font-weight:500; }}
    input {{ width:100%; height:44px; margin-top:7px; padding:0 12px; color:var(--text);
      background:white; border:1px solid #bdc8d8; border-radius:9px;
      font-family:inherit; font-size:15px; font-weight:500; }}
    input:focus {{ outline:3px solid #d5eaff; border-color:var(--blue); }}
    .two-cols,.options-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
    .dates {{ display:flex; flex-wrap:wrap; gap:9px; margin-top:7px; }}
    .date-row {{ display:flex; align-items:center; gap:4px; }}
    .dates input {{ width:185px; margin:0; }}
    .remove-date {{ width:32px; height:32px; color:#8a4a44; background:#f7eceb;
      border:0; border-radius:8px; font-size:20px; line-height:1; }}
    .remove-date:disabled {{ opacity:.35; cursor:not-allowed; }}
    button {{ font-family:inherit; cursor:pointer; }}
    .add-date,.add-route {{ margin-top:10px; padding:9px 12px; color:var(--blue);
      background:#eef6ff; border:0; border-radius:8px; font-weight:750; }}
    .remove {{ color:#a4372f; background:none; border:0; font-weight:700; }}
    .price {{ max-width:250px; margin-top:20px; }}
    .price-input {{ position:relative; }}
    .price-input span {{ position:absolute; top:19px; right:13px; color:#65738a; }}
    .options h2 {{ margin:0 0 17px; font-size:18px; }}
    .actions {{ position:sticky; bottom:0; display:flex; justify-content:flex-end; gap:10px;
      padding:15px 0; background:linear-gradient(transparent,#f5f7fb 25%); }}
    .actions button {{ padding:13px 18px; border-radius:9px; font-weight:800; }}
    .save {{ color:var(--blue); background:white; border:1px solid #a9cbed; }}
    .run {{ color:white; background:var(--blue); border:1px solid var(--blue); }}
    .overlay {{ position:fixed; inset:0; display:none; place-items:center;
      background:rgba(12,18,34,.55); backdrop-filter:blur(8px); z-index:40; padding:20px; }}
    .overlay.open {{ display:grid; }}
    .sheet {{ width:min(440px,100%); color:white; background:#111a30; border-radius:22px;
      padding:28px 26px 22px; box-shadow:0 24px 60px rgba(8,14,30,.35); }}
    .sheet h2 {{ margin:0 0 6px; font-size:22px; }}
    .sheet .live {{ margin:0 0 22px; color:#9eb4d4; font-size:14px; line-height:1.45; min-height:2.6em; }}
    .steps {{ list-style:none; margin:0; padding:0; display:grid; gap:13px; }}
    .steps li {{ display:grid; grid-template-columns:22px 1fr; gap:12px; align-items:center;
      color:#7f90ab; font-weight:650; }}
    .steps li .dot {{ width:14px; height:14px; margin:4px; border-radius:50%;
      border:2px solid #3a4b6a; background:transparent; }}
    .steps li.done {{ color:#d5e7ff; }}
    .steps li.done .dot {{ border-color:#3ecf8e; background:#3ecf8e; }}
    .steps li.current {{ color:white; }}
    .steps li.current .dot {{ border-color:#5aa8ff; background:#5aa8ff;
      box-shadow:0 0 0 6px rgba(90,168,255,.18); animation:pulse 1.4s ease-in-out infinite; }}
    .steps li.error {{ color:#ffc4bc; }}
    .steps li.error .dot {{ border-color:#ff6b5c; background:#ff6b5c; }}
    @keyframes pulse {{ 50% {{ box-shadow:0 0 0 10px rgba(90,168,255,.08); }} }}
    .sheet-actions {{ margin-top:24px; display:none; }}
    .sheet-actions.show {{ display:block; }}
    .sheet-actions a {{ display:block; text-align:center; text-decoration:none;
      color:#111a30; background:white; border-radius:12px; padding:13px;
      font-weight:800; }}
    .sheet-actions button {{ width:100%; color:white; background:#26324a; border:0;
      border-radius:12px; padding:13px; font-weight:800; }}
    @media(max-width:620px) {{
      .two-cols,.options-grid {{ grid-template-columns:1fr; }}
      .dates input {{ width:100%; }} .actions {{ flex-direction:column; }}
    }}
  </style>
</head>
<body>
  <header><a href="/">← Retour aux résultats</a>
    <h1>Préparer une recherche</h1>
    <p>Choisis les trajets et les jours que le bot doit comparer.</p></header>
  <main>{notice}
    <form method="post" action="/settings">
      <div id="searches">{cards}</div>
      <button type="button" class="add-route" onclick="addRoute()">＋ Ajouter un trajet</button>
      <section class="options"><h2>Options</h2><div class="options-grid">
        <!-- <label>Alertes Discord par trajet
          <input type="number" name="max_alerts" min="0"
            value="{instructions.get('max_alerts', 1)}">
        </label> -->
        <label>Nombre maximum de résultats <small>(0 = tous)</small>
          <input type="number" name="max_results" min="0"
            value="{instructions.get('max_results', 0)}">
        </label>
      </div></section>
      <div class="actions">
        <button class="save" name="action" value="save">Enregistrer</button>
        <button class="run" name="action" value="run">Enregistrer et lancer la recherche</button>
      </div>
    </form>
  </main>
  <div class="overlay" id="searchOverlay" role="dialog" aria-modal="true"
    aria-labelledby="searchTitle">
    <div class="sheet">
      <h2 id="searchTitle">Recherche en cours</h2>
      <p class="live" id="searchLive">Préparation de la recherche…</p>
      <ol class="steps" id="searchSteps"></ol>
      <div class="sheet-actions" id="searchActions"></div>
    </div>
  </div>
  <script>
    let nextIndex = {len(searches)};
    function syncDateRemoves(dates) {{
      const buttons = dates.querySelectorAll(".remove-date");
      buttons.forEach(button => {{ button.disabled = buttons.length < 2; }});
    }}
    function addDate(button) {{
      const dates = button.previousElementSibling;
      const row = document.createElement("div");
      row.className = "date-row";
      row.innerHTML = `<input type="date" name="${{dates.dataset.dateName}}" required>
        <button type="button" class="remove-date" onclick="removeDate(this)"
          aria-label="Retirer ce jour">×</button>`;
      dates.appendChild(row);
      syncDateRemoves(dates);
    }}
    function removeDate(button) {{
      const dates = button.closest(".dates");
      if (dates.querySelectorAll(".date-row").length < 2) return;
      button.closest(".date-row").remove();
      syncDateRemoves(dates);
    }}
    document.querySelectorAll(".dates").forEach(syncDateRemoves);
    function removeRoute(button) {{
      if (document.querySelectorAll(".search-card").length > 1)
        button.closest(".search-card").remove();
    }}
    function addRoute() {{
      const index = nextIndex++;
      const section = document.createElement("section");
      section.className = "search-card"; section.dataset.index = index;
      section.innerHTML = `
        <div class="card-head"><h2>Trajet <span>${{index + 1}}</span></h2>
          <button type="button" class="remove" onclick="removeRoute(this)">Supprimer</button></div>
        <div class="two-cols">
          <label>Gare ou ville de départ<input name="origin_${{index}}"
            placeholder="Ex. Le Mans" required></label>
          <label>Destination<input name="destination_${{index}}"
            placeholder="Ex. Bordeaux" required></label>
        </div>
        <label>Jours à comparer</label>
        <div class="dates" data-date-name="dates_${{index}}">
          <div class="date-row"><input type="date" name="dates_${{index}}" required>
            <button type="button" class="remove-date" onclick="removeDate(this)"
              aria-label="Retirer ce jour">×</button></div></div>
        <button type="button" class="add-date" onclick="addDate(this)">＋ Ajouter un jour</button>
        <label class="price">Prix maximum <small>(facultatif)</small>
          <div class="price-input"><input type="number" min="0" step="0.01"
            name="max_price_${{index}}" placeholder="Aucune limite"><span>€</span></div>
        </label>`;
      document.querySelector("#searches").appendChild(section);
      syncDateRemoves(section.querySelector(".dates"));
    }}
    const overlay = document.querySelector("#searchOverlay");
    const live = document.querySelector("#searchLive");
    const stepsEl = document.querySelector("#searchSteps");
    const actions = document.querySelector("#searchActions");
    let poller = null;
    function renderStatus(data) {{
      const steps = data.steps || [];
      const step = Number(data.step || 0);
      const state = data.state || "idle";
      live.textContent = data.error || data.label || "Recherche en cours…";
      stepsEl.innerHTML = steps.map((name, index) => {{
        let cls = "";
        if (state === "error" && index === step) cls = "error";
        else if (state === "done" || index < step) cls = "done";
        else if (index === step) cls = "current";
        return `<li class="${{cls}}"><span class="dot"></span>${{name}}</li>`;
      }}).join("");
      if (state === "done") {{
        document.querySelector("#searchTitle").textContent = "Recherche terminée";
        actions.className = "sheet-actions show";
        actions.innerHTML = '<a href="/">Voir les trains</a>';
        if (poller) clearInterval(poller);
      }} else if (state === "error") {{
        document.querySelector("#searchTitle").textContent = "Recherche interrompue";
        actions.className = "sheet-actions show";
        actions.innerHTML = '<button type="button" id="closeSearch">Fermer</button>';
        document.querySelector("#closeSearch").onclick = () => overlay.classList.remove("open");
        if (poller) clearInterval(poller);
      }} else {{
        document.querySelector("#searchTitle").textContent = "Recherche en cours";
        actions.className = "sheet-actions";
        actions.innerHTML = "";
      }}
    }}
    async function pollStatus() {{
      try {{
        const response = await fetch("/search-status");
        if (!response.ok) return;
        renderStatus(await response.json());
      }} catch (error) {{}}
    }}
    if ({str(watch_search).lower()}) {{
      overlay.classList.add("open");
      pollStatus();
      poller = setInterval(pollStatus, 1200);
    }}
  </script>
</body>
</html>""".encode("utf-8")


def save_settings(parameters: dict[str, list[str]]):
    indices = sorted({
        int(match.group(1))
        for key in parameters
        if (match := re.fullmatch(r"origin_(\d+)", key))
    })
    searches = []
    for index in indices:
        origin = parameters.get(f"origin_{index}", [""])[0].strip()
        destination = parameters.get(f"destination_{index}", [""])[0].strip()
        raw_dates = parameters.get(f"dates_{index}", [])
        dates = []
        for raw_date in raw_dates:
            parsed = date.fromisoformat(raw_date)
            if parsed < date.today():
                raise ValueError(f"La date {raw_date} est déjà passée")
            if raw_date not in dates:
                dates.append(raw_date)
        if not origin or not destination or not dates:
            raise ValueError("Chaque trajet doit avoir un départ, une destination et une date")

        search = {"depart": origin, "destination": destination, "dates": dates}
        raw_max_price = parameters.get(f"max_price_{index}", [""])[0].strip()
        if raw_max_price:
            max_price = float(raw_max_price)
            if max_price < 0:
                raise ValueError("Le prix maximum doit être positif")
            search["prix_max"] = max_price
        searches.append(search)

    if not searches:
        raise ValueError("Ajoute au moins un trajet")
    max_alerts = max(0, int(parameters.get("max_alerts", ["1"])[0]))
    max_results = max(0, int(parameters.get("max_results", ["0"])[0]))
    payload = {
        "site": "https://www.sncf-connect.com",
        "max_resultats": max_results,
        "max_alertes": max_alerts,
        "recherches": searches,
    }
    path = Path(Config.INSTRUCTIONS_FILE)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    temporary.replace(path)


def start_bot() -> bool:
    global RUN_PROCESS
    if RUN_PROCESS and RUN_PROCESS.poll() is None:
        return False
    set_search_status("queued", "La recherche va démarrer", step=0)
    log = (ROOT / "bot-run.log").open("a", encoding="utf-8")
    try:
        RUN_PROCESS = subprocess.Popen(
            [sys.executable, str(ROOT / "main.py")],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        set_search_status(
            "queued",
            "La recherche va démarrer",
            step=0,
            pid=RUN_PROCESS.pid,
        )
    finally:
        log.close()
    return True


class LinkHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed_url = urlparse(self.path)
        path = unquote(parsed_url.path)
        if path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(SERVER_SIGNATURE)
            return
        if path in ("/", "/dashboard"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(render_dashboard())
            return
        if path == "/search-status":
            payload = load_search_status()
            running = bool(
                (RUN_PROCESS and RUN_PROCESS.poll() is None)
                or process_is_alive(payload.get("pid"))
            )
            payload["running"] = running
            if (
                not running
                and payload.get("state") in {
                    "queued", "starting", "opening", "searching", "ranking",
                }
            ):
                payload["state"] = "error"
                payload["error"] = payload.get("error") or "La recherche s'est arrêtée."
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/settings":
            query = parse_qs(parsed_url.query)
            watch_search = "started" in query or "running" in query
            if "started" in query:
                message = "Recherche lancée."
            elif "running" in query:
                message = "Une recherche est déjà en cours."
            elif "saved" in query:
                message = "Configuration enregistrée."
            else:
                message = ""
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(render_settings(message, watch_search=watch_search))
            return

        match = re.fullmatch(r"/offer/([a-f0-9]{20})", path)
        offer = load_offers().get(match.group(1)) if match else None
        if not offer:
            self.send_response(404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(_html_page(
                "Trajet introuvable",
                "Ce trajet n'est plus enregistré par le bot SNCF.",
            ))
            return

        if Config.OPEN_OFFERS_IN_CLIENT:
            target = train_href(offer)
            self.send_response(302)
            self.send_header("Location", target)
            self.end_headers()
            return

        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "open", offer["id"]],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(_html_page(
            "Ouverture du trajet",
            (
                f"Chrome va ouvrir {offer['origin']} → {offer['destination']} "
                f"le {offer['date']} à {offer['departure_time']}. "
                "Valide DataDome dans Chrome s'il apparaît."
            ),
        ))

    def do_POST(self):
        path = unquote(urlparse(self.path).path)
        if path != "/settings":
            self.send_error(404)
            return
        try:
            length = min(int(self.headers.get("Content-Length", "0")), 100_000)
            body = self.rfile.read(length).decode("utf-8")
            parameters = parse_qs(body, keep_blank_values=True)
            save_settings(parameters)
            action = parameters.get("action", ["save"])[0]
            if action == "run":
                target = "/settings?started=1" if start_bot() else "/settings?running=1"
            else:
                target = "/settings?saved=1"
            self.send_response(303)
            self.send_header("Location", target)
            self.end_headers()
        except (ValueError, OSError) as error:
            self.send_response(400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(render_settings(str(error), is_error=True))

    def log_message(self, _format, *_args):
        return


def run_server():
    server = ThreadingHTTPServer(
        (Config.LINK_SERVER_HOST, Config.LINK_SERVER_PORT),
        LinkHandler,
    )
    server.serve_forever()


def _is_challenged(page) -> bool:
    try:
        return (
            "captcha-delivery.com" in page.url
            or page.locator('iframe[title*="captcha" i]').count() > 0
            or page.locator('script[src*="captcha-delivery.com"]').count() > 0
            or "please enable js" in page.locator("body").inner_text().lower()
        )
    except Exception:
        return False


def _wait_for_challenge(page, timeout_seconds: int = 180):
    if not _is_challenged(page):
        return
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        time.sleep(2)
        if not _is_challenged(page):
            return
    raise RuntimeError("Challenge DataDome non validé")


def _accept_cookies(page):
    for button in (
        page.locator(".didomi-continue-without-agreeing"),
        page.locator("#onetrust-accept-btn-handler"),
        page.get_by_role("button", name="Accepter et fermer"),
    ):
        try:
            if button.first.is_visible(timeout=700):
                button.first.click()
                return
        except Exception:
            continue


def _matching_card(page, offer: dict):
    cards = page.locator(
        '[data-test="proposal-card"], [data-testid="proposal-card"]'
    )
    expected_operator = offer["operator"].casefold()
    for index in range(cards.count()):
        card = cards.nth(index)
        text = " ".join(card.inner_text().split()).casefold()
        if (
            offer["departure_time"] in text
            and offer["arrival_time"] in text
            and expected_operator in text
        ):
            return card
    return None


def open_offer(offer_id: str):
    offer = load_offers().get(offer_id)
    if not offer:
        return

    manager = BrowserManager(profile_id="sncf-booking")
    page = manager.start()
    try:
        page.goto(
            "https://www.sncf-connect.com/home/search/od",
            wait_until="domcontentloaded",
            timeout=60000,
        )
        _wait_for_challenge(page)
        _accept_cookies(page)
        search_journeys(page, {
            "origin": offer["origin"],
            "destination": offer["destination"],
            "date": offer["date"],
        })
        _wait_for_challenge(page)

        card = None
        for _ in range(12):
            card = _matching_card(page, offer)
            if card:
                break
            next_button = page.get_by_role(
                "button",
                name=re.compile(r"afficher les trajets suivants", re.I),
            )
            if (
                next_button.count() == 0
                or not next_button.first.is_visible(timeout=700)
                or not next_button.first.is_enabled()
            ):
                break
            next_button.first.click()
            page.wait_for_timeout(1300)

        if card:
            card.scroll_into_view_if_needed()
            fare = card.locator('button[data-test="offer-card-button"]').first
            if fare.count() and fare.is_visible():
                fare.click()
        while not page.is_closed():
            time.sleep(1)
    finally:
        manager.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("serve", "open"))
    parser.add_argument("offer_id", nargs="?")
    args = parser.parse_args()
    if args.command == "serve":
        run_server()
    elif args.offer_id:
        open_offer(args.offer_id)


if __name__ == "__main__":
    main()
