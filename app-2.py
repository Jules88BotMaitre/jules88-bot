import os
import json
import discord
import requests
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
async def on_message(message):
    if message.author.bot:
        return

    if bot.user.mentioned_in(message):
        await message.channel.send(f"Tu m'as appelé, {message.author.mention} ? 👀")

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


# ------------------------------------------------------------
# LANCEMENT DU BOT
# ------------------------------------------------------------
if __name__ == "__main__":
    if not TOKEN:
        print("ERREUR : le token n'est pas défini (variable d'environnement DISCORD_TOKEN manquante).")
    else:
        bot.run(TOKEN)
