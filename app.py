import asyncio
import os
import json
import html
import random
import re
import time
from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo
from discord.ext import tasks
from alerte_et_autre import start_watch_categories
import discord
import requests
import aiohttp
from discord import app_commands
from discord.ext import commands
import threading
try:
    from dotenv import load_dotenv
    load_dotenv ( )  # charge .env si présent (utile en local ; sur l'hébergeur, les variables sont mises dans son dashboard)
except ImportError:
    pass

# ------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------
# ⚠️ Le token et le secret NE sont plus écrits en dur ici.
# Ils viennent des variables d'environnement (voir .env / README ) .
TOKEN = os.environ.get ( "DISCORD_TOKEN")
OWNER_ID = int ( os.environ.get ( "OWNER_ID", "0" ) )
RENEWAL_CHANNEL_ID = 371751530824728579
API_SECRET = os.environ.get ( "DISCORD_BOT_API_SECRET")
SITE_URL = os.environ.get ( "SITE_URL", "https://jules88.pythonanywhere.com")

intents = discord.Intents.default ( )
intents.message_content = True
intents.members = True

bot = commands.Bot ( command_prefix="!", intents=intents)
bot.remove_command ( "help")

# ------------------------------------------------------------
# GESTION DES PERMISSIONS (fichier permissions.json)
# ------------------------------------------------------------
PERMS_FILE = "permissions.json"


def load_perms (  ) :
    if not os.path.exists ( PERMS_FILE ) :
        data = {"authorized_users": [], "maintenance": False}
        save_perms ( data)
        return data
    with open ( PERMS_FILE, "r") as f:
        return json.load ( f)


def save_perms ( data ) :
    with open ( PERMS_FILE, "w") as f:
        json.dump ( data, f, indent=2)


def has_dashboard_access ( user_id: int) -> bool:
    perms = load_perms ( )
    if user_id == OWNER_ID:
        return True
    if perms["maintenance"]:
        return False
    return user_id in perms["authorized_users"]


def is_owner (  ) :
    async def predicate ( interaction: discord.Interaction ) :
        return interaction.user.id == OWNER_ID
    return app_commands.check ( predicate)


def has_access (  ) :
    async def predicate ( interaction: discord.Interaction ) :
        return has_dashboard_access ( interaction.user.id)
    return app_commands.check ( predicate)


# ------------------------------------------------------------
# BLAGUES (pour la commande /blague)
# ------------------------------------------------------------
BLAGUES = [
    "Pourquoi les plongeurs plongent-ils toujours en arrière et jamais en avant ? Parce que sinon ils tombent dans le bateau !",
    "Qu'est-ce qui est jaune et qui attend ? Jonathan.",
    "Quel est le comble pour un électricien ? De ne pas être au courant.",
    "Pourquoi les poissons détestent-ils l'ordinateur ? Ils ont peur du net.",
    "Que dit un mur à un autre mur ? On se retrouve au coin !",
]


# ------------------------------------------------------------
# ÉVÉNEMENTS
# ------------------------------------------------------------
_slash_commands_synced = False


@bot.event
async def on_ready (  ) :
    global _slash_commands_synced
    if not _slash_commands_synced:
        try:
            # Publication globale (peut prendre un peu de temps côté Discord ) .
            synced = await bot.tree.sync ( )
            print ( f"{len ( synced ) } commande ( s) globale ( s) synchronisée ( s ) .")

            # Copie aussi les commandes globales dans chaque serveur du bot :
            # elles deviennent visibles plus rapidement dans ces serveurs.
            for guild in bot.guilds:
                bot.tree.copy_global_to ( guild=guild)
                guild_synced = await bot.tree.sync ( guild=guild)
                print(
                    f"[slash] {len ( guild_synced ) } commande ( s) synchronisée ( s) "
                    f"sur le serveur {guild.name} ({guild.id} ) ."
                )

            _slash_commands_synced = True
        except Exception as e:
            print ( f"Erreur de synchronisation des commandes : {e}")
    print ( f"{bot.user} est connecté et en ligne sur {len ( bot.guilds ) } serveur ( s ) .")

@bot.event
async def on_message ( message ) :
    if message.author.bot:
        return

    contenu_global = message.content.lower ( )

    # Bonjour / bonne nuit / merci -- pas besoin de mentionner le bot
    if "bonjour" in contenu_global:
        await message.channel.send ( f"Bonjour {message.author.mention} !")
    elif "bonne nuit" in contenu_global:
        await message.channel.send ( f"Bonne nuit {message.author.mention} !")
    elif "merci Jules88!!" in contenu_global:
        await message.channel.send ( f"Avec plaisir, {message.author.mention} !")

    # Ça va / coucou / salut -- nécessite la mention du bot
    if bot.user.mentioned_in ( message ) :
        contenu = message.content.lower ( )
        if "ça va" in contenu or "ca va" in contenu:
            await message.channel.send ( "oui ça va et toi ?")
        elif "coucou" in contenu:
            await message.channel.send ( "coucou !")
        elif "salut" in contenu:
            await message.channel.send ( "salut !")

    await bot.process_commands ( message)


@bot.tree.error
async def on_app_command_error ( interaction: discord.Interaction, error ) :
    if isinstance ( error, app_commands.CheckFailure ) :
        await interaction.response.send_message ( "⛔ Tu n'as pas accès à cette commande.", ephemeral=True)
    else:
        await interaction.response.send_message ( f"❌ Erreur : {error}", ephemeral=True)
        raise error


# ------------------------------------------------------------
# GESTION DES PERMISSIONS (réservé au propriétaire)
# ------------------------------------------------------------
@bot.tree.command ( name="autoriser", description="Donne accès au dashboard à quelqu'un")
@is_owner ( )
async def autoriser ( interaction: discord.Interaction, membre: discord.Member ) :
    perms = load_perms ( )
    if membre.id not in perms["authorized_users"]:
        perms["authorized_users"].append ( membre.id)
        save_perms ( perms)
        await interaction.response.send_message ( f"✅ {membre.mention} a maintenant accès au dashboard.")
    else:
        await interaction.response.send_message ( f"{membre.mention} est déjà autorisé.")


@bot.tree.command ( name="revoquer", description="Retire l'accès au dashboard à quelqu'un")
@is_owner ( )
async def revoquer ( interaction: discord.Interaction, membre: discord.Member ) :
    perms = load_perms ( )
    if membre.id in perms["authorized_users"]:
        perms["authorized_users"].remove ( membre.id)
        save_perms ( perms)
        await interaction.response.send_message ( f"✅ Accès retiré à {membre.mention}.")
    else:
        await interaction.response.send_message ( f"{membre.mention} n'était pas autorisé.")


@bot.tree.command ( name="liste_acces", description="Affiche qui a accès au dashboard")
@is_owner ( )
async def liste_acces ( interaction: discord.Interaction ) :
    perms = load_perms ( )
    if not perms["authorized_users"]:
        await interaction.response.send_message ( "Personne n'est autorisé pour l'instant (à part toi ) .")
        return
    noms = []
    for uid in perms["authorized_users"]:
        membre = interaction.guild.get_member ( uid)
        noms.append ( membre.mention if membre else str ( uid ) )
    await interaction.response.send_message ( "Personnes autorisées : " + ", ".join ( noms ) )


@bot.tree.command ( name="maintenance", description="Active/désactive le mode maintenance (bloque tout sauf toi ) ")
@app_commands.describe ( etat="on ou off")
@is_owner ( )
async def maintenance ( interaction: discord.Interaction, etat: str ) :
    perms = load_perms ( )
    if etat.lower ( ) in ("on", "actif", "oui" ) :
        perms["maintenance"] = True
        save_perms ( perms)
        await interaction.response.send_message ( "🔒 Mode maintenance activé. Seul toi as accès au dashboard.")
    elif etat.lower ( ) in ("off", "inactif", "non" ) :
        perms["maintenance"] = False
        save_perms ( perms)
        await interaction.response.send_message ( "🔓 Mode maintenance désactivé.")
    else:
        await interaction.response.send_message ( "Utilise `on` ou `off`.")


