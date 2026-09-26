"""
Script de correction typographique — fr.vikidia.org ET en.vikidia.org

Objectif : corriger la typographie du texte visible d'une page (espaces doubles,
espaces avant ponctuation, espaces manquants après ponctuation, etc.) SANS toucher
au contenu des modèles ({{...}}), y compris les infobox, ni aux liens internes/
fichiers, commentaires HTML, balises <nowiki>/<pre>/<code>, etc.

Principe : on parse le wikitexte avec mwparserfromhell, on isole tout ce qui n'est
pas du texte brut (modèles, tags, liens, commentaires) en le remplaçant par des
"jetons" temporaires, on corrige la typo sur ce qui reste, puis on réinjecte les
jetons. Ainsi le nombre de correction ne "compte" pas ce qu'il y a dans les
modèles/infobox : leur contenu ressort strictement identique.

Ce script tourne en tâche de fond sur KataBump (un thread par site, comme
bienvenue.py) et surveille les deux Vikidia en parallèle. Le résumé de
modification est adapté à la langue du site : français sur fr.vikidia.org,
anglais sur en.vikidia.org.
"""

import os
import re
import time
import threading
import requests
import mwparserfromhell

WATCH_INTERVAL_SECONDS = 30  # fréquence de vérification des modifications récentes
EDIT_PAUSE_SECONDS = 60      # pause de sécurité entre deux corrections effectives

# ---------------------------------------------------------------------------
# Configuration des sites à surveiller (identifiants + résumé dans la bonne langue)
# ---------------------------------------------------------------------------
SITES = [
    {
        "nom": "fr",
        "api_url": "https://fr.vikidia.org/w/api.php",
        "user_agent": "Jules88!!Bot/typo-fix (fr.vikidia.org)",
        "username": os.getenv("VIKIDIA_BOT_USERNAME_FR"),
        "password": os.getenv("VIKIDIA_BOT_PASSWORD_FR"),
        "summary": "Correction typographique automatique (espaces, ponctuation) — "
                   "modèles et infobox non modifiés [bot]",
    },
    {
        "nom": "en",
        "api_url": "https://en.vikidia.org/w/api.php",
        "user_agent": "Jules88!!Bot/typo-fix (en.vikidia.org)",
        "username": os.getenv("VIKIDIA_EN_BOT_USERNAME"),
        "password": os.getenv("VIKIDIA_EN_BOT_PASSWORD"),
        "summary": "Automatic typo fix (spacing, punctuation) — "
                   "templates and infoboxes left unchanged [bot]",
    },
]

# ---------------------------------------------------------------------------
# 1. Règles de correction typographique (texte brut uniquement)
# ---------------------------------------------------------------------------
# Chaque règle : (regex compilée, remplacement). L'ordre compte.
TYPO_RULES = [
    # Espaces doubles (ou plus) -> un seul espace
    (re.compile(r"[ \t]{2,}"), " "),
    # Espace avant une virgule / point / point-virgule -> supprimé
    (re.compile(r" +([,.;])"), r"\1"),
    # Espace avant ! ou ? -> supprimé (typographie anglaise ; pas d'espace
    # insécable avant ! ? sur en.vikidia contrairement à fr.vikidia)
    (re.compile(r" +([!?])"), r"\1"),
    # Pas d'espace après une parenthèse ouvrante / avant une fermante
    (re.compile(r"\( +"), "("),
    (re.compile(r" +\)"), ")"),
    # Espace manquant après , . ; ! ? quand suivi directement d'une lettre
    # (mais pas d'un chiffre, pour ne pas casser 1,5 ou une abréviation type "p.ex")
    (re.compile(r"([,.;!?])(?=[A-Za-z])"), r"\1 "),
    # Espaces en fin de ligne
    (re.compile(r"[ \t]+\n"), "\n"),
    # Plus de 2 sauts de ligne consécutifs -> 2 (un seul paragraphe vide max)
    (re.compile(r"\n{3,}"), "\n\n"),
]


def fix_typo_in_text(text: str) -> str:
    """Applique les règles de typo à un morceau de texte brut."""
    for pattern, repl in TYPO_RULES:
        text = pattern.sub(repl, text)
    return text


