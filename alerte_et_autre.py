import asyncio
import os
import time

import requests


# ============================================================
# CONFIGURATION
# ============================================================

VIKIDIA_API_URL = "https://fr.vikidia.org/w/api.php"

CATEGORIES_A_SURVEILLER = [
    "Suppression immédiate",
    "Demande à traiter",
]

PDD_BOT = "Discussion utilisateur:Jules88!!Bot"

INTERVALLE_SECONDES = 60


# ============================================================
# RÉCUPÉRATION DES PAGES D'UNE CATÉGORIE
# ============================================================

def _get_pages_categorie(categorie):
    pages = []

    params = {
        "action": "query",
        "list": "categorymembers",
        "cmtitle": f"Catégorie:{categorie}",
        "cmlimit": "500",
        "format": "json",
    }

    try:
        response = requests.get(
            VIKIDIA_API_URL,
            params=params,
            timeout=10
        )
        response.raise_for_status()

        data = response.json()

        membres = data.get("query", {}).get("categorymembers", [])

        for membre in membres:
            titre = membre.get("title")

            if titre:
                pages.append(titre)

    except Exception as e:
        print(
            f"[alerte_et_autre] ❌ Erreur récupération "
            f"catégorie {categorie} : {e}"
        )

    return pages


# ============================================================
# RÉCUPÉRATION DE LA DERNIÈRE RÉVISION DE LA PDD
# ============================================================

def _get_derniere_revision_pdd():
    params = {
        "action": "query",
        "prop": "revisions",
        "titles": PDD_BOT,
        "rvprop": "ids|timestamp",
        "rvlimit": "1",
        "format": "json",
    }

    try:
        response = requests.get(
            VIKIDIA_API_URL,
            params=params,
            timeout=10
        )

        response.raise_for_status()

        data = response.json()

        pages = data.get(
            "query",
            {}
        ).get(
            "pages",
            {}
        )

        for page in pages.values():

            revisions = page.get(
                "revisions",
                []
            )

            if revisions:

                return revisions[0].get(
                    "revid"
                )

    except Exception as e:

        print(
            f"[alerte_et_autre] ❌ Erreur récupération "
            f"révision PDD : {e}"
        )

    return None


# ============================================================
# ENVOI DU MESSAGE PRIVÉ DISCORD
# ============================================================

async def _envoyer_mp_arret_async(bot, owner_id):

    try:

        utilisateur = await bot.fetch_user(
            int(owner_id)
        )

        embed = {
            "title": "🛑 Arrêt de KataBump",
            "description": (
                "Une nouvelle modification a été détectée "
                "sur la page de discussion du bot :\n\n"
                f"`{PDD_BOT}`\n\n"
                "KataBump va maintenant s'arrêter."
            ),
            "color": 0xFF0000,
        }

        # Création d'un embed Discord
        import discord

        discord_embed = discord.Embed(
            title=embed["title"],
            description=embed["description"],
            color=embed["color"],
        )

        await utilisateur.send(
            embed=discord_embed
        )

        print(
            "[alerte_et_autre] ✅ Message privé envoyé."
        )

    except Exception as e:

        print(
            f"[alerte_et_autre] ❌ Impossible d'envoyer "
            f"le message privé : {e}"
        )

        raise


def _envoyer_mp_arret(bot, owner_id):

    try:

        loop = bot.loop

        if loop.is_running():

            future = asyncio.run_coroutine_threadsafe(
                _envoyer_mp_arret_async(
                    bot,
                    owner_id
                ),
                loop
            )

            future.result(
                timeout=15
            )

        else:

            asyncio.run(
                _envoyer_mp_arret_async(
                    bot,
                    owner_id
                )
            )

    except Exception as e:

        print(
            f"[alerte_et_autre] ❌ Erreur envoi MP : {e}"
        )


# ============================================================
# ARRÊT DE KATABUMP
# ============================================================

def _arreter_katabump():

    print(
        "[alerte_et_autre] 🛑 Arrêt de KataBump..."
    )

    # Arrêt immédiat du processus
    os._exit(0)


# ============================================================
# SURVEILLANCE
# ============================================================

def start_watch_categories(bot, owner_id):

    print(
        "[alerte_et_autre] 👀 Surveillance démarrée."
    )

    print(
        f"[alerte_et_autre] 📄 PDD surveillée : {PDD_BOT}"
    )

    print(
        f"[alerte_et_autre] ⏱️ Vérification toutes les "
        f"{INTERVALLE_SECONDES} secondes."
    )

    # --------------------------------------------------------
    # On récupère la révision actuelle au démarrage.
    #
    # Cela signifie qu'une modification déjà présente avant
    # le démarrage ne déclenchera PAS immédiatement l'arrêt.
    # --------------------------------------------------------

    derniere_revision_pdd = _get_derniere_revision_pdd()

    print(
        f"[alerte_et_autre] "
        f"Révision actuelle de la PDD : "
        f"{derniere_revision_pdd}"
    )

    while True:

        try:

            # =================================================
            # SURVEILLANCE DES CATÉGORIES
            # =================================================

            for categorie in CATEGORIES_A_SURVEILLER:

                pages = _get_pages_categorie(
                    categorie
                )

                if pages:

                    print(
                        f"[alerte_et_autre] 📂 "
                        f"{categorie} : "
                        f"{len(pages)} page(s)"
                    )

            # =================================================
            # SURVEILLANCE DE LA PDD
            # =================================================

            nouvelle_revision = _get_derniere_revision_pdd()

            if nouvelle_revision is not None:

                if derniere_revision_pdd is not None:

                    if nouvelle_revision != derniere_revision_pdd:

                        print(
                            "[alerte_et_autre] 🚨 "
                            "NOUVELLE MODIFICATION DÉTECTÉE "
                            "SUR LA PDD !"
                        )

                        print(
                            f"[alerte_et_autre] "
                            f"Ancienne révision : "
                            f"{derniere_revision_pdd}"
                        )

                        print(
                            f"[alerte_et_autre] "
                            f"Nouvelle révision : "
                            f"{nouvelle_revision}"
                        )

                        # -------------------------------------
                        # Envoi du MP AVANT l'arrêt
                        # -------------------------------------

                        _envoyer_mp_arret(
                            bot,
                            owner_id
                        )

                        # -------------------------------------
                        # Arrêt de KataBump
                        # -------------------------------------

                        _arreter_katabump()

                derniere_revision_pdd = nouvelle_revision

        except Exception as e:

            print(
                f"[alerte_et_autre] ❌ Erreur dans la "
                f"surveillance : {e}"
            )

        time.sleep(
            INTERVALLE_SECONDES
        )