# ------------------------------------------------------------
# AUTHENTIFICATION (lien du compte Discord au compte Vikidia)
# ------------------------------------------------------------
@bot.tree.command ( name="auth", description="Lie ton compte Discord à ton compte Vikidia")
async def auth_cmd ( interaction: discord.Interaction ) :
    lien = f"{SITE_URL}/oauth/login?discord_id={interaction.user.id}"
    await interaction.response.send_message(
        "🔗 Clique sur ce lien pour connecter ton compte Vikidia à Discord :\n"
        f"{lien}\n\n"
        "Tu seras redirigé vers Vikidia pour te connecter, puis renvoyé vers le site — c'est tout !",
        ephemeral=True
    )


# ------------------------------------------------------------
# SCRIPTS DU SITE (via l'API)
# ------------------------------------------------------------
scripts_group = app_commands.Group ( name="scripts", description="Gère les scripts du site et les scripts automatiques")

@scripts_group.command ( name="liste", description="Liste les scripts disponibles sur le site")
@has_access ( )
async def scripts_list ( interaction: discord.Interaction ) :
    await interaction.response.defer ( )
    try:
        reponse = requests.get(
            f"{SITE_URL}/api/discord/scripts",
            headers={"X-Api-Secret": API_SECRET},
            timeout=10,
        )
        donnees = reponse.json ( )
    except Exception:
        await interaction.followup.send ( "❌ Impossible de contacter le site pour l'instant.")
        return

    if reponse.status_code != 200:
        await interaction.followup.send ( f"❌ Erreur : {donnees.get ( 'erreur', 'inconnue' ) }")
        return

    if donnees["feu"] == "rouge":
        await interaction.followup.send ( "🔴 Le feu est au rouge sur le site, les scripts sont bloqués pour le moment.")
        return

    if not donnees["scripts"]:
        await interaction.followup.send ( "Aucun script disponible pour le moment.")
        return

    lignes = []
    for s in donnees["scripts"]:
        tag = " * ( demande un paramètre ) *" if s["demande_parametre"] else ""
        lignes.append ( f"**#{s['id']}** — {s['nom']}{tag}")
    await interaction.followup.send(
        "📜 Scripts disponibles :\n" + "\n".join ( lignes) + "\n\nLance avec `/lancer`"
    )


async def script_autocomplete ( interaction: discord.Interaction, current: str ) :
    """Propose les scripts disponibles (nom + numéro) pendant que tu tapes /lancer."""
    try:
        reponse = requests.get(
            f"{SITE_URL}/api/discord/scripts",
            headers={"X-Api-Secret": API_SECRET},
            timeout=5,
        )
        donnees = reponse.json ( )
        scripts = donnees.get ( "scripts", [])
    except Exception:
        return []

    choix = []
    for s in scripts:
        libelle = f"#{s['id']} — {s['nom']}"
        if current.lower ( ) in libelle.lower (  ) :
            choix.append ( app_commands.Choice ( name=libelle[:100], value=s["id"] ) )
    return choix[:25]  # Discord limite à 25 propositions max


@bot.tree.command ( name="lancer", description="Lance un script du site")
@app_commands.describe ( script_id="Choisis le script dans la liste", parametre="Paramètre optionnel (ex: nom de page ) ")
@app_commands.autocomplete ( script_id=script_autocomplete)
@has_access ( )
async def lancer ( interaction: discord.Interaction, script_id: int, parametre: str = None ) :
    await interaction.response.defer ( )

    # On récupère le nom du script pour l'afficher clairement dans la réponse.
    nom_script = f"#{script_id}"
    try:
        reponse_liste = requests.get(
            f"{SITE_URL}/api/discord/scripts",
            headers={"X-Api-Secret": API_SECRET},
            timeout=5,
        )
        for s in reponse_liste.json (  ) .get ( "scripts", [] ) :
            if s["id"] == script_id:
                nom_script = s["nom"]
                break
    except Exception:
        pass

    try:
        reponse = requests.post(
            f"{SITE_URL}/api/discord/lancer",
            headers={"X-Api-Secret": API_SECRET},
            json={
                "discord_id": str ( interaction.user.id ) ,
                "script_id": script_id,
                "parametre": parametre,
            },
            timeout=35,
        )
        donnees = reponse.json ( )
    except Exception:
        await interaction.followup.send ( "❌ Impossible de contacter le site pour l'instant.")
        return

    if donnees.get ( "ok" ) :
        await interaction.followup.send(
            f"✅ **{nom_script}** lancé !\n```\n{donnees['message']}\n```"
        )
    else:
        await interaction.followup.send ( f"❌ **{nom_script}** — {donnees.get ( 'message', 'Erreur inconnue.' ) }")


# ------------------------------------------------------------
# SCRIPTS AUTOMATIQUES : activation/désactivation globale
# ------------------------------------------------------------
from scripts_auto_control import (
    is_enabled as scripts_auto_enabled,
    toggle as toggle_scripts_auto,
    set_enabled as set_scripts_auto_enabled,
)


class ConfirmationArretView ( discord.ui.View ) :
    """Confirmation finale réservée au propriétaire du bot."""
    def __init__ ( self, requester_id: int, urgent: bool ) :
        super (  ) .__init__ ( timeout=600)
        self.requester_id = requester_id
        self.urgent = urgent

    async def interaction_check ( self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message(
                "⛔ Seul le propriétaire du bot peut confirmer ou refuser cette demande.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button ( label="Oui, confirmer", style=discord.ButtonStyle.danger)
    async def confirmer ( self, interaction: discord.Interaction, button: discord.ui.Button ) :
        # Désactive les boutons pour éviter plusieurs décisions sur la même demande.
        for item in self.children:
            item.disabled = True
        if self.urgent:
            await interaction.response.edit_message(
                content=f"✅ Arrêt d’urgence confirmé par {interaction.user.mention}. Le bot Discord va s’arrêter.",
                embed=None, view=self,
            )
            print ( f"[ARRET] Arrêt d'urgence confirmé par OWNER_ID={OWNER_ID}; demandeur={self.requester_id}")
            await asyncio.sleep ( 1)
            await bot.close ( )
            return

        set_scripts_auto_enabled ( False)
        await interaction.response.edit_message(
            content=f"✅ Demande acceptée par {interaction.user.mention} : les scripts automatiques sont maintenant désactivés. Les commandes manuelles restent disponibles.",
            embed=None, view=self,
        )
        print ( f"[ARRET] Arrêt normal des scripts confirmé par OWNER_ID={OWNER_ID}; demandeur={self.requester_id}")

    @discord.ui.button ( label="Non, refuser", style=discord.ButtonStyle.secondary)
    async def refuser ( self, interaction: discord.Interaction, button: discord.ui.Button ) :
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=f"❎ Demande refusée par {interaction.user.mention}. Aucun arrêt n’a été effectué.",
            embed=None, view=self,
        )


class ConfirmationUrgenceView ( discord.ui.View ) :
    """Deuxième étape : le demandeur doit confirmer qu'il sollicite un arrêt d'urgence."""
    def __init__ ( self, requester_id: int ) :
        super (  ) .__init__ ( timeout=120)
        self.requester_id = requester_id

    @discord.ui.button ( label="Oui, demander l’arrêt d’urgence", style=discord.ButtonStyle.danger)
    async def demander ( self, interaction: discord.Interaction, button: discord.ui.Button ) :
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "⛔ Seule la personne qui a lancé cette demande peut confirmer cette étape.",
                ephemeral=True,
            )
            return
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=f"🚨 Demande transmise à <@{OWNER_ID}>. Le bot ne s’arrêtera pas tant que le propriétaire n’aura pas confirmé.",
            view=self,
            allowed_mentions=discord.AllowedMentions ( users=True ) ,
        )
        channel = interaction.channel
        if channel is None:
            try:
                channel = await interaction.user.create_dm ( )
            except discord.HTTPException:
                return
        embed = discord.Embed(
            title="🚨 Demande d’arrêt d’urgence du bot Discord",
            description=(
                f"{interaction.user.mention} demande un arrêt d’urgence du bot.\n\n"
                "Cela arrêtera le processus du bot Discord sur l’hébergeur. "
                "Confirme uniquement si tu souhaites réellement l’arrêter."
            ),
            color=discord.Color.dark_red (  ) ,
        )
        await channel.send(
            content=f"<@{OWNER_ID}> — confirmation personnelle requise.",
            embed=embed,
            view=ConfirmationArretView ( self.requester_id, urgent=True ) ,
            allowed_mentions=discord.AllowedMentions ( users=True ) ,
        )

    @discord.ui.button ( label="Annuler", style=discord.ButtonStyle.secondary)
    async def annuler ( self, interaction: discord.Interaction, button: discord.ui.Button ) :
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message ( "Seul le demandeur peut annuler cette étape.", ephemeral=True)
            return
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message ( content="Demande d’arrêt d’urgence annulée. Le bot continue de fonctionner.", view=self)


