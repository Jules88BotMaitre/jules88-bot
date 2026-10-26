"""
Script de correction typographique — fr.vikidia.org ET en.vikidia.org

- Surveillance des modifications de l'espace principal.
- Attente de 120 minutes après la dernière modification.
- Redémarrage du délai si la page est modifiée.
- Protection des URL, liens, modèles, infobox et balises protégées.
- Fonctionnement en parallèle sur les deux wikis.
- Pause/reprise contrôlée par scripts_auto_control.py via /scripts_auto.
"""

import os
import re
import time
import threading
from datetime import datetime, timezone

import requests
import mwparserfromhell
from scripts_auto_control import wait_until_enabled, wait_or_disabled


# ===========================================================================
# CONFIGURATION
# ===========================================================================

WAIT_AFTER_LAST_EDIT_SECONDS = 60 * 120
WATCH_INTERVAL_SECONDS = 30
EDIT_PAUSE_SECONDS = 999999999

NBSP = "\u00A0"

SITES = [
    {
        "nom": "fr",
        "lang": "fr",
        "api_url": "https://fr.vikidia.org/w/api.php",
        "user_agent": "Jules88!!Bot/typo-fix (fr.vikidia.org)",
        "username": os.getenv("VIKIDIA_BOT_USERNAME_FR"),
        "password": os.getenv("VIKIDIA_BOT_PASSWORD_FR"),
        "summary": (
            "Correction typographique automatique "
            "(espaces, ponctuation) — liens et modèles protégés [bot]"
        ),
    },
    {
        "nom": "en",
        "lang": "en",
        "api_url": "https://en.vikidia.org/w/api.php",
        "user_agent": "Jules88!!Bot/typo-fix (en.vikidia.org)",
        "username": os.getenv("VIKIDIA_BOT_USERNAME_EN"),
        "password": os.getenv("VIKIDIA_BOT_PASSWORD_EN"),
        "summary": (
            "Automatic typo fix (spacing, punctuation) — "
            "links and templates protected [bot]"
        ),
    },
]


# ===========================================================================
# 1. RÈGLES TYPOGRAPHIQUES
# ===========================================================================

COMMON_TYPO_RULES = [
    # Espaces multiples.
    (re.compile(r"[ \t]{2,}"), " "),

    # Espaces avant virgules et points.
    (re.compile(r"[ \t\u00A0]+([,.])"), r"\1"),

    # Espaces autour des parenthèses.
    (re.compile(r"\( +"), "( "),
    (re.compile(r" +\)"), " )"),

    # Espace après la ponctuation, sans modifier les décimales.
    (re.compile(r"([,.;:!?]) {2,}(?=[A-Za-zÀ-ÿ])"), r"\1 "),

    # Espaces en fin de ligne.
    (re.compile(r"[ \t]+\n"), "\n"),

    # Maximum deux sauts de ligne.
    (re.compile(r"\n{3,}"), "\n\n"),
]

_PUNCT_RUN = re.compile(r"[ \t\u00A0]*([;:!?]+)")

_FR_PUNCT_RUN = re.compile(r"(?<=[a-zA-Z0-9À-ÿ\)])[\t ]*([;:!?]+)")

FR_PUNCT_RULE = (
    _FR_PUNCT_RUN,
    NBSP + r"\1",
)

FR_GUILLEMETS_RULE = (
    re.compile(r"«[ \t\u00A0]*([^»\n]+?)[ \t\u00A0]*»"),
    r'{{"|\1}}',
)

EN_PUNCT_RULE = (
    _PUNCT_RUN,
    r"\1",
)

LANG_PUNCT_RULES = {
    "fr": [
        FR_PUNCT_RULE,
        FR_GUILLEMETS_RULE,
    ],
    "en": [
        EN_PUNCT_RULE,
    ],
}


# ===========================================================================
# 2. PROTECTION DES URL
# ===========================================================================

URL_PATTERN = re.compile(r"(?i)\b(?:https?://|ftp://|www\.)[^\s<>\[\]{}|]+")


