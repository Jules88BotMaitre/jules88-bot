import os
import json
import random
from datetime import datetime
from zoneinfo import ZoneInfo
from discord.ext import tasks
import discord
import requests
import aiohttp
from discord import app_commands
from discord.ext import commands

try:
    from dotenv import load_dotenv
    load_dotenv()  # charge .env si présent (utile en local ; sur l'hébergeur, les variables sont mises dans son dashboard)
except ImportError:
    pass

# ------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------
# ⚠️ Le token et le secret NE sont plus écrits en dur ici.
# Ils viennent des variables d'environnement (voir .env / README).
TOKEN = os.environ.get("DISCORD_TOKEN")
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))

API_SECRET = os.environ.get("DISCORD_BOT_API_SECRET")
SITE_URL = os.environ.get("SITE_URL", "https://jules88.pythonanywhere.com")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
bot.remove_command("help")

# ------------------------------------------------------------
# GESTION DES PERMISSIONS (fichier permissions.json)
# ------------------------------------------------------------
PERMS_FILE = "permissions.json"


def load_perms():
    if not os.path.exists(PERMS_FILE):
        data = {"authorized_users": [], "maintenance": False}
        save_perms(data)
        return data
    with open(PERMS_FILE, "r") as f:
        return json.load(f)


def save_perms(data):
    with open(PERMS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def has_dashboard_access(user_id: int) -> bool:
    perms = load_perms()
    if user_id == OWNER_ID:
        return True
    if perms["maintenance"]:
        return False
    return user_id in perms["authorized_users"]


def is_owner():
    async def predicate(interaction: discord.Interaction):
        return interaction.user.id == OWNER_ID
    return app_commands.check(predicate)


def has_access():
    async def predicate(interaction: discord.Interaction):
        return has_dashboard_access(interaction.user.id)
    return app_commands.check(predicate)


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
@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"{len(synced)} commande(s) slash synchronisée(s).")
    except Exception as e:
        print(f"Erreur de synchronisation des commandes : {e}")
    print(f"{bot.user} est connecté et en ligne sur {len(bot.guilds)} serveur(s).")