# ---------------------------------------------------------------------------
# 2. Isolation des zones à ne PAS toucher (modèles/infobox, tags, liens, etc.)
# ---------------------------------------------------------------------------
def _process_wikicode(code: "mwparserfromhell.wikicode.Wikicode") -> str:
    """
    Reconstruit une chaîne à partir d'un objet Wikicode en ne corrigeant que le
    texte visible, niveau par niveau (jamais en mode récursif "à plat" : c'est
    ce qui garantissait auparavant, à tort, que le texte À L'INTÉRIEUR d'un
    modèle protégé était quand même retouché — mwparserfromhell.filter(recursive=True)
    renvoie aussi les nœuds Texte imbriqués dans les modèles/liens, indépendamment
    du nœud parent).

    Ici, on ne parcourt que les nœuds de premier niveau de chaque objet Wikicode
    (node.nodes, non récursif), et on ne redescend manuellement QUE dans les
    titres de section (Heading), le seul cas où du texte visible peut être
    imbriqué en dehors d'un modèle/tag/lien.
    """
    parts = []
    for node in code.nodes:
        if isinstance(node, mwparserfromhell.nodes.Template):
            # Modèle entier (donc infobox) : protégé tel quel, rien à l'intérieur
            # n'est modifié.
            parts.append(str(node))

        elif isinstance(node, mwparserfromhell.nodes.Tag):
            # Balises (ref, nowiki, pre, code, math, etc.) : protégées telles
            # quelles, contenu inclus.
            parts.append(str(node))

        elif isinstance(node, mwparserfromhell.nodes.Comment):
            parts.append(str(node))

        elif isinstance(node, mwparserfromhell.nodes.Wikilink):
            target = str(node.title).strip().lower()
            if target.startswith(("file:", "image:", "category:")) or node.text is None:
                # Fichiers/catégories/liens sans texte affiché : protégés en entier.
                parts.append(str(node))
            else:
                # Page/mot cible jamais touché ; seul le texte affiché est corrigé.
                fixed_text = fix_typo_in_text(str(node.text))
                parts.append(f"[[{node.title}|{fixed_text}]]")

        elif isinstance(node, mwparserfromhell.nodes.ExternalLink):
            if node.title is not None:
                fixed_title = fix_typo_in_text(str(node.title))
                bracket_open = "[" if node.brackets else ""
                bracket_close = "]" if node.brackets else ""
                parts.append(f"{bracket_open}{node.url} {fixed_title}{bracket_close}")
            else:
                parts.append(str(node))

        elif isinstance(node, mwparserfromhell.nodes.Heading):
            fixed_title = _process_wikicode(node.title)
            parts.append("=" * node.level + fixed_title + "=" * node.level)

        elif isinstance(node, mwparserfromhell.nodes.Text):
            parts.append(fix_typo_in_text(str(node.value)))

        else:
            # Argument, HTMLEntity, ou tout nœud non prévu : protégé par défaut.
            parts.append(str(node))

    return "".join(parts)


def clean_wikitext(wikitext: str) -> tuple[str, bool]:
    """
    Corrige la typo du texte visible d'une page sans modifier :
    - les modèles {{...}} (donc les infobox, qui sont des modèles sur Vikidia)
    - le contenu des liens fichiers/catégories [[File:...]] (nom, légende compris)
    - la cible des liens internes [[Page|texte]] (seul "texte" est corrigé)
    - le contenu des balises <nowiki>, <pre>, <code>, <math>, <ref>...</ref>
    - les commentaires HTML <!-- ... -->
    - les URL des liens externes (seul le texte affiché est corrigé)

    Retourne (nouveau_wikitexte, a_change).
    """
    code = mwparserfromhell.parse(wikitext)
    new_wikitext = _process_wikicode(code)
    return new_wikitext, new_wikitext != wikitext


# ---------------------------------------------------------------------------
# 3. Connexion / récupération / sauvegarde du wikitexte (paramétrées par site)
# ---------------------------------------------------------------------------
def login(session: requests.Session, api_url: str, user_agent: str, username: str, password: str, nom_site: str) -> None:
    if not username or not password:
        raise RuntimeError(f"Identifiants manquants pour le site {nom_site} dans le .env")

    r = session.get(
        api_url,
        params={"action": "query", "meta": "tokens", "type": "login", "format": "json"},
        headers={"User-Agent": user_agent},
    )
    login_token = r.json()["query"]["tokens"]["logintoken"]

    r = session.post(
        api_url,
        data={
            "action": "login",
            "lgname": username,
            "lgpassword": password,
            "lgtoken": login_token,
            "format": "json",
        },
        headers={"User-Agent": user_agent},
    )
    result = r.json().get("login", {})
    if result.get("result") != "Success":
        raise RuntimeError(f"Échec de connexion sur {nom_site} : {result}")
    print(f"[typo-{nom_site}] ✅ Connecté en tant que {username}")