class DemandeArretView ( discord.ui.View ) :
    """Choix entre arrêt normal des scripts et demande d'arrêt d'urgence du bot."""
    def __init__ ( self ) :
        super (  ) .__init__ ( timeout=300)

    @discord.ui.button ( label="Arrêt normal", style=discord.ButtonStyle.primary)
    async def arret_normal ( self, interaction: discord.Interaction, button: discord.ui.Button ) :
        await interaction.response.send_message(
            content=f"<@{OWNER_ID}> — {interaction.user.mention} demande l’arrêt normal des scripts automatiques. Acceptes-tu ?",
            embed=discord.Embed(
                title="Demande d’arrêt normal",
                description="Si tu acceptes, les scripts automatiques seront désactivés. Le bot et ses commandes manuelles resteront en fonctionnement.",
                color=discord.Color.orange (  ) ,
            ),
            view=ConfirmationArretView ( interaction.user.id, urgent=False ) ,
            allowed_mentions=discord.AllowedMentions ( users=True ) ,
        )

    @discord.ui.button ( label="Arrêt d’urgence", style=discord.ButtonStyle.danger)
    async def arret_urgence ( self, interaction: discord.Interaction, button: discord.ui.Button ) :
        await interaction.response.send_message(
            embed=discord.Embed(
                title="⚠️ Confirmation de l’arrêt d’urgence",
                description=(
                    f"Es-tu sûr de vouloir demander à <@{OWNER_ID}> l’arrêt d’urgence du bot Discord ?\n\n"
                    "Un deuxième message sera envoyé au propriétaire. Le bot ne s’arrêtera pas sans sa confirmation."
                ),
                color=discord.Color.dark_red (  ) ,
            ),
            view=ConfirmationUrgenceView ( interaction.user.id ) ,
            allowed_mentions=discord.AllowedMentions ( users=True ) ,
        )


@bot.tree.command ( name="arret", description="Demande un arrêt normal des scripts ou un arrêt d’urgence du bot")
async def arret_cmd ( interaction: discord.Interaction ) :
    embed = discord.Embed(
        title="Demande d’arrêt",
        description=(
            "Choisis le type de demande ci-dessous.\n\n"
            "**Arrêt normal :** demande au propriétaire de mettre en pause les scripts automatiques.\n"
            "**Arrêt d’urgence :** demande un arrêt complet du bot Discord, avec deux confirmations et l’accord final du propriétaire."
        ),
        color=discord.Color.blurple (  ) ,
    )
    await interaction.response.send_message ( embed=embed, view=DemandeArretView (  ) , ephemeral=True)


class ScriptsAutoView ( discord.ui.View ) :
    """Bouton persistant : chaque clic publie un nouveau message de statut."""
    def __init__ ( self ) :
        super (  ) .__init__ ( timeout=None)

    @discord.ui.button(
        label="Basculer l'état",
        style=discord.ButtonStyle.primary,
        custom_id="scripts_auto:toggle",
    )
    async def basculer ( self, interaction: discord.Interaction, button: discord.ui.Button ) :
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message(
                "⛔ Seul le propriétaire du bot peut activer ou désactiver les scripts automatiques.",
                ephemeral=True,
            )
            return

        enabled = toggle_scripts_auto ( )
        scripts = "• `typo_fix.py` — corrections typographiques FR/EN\n" \
                  "• `bienvenue.py` — messages de bienvenue\n" \
                  "• `alerte_et_autre.py` — surveillance des catégories et de la PDD"
        etat = "ACTIVÉS" if enabled else "DÉSACTIVÉS"
        couleur = discord.Color.green ( ) if enabled else discord.Color.red ( )
        embed = discord.Embed(
            title=f"Scripts automatiques {etat}",
            description=(
                ("Les scripts automatiques ont été réactivés." if enabled else
                 "Les scripts automatiques sont en pause.")
                + "\n\n**Scripts concernés :**\n" + scripts
                + "\n\nLes commandes manuelles de Discord, notamment `/minuteur`, `/ping`, `/diff` et `/historiques`, restent disponibles."
            ),
            color=couleur,
        )
        # Nouveau message à chaque clic : le message d'origine n'est pas modifié.
        await interaction.response.send_message ( embed=embed)


@scripts_group.command(
    name="auto",
    description="Affiche le bouton pour activer ou désactiver les scripts automatiques",
)
async def scripts_auto_cmd ( interaction: discord.Interaction ) :
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message(
            "⛔ Seul le propriétaire du bot peut utiliser cette commande.",
            ephemeral=True,
        )
        return

    enabled = scripts_auto_enabled ( )
    etat = "ACTIVÉS" if enabled else "DÉSACTIVÉS"
    embed = discord.Embed(
        title=f"Scripts automatiques {etat}",
        description=(
            "État global actuel de KataBump. Utilise le bouton pour basculer cet état.\n\n"
            "**Scripts concernés :**\n"
            "• `typo_fix.py` — corrections typographiques FR/EN\n"
            "• `bienvenue.py` — messages de bienvenue\n"
            "• `alerte_et_autre.py` — surveillance des catégories et de la PDD\n\n"
            "Les commandes manuelles comme `/minuteur`, `/ping`, `/diff` et `/historiques` continuent de fonctionner."
        ),
        color=discord.Color.green ( ) if enabled else discord.Color.red (  ) ,
    )
    await interaction.response.send_message ( embed=embed, view=ScriptsAutoView (  ) )


bot.tree.add_command ( scripts_group)


@bot.tree.command ( name="scripts_auto", description="Alias : active ou désactive les scripts automatiques")
async def scripts_auto_alias ( interaction: discord.Interaction ) :
    await scripts_auto_cmd ( interaction)


# ------------------------------------------------------------
# MINUTEUR DISCORD (/minuteur)
# ------------------------------------------------------------
MINUTEUR_AUTO_DELETE_SECONDS = 5 * 60
MINUTEUR_REFRESH_SECONDS = 1


def parse_duree_minuteur ( texte: str) -> int:
    """Convertit une durée comme 90s, 15m, 2h30m ou 1d 2h en secondes."""
    texte = texte.strip (  ) .lower ( )
    if not texte:
        raise ValueError ( "Indique une durée, par exemple `10m`, `1h30m` ou `2d 4h`.")

    # Accepte les unités françaises et anglaises, avec ou sans espaces.
    pattern = re.compile(
        r" ( \d+ ) \s* ( jours?|j|days?|d|heures?|hrs?|h|minutes?|mins?|m|secondes?|secs?|s ) ",
        re.IGNORECASE,
    )
    matches = list ( pattern.finditer ( texte ) )
    compact = re.sub ( r"\s+", "", texte)
    reconstruite = "".join ( m.group ( 0 ) .replace ( " ", "") for m in matches)
    if not matches or compact != reconstruite:
        raise ValueError ( "Format invalide. Exemples : `45s`, `10m`, `1h30m`, `2d 4h`.")

    total = 0
    for match in matches:
        nombre = int ( match.group ( 1 ) )
        unite = match.group ( 2 ) .lower ( )
        if unite.startswith (  ( "j", "d" )  ) :
            total += nombre * 86400
        elif unite.startswith (  ( "h", ) ) or unite.startswith ( "hr" ) :
            total += nombre * 3600
        elif unite.startswith ( "m" ) :
            total += nombre * 60
        else:
            total += nombre

    if total <= 0:
        raise ValueError ( "La durée doit être supérieure à zéro.")
    if total > 365 * 24 * 60 * 60:
        raise ValueError ( "La durée maximale est de 365 jours.")
    return total