def protect_urls(text: str):
    """Remplace temporairement les URL par des marqueurs et les restitue ensuite."""
    urls = []

    def replace_url(match):
        url = match.group(0)
        trailing = ""

        # La ponctuation finale d'une phrase n'est généralement pas dans l'URL.
        while url and url[-1] in ".,;:!?":
            trailing = url[-1] + trailing
            url = url[:-1]

        # Garde une parenthèse fermante de phrase hors de l'URL si nécessaire.
        while url.endswith(")") and url.count("(") < url.count(")"):
            trailing = ")" + trailing
            url = url[:-1]

        index = len(urls)
        urls.append(url)
        return f"ZZURLTOKEN{index}ZZ{trailing}"

    return URL_PATTERN.sub(replace_url, text), urls


def restore_urls(text: str, urls: list[str]) -> str:
    """Restaure les URL exactement comme elles étaient."""
    for index, url in enumerate(urls):
        text = text.replace(f"ZZURLTOKEN{index}ZZ", url)
    return text


def fix_typo_in_text(text: str, lang: str) -> str:
    """Applique les règles au texte ordinaire sans modifier les URL."""
    text, urls = protect_urls(text)

    for pattern, replacement in COMMON_TYPO_RULES:
        text = pattern.sub(replacement, text)

    for pattern, replacement in LANG_PUNCT_RULES.get(lang, []):
        text = pattern.sub(replacement, text)

    return restore_urls(text, urls)


def contains_url(text: str) -> bool:
    return bool(URL_PATTERN.search(text))


# ===========================================================================
# 3. PROTECTION DU WIKITEXTE
# ===========================================================================

def _process_wikicode(code: "mwparserfromhell.wikicode.Wikicode", lang: str) -> str:
    """Corrige le texte ordinaire et conserve les structures protégées."""
    parts = []

    for node in code.nodes:
        if isinstance(node, mwparserfromhell.nodes.Template):
            parts.append(str(node))

        elif isinstance(node, mwparserfromhell.nodes.Tag):
            parts.append(str(node))

        elif isinstance(node, mwparserfromhell.nodes.Comment):
            parts.append(str(node))

        elif isinstance(node, mwparserfromhell.nodes.Wikilink):
            original = str(node)
            target = str(node.title).strip()
            target_lower = target.lower()

            if contains_url(original):
                parts.append(original)
                continue

            if target_lower.startswith((
                "file:", "fichier:", "image:", "category:", "catégorie:"
            )):
                parts.append(original)
                continue

            if node.text is None:
                parts.append(original)
                continue

            fixed_text = fix_typo_in_text(str(node.text), lang)
            parts.append(f"[[{target}|{fixed_text}]]")

        elif isinstance(node, mwparserfromhell.nodes.ExternalLink):
            # Conserve intégralement les liens externes, y compris leur URL.
            parts.append(str(node))

        elif isinstance(node, mwparserfromhell.nodes.Heading):
            fixed_title = _process_wikicode(node.title, lang)
            eq = "=" * node.level
            parts.append(f"{eq} {fixed_title.strip()} {eq}")

        elif isinstance(node, mwparserfromhell.nodes.Text):
            parts.append(fix_typo_in_text(str(node.value), lang))

        else:
            parts.append(str(node))

    return "".join(parts)


def clean_wikitext(wikitext: str, lang: str) -> tuple[str, bool]:
    """Retourne le nouveau texte et indique s'il a changé."""
    code = mwparserfromhell.parse(wikitext)
    new_wikitext = _process_wikicode(code, lang)
    return new_wikitext, new_wikitext != wikitext


# ===========================================================================
# 4. DATES
# ===========================================================================

def parse_mediawiki_timestamp(timestamp: str) -> float:
    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    return dt.timestamp()


def current_utc_timestamp() -> float:
    return datetime.now(timezone.utc).timestamp()


def timestamp_to_iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ===========================================================================
# 5. CONNEXION
# ===========================================================================

def login(
    session: requests.Session,
    api_url: str,
    user_agent: str,
    username: str,
    password: str,
    nom_site: str,
) -> None:
    if not username or not password:
        raise RuntimeError(f"Identifiants manquants pour le site {nom_site}.")

    headers = {"User-Agent": user_agent}
    response = session.get(
        api_url,
        params={
            "action": "query",
            "meta": "tokens",
            "type": "login",
            "format": "json",
        },
        headers=headers,
        timeout=30,
    )
    response.raise_for_status()
    login_token = response.json()["query"]["tokens"]["logintoken"]

    response = session.post(
        api_url,
        data={
            "action": "login",
            "lgname": username,
            "lgpassword": password,
            "lgtoken": login_token,
            "format": "json",
        },
        headers=headers,
        timeout=30,
    )
    response.raise_for_status()
    result = response.json().get("login", {})

    if result.get("result") != "Success":
        raise RuntimeError(f"Échec de connexion sur {nom_site} : {result}")

    print(f"[typo-{nom_site}] Connecté en tant que {username}")


