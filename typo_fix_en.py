"""
Script de correction typographique — en.vikidia.org (Jules88!!Bot)

Objectif : corriger la typographie du texte visible d'une page (espaces doubles,
espaces avant ponctuation, espaces manquants après ponctuation, etc.) SANS toucher
au contenu des modèles ({{...}}), y compris les infobox, ni aux liens internes/
fichiers, commentaires HTML, balises <nowiki>/<pre>/<code>, etc.

Principe : on parse le wikitexte avec mwparserfromhell, on isole tout ce qui n'est
pas du texte brut (modèles, tags, liens, commentaires) en le remplaçant par des
"jetons" temporaires, on corrige la typo sur ce qui reste, puis on réinjecte les
jetons. Ainsi le nombre de correction ne "compte" pas ce qu'il y a dans les
modèles/infobox : leur contenu ressort strictement identique.

À brancher sur le framework existant du bot (login, pause de 120s entre
modifications, arrêt urgence, détection PDD, statut en ligne/hors ligne) :
remplacer les fonctions get_wikitext / save_wikitext ci-dessous par les
équivalents déjà utilisés ailleurs dans mysite/.
"""

import re
import time
import requests
import mwparserfromhell

API_URL = "https://en.vikidia.org/w/api.php"
USER_AGENT = "Jules88!!Bot/typo-fix (en.vikidia.org)"

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
# 3. Récupération / sauvegarde du wikitexte (à adapter au framework du bot)
# ---------------------------------------------------------------------------
def get_wikitext(session: requests.Session, title: str) -> tuple[str, str]:
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
    r = session.get(API_URL, params=params, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    page = r.json()["query"]["pages"][0]
    rev = page["revisions"][0]
    return rev["slots"]["main"]["content"], rev["timestamp"]


def get_csrf_token(session: requests.Session) -> str:
    params = {"action": "query", "meta": "tokens", "format": "json"}
    r = session.get(API_URL, params=params, headers={"User-Agent": USER_AGENT})
    return r.json()["query"]["tokens"]["csrftoken"]


def save_wikitext(session: requests.Session, title: str, text: str, summary: str) -> None:
    token = get_csrf_token(session)
    data = {
        "action": "edit",
        "title": title,
        "text": text,
        "summary": summary,
        "token": token,
        "bot": True,
        "format": "json",
    }
    r = session.post(API_URL, data=data, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    result = r.json()
    if "error" in result:
        raise RuntimeError(f"Erreur d'édition sur {title} : {result['error']}")


# ---------------------------------------------------------------------------
# 4. Boucle principale sur une liste de pages
# ---------------------------------------------------------------------------
def run_typo_fix(session: requests.Session, titles: list[str], pause_seconds: int = 120) -> None:
    """
    Parcourt une liste de titres de pages et corrige leur typographie.
    Respecte la pause de sécurité entre deux modifications, comme les autres
    scripts du bot. À brancher sur les vérifications existantes (feu vert,
    maintenance, arrêt urgence, message sur la PDD du bot) avant chaque édition.
    """
    for title in titles:
        wikitext, _ = get_wikitext(session, title)
        new_wikitext, changed = clean_wikitext(wikitext)

        if not changed:
            continue

        save_wikitext(
            session,
            title,
            new_wikitext,
            summary="Correction typographique automatique (espaces, ponctuation) — "
                    "modèles et infobox non modifiés [bot]",
        )
        print(f"Corrigé : {title}")

        time.sleep(pause_seconds)


# ---------------------------------------------------------------------------
# 5. Version "toujours active" pour KataBump (même principe que bienvenue.py :
#    thread de fond, boucle infinie, aucun lancement manuel nécessaire)
# ---------------------------------------------------------------------------
import os
import threading

# Identifiants dédiés à ce script, dans le .env de KataBump (à côté de
# VIKIDIA_BOT_USERNAME/VIKIDIA_BOT_PASSWORD utilisés par bienvenue.py — même
# compte ou compte dédié typo, au choix ; sur en.vikidia.org il faut se logger
# séparément même si c'est le même compte que sur fr.vikidia.org).
EN_BOT_USERNAME = os.getenv("VIKIDIA_EN_BOT_USERNAME")
EN_BOT_PASSWORD = os.getenv("VIKIDIA_EN_BOT_PASSWORD")

WATCH_INTERVAL_SECONDS = 60  # fréquence de vérification des modifications récentes
EDIT_PAUSE_SECONDS = 60     # pause de sécurité entre deux corrections (comme les autres scripts)


def login(session: requests.Session) -> None:
    if not EN_BOT_USERNAME or not EN_BOT_PASSWORD:
        raise RuntimeError(
            "VIKIDIA_EN_BOT_USERNAME / VIKIDIA_EN_BOT_PASSWORD manquants dans le .env"
        )
    r = session.get(
        API_URL,
        params={"action": "query", "meta": "tokens", "type": "login", "format": "json"},
        headers={"User-Agent": USER_AGENT},
    )
    login_token = r.json()["query"]["tokens"]["logintoken"]

    r = session.post(
        API_URL,
        data={
            "action": "login",
            "lgname": EN_BOT_USERNAME,
            "lgpassword": EN_BOT_PASSWORD,
            "lgtoken": login_token,
            "format": "json",
        },
        headers={"User-Agent": USER_AGENT},
    )
    result = r.json().get("login", {})
    if result.get("result") != "Success":
        raise RuntimeError(f"Échec de connexion sur en.vikidia.org : {result}")
    print("Connecté à en.vikidia.org en tant que", EN_BOT_USERNAME)


def get_recent_article_titles(session: requests.Session, since_iso: str) -> list[str]:
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
    r = session.get(API_URL, params=params, headers={"User-Agent": USER_AGENT})
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


def watch_and_fix_typo() -> None:
    """
    Boucle infinie : surveille les modifications récentes de en.vikidia.org
    toutes les WATCH_INTERVAL_SECONDS, corrige automatiquement la typo des
    pages touchées (sans jamais modifier modèles/infobox/refs/etc.), avec une
    pause de EDIT_PAUSE_SECONDS entre deux corrections effectives. Conçu pour
    tourner en tâche de fond sur KataBump, comme bienvenue.py.
    """
    session = requests.Session()
    login(session)

    # Idempotence : si une page est déjà "propre", clean_wikitext ne renvoie
    # aucun changement, donc pas de risque de boucle même si le bot revoit
    # ses propres modifications dans les changements récents suivants.
    last_check = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    while True:
        try:
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            titles = get_recent_article_titles(session, last_check)
            last_check = now

            for title in titles:
                wikitext, _ = get_wikitext(session, title)
                new_wikitext, changed = clean_wikitext(wikitext)
                if not changed:
                    continue

                save_wikitext(
                    session,
                    title,
                    new_wikitext,
                    summary="Correction typographique automatique (espaces, ponctuation) — "
                            "modèles et infobox non modifiés [bot]",
                )
                print(f"Corrigé : {title}")
                time.sleep(EDIT_PAUSE_SECONDS)

        except Exception as e:
            print("Erreur dans watch_and_fix_typo :", e)

        time.sleep(WATCH_INTERVAL_SECONDS)


if __name__ == "__main__":
    # Test manuel autonome.
    watch_and_fix_typo()