def format_duree_minuteur ( secondes: float) -> str:
    """Affiche une durée lisible en jours, heures, minutes et secondes."""
    secondes = max ( 0, int ( secondes + 0.999 ) )
    jours, reste = divmod ( secondes, 86400)
    heures, reste = divmod ( reste, 3600)
    minutes, secs = divmod ( reste, 60)
    morceaux = []
    if jours:
        morceaux.append ( f"{jours} j")
    if heures:
        morceaux.append ( f"{heures} h")
    if minutes:
        morceaux.append ( f"{minutes} min")
    if secs or not morceaux:
        morceaux.append ( f"{secs} s")
    return " ".join ( morceaux)


class MinuteurView ( discord.ui.View ) :
    """Un seul bouton bascule entre démarrer et mettre en pause."""

    def __init__ ( self, duree_secondes: int, createur_id: int, titre: str | None = None ) :
        super (  ) .__init__ ( timeout=None)
        self.duree_totale = duree_secondes
        self.secondes_restantes = float ( duree_secondes)
        self.createur_id = createur_id
        self.titre = titre.strip (  ) [:100] if titre and titre.strip ( ) else "Minuteur"
        self.demarre = False
        self.termine = False
        self.dernier_depart = None
        self.pause_depuis = time.monotonic ( )
        self.fini_depuis = None
        self.message = None
        self.tache = None
        self.bouton.label = "Start"
        self.bouton.style = discord.ButtonStyle.success

    def temps_restant ( self) -> float:
        if self.demarre and self.dernier_depart is not None:
            ecoule = time.monotonic ( ) - self.dernier_depart
            return max ( 0.0, self.secondes_restantes - ecoule)
        return max ( 0.0, self.secondes_restantes)

    def creer_embed ( self) -> discord.Embed:
        restant = self.temps_restant ( )
        embed = discord.Embed ( title=self.titre, color=discord.Color.blurple (  ) )
        embed.add_field ( name="Temps restant", value=f"**{format_duree_minuteur ( restant ) }**", inline=False)
        if self.termine:
            embed.description = "Minuteur terminé. Ce message sera supprimé dans 5 minutes."
            embed.color = discord.Color.green ( )
        elif self.demarre:
            embed.description = "Minuteur en cours. Utilise le bouton pour le mettre en pause."
        else:
            embed.description = "Minuteur en pause. Appuie sur Start pour le démarrer."
        return embed

    async def actualiser_message ( self ) :
        if self.message is None:
            return
        try:
            await self.message.edit ( embed=self.creer_embed (  ) , view=self)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException ) :
            pass

    async def supprimer_message_apres ( self, secondes: int ) :
        await asyncio.sleep ( secondes)
        if self.message is not None:
            try:
                await self.message.delete ( )
            except (discord.NotFound, discord.Forbidden, discord.HTTPException ) :
                pass

    async def boucle_minuteur ( self ) :
        """Met à jour le message existant, sans envoyer de nouveau message."""
        try:
            while self.message is not None:
                await asyncio.sleep ( MINUTEUR_REFRESH_SECONDS)
                maintenant = time.monotonic ( )

                if self.termine:
                    if self.fini_depuis is not None and maintenant - self.fini_depuis >= MINUTEUR_AUTO_DELETE_SECONDS:
                        try:
                            await self.message.delete ( )
                        except (discord.NotFound, discord.Forbidden, discord.HTTPException ) :
                            pass
                        return
                    continue

                if not self.demarre:
                    if self.pause_depuis is not None and maintenant - self.pause_depuis >= MINUTEUR_AUTO_DELETE_SECONDS:
                        try:
                            await self.message.delete ( )
                        except (discord.NotFound, discord.Forbidden, discord.HTTPException ) :
                            pass
                        return
                    continue

                restant = self.temps_restant ( )
                if restant <= 0:
                    self.secondes_restantes = 0
                    self.demarre = False
                    self.termine = True
                    self.fini_depuis = time.monotonic ( )
                    self.bouton.disabled = True
                    await self.actualiser_message ( )
                    continue

                await self.actualiser_message ( )
        except asyncio.CancelledError:
            raise

    @discord.ui.button ( label="Start", style=discord.ButtonStyle.success)
    async def bouton ( self, interaction: discord.Interaction, button: discord.ui.Button ) :
        if self.termine:
            await interaction.response.send_message ( "Ce minuteur est terminé.", ephemeral=True)
            return

        if self.demarre:
            self.secondes_restantes = self.temps_restant ( )
            self.demarre = False
            self.dernier_depart = None
            self.pause_depuis = time.monotonic ( )
            button.label = "Start"
            button.style = discord.ButtonStyle.success
        else:
            self.demarre = True
            self.dernier_depart = time.monotonic ( )
            self.pause_depuis = None
            button.label = "Pause"
            button.style = discord.ButtonStyle.secondary

        await interaction.response.edit_message ( embed=self.creer_embed (  ) , view=self)


@bot.tree.command ( name="minuteur", description="Crée un minuteur avec un bouton Start/Pause")
@app_commands.describe(
    duree="Durée : 30s, 10m, 1h30m, 2d 4h, etc.",
    titre="Titre facultatif du minuteur",
)
async def minuteur ( interaction: discord.Interaction, duree: str, titre: str = "Minuteur" ) :
    try:
        secondes = parse_duree_minuteur ( duree)
    except ValueError as erreur:
        await interaction.response.send_message ( f"Durée invalide : {erreur}", ephemeral=True)
        return

    view = MinuteurView ( secondes, interaction.user.id, titre)
    await interaction.response.send_message ( embed=view.creer_embed (  ) , view=view)
    view.message = await interaction.original_response ( )
    view.tache = asyncio.create_task ( view.boucle_minuteur (  ) )


# ------------------------------------------------------------
# COMMANDES DE BASE
# ------------------------------------------------------------
@bot.tree.command ( name="ping", description="Vérifie que le bot répond")
async def ping ( interaction: discord.Interaction ) :
    latence_ms = round ( bot.latency * 1000)
    await interaction.response.send_message ( f"Pong ! ({latence_ms} ms ) ")


@bot.command ( name="test")
async def test ( ctx ) :
    await ctx.send ( "Ça marche !")


@bot.tree.command ( name="date", description="Affiche la date et l'heure actuelles")
async def date_cmd ( interaction: discord.Interaction ) :
    maintenant = datetime.now ( ZoneInfo ( "Europe/Paris" )  ) .strftime ( "%d/%m/%Y à %H:%M")
    await interaction.response.send_message ( f"Nous sommes le {maintenant}")

@bot.tree.command ( name="dédicace", description="Affiche les remerciements")
async def dedicace ( interaction: discord.Interaction ) :
    await interaction.response.send_message(
        "Merci à Célian, Janus, Linedwell, Bulest, Loulla Blackcurrant, Muffy, Menthe,  Bahati11, Thilp pour m'avoir encouragé sur vikidia et m'aider."
    )
    
@bot.tree.command ( name="blague", description="Raconte une blague")
async def blague_cmd ( interaction: discord.Interaction ) :
    await interaction.response.send_message ( random.choice ( BLAGUES ) )