# ===========================================================================
# 6. RÉCUPÉRATION DU WIKITEXTE
# ===========================================================================

def get_wikitext(
    session: requests.Session,
    api_url: str,
    user_agent: str,
    title: str,
) -> tuple[str, str]:
    response = session.get(
        api_url,
        params={
            "action": "query",
            "prop": "revisions",
            "rvprop": "content|timestamp",
            "rvslots": "main",
            "titles": title,
            "format": "json",
            "formatversion": "2",
        },
        headers={"User-Agent": user_agent},
        timeout=30,
    )
    response.raise_for_status()
    pages = response.json()["query"]["pages"]

    if not pages:
        raise RuntimeError(f"Page introuvable : {title}")

    page = pages[0]
    if "missing" in page:
        raise RuntimeError(f"Page introuvable : {title}")

    revisions = page.get("revisions", [])
    if not revisions:
        raise RuntimeError(f"Aucune révision trouvée pour : {title}")

    revision = revisions[0]
    return revision["slots"]["main"]["content"], revision["timestamp"]


# ===========================================================================
# 7. TOKEN CSRF
# ===========================================================================

def get_csrf_token(
    session: requests.Session,
    api_url: str,
    user_agent: str,
) -> str:
    response = session.get(
        api_url,
        params={"action": "query", "meta": "tokens", "format": "json"},
        headers={"User-Agent": user_agent},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["query"]["tokens"]["csrftoken"]


# ===========================================================================
# 8. SAUVEGARDE
# ===========================================================================

def save_wikitext(
    session: requests.Session,
    api_url: str,
    user_agent: str,
    title: str,
    text: str,
    summary: str,
    base_timestamp: str,
) -> None:
    token = get_csrf_token(session, api_url, user_agent)
    response = session.post(
        api_url,
        data={
            "action": "edit",
            "title": title,
            "text": text,
            "summary": summary,
            "token": token,
            "bot": True,
            "basetimestamp": base_timestamp,
            "format": "json",
        },
        headers={"User-Agent": user_agent},
        timeout=30,
    )
    response.raise_for_status()
    result = response.json()

    if "error" in result:
        raise RuntimeError(f"Erreur d'édition sur {title} : {result['error']}")

    if result.get("edit", {}).get("result") != "Success":
        raise RuntimeError(f"Édition non effectuée sur {title} : {result}")


# ===========================================================================
# 9. MODIFICATIONS RÉCENTES
# ===========================================================================

def get_recent_article_changes(
    session: requests.Session,
    api_url: str,
    user_agent: str,
    since_iso: str,
    own_username: str,
) -> list[dict]:
    changes = []
    params = {
        "action": "query",
        "list": "recentchanges",
        "rcprop": "title|timestamp|user",
        "rcstart": since_iso,
        "rcdir": "newer",
        "rcnamespace": 0,
        "rclimit": 50,
        "rctype": "edit|new",
        "format": "json",
    }

    while True:
        response = session.get(
            api_url,
            params=params,
            headers={"User-Agent": user_agent},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        batch = data.get("query", {}).get("recentchanges", [])
        for change in batch:
            username = change.get("user", "")
            if own_username and username == own_username:
                continue
            changes.append({
                "title": change["title"],
                "timestamp": change["timestamp"],
                "user": username,
            })

        if "continue" not in data:
            break
        params.update(data["continue"])

    return changes


# ===========================================================================
# 10. SURVEILLANCE D'UN SITE
# ===========================================================================

def watch_and_fix_typo_site(config: dict) -> None:
    nom_site = config["nom"]
    lang = config["lang"]
    api_url = config["api_url"]
    user_agent = config["user_agent"]
    username = config["username"]
    password = config["password"]
    summary = config["summary"]

    if not username or not password:
        print(f"[typo-{nom_site}] Identifiants manquants, site non surveillé.")
        return

    session = requests.Session()
    try:
        login(session, api_url, user_agent, username, password, nom_site)
    except Exception as error:
        print(f"[typo-{nom_site}] Erreur de connexion : {error}")
        return

    pending_pages = {}
    last_check_timestamp = current_utc_timestamp()
    last_check_iso = timestamp_to_iso(last_check_timestamp)

    print(f"[typo-{nom_site}] Surveillance démarrée.")
    print(
        f"[typo-{nom_site}] Délai : "
        f"{WAIT_AFTER_LAST_EDIT_SECONDS // 60} minutes."
    )

    while True:
        # Pause globale : le cycle ne reprend qu'après réactivation.
        wait_until_enabled()

        try:
            now = current_utc_timestamp()
            now_iso = timestamp_to_iso(now)
            changes = get_recent_article_changes(
                session, api_url, user_agent, last_check_iso, username
            )
            last_check_iso = now_iso

            for change in changes:
                title = change["title"]
                timestamp = parse_mediawiki_timestamp(change["timestamp"])
                old_timestamp = pending_pages.get(title)

                if old_timestamp is None or timestamp > old_timestamp:
                    pending_pages[title] = timestamp
                    print(
                        f"[typo-{nom_site}] En attente : {title} "
                        f"(dernière modification : {change['timestamp']})"
                    )

            current_time = current_utc_timestamp()
            pages_ready = [
                title
                for title, last_edit in pending_pages.items()
                if current_time - last_edit >= WAIT_AFTER_LAST_EDIT_SECONDS
            ]

            for title in pages_ready:
                # Empêche de commencer la page suivante si le script est désactivé.
                wait_until_enabled()

                try:
                    wikitext, revision_timestamp = get_wikitext(
                        session, api_url, user_agent, title
                    )
                    revision_unix = parse_mediawiki_timestamp(revision_timestamp)
                    last_known_edit = pending_pages.get(title)

                    if last_known_edit is not None and revision_unix > last_known_edit:
                        pending_pages[title] = revision_unix
                        print(
                            f"[typo-{nom_site}] Nouvelle modification : "
                            f"{title}. Délai relancé."
                        )
                        continue

                    new_wikitext, changed = clean_wikitext(wikitext, lang)
                    if not changed:
                        print(f"[typo-{nom_site}] Rien à corriger : {title}")
                        pending_pages.pop(title, None)
                        continue

                    # Vérifie à nouveau juste avant de modifier Vikidia.
                    wait_until_enabled()
                    save_wikitext(
                        session,
                        api_url,
                        user_agent,
                        title,
                        new_wikitext,
                        summary,
                        revision_timestamp,
                    )
                    print(f"[typo-{nom_site}] Corrigé : {title}")
                    pending_pages.pop(title, None)

                    # Cette longue pause devient interruptible par /scripts_auto.
                    if not wait_or_disabled(EDIT_PAUSE_SECONDS):
                        wait_until_enabled()

                except Exception as error:
                    error_text = str(error)
                    print(f"[typo-{nom_site}] Erreur pour {title} : {error_text}")
                    if "editconflict" in error_text.lower():
                        pending_pages[title] = current_utc_timestamp()

            current_time = current_utc_timestamp()
            for title, last_edit in list(pending_pages.items()):
                remaining = WAIT_AFTER_LAST_EDIT_SECONDS - (current_time - last_edit)
                if remaining > 0:
                    print(
                        f"[typo-{nom_site}] {title} : "
                        f"encore environ {int(remaining // 60)} min."
                    )

        except Exception as error:
            print(f"[typo-{nom_site}] Erreur dans la boucle : {error}")

        # Attend 30 secondes au maximum, mais se réveille si on désactive le script.
        wait_or_disabled(WATCH_INTERVAL_SECONDS)


# ===========================================================================
# 11. LANCEMENT DES DEUX SITES
# ===========================================================================

def watch_and_fix_typo() -> None:
    threads = []
    for config in SITES:
        thread = threading.Thread(
            target=watch_and_fix_typo_site,
            args=(config,),
            daemon=True,
        )
        thread.start()
        threads.append(thread)

    for thread in threads:
        thread.join()


if __name__ == "__main__":
    watch_and_fix_typo()