@bot.event
async def on_member_join(member):
    channel = member.guild.system_channel
    if channel is not None:
        await channel.send(f"Bienvenue sur le serveur {member.mention} ! 🎉")


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    contenu_global = message.content.lower()

    # Bonjour / bonne nuit / merci -- pas besoin de mentionner le bot
    if "bonjour" in contenu_global:
        await message.channel.send(f"Bonjour {message.author.mention} !")
    elif "bonne nuit" in contenu_global:
        await message.channel.send(f"Bonne nuit {message.author.mention} !")
    elif "merci Jules88!!" in contenu_global:
        await message.channel.send(f"Avec plaisir, {message.author.mention} !")

    # Ça va / coucou / salut -- nécessite la mention du bot
    if bot.user.mentioned_in(message):
        contenu = message.content.lower()
        if "ça va" in contenu or "ca va" in contenu:
            await message.channel.send("oui ça va et toi ?")
        elif "coucou" in contenu:
            await message.channel.send("coucou !")
        elif "salut" in contenu:
            await message.channel.send("salut !")

    await bot.process_commands(message)


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message("⛔ Tu n'as pas accès à cette commande.", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ Erreur : {error}", ephemeral=True)
        raise error


# ------------------------------------------------------------
# GESTION DES PERMISSIONS (réservé au propriétaire)
# ------------------------------------------------------------
@bot.tree.command(name="autoriser", description="Donne accès au dashboard à quelqu'un")
@is_owner()
async def autoriser(interaction: discord.Interaction, membre: discord.Member):
    perms = load_perms()
    if membre.id not in perms["authorized_users"]:
        perms["authorized_users"].append(membre.id)
        save_perms(perms)
        await interaction.response.send_message(f"✅ {membre.mention} a maintenant accès au dashboard.")
    else:
        await interaction.response.send_message(f"{membre.mention} est déjà autorisé.")


@bot.tree.command(name="revoquer", description="Retire l'accès au dashboard à quelqu'un")
@is_owner()
async def revoquer(interaction: discord.Interaction, membre: discord.Member):
    perms = load_perms()
    if membre.id in perms["authorized_users"]:
        perms["authorized_users"].remove(membre.id)
        save_perms(perms)
        await interaction.response.send_message(f"✅ Accès retiré à {membre.mention}.")
    else:
        await interaction.response.send_message(f"{membre.mention} n'était pas autorisé.")


@bot.tree.command(name="liste_acces", description="Affiche qui a accès au dashboard")
@is_owner()
async def liste_acces(interaction: discord.Interaction):
    perms = load_perms()
    if not perms["authorized_users"]:
        await interaction.response.send_message("Personne n'est autorisé pour l'instant (à part toi).")
        return
    noms = []
    for uid in perms["authorized_users"]:
        membre = interaction.guild.get_member(uid)
        noms.append(membre.mention if membre else str(uid))
    await interaction.response.send_message("Personnes autorisées : " + ", ".join(noms))


@bot.tree.command(name="maintenance", description="Active/désactive le mode maintenance (bloque tout sauf toi)")
@app_commands.describe(etat="on ou off")
@is_owner()
async def maintenance(interaction: discord.Interaction, etat: str):
    perms = load_perms()
    if etat.lower() in ("on", "actif", "oui"):
        perms["maintenance"] = True
        save_perms(perms)
        await interaction.response.send_message("🔒 Mode maintenance activé. Seul toi as accès au dashboard.")
    elif etat.lower() in ("off", "inactif", "non"):
        perms["maintenance"] = False
        save_perms(perms)
        await interaction.response.send_message("🔓 Mode maintenance désactivé.")
    else:
        await interaction.response.send_message("Utilise `on` ou `off`.")


# ------------------------------------------------------------
# SCRIPTS DU SITE (via l'API)
# ------------------------------------------------------------
@bot.tree.command(name="scripts", description="Liste les scripts disponibles sur le site")
@has_access()
async def scripts_list(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        reponse = requests.get(
            f"{SITE_URL}/api/discord/scripts",
            headers={"X-Api-Secret": API_SECRET},
            timeout=10,
        )
        donnees = reponse.json()
    except Exception:
        await interaction.followup.send("❌ Impossible de contacter le site pour l'instant.")
        return

    if reponse.status_code != 200:
        await interaction.followup.send(f"❌ Erreur : {donnees.get('erreur', 'inconnue')}")
        return

    if donnees["feu"] == "rouge":
        await interaction.followup.send("🔴 Le feu est au rouge sur le site, les scripts sont bloqués pour le moment.")
        return

    if not donnees["scripts"]:
        await interaction.followup.send("Aucun script disponible pour le moment.")
        return

    lignes = []
    for s in donnees["scripts"]:
        tag = " *(demande un paramètre)*" if s["demande_parametre"] else ""
        lignes.append(f"**#{s['id']}** — {s['nom']}{tag}")
    await interaction.followup.send(
        "📜 Scripts disponibles :\n" + "\n".join(lignes) + "\n\nLance avec `/lancer`"
    )


async def script_autocomplete(interaction: discord.Interaction, current: str):
    """Propose les scripts disponibles (nom + numéro) pendant que tu tapes /lancer."""
    try:
        reponse = requests.get(
            f"{SITE_URL}/api/discord/scripts",
            headers={"X-Api-Secret": API_SECRET},
            timeout=5,
        )
        donnees = reponse.json()
        scripts = donnees.get("scripts", [])
    except Exception:
        return []

    choix = []
    for s in scripts:
        libelle = f"#{s['id']} — {s['nom']}"
        if current.lower() in libelle.lower():
            choix.append(app_commands.Choice(name=libelle[:100], value=s["id"]))
    return choix[:25]  # Discord limite à 25 propositions max


@bot.tree.command(name="lancer", description="Lance un script du site")
@app_commands.describe(script_id="Choisis le script dans la liste", parametre="Paramètre optionnel (ex: nom de page)")
@app_commands.autocomplete(script_id=script_autocomplete)
@has_access()
async def lancer(interaction: discord.Interaction, script_id: int, parametre: str = None):
    await interaction.response.defer()

    # On récupère le nom du script pour l'afficher clairement dans la réponse.
    nom_script = f"#{script_id}"
    try:
        reponse_liste = requests.get(
            f"{SITE_URL}/api/discord/scripts",
            headers={"X-Api-Secret": API_SECRET},
            timeout=5,
        )
        for s in reponse_liste.json().get("scripts", []):
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
                "discord_id": str(interaction.user.id),
                "script_id": script_id,
                "parametre": parametre,
            },
            timeout=35,
        )
        donnees = reponse.json()
    except Exception:
        await interaction.followup.send("❌ Impossible de contacter le site pour l'instant.")
        return

    if donnees.get("ok"):
        await interaction.followup.send(
            f"✅ **{nom_script}** lancé !\n```\n{donnees['message']}\n```"
        )
    else:
        await interaction.followup.send(f"❌ **{nom_script}** — {donnees.get('message', 'Erreur inconnue.')}")