@bot.tree.command ( name="stats", description="Affiche les statistiques de Vikidia")
async def stats_cmd ( interaction: discord.Interaction ) :
    await interaction.response.defer ( )
    try:
        async with aiohttp.ClientSession ( ) as session:
            url = "https://fr.vikidia.org/w/api.php?action=query&meta=siteinfo&siprop=statistics&format=json"
            async with session.get ( url, timeout=10) as resp:
                data = await resp.json ( )
                stats = data["query"]["statistics"]
                message = (
                    f"📊 **Statistiques Vikidia**\n"
                    f"Articles : {stats['articles']}\n"
                    f"Pages totales : {stats['pages']}\n"
                    f"Utilisateurs : {stats['users']}\n"
                    f"Utilisateurs actifs : {stats['activeusers']}\n"
                    f"Modifications : {stats['edits']}"
                )
                await interaction.followup.send ( message)
    except Exception as e:
        await interaction.followup.send ( f"❌ Impossible de récupérer les statistiques ({e} ) .")
# ==========================================================
# Commande /userinfo
# ==========================================================

VIKIDIA_API = "https://fr.vikidia.org/w/api.php"  # change en "https://en.vikidia.org/w/api.php" si besoin


# Threads de scripts automatiques : remplis au démarrage du bot.
SCRIPT_THREADS = {}

async def _tester_url ( session, url, params=None ) :
    try:
        async with session.get ( url, params=params, timeout=aiohttp.ClientTimeout ( total=8 ) ) as response:
            return response.status < 500
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError ) :
        return False


@bot.tree.command ( name="statut", description="Vérifie l'état du bot, de Vikidia, du site et des scripts")
async def statut_cmd ( interaction: discord.Interaction ) :
    await interaction.response.defer ( ephemeral=True)
    async with aiohttp.ClientSession ( ) as session:
        site_ok = await _tester_url ( session, SITE_URL)
        vikidia_ok = await _tester_url ( session, VIKIDIA_API, {"action": "query", "meta": "siteinfo", "format": "json"})

    scripts_actifs = scripts_auto_enabled ( )
    lignes = [
        f"**Bot Discord :** {'🟢 En ligne' if not bot.is_closed ( ) else '🔴 Arrêté'}",
        f"**Latence Discord :** {round ( bot.latency * 1000 ) } ms" if bot.latency is not None else "**Latence Discord :** inconnue",
        f"**Site PythonAnywhere :** {'🟢 Répond' if site_ok else '🔴 Ne répond pas'}",
        f"**API Vikidia :** {'🟢 Répond' if vikidia_ok else '🔴 Ne répond pas'}",
        f"**Scripts automatiques :** {'🟢 Activés' if scripts_actifs else '🔴 Désactivés'}",
    ]
    if SCRIPT_THREADS:
        for nom, thread in SCRIPT_THREADS.items (  ) :
            lignes.append ( f"**Thread {nom} :** {'🟢 actif' if thread.is_alive ( ) else '🔴 arrêté'}")
    else:
        lignes.append ( "**Threads des scripts :** état indisponible (démarrage non terminé ) .")
    embed = discord.Embed ( title="Statut de KataBump", description="\n".join ( lignes ) , color=discord.Color.green ( ) if site_ok and vikidia_ok else discord.Color.orange (  ) )
    embed.set_footer ( text="Un thread actif ne garantit pas à lui seul que le script fonctionne correctement.")
    await interaction.followup.send ( embed=embed, ephemeral=True)


class RechercheVikidiaView ( discord.ui.View ) :
    def __init__ ( self, results, index=0 ) :
        super (  ) .__init__ ( timeout=180)
        self.results = results
        self.index = index
        self._rebuild_link_button ( )

    def _rebuild_link_button ( self ) :
        # Le bouton lien est recréé à chaque changement de résultat.
        for item in list ( self.children ) :
            if getattr ( item, "custom_id", None) == "recherche:ouvrir" or getattr ( item, "label", None) == "Ouvrir l'article":
                self.remove_item ( item)
        result = self.results[self.index]
        title = result.get ( "title", "Article Vikidia")
        url = "https://fr.vikidia.org/wiki/" + quote ( title.replace ( " ", "_" ) , safe=" (  ) /:@")
        self.add_item ( discord.ui.Button ( label="Ouvrir l'article", style=discord.ButtonStyle.link, url=url, row=0 ) )

    def make_embed ( self, resume=None ) :
        result = self.results[self.index]
        title = result.get ( "title", "Article Vikidia")
        snippet = html.unescape ( re.sub ( r"<[^>]+>", "", result.get ( "snippet", "" )  ) )
        embed = discord.Embed ( title=title[:256], url="https://fr.vikidia.org/wiki/" + quote ( title.replace ( " ", "_" ) , safe=" (  ) /:@" ) , description= ( resume or snippet or "Aucun extrait disponible." ) [:4000], color=discord.Color.blurple (  ) )
        embed.set_footer ( text=f"Résultat {self.index + 1}/{len ( self.results ) } — Recherche Vikidia")
        return embed

    @discord.ui.button ( label="Résumé", style=discord.ButtonStyle.primary, row=1)
    async def resume ( self, interaction: discord.Interaction, button: discord.ui.Button ) :
        result = self.results[self.index]
        async with aiohttp.ClientSession ( ) as session:
            params = {"action": "query", "prop": "extracts", "exintro": 1, "explaintext": 1, "exchars": 1200, "titles": result.get ( "title", "" ) , "format": "json", "formatversion": 2}
            try:
                async with session.get ( VIKIDIA_API, params=params, timeout=aiohttp.ClientTimeout ( total=10 ) ) as response:
                    data = await response.json ( )
                pages = data.get ( "query", {} ) .get ( "pages", [])
                resume = pages[0].get ( "extract", "Aucun résumé disponible.") if pages else "Aucun résumé disponible."
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, IndexError ) :
                resume = "Impossible de récupérer le résumé pour le moment."
        await interaction.response.edit_message ( embed=self.make_embed ( resume ) , view=self)

    @discord.ui.button ( label="Autres résultats", style=discord.ButtonStyle.secondary, row=1)
    async def autres ( self, interaction: discord.Interaction, button: discord.ui.Button ) :
        self.index = (self.index + 1) % len ( self.results)
        self._rebuild_link_button ( )
        await interaction.response.edit_message ( embed=self.make_embed (  ) , view=self)


@bot.tree.command ( name="recherche", description="Recherche des articles sur Vikidia")
@app_commands.describe ( sujet="Sujet ou titre à rechercher sur Vikidia")
async def recherche_cmd ( interaction: discord.Interaction, sujet: str ) :
    await interaction.response.defer ( )
    sujet = sujet.strip ( )
    if not sujet:
        await interaction.followup.send ( "Indique un sujet à rechercher.", ephemeral=True)
        return
    params = {"action": "query", "list": "search", "srsearch": sujet, "srnamespace": 0, "srlimit": 10, "srprop": "snippet", "format": "json", "formatversion": 2}
    try:
        async with aiohttp.ClientSession ( ) as session:
            async with session.get ( VIKIDIA_API, params=params, timeout=aiohttp.ClientTimeout ( total=12 ) ) as response:
                response.raise_for_status ( )
                data = await response.json ( )
        results = data.get ( "query", {} ) .get ( "search", [])
        if not results:
            await interaction.followup.send ( f"Aucun article trouvé sur Vikidia pour **{sujet[:150]}**.")
            return
        view = RechercheVikidiaView ( results)
        await interaction.followup.send ( embed=view.make_embed (  ) , view=view)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as error:
        print ( f"[/recherche] Erreur API Vikidia : {error}")
        await interaction.followup.send ( "Impossible de contacter l'API Vikidia pour le moment.", ephemeral=True)


def is_ip ( text: str) -> bool:
    """Détection simple IPv4 / IPv6"""
    import re
    ipv4 = re.match ( r"^\d{1,3} ( \.\d{1,3} ) {3}$", text)
    ipv6 = re.match ( r"^[0-9a-fA-F:]+$", text) and ":" in text
    return bool ( ipv4 or ipv6)

