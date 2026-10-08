"""
Script de correction typographique — fr.vikidia.org ET en.vikidia.org

Fonctionnement :
- Le bot surveille les modifications des pages de l'espace principal.
- Lorsqu'une page est modifiée, le bot attend WAIT_AFTER_LAST_EDIT_SECONDS
  après LA DERNIÈRE modification de cette page.
- Si quelqu'un modifie à nouveau la page pendant l'attente, le compte à
  rebours repart de zéro.
- Exemple :
      12:00 -> modification
      12:10 -> modification
      12:25 -> modification
      12:55 -> correction possible
  (30 minutes après la dernière modification)
- Le délai est facilement modifiable en haut du fichier.

Le bot fonctionne en parallèle sur fr.vikidia.org et en.vikidia.org.

Le texte à l'intérieur des modèles, infobox, balises protégées, commentaires,
fichiers, etc. n'est pas modifié.
"""

import os
import re
import time
import threading
from datetime import datetime, timezone

import requests
import mwparserfromhell


# ===========================================================================
# CONFIGURATION GÉNÉRALE
# ===========================================================================

# ---------------------------------------------------------------------------
# TEMPS D'ATTENTE APRÈS LA DERNIÈRE MODIFICATION
# ---------------------------------------------------------------------------
#
# 30 * 60 = 30 minutes
#
# Tu peux changer cette valeur facilement :
#
#   5 * 60          = 5 minutes
#   10 * 60         = 10 minutes
#   30 * 60         = 30 minutes
#   60 * 60         = 1 heure
#   2 * 60 * 60     = 2 heures
#
WAIT_AFTER_LAST_EDIT_SECONDS = 30 * 60


# Toutes les combien de secondes le bot regarde les nouvelles modifications.
WATCH_INTERVAL_SECONDS = 30

# Pause entre deux éditions du bot.
EDIT_PAUSE_SECONDS = 60

NBSP = "\u00A0"


# ===========================================================================
# CONFIGURATION DES SITES
# ===========================================================================

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
            "(espaces, ponctuation) — "
            "modèles et infobox non modifiés [bot]"
        ),
    },

    {
        "nom": "en",
        "lang": "en",
        "api_url": "https://en.vikidia.org/w/api.php",
        "user_agent": "Jules88!!Bot/typo-fix (en.vikidia.org)",

        "username": os.getenv("VIKIDIA_EN_BOT_USERNAME"),
        "password": os.getenv("VIKIDIA_EN_BOT_PASSWORD"),

        "summary": (
            "Automatic typo fix (spacing, punctuation) — "
            "templates and infoboxes left unchanged [bot]"
        ),
    },
]


# ===========================================================================
# 1. RÈGLES DE CORRECTION TYPOGRAPHIQUE
# ===========================================================================

# ---------------------------------------------------------------------------
# Règles communes aux deux langues.
# ---------------------------------------------------------------------------

COMMON_TYPO_RULES = [

    # Espaces doubles ou plus -> un seul espace.
    (re.compile(r"[ \t]{2,}"), " "),

    # Jamais d'espace avant une virgule ou un point.
    (re.compile(r"[ \t\u00A0]+([,.])"), r"\1"),

    # Pas d'espace après une parenthèse ouvrante.
    (re.compile(r"\( +"), "("),

    # Pas d'espace avant une parenthèse fermante.
    (re.compile(r" +\)"), ")"),

    # Espace manquant après ponctuation lorsqu'elle est directement
    # suivie d'une lettre.
    #
    # Exemple :
    #   "Bonjour,comment" -> "Bonjour, comment"
    #
    # On ne touche pas aux nombres :
    #   "1,5" reste "1,5"
    #
    (re.compile(r"([,.;:!?])(?=[A-Za-zÀ-ÿ])"), r"\1 "),

    # Espaces en fin de ligne.
    (re.compile(r"[ \t]+\n"), "\n"),

    # Maximum deux sauts de ligne consécutifs.
    (re.compile(r"\n{3,}"), "\n\n"),
]


# ---------------------------------------------------------------------------
# Ponctuation ; : ! ?
# ---------------------------------------------------------------------------

_PUNCT_RUN = re.compile(r"[ \t\u00A0]*([;:!?]+)")