# ------------------------------------------------------------
# COMMANDES DE BASE
# ------------------------------------------------------------
@bot.tree.command(name="ping", description="Vérifie que le bot répond")
async def ping(interaction: discord.Interaction):
    latence_ms = round(bot.latency * 1000)
    await interaction.response.send_message(f"Pong ! ({latence_ms} ms)")


@bot.command(name="test")
async def test(ctx):
    await ctx.send("Ça marche !")

@bot.tree.command(name="dédicace", description="Affiche les remerciements")
async def dedicace(interaction: discord.Interaction):
    await interaction.response.send_message(
        "Merci à Célian, Janus, Muffy Linedwell, Bulest, Bahati11, Thilp, Blackcurrant pour m'avoir encouragé sur vikidia et m'aider."
    )

@bot.tree.command(name="date", description="Affiche la date et l'heure actuelles")
async def date_cmd(interaction: discord.Interaction):
    maintenant = datetime.now(ZoneInfo("Europe/Paris")).strftime("%d/%m/%Y à %H:%M")
    await interaction.response.send_message(f"Nous sommes le {maintenant}")


@bot.tree.command(name="blague", description="Raconte une blague")
async def blague_cmd(interaction: discord.Interaction):
    await interaction.response.send_message(random.choice(BLAGUES))