@bot.tree.command ( name="userinfo", description="Affiche les infos d'un utilisateur ou d'une IP Vikidia")
@app_commands.describe ( pseudo="Nom d'utilisateur ou adresse IP Vikidia")
async def userinfo ( interaction: discord.Interaction, pseudo: str ) :
    await interaction.response.defer ( )

    async with aiohttp.ClientSession ( ) as session:

        if is_ip ( pseudo ) :
            # Cas IP : pas de compte, juste blocages + contributions
            embed = discord.Embed(
                title=f"📡 IP : {pseudo}",
                color=discord.Color.orange ( )
            )
            embed.add_field ( name="Type", value="Adresse IP (non-connecté ) ", inline=False)

            # Blocages
            params_blocks = {
                "action": "query", "list": "blocks", "bkip": pseudo,
                "format": "json", "bklimit": "5"
            }
            async with session.get ( VIKIDIA_API, params=params_blocks) as r:
                data_blocks = await r.json ( )
            blocks = data_blocks.get ( "query", {} ) .get ( "blocks", [])
            embed.add_field ( name="Blocages", value=str ( len ( blocks )  ) , inline=True)

            # Contributions
            params_contribs = {
                "action": "query", "list": "usercontribs", "ucuser": pseudo,
                "format": "json", "uclimit": "1", "ucprop": "timestamp"
            }
            async with session.get ( VIKIDIA_API, params=params_contribs) as r:
                data_contribs = await r.json ( )
            contribs = data_contribs.get ( "query", {} ) .get ( "usercontribs", [])
            if contribs:
                last_date = contribs[0]["timestamp"][:10]
                embed.add_field ( name="Dernière contribution", value=last_date, inline=True)
            else:
                embed.add_field ( name="Dernière contribution", value="Aucune trouvée", inline=True)

            embed.add_field(
                name="Page utilisateur",
                value=f"[Voir la page] ( https://fr.vikidia.org/wiki/Sp%C3%A9cial:Contributions/{pseudo} ) ",
                inline=False
            )

            await interaction.followup.send ( embed=embed)
            return

        # Cas compte utilisateur
        params_user = {
            "action": "query", "list": "users", "ususers": pseudo,
            "usprop": "groups|registration|editcount|blockinfo",
            "format": "json"
        }
        async with session.get ( VIKIDIA_API, params=params_user) as r:
            data_user = await r.json ( )

        users = data_user.get ( "query", {} ) .get ( "users", [])
        if not users or "missing" in users[0]:
            await interaction.followup.send ( f"❌ Aucun utilisateur trouvé pour `{pseudo}`.")
            return

        user = users[0]
        name = user.get ( "name", pseudo)
        registration = user.get ( "registration", "Inconnue")
        if registration and registration != "Inconnue":
            registration = registration[:10]
        editcount = user.get ( "editcount", 0)
        groups = user.get ( "groups", [])

        # Traduction des groupes utiles
        statuts = []
        if "autopatrolled" in groups:
            statuts.append ( "Autopatrolled")
        if "patrol" in groups or "patroller" in groups:
            statuts.append ( "Patrouilleur")
        if "autoconfirmed" in groups or "autoconfirmed" in groups:
            statuts.append ( "Autoconfirmé")
        if not statuts:
            statuts.append ( "Connecté (sans statut particulier ) ")

        # Blocages (historique via liste des logs de blocage)
        params_logs = {
            "action": "query", "list": "logevents", "letype": "block",
            "letitle": f"Utilisateur:{name}", "format": "json", "lelimit": "50"
        }
        async with session.get ( VIKIDIA_API, params=params_logs) as r:
            data_logs = await r.json ( )
        block_count = len ( data_logs.get ( "query", {} ) .get ( "logevents", [] ) )

        # Dernière contribution
        params_contribs = {
            "action": "query", "list": "usercontribs", "ucuser": name,
            "format": "json", "uclimit": "1", "ucprop": "timestamp"
        }
        async with session.get ( VIKIDIA_API, params=params_contribs) as r:
            data_contribs = await r.json ( )
        contribs = data_contribs.get ( "query", {} ) .get ( "usercontribs", [])
        last_contrib = contribs[0]["timestamp"][:10] if contribs else "Aucune"

        embed = discord.Embed(
            title=f"👤 {name}",
            color=discord.Color.blue ( )
        )
        embed.add_field ( name="Type", value="Compte utilisateur", inline=True)
        embed.add_field ( name="Créé le", value=registration, inline=True)
        embed.add_field ( name="Statuts", value=", ".join ( statuts ) , inline=False)
        embed.add_field ( name="Blocages reçus", value=str ( block_count ) , inline=True)
        embed.add_field ( name="Contributions totales", value=str ( editcount ) , inline=True)
        embed.add_field ( name="Dernière contribution", value=last_contrib, inline=True)
        embed.add_field(
            name="Page utilisateur",
            value=f"[Voir la page] ( https://fr.vikidia.org/wiki/Utilisateur:{name.replace ( ' ', '_' ) } ) ",
            inline=False
        )

        await interaction.followup.send ( embed=embed)

# ==========================================================
# BOUTONS DU RAPPORT DE VANDALISME
# ==========================================================
VANDALISME_NIVEAUX = ["Pas grave", "Faible", "Modéré", "Grave", "Très grave"]
VANDALISME_COULEURS = {
    "Pas grave": discord.Color.green (  ) ,
    "Faible": discord.Color.yellow (  ) ,
    "Modéré": discord.Color.orange (  ) ,
    "Grave": discord.Color.red (  ) ,
    "Très grave": discord.Color.dark_red (  ) ,
}