# ---------------------------------------------------------------------------
# Français :
#
# Une espace insécable avant ; : ! ?
#
# Exemple :
#   Bonjour ! -> Bonjour !
#   Attention : -> Attention :
# ---------------------------------------------------------------------------

_FR_PUNCT_RUN = re.compile(
    r"(?<=[a-zA-Z0-9À-ÿ\)])[\t ]*([;:!?]+)"
)

FR_PUNCT_RULE = (
    _FR_PUNCT_RUN,
    NBSP + r"\1"
)


# ---------------------------------------------------------------------------
# Guillemets français.
#
# Exemple :
#   « Bonjour » -> {{ " ? }}
#
# ATTENTION :
# Cette règle reprend exactement le comportement de ton script original.
# ---------------------------------------------------------------------------

FR_GUILLEMETS_RULE = (
    re.compile(r'«[ \t\u00A0]*([^»\n]+?)[ \t\u00A0]*»'),
    r'{{"|\1}}'
)


# ---------------------------------------------------------------------------
# Anglais :
#
# Aucune espace avant ; : ! ?
#
# Exemple :
#   Hello ! -> Hello!
# ---------------------------------------------------------------------------

EN_PUNCT_RULE = (
    _PUNCT_RUN,
    r"\1"
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


def fix_typo_in_text(text: str, lang: str) -> str:
    """
    Applique les règles typographiques à du texte brut uniquement.
    """

    for pattern, replacement in COMMON_TYPO_RULES:
        text = pattern.sub(replacement, text)

    for pattern, replacement in LANG_PUNCT_RULES.get(lang, []):
        text = pattern.sub(replacement, text)

    return text


# ===========================================================================
# 2. PROTECTION DU WIKITEXTE
# ===========================================================================

def _process_wikicode(
    code: "mwparserfromhell.wikicode.Wikicode",
    lang: str
) -> str:
    """
    Reconstruit le wikitexte en corrigeant uniquement le texte visible.

    Sont protégés :
    - modèles {{...}}
    - infobox
    - balises HTML
    - <nowiki>
    - <pre>
    - <code>
    - <math>
    - <ref>
    - commentaires HTML
    - fichiers
    - catégories
    - cibles des liens internes
    - URL des liens externes

    Pour les liens internes avec un texte visible, seul le texte visible
    peut être corrigé.
    """

    parts = []

    for node in code.nodes:

        # -------------------------------------------------------------------
        # Modèles
        # -------------------------------------------------------------------

        if isinstance(node, mwparserfromhell.nodes.Template):
            parts.append(str(node))


        # -------------------------------------------------------------------
        # Balises
        # -------------------------------------------------------------------

        elif isinstance(node, mwparserfromhell.nodes.Tag):
            parts.append(str(node))


        # -------------------------------------------------------------------
        # Commentaires HTML
        # -------------------------------------------------------------------

        elif isinstance(node, mwparserfromhell.nodes.Comment):
            parts.append(str(node))


        # -------------------------------------------------------------------
        # Liens internes
        # -------------------------------------------------------------------

        elif isinstance(node, mwparserfromhell.nodes.Wikilink):

            target = str(node.title).strip().lower()

            # Fichiers / images / catégories :
            # tout le lien est protégé.
            if target.startswith(
                (
                    "file:",
                    "fichier:",
                    "image:",
                    "category:",
                    "catégorie:",
                )
            ) or node.text is None:

                parts.append(str(node))

            else:
                # On protège la cible mais on corrige le texte affiché.
                fixed_text = fix_typo_in_text(
                    str(node.text),
                    lang
                )

                parts.append(
                    f"[[{node.title}|{fixed_text}]]"
                )


        # -------------------------------------------------------------------
        # Liens externes
        # -------------------------------------------------------------------

        elif isinstance(node, mwparserfromhell.nodes.ExternalLink):

            if node.title is not None:

                fixed_title = fix_typo_in_text(
                    str(node.title),
                    lang
                )

                bracket_open = "[" if node.brackets else ""
                bracket_close = "]" if node.brackets else ""

                parts.append(
                    f"{bracket_open}"
                    f"{node.url} "
                    f"{fixed_title}"
                    f"{bracket_close}"
                )

            else:
                # URL brute : aucun changement.
                parts.append(str(node))


        # -------------------------------------------------------------------
        # Titres
        # -------------------------------------------------------------------

        elif isinstance(node, mwparserfromhell.nodes.Heading):

            fixed_title = _process_wikicode(
                node.title,
                lang
            )

            eq = "=" * node.level

            parts.append(
                f"{eq} {fixed_title.strip()} {eq}"
            )


        # -------------------------------------------------------------------
        # Texte brut
        # -------------------------------------------------------------------

        elif isinstance(node, mwparserfromhell.nodes.Text):

            parts.append(
                fix_typo_in_text(
                    str(node.value),
                    lang
                )
            )


        # -------------------------------------------------------------------
        # Tout le reste est protégé par défaut.
        # -------------------------------------------------------------------

        else:
            parts.append(str(node))

    return "".join(parts)


def clean_wikitext(
    wikitext: str,
    lang: str
) -> tuple[str, bool]:
    """
    Corrige la typographie d'un wikitexte.

    Retourne :
        (nouveau_wikitexte, a_change)
    """

    code = mwparserfromhell.parse(wikitext)

    new_wikitext = _process_wikicode(
        code,
        lang
    )

    return (
        new_wikitext,
        new_wikitext != wikitext
    )


# ===========================================================================
# 3. OUTILS POUR LES DATES MEDIAWIKI
# ===========================================================================

def parse_mediawiki_timestamp(timestamp: str) -> float:
    """
    Transforme un timestamp MediaWiki UTC en timestamp Unix.

    Exemple :
        2026-10-06T19:30:00Z
    """

    dt = datetime.fromisoformat(
        timestamp.replace("Z", "+00:00")
    )

    return dt.timestamp()


def current_utc_timestamp() -> float:
    """
    Timestamp Unix actuel en UTC.
    """

    return datetime.now(timezone.utc).timestamp()


# ===========================================================================
# 4. CONNEXION
# ===========================================================================

def login(
    session: requests.Session,
    api_url: str,
    user_agent: str,
    username: str,
    password: str,
    nom_site: str
) -> None:

    if not username or not password:
        raise RuntimeError(
            f"Identifiants manquants pour le site {nom_site} "
            f"dans le .env"
        )

    # -----------------------------------------------------------------------
    # Récupération du login token.
    # -----------------------------------------------------------------------

    r = session.get(
        api_url,
        params={
            "action": "query",
            "meta": "tokens",
            "type": "login",
            "format": "json",
        },
        headers={
            "User-Agent": user_agent
        },
        timeout=30,
    )

    r.raise_for_status()

    login_token = (
        r.json()["query"]["tokens"]["logintoken"]
    )


    # -----------------------------------------------------------------------
    # Connexion.
    # -----------------------------------------------------------------------

    r = session.post(
        api_url,
        data={
            "action": "login",
            "lgname": username,
            "lgpassword": password,
            "lgtoken": login_token,
            "format": "json",
        },
        headers={
            "User-Agent": user_agent
        },
        timeout=30,
    )

    r.raise_for_status()

    result = r.json().get("login", {})

    if result.get("result") != "Success":
        raise RuntimeError(
            f"Échec de connexion sur {nom_site} : {result}"
        )

    print(
        f"[typo-{nom_site}] "
        f"✅ Connecté en tant que {username}"
    )


# ===========================================================================
# 5. RÉCUPÉRATION DU WIKITEXTE
# ===========================================================================

def get_wikitext(
    session: requests.Session,
    api_url: str,
    user_agent: str,
    title: str
) -> tuple[str, str]:
    """
    Retourne :
        (wikitexte, timestamp_de_la_revision)
    """

    params = {
        "action": "query",
        "prop": "revisions",
        "rvprop": "content|timestamp",
        "rvslots": "main",
        "titles": title,
        "format": "json",
        "formatversion": "2",
    }

    r = session.get(
        api_url,
        params=params,
        headers={
            "User-Agent": user_agent
        },
        timeout=30,
    )

    r.raise_for_status()

    pages = r.json()["query"]["pages"]

    if not pages:
        raise RuntimeError(
            f"Page introuvable : {title}"
        )

    page = pages[0]

    if "revisions" not in page or not page["revisions"]:
        raise RuntimeError(
            f"Aucune révision trouvée pour : {title}"
        )

    revision = page["revisions"][0]

    return (
        revision["slots"]["main"]["content"],
        revision["timestamp"],
    )


# ===========================================================================
# 6. TOKEN CSRF
# ===========================================================================

def get_csrf_token(
    session: requests.Session,
    api_url: str,
    user_agent: str
) -> str:

    params = {
        "action": "query",
        "meta": "tokens",
        "format": "json",
    }

    r = session.get(
        api_url,
        params=params,
        headers={
            "User-Agent": user_agent
        },
        timeout=30,
    )

    r.raise_for_status()

    return r.json()["query"]["tokens"]["csrftoken"]


# ===========================================================================
# 7. SAUVEGARDE
# ===========================================================================

def save_wikitext(
    session: requests.Session,
    api_url: str,
    user_agent: str,
    title: str,
    text: str,
    summary: str,
    base_timestamp: str
) -> None:
    """
    Sauvegarde le texte.

    IMPORTANT :
    basetimestamp empêche le bot d'écraser une modification survenue
    entre la lecture de la page et l'édition.
    """

    token = get_csrf_token(
        session,
        api_url,
        user_agent
    )

    data = {
        "action": "edit",
        "title": title,
        "text": text,
        "summary": summary,
        "token": token,
        "bot": True,

        # Protection contre les conflits / écrasements.
        "basetimestamp": base_timestamp,

        "format": "json",
    }

    r = session.post(
        api_url,
        data=data,
        headers={
            "User-Agent": user_agent
        },
        timeout=30,
    )

    r.raise_for_status()

    result = r.json()

    if "error" in result:
        raise RuntimeError(
            f"Erreur d'édition sur {title} : "
            f"{result['error']}"
        )

    edit_result = result.get("edit", {}).get("result")

    if edit_result != "Success":
        raise RuntimeError(
            f"Édition non effectuée sur {title} : "
            f"{result}"
        )


# ===========================================================================
# 8. RÉCUPÉRATION DES MODIFICATIONS RÉCENTES
# ===========================================================================

def get_recent_article_changes(
    session: requests.Session,
    api_url: str,
    user_agent: str,
    since_iso: str,
    own_username: str
) -> list[dict]:
    """
    Retourne les modifications de l'espace principal depuis since_iso.

    Chaque élément contient notamment :
        {
            "title": ...,
            "timestamp": ...,
            "user": ...
        }

    Les modifications faites par le bot lui-même sont ignorées.
    """

    changes = []

    params = {
        "action": "query",
        "list": "recentchanges",

        # On récupère titre + date + utilisateur.
        "rcprop": "title|timestamp|user",

        "rcstart": since_iso,
        "rcdir": "newer",

        # Espace principal uniquement.
        "rcnamespace": 0,

        "rclimit": 50,

        "rctype": "edit|new",

        "format": "json",
    }

    while True:

        r = session.get(
            api_url,
            params=params,
            headers={
                "User-Agent": user_agent
            },
            timeout=30,
        )

        r.raise_for_status()

        data = r.json()

        batch = data.get(
            "query",
            {}
        ).get(
            "recentchanges",
            []
        )

        for change in batch:

            username = change.get("user", "")

            # Ne pas remettre une page en attente à cause de notre
            # propre modification.
            if own_username and username == own_username:
                continue

            changes.append(
                {
                    "title": change["title"],
                    "timestamp": change["timestamp"],
                    "user": username,
                }
            )

        # -------------------------------------------------------------------
        # Pagination MediaWiki.
        #
        # Cela évite de perdre des modifications si plus de 50 changements
        # ont eu lieu pendant une période.
        # -------------------------------------------------------------------

        if "continue" not in data:
            break

        params.update(
            data["continue"]
        )

    return changes


# ===========================================================================
# 9. BOUCLE DE SURVEILLANCE D'UN SITE
# ===========================================================================

def watch_and_fix_typo_site(config: dict) -> None:

    nom_site = config["nom"]
    lang = config["lang"]
    api_url = config["api_url"]
    user_agent = config["user_agent"]
    username = config["username"]
    password = config["password"]
    summary = config["summary"]


    # -----------------------------------------------------------------------
    # Vérification des identifiants.
    # -----------------------------------------------------------------------

    if not username or not password:

        print(
            f"[typo-{nom_site}] "
            f"❌ Identifiants manquants, "
            f"ce site ne sera pas surveillé."
        )

        return


    # -----------------------------------------------------------------------
    # Session HTTP.
    # -----------------------------------------------------------------------

    session = requests.Session()


    # -----------------------------------------------------------------------
    # Connexion.
    # -----------------------------------------------------------------------

    try:

        login(
            session,
            api_url,
            user_agent,
            username,
            password,
            nom_site
        )

    except Exception as e:

        print(
            f"[typo-{nom_site}] "
            f"❌ {e}"
        )

        return


    # =========================================================================
    # FILE D'ATTENTE DES PAGES
    # =========================================================================
    #
    # Format :
    #
    # pending_pages = {
    #     "Nom de la page": timestamp_de_la_dernière_modification
    # }
    #
    # Exemple :
    #
    #     {
    #         "France": 1791300000.0,
    #         "Paris": 1791300100.0
    #     }
    #
    # =========================================================================

    pending_pages = {}


    # -----------------------------------------------------------------------
    # Premier passage.
    #
    # On commence à surveiller à partir de maintenant.
    # Le bot ne va donc pas chercher à corriger toutes les anciennes pages
    # du wiki au démarrage.
    # -----------------------------------------------------------------------

    last_check_timestamp = current_utc_timestamp()

    last_check_iso = (
        datetime.fromtimestamp(
            last_check_timestamp,
            tz=timezone.utc
        )
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )


    print(
        f"[typo-{nom_site}] "
        f"👀 Surveillance démarrée."
    )

    print(
        f"[typo-{nom_site}] "
        f"⏳ Délai après dernière modification : "
        f"{WAIT_AFTER_LAST_EDIT_SECONDS // 60} minute(s)."
    )


    # =========================================================================
    # BOUCLE INFINIE
    # =========================================================================

    while True:

        try:

            # =================================================================
            # ÉTAPE 1 : récupérer les nouvelles modifications
            # =================================================================

            now = current_utc_timestamp()

            now_iso = (
                datetime.fromtimestamp(
                    now,
                    tz=timezone.utc
                )
                .strftime("%Y-%m-%dT%H:%M:%SZ")
            )


            changes = get_recent_article_changes(
                session,
                api_url,
                user_agent,
                last_check_iso,
                username
            )


            # On avance notre curseur.
            last_check_iso = now_iso


            # =================================================================
            # ÉTAPE 2 : mettre à jour la file d'attente
            # =================================================================

            for change in changes:

                title = change["title"]
                timestamp_iso = change["timestamp"]

                timestamp = parse_mediawiki_timestamp(
                    timestamp_iso
                )

                # -------------------------------------------------------------
                # TRÈS IMPORTANT :
                #
                # Si la page était déjà dans la file d'attente, on remplace
                # son ancienne date.
                #
                # Donc :
                #
                # 12:00 -> modification
                # 12:10 -> modification
                #
                # Le bot attendra jusqu'à 12:40 et non 12:30.
                # -------------------------------------------------------------

                old_timestamp = pending_pages.get(title)

                if (
                    old_timestamp is None
                    or timestamp > old_timestamp
                ):

                    pending_pages[title] = timestamp

                    print(
                        f"[typo-{nom_site}] "
                        f"🕒 En attente : {title} "
                        f"(dernière modification : "
                        f"{timestamp_iso})"
                    )


            # =================================================================
            # ÉTAPE 3 : vérifier les pages dont le délai est terminé
            # =================================================================

            current_time = current_utc_timestamp()

            pages_ready = []

            for title, last_edit_timestamp in pending_pages.items():

                elapsed = (
                    current_time -
                    last_edit_timestamp
                )

                if elapsed >= WAIT_AFTER_LAST_EDIT_SECONDS:

                    pages_ready.append(title)


            # =================================================================
            # ÉTAPE 4 : corriger les pages prêtes
            # =================================================================

            for title in pages_ready:

                try:

                    # ---------------------------------------------------------
                    # On récupère la version actuelle de la page.
                    # ---------------------------------------------------------

                    wikitext, revision_timestamp = get_wikitext(
                        session,
                        api_url,
                        user_agent,
                        title
                    )


                    # ---------------------------------------------------------
                    # On vérifie une dernière fois que la page n'a pas changé.
                    #
                    # Cela évite de corriger une ancienne version si une
                    # modification est arrivée juste avant le traitement.
                    # ---------------------------------------------------------

                    revision_unix = parse_mediawiki_timestamp(
                        revision_timestamp
                    )

                    last_known_edit = pending_pages.get(
                        title
                    )

                    if (
                        last_known_edit is not None
                        and revision_unix > last_known_edit
                    ):

                        # Une nouvelle modification est arrivée.
                        # On repart donc pour WAIT_AFTER_LAST_EDIT_SECONDS.
                        pending_pages[title] = revision_unix

                        print(
                            f"[typo-{nom_site}] "
                            f"🔄 Nouvelle modification détectée : "
                            f"{title} — attente relancée."
                        )

                        continue


                    # ---------------------------------------------------------
                    # Correction typographique.
                    # ---------------------------------------------------------

                    new_wikitext, changed = clean_wikitext(
                        wikitext,
                        lang
                    )


                    # ---------------------------------------------------------
                    # Rien à corriger.
                    # ---------------------------------------------------------

                    if not changed:

                        print(
                            f"[typo-{nom_site}] "
                            f"✅ Rien à corriger : {title}"
                        )

                        # La page peut sortir de la file.
                        pending_pages.pop(
                            title,
                            None
                        )

                        continue


                    # ---------------------------------------------------------
                    # Sauvegarde.
                    #
                    # basetimestamp garantit que si quelqu'un modifie la
                    # page entre notre GET et notre POST, MediaWiki refuse
                    # l'édition au lieu d'écraser la modification.
                    # ---------------------------------------------------------

                    save_wikitext(
                        session,
                        api_url,
                        user_agent,
                        title,
                        new_wikitext,
                        summary,
                        revision_timestamp
                    )


                    print(
                        f"[typo-{nom_site}] "
                        f"✏️ Corrigé : {title}"
                    )


                    # ---------------------------------------------------------
                    # La page est sortie de la file d'attente.
                    # ---------------------------------------------------------

                    pending_pages.pop(
                        title,
                        None
                    )


                    # ---------------------------------------------------------
                    # Pause entre les éditions.
                    # ---------------------------------------------------------

                    time.sleep(
                        EDIT_PAUSE_SECONDS
                    )


                except Exception as e:

                    error_text = str(e)

                    print(
                        f"[typo-{nom_site}] "
                        f"⚠️ Erreur pour {title} : "
                        f"{error_text}"
                    )

                    # ---------------------------------------------------------
                    # Si l'édition a échoué parce qu'une modification est
                    # arrivée entre-temps, on NE retire PAS la page de la
                    # file d'attente.
                    #
                    # Elle sera revue au prochain passage.
                    # ---------------------------------------------------------

                    if "editconflict" in error_text.lower():

                        pending_pages[title] = (
                            current_utc_timestamp()
                        )


            # =================================================================
            # ÉTAPE 5 : afficher éventuellement l'état de la file
            # =================================================================

            if pending_pages:

                current_time = current_utc_timestamp()

                for title, last_edit in list(
                    pending_pages.items()
                ):

                    remaining = (
                        WAIT_AFTER_LAST_EDIT_SECONDS
                        - (
                            current_time -
                            last_edit
                        )
                    )

                    if remaining > 0:

                        remaining_minutes = int(
                            remaining // 60
                        )

                        print(
                            f"[typo-{nom_site}] "
                            f"⏳ {title} : "
                            f"encore environ "
                            f"{remaining_minutes} min "
                            f"avant correction."
                        )


        except Exception as e:

            print(
                f"[typo-{nom_site}] "
                f"⚠️ Erreur dans la boucle : {e}"
            )


        # =====================================================================
        # Attente avant le prochain passage.
        # =====================================================================

        time.sleep(
            WATCH_INTERVAL_SECONDS
        )


# ===========================================================================
# 10. POINT D'ENTRÉE
# ===========================================================================

def watch_and_fix_typo() -> None:
    """
    Lance un thread de surveillance pour chaque site.
    """

    threads = []

    for config in SITES:

        thread = threading.Thread(
            target=watch_and_fix_typo_site,
            args=(config,),
            daemon=True
        )

        thread.start()

        threads.append(thread)


    # Les deux threads fonctionnent en parallèle.

    for thread in threads:
        thread.join()


# ===========================================================================
# LANCEMENT
# ===========================================================================

if __name__ == "__main__":
    watch_and_fix_typo()