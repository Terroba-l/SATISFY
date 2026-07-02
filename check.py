#!/usr/bin/env python3
"""SATISFY restock monitor.

Vérifie la disponibilité (par variante) d'un ou plusieurs produits Shopify et
envoie une notification ntfy.sh uniquement lors d'une transition
indisponible -> disponible (restock).

Dépendance externe unique : `requests`.

Configuration via variables d'environnement :

    PRODUCT_URLS   URLs produit séparées par des virgules.
                   Défaut : le HeatCrush Muscle Tee (Moonstruck).
    NTFY_TOPIC     Topic ntfy.sh où poster les alertes (ex: "mon-topic-secret").
                   Sans lui, aucune notification n'est envoyée (dry-run).
    NTFY_SERVER    Serveur ntfy. Défaut : https://ntfy.sh
    NTFY_TOKEN     Jeton d'auth ntfy optionnel (Bearer) pour topics protégés.
    STATE_FILE     Chemin du fichier d'état. Défaut : state.json
    USER_AGENT     User-Agent HTTP. Défaut : un UA navigateur générique.

Le script écrit/actualise STATE_FILE ; ce fichier est commité dans le repo par
le workflow GitHub Actions pour conserver l'état entre deux exécutions.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

import requests

DEFAULT_PRODUCT_URL = (
    "https://satisfyrunning.com/products/heatcrush-muscle-tee-moonstruck"
)
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
REQUEST_TIMEOUT = 20
# Petit délai poli entre deux requêtes vers le même hôte.
POLITE_DELAY = 1.0

# Regex de dernier recours sur le HTML : "available":true / "available":false
AVAILABLE_RE = re.compile(r'"available"\s*:\s*(true|false)', re.IGNORECASE)


def log(msg: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    print(f"[{stamp}] {msg}", flush=True)


def normalize_product_url(url: str) -> str:
    """Retire toute extension .js/.json et les query/fragments d'une URL produit."""
    parts = urlsplit(url.strip())
    path = parts.path
    for suffix in (".js", ".json"):
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break
    return urlunsplit((parts.scheme, parts.netloc, path.rstrip("/"), "", ""))


def variant_available_key(product_handle: str, variant_id, variant_title: str) -> str:
    """Clé stable identifiant une variante dans state.json."""
    vid = variant_id if variant_id is not None else variant_title
    return f"{product_handle}::{vid}"


def product_handle_from_url(url: str) -> str:
    parts = urlsplit(url)
    segments = [s for s in parts.path.split("/") if s]
    handle = segments[-1] if segments else parts.netloc
    return handle


def fetch(session: requests.Session, url: str) -> requests.Response | None:
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        log(f"  requête échouée sur {url} : {exc}")
        return None
    if resp.status_code != 200:
        log(f"  {url} -> HTTP {resp.status_code}")
        return None
    return resp


def parse_variants_from_js(data: dict) -> list[dict]:
    """`{url}.js` renvoie directement l'objet produit Shopify."""
    variants = data.get("variants")
    if not isinstance(variants, list):
        return []
    return _normalize_variants(variants)


def parse_variants_from_json(data: dict) -> list[dict]:
    """`{url}.json` renvoie `{"product": {...}}`."""
    product = data.get("product")
    if not isinstance(product, dict):
        return []
    variants = product.get("variants")
    if not isinstance(variants, list):
        return []
    return _normalize_variants(variants)


def _normalize_variants(raw_variants: list) -> list[dict]:
    out = []
    for v in raw_variants:
        if not isinstance(v, dict):
            continue
        out.append(
            {
                "id": v.get("id"),
                "title": v.get("title") or v.get("public_title") or "Default",
                "available": bool(v.get("available")),
            }
        )
    return out


def parse_variants_from_html(html: str) -> list[dict]:
    """Dernier recours : on scanne le HTML pour "available":true/false.

    Impossible d'isoler chaque variante de façon fiable en HTML brut : on
    produit une seule variante synthétique « (page) » considérée disponible dès
    qu'au moins une occurrence `"available":true` est présente.
    """
    matches = AVAILABLE_RE.findall(html)
    if not matches:
        return []
    any_available = any(m.lower() == "true" for m in matches)
    return [{"id": None, "title": "(page)", "available": any_available}]