class VandalismeView ( discord.ui.View ) :
    def __init__ ( self, gravite: str, demandeur_id: int ) :
        super (  ) .__init__ ( timeout=None)
        self.gravite = gravite
        self.demandeur_id = demandeur_id
        self.termine = False
        self._actualiser_boutons ( )

    async def interaction_check ( self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.demandeur_id:
            await interaction.response.send_message(
                "⛔ Seule la personne qui a créé ce rapport peut modifier sa gravité ou le marquer comme fait.",
                ephemeral=True,
            )
            return False
        return True

    def _actualiser_boutons ( self ) :
        for item in self.children:
            if isinstance ( item, discord.ui.Button ) :
                if item.custom_id == "vandalisme:augmenter":
                    item.disabled = self.termine or self.gravite == VANDALISME_NIVEAUX[-1]
                elif item.custom_id == "vandalisme:fait":
                    item.disabled = self.termine

    @discord.ui.button ( label="Augmenter la gravité", style=discord.ButtonStyle.danger, emoji="⬆️", custom_id="vandalisme:augmenter")
    async def augmenter ( self, interaction: discord.Interaction, button: discord.ui.Button ) :
        if self.termine:
            await interaction.response.send_message ( "Ce rapport est déjà marqué comme fait.", ephemeral=True)
            return
        index = VANDALISME_NIVEAUX.index ( self.gravite)
        if index >= len ( VANDALISME_NIVEAUX) - 1:
            await interaction.response.send_message ( "La gravité est déjà au maximum.", ephemeral=True)
            return
        self.gravite = VANDALISME_NIVEAUX[index + 1]
        embed = interaction.message.embeds[0].copy ( )
        embed.color = VANDALISME_COULEURS[self.gravite]
        for field_index, field in enumerate ( embed.fields ) :
            if field.name == "⚖️ Gravité estimée":
                embed.set_field_at ( field_index, name=field.name, value=self.gravite, inline=field.inline)
                break
        embed.set_footer ( text="Gravité modifiée par le créateur du rapport • rapport informatif, pas une sanction")
        self._actualiser_boutons ( )
        await interaction.response.edit_message ( embed=embed, view=self)

    @discord.ui.button ( label="Marquer comme fait", style=discord.ButtonStyle.success, emoji="✅", custom_id="vandalisme:fait")
    async def marquer_fait ( self, interaction: discord.Interaction, button: discord.ui.Button ) :
        if self.termine:
            await interaction.response.send_message ( "Ce rapport est déjà marqué comme fait.", ephemeral=True)
            return
        self.termine = True
        embed = interaction.message.embeds[0].copy ( )
        embed.title = "✅ Rapport de vandalisme — FAIT"
        embed.color = discord.Color.green ( )
        embed.add_field ( name="📌 État", value=f"Marqué comme fait par {interaction.user.mention}", inline=False)
        self._actualiser_boutons ( )
        await interaction.response.edit_message ( embed=embed, view=self)



# ==========================================================
# COMMANDE /vandalisme
# ==========================================================

VANDALISME_GRAVITES = [
    app_commands.Choice ( name="Pas grave", value="Pas grave" ) ,
    app_commands.Choice ( name="Faible", value="Faible" ) ,
    app_commands.Choice ( name="Modéré", value="Modéré" ) ,
    app_commands.Choice ( name="Grave", value="Grave" ) ,
    app_commands.Choice ( name="Très grave", value="Très grave" ) ,
]


@bot.tree.command(
    name="vandalisme",
    description="Crée un rapport sur un vandalisme présumé sur Vikidia"
)
@app_commands.describe(
    pseudo="Nom exact du compte Vikidia",
    motif="Décris les modifications problématiques observées",
    gravite="Gravité estimée du cas"
)
@app_commands.choices ( gravite=VANDALISME_GRAVITES)
async def vandalisme(
    interaction: discord.Interaction,
    pseudo: str,
    motif: str,
    gravite: app_commands.Choice[str],
):
    # Répond tout de suite pour éviter que Discord expire l'interaction.
    await interaction.response.defer ( thinking=True)

    pseudo = pseudo.strip ( )
    motif = motif.strip ( )
    if not pseudo or not motif:
        await interaction.followup.send(
            "❌ Il faut indiquer le pseudo et le motif.", ephemeral=True
        )
        return

    params = {
        "action": "query",
        "list": "users",
        "ususers": pseudo,
        "usprop": "groups|registration|editcount|blockinfo",
        "format": "json",
        "formatversion": "2",
    }
    headers = {"User-Agent": "Jules88!!Bot/Discord-vandalisme (fr.vikidia.org ) "}

    try:
        timeout = aiohttp.ClientTimeout ( total=15)
        async with aiohttp.ClientSession ( timeout=timeout, headers=headers) as session:
            async with session.get ( VIKIDIA_API, params=params) as response:
                response.raise_for_status ( )
                data = await response.json ( )

        users = data.get ( "query", {} ) .get ( "users", [])
        user = users[0] if users else {}
        compte_trouve = bool ( user) and "missing" not in user

        if compte_trouve:
            nom = user.get ( "name", pseudo)
            contributions = str ( user.get ( "editcount", "Inconnues" ) )
            inscription = user.get ( "registration") or "Inconnue"
            if inscription != "Inconnue":
                inscription = inscription[:10]

            groupes = user.get ( "groups", [])
            statuts = []
            if "sysop" in groupes:
                statuts.append ( "Administrateur")
            if "patroller" in groupes or "patrol" in groupes:
                statuts.append ( "Patrouilleur")
            if "autopatrolled" in groupes:
                statuts.append ( "Autopatrolled")
            if not statuts:
                statuts.append ( "Aucun statut particulier détecté")

            # blockinfo n'indique un blocage que si l'API renvoie ces champs.
            bloque = "Oui" if "blockid" in user else "Aucun blocage actif indiqué par l'API"
        else:
            nom = pseudo
            contributions = "Inconnues"
            inscription = "Inconnue"
            statuts = ["Compte introuvable ou données indisponibles"]
            bloque = "Inconnu"

        couleur = VANDALISME_COULEURS.get ( gravite.value, discord.Color.orange (  ) )

        embed = discord.Embed(
            title="🛡️ Rapport de vandalisme présumé",
            description=(
                "Rapport informatif basé sur le motif saisi. "
                "Vérifie les diffs avant de conclure qu'il s'agit de vandalisme."
            ),
            color=couleur,
            timestamp=discord.utils.utcnow (  ) ,
        )
        embed.add_field ( name="👤 Utilisateur Vikidia", value=f"`{nom[:200]}`", inline=False)
        embed.add_field ( name="📝 Motif indiqué", value=motif[:1024], inline=False)
        embed.add_field ( name="⚖️ Gravité estimée", value=gravite.value, inline=True)
        embed.add_field ( name="✏️ Contributions", value=contributions, inline=True)
        embed.add_field ( name="📅 Inscription", value=inscription, inline=True)
        embed.add_field ( name="🏷️ Statut du compte", value=", ".join ( statuts ) [:1024], inline=False)
        embed.add_field ( name="🚫 Blocage actif", value=bloque, inline=False)

        nom_url = quote ( nom.replace ( " ", "_" ) , safe=" (  ) /:@")
        embed.add_field(
            name="🔎 Vérifier les contributions",
            value=f"[Ouvrir les contributions de {nom}] ( https://fr.vikidia.org/wiki/Spécial:Contributions/{nom_url} ) ",
            inline=False,
        )
        embed.set_footer ( text=f"Rapport créé par {interaction.user} • ce rapport n'est pas une sanction")

        await interaction.followup.send ( embed=embed, view=VandalismeView ( gravite.value, interaction.user.id ) )

    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        print ( f"[vandalisme] Erreur API Vikidia : {e}")
        await interaction.followup.send(
            "❌ Impossible de contacter l'API de Vikidia pour le moment. Réessaie plus tard.",
            ephemeral=True,
        )
    except Exception as e:
        print ( f"[vandalisme] Erreur inattendue : {type ( e ) .__name__}: {e}")
        await interaction.followup.send(
            "❌ Une erreur est survenue pendant la création du rapport. Consulte la console du bot.",
            ephemeral=True,
        )


# ============================================================
# AIDE VIKIDIA (explications simples, adaptées aux débutants)
# ============================================================
@bot.tree.command ( name="aide_vikidia", description="Explique les règles et les bonnes pratiques de Vikidia")
async def aide_vikidia ( interaction: discord.Interaction ) :
    pages = [
        ("📚 1. À quoi sert Vikidia ?", "Vikidia est une encyclopédie pour apprendre et partager des connaissances. Ce n'est pas un réseau social : on y écrit et améliore des articles." ) ,
        ("🤝 2. Respecter les autres", "Reste poli, même si tu n'es pas d'accord. Explique calmement le problème et discute sur la page de discussion. N'insulte pas et ne harcèle personne." ) ,
        ("✍️ 3. Bien écrire un article", "Écris des informations utiles, claires et faciles à comprendre. Ajoute une introduction, des exemples et des sources fiables quand c'est possible. Vérifie l'orthographe et évite les informations inventées." ) ,
        ("🔎 4. Les sources et le droit d'auteur", "N'invente pas de faits. Vérifie les informations avec des sources fiables. Ne copie pas un texte d'un site ou d'un livre : reformule avec tes propres mots. Pour les images, vérifie que leur licence permet leur réutilisation et indique les informations demandées." ) ,
        ("🛠️ 5. Modifier une page", "Clique sur « Modifier », fais tes changements, puis prévisualise pour vérifier le résultat. Avant de publier, écris un petit résumé qui explique ce que tu as changé." ) ,
        ("🕰️ 6. Historique et diff", "L'historique liste les anciennes versions d'une page et les personnes qui l'ont modifiée. Le diff compare deux versions et montre ce qui a été ajouté ou retiré. Utilise-les pour comprendre une modification avant de la juger." ) ,
        ("🚫 7. Que faire face à un vandalisme ?", "Un vandalisme est une modification qui abîme volontairement une page, par exemple en effaçant du contenu sans raison ou en ajoutant des insultes. Une erreur n'est pas forcément du vandalisme. Vérifie le diff, compare avec les sources et demande conseil si tu hésites. Ne harcèle pas la personne." ) ,
        ("↩️ 8. Annuler une mauvaise modification", "Si tu sais quelle version était correcte, tu peux revenir à cette version selon les outils dont tu disposes. Explique ton annulation dans le résumé. Si tu n'es pas sûr, demande de l'aide à un contributeur expérimenté ou à un administrateur." ) ,
        ("🗳️ 9. Discussions et votes", "Sois poli, lis la question et les règles du vote, puis explique ton avis avec des raisons. N'essaie pas de forcer les autres à voter comme toi. Pour une dispute, cherche d'abord une solution calme et demande une médiation si besoin." ) ,
        ("🛡️ 10. Rôles et signalements", "Tout le monde peut aider à améliorer les articles, mais certaines actions techniques sont réservées aux administrateurs. Un signalement n'est pas une condamnation : donne des faits vérifiables et laisse les personnes responsables examiner le cas." ) ,
        ("🔗 Pages officielles utiles", "Lis les règles complètes et les pages d'aide de Vikidia :\n[Vikidia:Règles] ( https://fr.vikidia.org/wiki/Vikidia:Règles) · [Comment modifier] ( https://fr.vikidia.org/wiki/Aide:Comment_modifier_une_page) · [Historique] ( https://fr.vikidia.org/wiki/Aide:Historique) · [Modifications récentes] ( https://fr.vikidia.org/wiki/Aide:Modifications_récentes) · [Révocation] ( https://fr.vikidia.org/wiki/Aide:Révocation ) . Les règles du wiki peuvent évoluer : les pages officielles font foi." ) ,
    ]
    embeds = []
    for titre, texte in pages:
        embeds.append ( discord.Embed ( title=titre, description=texte, color=discord.Color.blurple (  )  ) )
    await interaction.response.send_message ( embeds=embeds[:10], ephemeral=True)
    if len ( embeds) > 10:
        await interaction.followup.send ( embeds=embeds[10:], ephemeral=True)


# ============================================================
# /diff : compare les deux dernières versions d'une page
# ============================================================
@bot.tree.command ( name="diff", description="Compare les deux dernières versions d'une page Vikidia")
@app_commands.describe ( page="Titre de la page, par exemple Histoire de France")
async def diff_cmd ( interaction: discord.Interaction, page: str ) :
    await interaction.response.defer ( thinking=True)
    params = {
        "action": "query", "prop": "revisions", "titles": page,
        "rvprop": "ids|timestamp|user|comment", "rvlimit": "2",
        "rvdir": "older", "format": "json", "formatversion": "2"
    }
    try:
        async with aiohttp.ClientSession ( ) as session:
            async with session.get ( VIKIDIA_API, params=params, timeout=aiohttp.ClientTimeout ( total=15 ) ) as response:
                response.raise_for_status ( )
                data = await response.json ( )
        pages = data.get ( "query", {} ) .get ( "pages", [])
        found = next (  ( x for x in pages if not x.get ( "missing" )  ) , None)
        revisions = found.get ( "revisions", []) if found else []
        if not found or len ( revisions) < 2:
            await interaction.followup.send ( "Je n'ai pas trouvé deux versions à comparer pour cette page.")
            return
        # L'API retourne ici la version la plus récente en premier.
        recent, previous = revisions[0], revisions[1]
        title = found.get ( "title", page)
        url = "https://fr.vikidia.org/wiki/Spécial:Diff/{}".format ( recent["revid"])
        embed = discord.Embed ( title=f"🔎 Comparaison : {title[:200]}", description=f"[Voir le diff sur Vikidia] ( {url} ) ", color=discord.Color.blurple (  ) )
        embed.add_field ( name="Version récente", value=f"ID : {recent.get ( 'revid' ) }\nAuteur : {recent.get ( 'user', 'inconnu' ) }\nDate : {recent.get ( 'timestamp', 'inconnue' ) }", inline=True)
        embed.add_field ( name="Version précédente", value=f"ID : {previous.get ( 'revid' ) }\nAuteur : {previous.get ( 'user', 'inconnu' ) }\nDate : {previous.get ( 'timestamp', 'inconnue' ) }", inline=True)
        embed.add_field ( name="Résumé récent", value= ( recent.get ( "comment") or "Aucun résumé" ) [:1024], inline=False)
        embed.set_footer ( text="Un diff aide à vérifier les changements ; il ne prouve pas à lui seul un vandalisme.")
        await interaction.followup.send ( embed=embed)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
        print ( f"[/diff] Erreur API Vikidia : {e}")
        await interaction.followup.send ( "❌ Impossible de récupérer les versions de cette page pour le moment.", ephemeral=True)


# ============================================================
# /historiques : affiche les dernières modifications d'une page
# ============================================================
@bot.tree.command ( name="historiques", description="Affiche les dernières modifications d'une page Vikidia")
@app_commands.describe ( page="Titre de la page, par exemple Histoire de France")
async def historiques_cmd ( interaction: discord.Interaction, page: str ) :
    await interaction.response.defer ( thinking=True)
    params = {
        "action": "query", "prop": "revisions", "titles": page,
        "rvprop": "ids|timestamp|user|comment|size", "rvlimit": "5",
        "rvdir": "older", "format": "json", "formatversion": "2"
    }
    try:
        async with aiohttp.ClientSession ( ) as session:
            async with session.get ( VIKIDIA_API, params=params, timeout=aiohttp.ClientTimeout ( total=15 ) ) as response:
                response.raise_for_status ( )
                data = await response.json ( )
        pages = data.get ( "query", {} ) .get ( "pages", [])
        found = next (  ( x for x in pages if not x.get ( "missing" )  ) , None)
        revisions = found.get ( "revisions", []) if found else []
        if not found or not revisions:
            await interaction.followup.send ( "Je n'ai trouvé aucun historique pour cette page.")
            return
        title = found.get ( "title", page)
        safe_title = quote ( title.replace ( " ", "_" ) , safe=" (  ) /:@")
        embed = discord.Embed ( title=f"🕰️ Historique : {title[:200]}", description=f"[Ouvrir l'historique complet] ( https://fr.vikidia.org/wiki/Spécial:Historique/{safe_title} ) ", color=discord.Color.blurple (  ) )
        for rev in revisions:
            date = rev.get ( "timestamp", "date inconnue" ) .replace ( "T", " " ) .replace ( "Z", " UTC")
            resume = (rev.get ( "comment") or "Aucun résumé" ) [:180]
            taille = rev.get ( "size", "?")
            valeur = f"Auteur : {rev.get ( 'user', 'inconnu' ) }\nDate : {date}\nTaille : {taille} octets\nRésumé : {resume}\n[Voir cette version] ( https://fr.vikidia.org/wiki/Spécial:Diff/{rev.get ( 'revid' ) } ) "
            embed.add_field ( name=f"Version {rev.get ( 'revid', '?' ) }", value=valeur[:1024], inline=False)
        embed.set_footer ( text="L'historique montre qui a modifié la page et quand ; vérifie le contenu avant de tirer une conclusion.")
        await interaction.followup.send ( embed=embed)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
        print ( f"[/historiques] Erreur API Vikidia : {e}")
        await interaction.followup.send ( "❌ Impossible de récupérer l'historique de cette page pour le moment.", ephemeral=True)


# ------------------------------------------------------------
# LANCEMENT DU BOT
# ------------------------------------------------------------
if __name__ == "__main__":
    if not TOKEN:
        print ( "ERREUR : le token n'est pas défini (variable d'environnement DISCORD_TOKEN manquante ) .")
    else:
        from bienvenue import boucle_bienvenue
        from typo_fix import watch_and_fix_typo
        SCRIPT_THREADS["bienvenue"] = threading.Thread ( target=boucle_bienvenue, daemon=True, name="script-bienvenue")
        SCRIPT_THREADS["typo"] = threading.Thread ( target=watch_and_fix_typo, daemon=True, name="script-typo")
        SCRIPT_THREADS["categories"] = threading.Thread ( target=start_watch_categories, args= ( bot, OWNER_ID ) , daemon=True, name="script-categories")
        for thread in SCRIPT_THREADS.values (  ) :
            thread.start ( )

        # Rend le bouton existant utilisable après un redémarrage du bot.
        bot.add_view ( ScriptsAutoView (  ) )
        bot.run ( TOKEN)