def get_wikitext(session: requests.Session, api_url: str, user_agent: str, title: str) -> tuple[str, str]:
    """Retourne (wikitexte, revision_timestamp) de la page."""
    params = {
        "action": "query",
        "prop": "revisions",
        "rvprop": "content|timestamp",
        "rvslots": "main",
        "titles": title,
        "format": "json",
        "formatversion": "2",
    }
    r = session.get(api_url, params=params, headers={"User-Agent": user_agent})
    r.raise_for_status()
    page = r.json()["query"]["pages"][0]
    rev = page["revisions"][0]
    return rev["slots"]["main"]["content"], rev["timestamp"]


def get_csrf_token(session: requests.Session, api_url: str, user_agent: str) -> str:
    params = {"action": "query", "meta": "tokens", "format": "json"}
    r = session.get(api_url, params=params, headers={"User-Agent": user_agent})
    return r.json()["query"]["tokens"]["csrftoken"]


def save_wikitext(session: requests.Session, api_url: str, user_agent: str, title: str, text: str, summary: str) -> None:
    token = get_csrf_token(session, api_url, user_agent)
    data = {
        "action": "edit",
        "title": title,
        "text": text,
        "summary": summary,
        "token": token,
        "bot": True,
        "format": "json",
    }
    r = session.post(api_url, data=data, headers={"User-Agent": user_agent})
    r.raise_for_status()
    result = r.json()
    if "error" in result:
        raise RuntimeError(f"Erreur d'édition sur {title} : {result['error']}")


def get_recent_article_titles(session: requests.Session, api_url: str, user_agent: str, since_iso: str) -> list[str]:
    """Titres des pages (espace principal) modifiées depuis `since_iso`."""
    params = {
        "action": "query",
        "list": "recentchanges",
        "rcstart": since_iso,
        "rcdir": "newer",
        "rcnamespace": 0,
        "rcprop": "title",
        "rclimit": 50,
        "rctype": "edit|new",
        "format": "json",
    }
    r = session.get(api_url, params=params, headers={"User-Agent": user_agent})
    r.raise_for_status()
    changes = r.json().get("query", {}).get("recentchanges", [])
    # dédoublonnage en conservant l'ordre (une page peut apparaître plusieurs fois)
    seen = set()
    titles = []
    for change in changes:
        title = change["title"]
        if title not in seen:
            seen.add(title)
            titles.append(title)
    return titles


# ---------------------------------------------------------------------------
# 4. Boucle de surveillance pour un site donné, à lancer dans son propre thread
# ---------------------------------------------------------------------------
def watch_and_fix_typo_site(config: dict) -> None:
    nom_site = config["nom"]
    api_url = config["api_url"]
    user_agent = config["user_agent"]
    username = config["username"]
    password = config["password"]
    summary = config["summary"]

    if not username or not password:
        print(f"[typo-{nom_site}] ❌ Identifiants manquants, ce site ne sera pas surveillé.")
        return

    session = requests.Session()
    try:
        login(session, api_url, user_agent, username, password, nom_site)
    except Exception as e:
        print(f"[typo-{nom_site}] ❌ {e}")
        return

    # Idempotence : si une page est déjà "propre", clean_wikitext ne renvoie
    # aucun changement, donc pas de risque de boucle même si le bot revoit
    # ses propres modifications dans les changements récents suivants.
    last_check = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    while True:
        try:
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            titles = get_recent_article_titles(session, api_url, user_agent, last_check)
            last_check = now

            for title in titles:
                wikitext, _ = get_wikitext(session, api_url, user_agent, title)
                new_wikitext, changed = clean_wikitext(wikitext)
                if not changed:
                    continue

                save_wikitext(session, api_url, user_agent, title, new_wikitext, summary)
                print(f"[typo-{nom_site}] Corrigé : {title}")
                time.sleep(EDIT_PAUSE_SECONDS)

        except Exception as e:
            print(f"[typo-{nom_site}] ⚠️ Erreur dans la boucle : {e}")

        time.sleep(WATCH_INTERVAL_SECONDS)


def watch_and_fix_typo() -> None:
    """Point d'entrée : lance un thread par site configuré (fr + en)."""
    threads = []
    for config in SITES:
        t = threading.Thread(target=watch_and_fix_typo_site, args=(config,), daemon=True)
        t.start()
        threads.append(t)

    for t in threads:
        t.join()


if __name__ == "__main__":
    watch_and_fix_typo()