def check_product(session: requests.Session, product_url: str) -> list[dict] | None:
    """Retourne la liste des variantes via la cascade .js -> .json -> HTML.

    Renvoie None si les trois méthodes échouent (erreur réseau/format), ce qui
    permet de ne PAS écraser l'état connu par de fausses "indisponibilités".
    """
    handle = product_handle_from_url(product_url)

    # 1) {url}.js
    resp = fetch(session, product_url + ".js")
    if resp is not None:
        try:
            variants = parse_variants_from_js(resp.json())
            if variants:
                log(f"  source .js : {len(variants)} variante(s)")
                return _attach_meta(handle, product_url, variants)
        except ValueError:
            log("  .js : JSON invalide, on passe à .json")

    time.sleep(POLITE_DELAY)

    # 2) {url}.json
    resp = fetch(session, product_url + ".json")
    if resp is not None:
        try:
            variants = parse_variants_from_json(resp.json())
            if variants:
                log(f"  source .json : {len(variants)} variante(s)")
                return _attach_meta(handle, product_url, variants)
        except ValueError:
            log("  .json : JSON invalide, on passe au HTML")

    time.sleep(POLITE_DELAY)

    # 3) HTML brut + regex
    resp = fetch(session, product_url)
    if resp is not None:
        variants = parse_variants_from_html(resp.text)
        if variants:
            log(f"  source HTML : {len(variants)} variante(s) (regex)")
            return _attach_meta(handle, product_url, variants)

    log("  aucune méthode n'a fonctionné pour ce produit")
    return None


def _attach_meta(handle: str, product_url: str, variants: list[dict]) -> list[dict]:
    for v in variants:
        v["handle"] = handle
        v["product_url"] = product_url
        v["key"] = variant_available_key(handle, v["id"], v["title"])
    return variants


def load_state(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        log(f"état illisible ({exc}), on repart d'un état vide")
        return {}
    return data if isinstance(data, dict) else {}


def save_state(path: str, state: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


def send_ntfy(server: str, topic: str, token: str | None, *, title: str,
              message: str, click: str, tags: str, priority: str) -> bool:
    url = f"{server.rstrip('/')}/{topic}"
    headers = {
        "Title": title.encode("utf-8"),
        "Click": click,
        "Tags": tags,
        "Priority": priority,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        resp = requests.post(
            url,
            data=message.encode("utf-8"),
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        log(f"  échec envoi ntfy : {exc}")
        return False
    if resp.status_code >= 300:
        log(f"  ntfy a répondu HTTP {resp.status_code} : {resp.text[:200]}")
        return False
    return True


def main() -> int:
    raw_urls = os.environ.get("PRODUCT_URLS", DEFAULT_PRODUCT_URL)
    product_urls = [normalize_product_url(u) for u in raw_urls.split(",") if u.strip()]
    if not product_urls:
        log("Aucune URL produit configurée (PRODUCT_URLS). Abandon.")
        return 1

    state_file = os.environ.get("STATE_FILE", "state.json")
    ntfy_topic = os.environ.get("NTFY_TOPIC", "").strip()
    ntfy_server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").strip()
    ntfy_token = os.environ.get("NTFY_TOKEN", "").strip() or None
    user_agent = os.environ.get("USER_AGENT", DEFAULT_USER_AGENT)

    if not ntfy_topic:
        log("NTFY_TOPIC non défini : mode dry-run (aucune notification envoyée).")

    session = requests.Session()
    session.headers.update({"User-Agent": user_agent, "Accept": "*/*"})

    state = load_state(state_file)
    # Nouvel état construit à partir de l'ancien pour conserver les produits non
    # vérifiés cette fois-ci (ex: erreur réseau ponctuelle).
    new_state = dict(state)

    restocks = []  # transitions indisponible -> disponible

    for product_url in product_urls:
        log(f"Vérification : {product_url}")
        variants = check_product(session, product_url)
        if variants is None:
            # Échec total : on garde l'ancien état inchangé pour ce produit.
            continue

        for v in variants:
            key = v["key"]
            available = v["available"]
            previous = state.get(key)
            prev_available = previous.get("available") if isinstance(previous, dict) else None

            status = "DISPO" if available else "indispo"
            log(f"    [{status}] {v['handle']} / {v['title']}")

            # Alerte uniquement sur transition explicite False -> True.
            if prev_available is False and available is True:
                restocks.append(v)

            new_state[key] = {
                "handle": v["handle"],
                "title": v["title"],
                "product_url": v["product_url"],
                "available": available,
                "last_checked": datetime.now(timezone.utc).isoformat(),
            }

        time.sleep(POLITE_DELAY)

    # Notifications
    if restocks:
        log(f"{len(restocks)} restock(s) détecté(s).")
        for v in restocks:
            title = "🟢 RESTOCK SATISFY"
            message = f"{v['handle']} — {v['title']} est de nouveau DISPONIBLE !"
            log(f"  ALERTE : {message}")
            if ntfy_topic:
                ok = send_ntfy(
                    ntfy_server,
                    ntfy_topic,
                    ntfy_token,
                    title=title,
                    message=message,
                    click=v["product_url"],
                    tags="shopping,tshirt,green_circle",
                    priority="5",
                )
                if not ok:
                    log("  (notification non délivrée)")
    else:
        log("Aucune nouvelle disponibilité (pas d'alerte).")

    save_state(state_file, new_state)
    log(f"État enregistré dans {state_file} ({len(new_state)} variante(s) suivie(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