@bot.tree.command(name="stats", description="Affiche les statistiques de Vikidia")
async def stats_cmd(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        async with aiohttp.ClientSession() as session:
            url = "https://fr.vikidia.org/w/api.php?action=query&meta=siteinfo&siprop=statistics&format=json"
            async with session.get(url, timeout=10) as resp:
                data = await resp.json()
                stats = data["query"]["statistics"]
                message = (
                    f"📊 **Statistiques Vikidia**\n"
                    f"Articles : {stats['articles']}\n"
                    f"Pages totales : {stats['pages']}\n"
                    f"Utilisateurs : {stats['users']}\n"
                    f"Utilisateurs actifs : {stats['activeusers']}\n"
                    f"Modifications : {stats['edits']}"
                )
                await interaction.followup.send(message)
    except Exception as e:
        await interaction.followup.send(f"❌ Impossible de récupérer les statistiques ({e}).")
# ==========================================================
# Commande /userinfo — à coller dans app.py (KataBump)
# Va dans la classe/fichier où sont déjà déclarées tes autres
# commandes slash (comme /stats, /date, /blague)
# ==========================================================

import aiohttp
import discord
from discord import app_commands
from datetime import datetime

VIKIDIA_API = "https://fr.vikidia.org/w/api.php"  # change en "https://en.vikidia.org/w/api.php" si besoin


def is_ip(text: str) -> bool:
    """Détection simple IPv4 / IPv6"""
    import re
    ipv4 = re.match(r"^\d{1,3}(\.\d{1,3}){3}$", text)
    ipv6 = re.match(r"^[0-9a-fA-F:]+$", text) and ":" in text
    return bool(ipv4 or ipv6)


@bot.tree.command(name="userinfo", description="Affiche les infos d'un utilisateur ou d'une IP Vikidia")
@app_commands.describe(pseudo="Nom d'utilisateur ou adresse IP Vikidia")
async def userinfo(interaction: discord.Interaction, pseudo: str):
    await interaction.response.defer()

    async with aiohttp.ClientSession() as session:

        if is_ip(pseudo):
            # Cas IP : pas de compte, juste blocages + contributions
            embed = discord.Embed(
                title=f"📡 IP : {pseudo}",
                color=discord.Color.orange()
            )
            embed.add_field(name="Type", value="Adresse IP (non-connecté)", inline=False)

            # Blocages
            params_blocks = {
                "action": "query", "list": "blocks", "bkip": pseudo,
                "format": "json", "bklimit": "5"
            }
            async with session.get(VIKIDIA_API, params=params_blocks) as r:
                data_blocks = await r.json()
            blocks = data_blocks.get("query", {}).get("blocks", [])
            embed.add_field(name="Blocages", value=str(len(blocks)), inline=True)

            # Contributions
            params_contribs = {
                "action": "query", "list": "usercontribs", "ucuser": pseudo,
                "format": "json", "uclimit": "1", "ucprop": "timestamp"
            }
            async with session.get(VIKIDIA_API, params=params_contribs) as r:
                data_contribs = await r.json()
            contribs = data_contribs.get("query", {}).get("usercontribs", [])
            if contribs:
                last_date = contribs[0]["timestamp"][:10]
                embed.add_field(name="Dernière contribution", value=last_date, inline=True)
            else:
                embed.add_field(name="Dernière contribution", value="Aucune trouvée", inline=True)

            embed.add_field(
                name="Page utilisateur",
                value=f"[Voir la page](https://fr.vikidia.org/wiki/Sp%C3%A9cial:Contributions/{pseudo})",
                inline=False
            )

            await interaction.followup.send(embed=embed)
            return

        # Cas compte utilisateur
        params_user = {
            "action": "query", "list": "users", "ususers": pseudo,
            "usprop": "groups|registration|editcount|blockinfo",
            "format": "json"
        }
        async with session.get(VIKIDIA_API, params=params_user) as r:
            data_user = await r.json()

        users = data_user.get("query", {}).get("users", [])
        if not users or "missing" in users[0]:
            await interaction.followup.send(f"❌ Aucun utilisateur trouvé pour `{pseudo}`.")
            return

        user = users[0]
        name = user.get("name", pseudo)
        registration = user.get("registration", "Inconnue")
        if registration and registration != "Inconnue":
            registration = registration[:10]
        editcount = user.get("editcount", 0)
        groups = user.get("groups", [])

        # Traduction des groupes utiles
        statuts = []
        if "autopatrolled" in groups:
            statuts.append("Autopatrolled")
        if "patrol" in groups or "patroller" in groups:
            statuts.append("Patrouilleur")
        if "autoconfirmed" in groups or "autoconfirmed" in groups:
            statuts.append("Autoconfirmé")
        if not statuts:
            statuts.append("Connecté (sans statut particulier)")

        # Blocages (historique via liste des logs de blocage)
        params_logs = {
            "action": "query", "list": "logevents", "letype": "block",
            "letitle": f"Utilisateur:{name}", "format": "json", "lelimit": "50"
        }
        async with session.get(VIKIDIA_API, params=params_logs) as r:
            data_logs = await r.json()
        block_count = len(data_logs.get("query", {}).get("logevents", []))

        # Dernière contribution
        params_contribs = {
            "action": "query", "list": "usercontribs", "ucuser": name,
            "format": "json", "uclimit": "1", "ucprop": "timestamp"
        }
        async with session.get(VIKIDIA_API, params=params_contribs) as r:
            data_contribs = await r.json()
        contribs = data_contribs.get("query", {}).get("usercontribs", [])
        last_contrib = contribs[0]["timestamp"][:10] if contribs else "Aucune"

        embed = discord.Embed(
            title=f"👤 {name}",
            color=discord.Color.blue()
        )
        embed.add_field(name="Type", value="Compte utilisateur", inline=True)
        embed.add_field(name="Créé le", value=registration, inline=True)
        embed.add_field(name="Statuts", value=", ".join(statuts), inline=False)
        embed.add_field(name="Blocages reçus", value=str(block_count), inline=True)
        embed.add_field(name="Contributions totales", value=str(editcount), inline=True)
        embed.add_field(name="Dernière contribution", value=last_contrib, inline=True)
        embed.add_field(
            name="Page utilisateur",
            value=f"[Voir la page](https://fr.vikidia.org/wiki/Utilisateur:{name.replace(' ', '_')})",
            inline=False
        )

        await interaction.followup.send(embed=embed)


# ------------------------------------------------------------
# LANCEMENT DU BOT
# ------------------------------------------------------------
if __name__ == "__main__":
    if not TOKEN:
        print("ERREUR : le token n'est pas défini (variable d'environnement DISCORD_TOKEN manquante).")
    else:
        import threading
        from bienvenue import boucle_bienvenue

        threading.Thread(target=boucle_bienvenue, daemon=True).start()
@tasks.loop(hours=72)
async def rappel_renouvellement():
    channel = bot.get_channel(RENEWAL_CHANNEL_ID)
    if channel:
        await channel.send(f"<@{OWNER_ID}> ⏰ Rappel : pense à renouveler le serveur KataBump avant qu'il ne soit suspendu !")

@rappel_renouvellement.before_loop
async def before_rappel():
    await bot.wait_until_ready()
rappel_renouvellement.start()
        bot.run(TOKEN)
