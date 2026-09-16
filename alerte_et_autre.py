"""
alerte_et_autre.py

Surveille les catégories Vikidia :
- Catégorie:Suppression immédiate
- Catégorie:Demande à traiter

Et envoie un MP Discord (style BotCélian) dès qu'une nouvelle page
apparaît dans l'une de ces catégories. Vérification toutes les 60 secondes.

À FAIRE dans app.py :
    from alerte_et_autre import start_watch_categories
    ...
    threading.Thread(target=start_watch_categories, args=(bot, OWNER_ID), daemon=True).start()
    (à mettre à côté de tes autres threading.Thread(...).start(), avant bot.run(TOKEN))
"""

import time
import asyncio
import requests
import discord

# ------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------

# ⚠️ Vérifie que c'est bien le bon wiki (fr.vikidia.org, en.vikidia.org, etc.)
VIKIDIA_API_URL = "https://fr.vikidia.org/w/api.php"

CATEGORIES_SURVEILLEES = {
    "Catégorie:Suppression immédiate": {
        "emoji": "🗑️",
        "titre": "Suppression Immédiate",
        "couleur": 0xE6B800,
    },
    "Catégorie:Demande à traiter": {
        "emoji": "📌",
        "titre": "Demande à traiter",
        "couleur": 0xFF8C00,
    },
}

INTERVALLE_SECONDES = 60

# État interne : pages déjà vues par catégorie
_pages_deja_vues = {cat: set() for cat in CATEGORIES_SURVEILLEES}


# ------------------------------------------------------------------
# Fonctions
# ------------------------------------------------------------------

def _get_pages_categorie(nom_categorie):
    """Récupère la liste des pages actuellement dans une catégorie Vikidia."""
    params = {
        "action": "query",
        "list": "categorymembers",
        "cmtitle": nom_categorie,
        "cmlimit": "50",
        "format": "json",
    }
    r = requests.get(VIKIDIA_API_URL, params=params, timeout=10)
    data = r.json()
    return {page["title"] for page in data.get("query", {}).get("categorymembers", [])}


async def _envoyer_mp_categorie(bot, owner_id, page, style):
    """Envoie un MP stylé (embed) au propriétaire du bot pour une nouvelle page."""
    user = await bot.fetch_user(owner_id)
    embed = discord.Embed(
        title=f"{style['emoji']} {style['titre']}",
        description=f"**{page}** a rejoint la catégorie.",
        color=style["couleur"],
    )
    embed.timestamp = discord.utils.utcnow()
    embed.set_footer(text="Vikidia • Surveillance auto")
    await user.send(embed=embed)


def start_watch_categories(bot, owner_id):
    """
    Boucle de surveillance à lancer dans un thread à part.

    Exemple d'utilisation dans app.py :
        threading.Thread(target=start_watch_categories, args=(bot, OWNER_ID), daemon=True).start()
    """
    # État initial : on note ce qui existe déjà, sans envoyer de MP au démarrage
    for cat in CATEGORIES_SURVEILLEES:
        try:
            _pages_deja_vues[cat] = _get_pages_categorie(cat)
        except Exception as e:
            print(f"[alerte_et_autre] Erreur initialisation ({cat}) : {e}")

    while True:
        time.sleep(INTERVALLE_SECONDES)
        for cat, style in CATEGORIES_SURVEILLEES.items():
            try:
                pages_actuelles = _get_pages_categorie(cat)
                nouvelles = pages_actuelles - _pages_deja_vues[cat]
                for page in nouvelles:
                    asyncio.run_coroutine_threadsafe(
                        _envoyer_mp_categorie(bot, owner_id, page, style),
                        bot.loop,
                    )
                _pages_deja_vues[cat] = pages_actuelles
            except Exception as e:
                print(f"[alerte_et_autre] Erreur watch_categories ({cat}) : {e}")
