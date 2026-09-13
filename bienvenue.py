import os
import json
import time
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

API_URL = "https://fr.vikidia.org/w/api.php"
BOT_USERNAME = os.environ.get("VIKIDIA_BOT_USERNAME")
BOT_PASSWORD = os.environ.get("VIKIDIA_BOT_PASSWORD")

WELCOMED_FILE = "welcomed_users.json"
PAUSE_ENTRE_VERIFS = 60      # on regarde les nouvelles modifs toutes les 60s
PAUSE_APRES_MODIF = 120      # pause de sécurité après avoir posté une bienvenue

session = requests.Session()


def charger_donnees():
    if not os.path.exists(WELCOMED_FILE):
        return {"users": [], "last_rcid": 0}
    with open(WELCOMED_FILE, "r") as f:
        return json.load(f)


def sauver_donnees(data):
    with open(WELCOMED_FILE, "w") as f:
        json.dump(data, f, indent=2)


def se_connecter():
    r = session.get(API_URL, params={
        "action": "query", "meta": "tokens", "type": "login", "format": "json"
    })
    login_token = r.json()["query"]["tokens"]["logintoken"]

    r = session.post(API_URL, data={
        "action": "login",
        "lgname": BOT_USERNAME,
        "lgpassword": BOT_PASSWORD,
        "lgtoken": login_token,
        "format": "json",
    })
    result = r.json().get("login", {}).get("result")
    if result != "Success":
        print(f"[bienvenue] ❌ Échec de connexion au bot Vikidia : {result}")
        return False
    print("[bienvenue] ✅ Bot connecté à fr.vikidia.org")
    return True


def obtenir_csrf_token():
    r = session.get(API_URL, params={
        "action": "query", "meta": "tokens", "format": "json"
    })
    return r.json()["query"]["tokens"]["csrftoken"]


def get_recent_changes(last_rcid):
    r = session.get(API_URL, params={
        "action": "query",
        "list": "recentchanges",
        "rcprop": "ids|user|timestamp|title",
        "rctype": "new|edit",
        "rclimit": 50,
        "rcdir": "older",
        "format": "json",
    })
    changes = r.json().get("query", {}).get("recentchanges", [])
    nouvelles = [c for c in changes if c["rcid"] > last_rcid]
    return nouvelles, changes


def get_editcount(username):
    r = session.get(API_URL, params={
        "action": "query",
        "list": "users",
        "ususers": username,
        "usprop": "editcount",
        "format": "json",
    })
    users = r.json().get("query", {}).get("users", [])
    if users and "editcount" in users[0]:
        return users[0]["editcount"]
    return None


def pdd_est_vide(username):
    titre = f"Discussion utilisateur:{username}"
    r = session.get(API_URL, params={
        "action": "query",
        "titles": titre,
        "prop": "info",
        "format": "json",
    })
    pages = r.json().get("query", {}).get("pages", {})
    for page in pages.values():
        return "missing" in page  # page absente = considérée comme vide
    return True


def souhaiter_bienvenue(username, csrf_token):
    titre = f"Discussion utilisateur:{username}"
    contenu = "\n{{subst:Bienvenue}} ~~~~"
    r = session.post(API_URL, data={
        "action": "edit",
        "title": titre,
        "appendtext": contenu,
        "token": csrf_token,
        "bot": True,
        "format": "json",
    })
    reponse = r.json()
    if "edit" in reponse and reponse["edit"].get("result") == "Success":
        print(f"[bienvenue] 🎉 Bienvenue posée sur la PDD de {username}")
        return True
    print(f"[bienvenue] ❌ Erreur en postant la bienvenue à {username} : {reponse}")
    return False


def boucle_bienvenue():
    """Boucle principale : à lancer en tâche de fond (thread) ou en script à part."""
    if not BOT_USERNAME or not BOT_PASSWORD:
        print("[bienvenue] ❌ VIKIDIA_BOT_USERNAME / VIKIDIA_BOT_PASSWORD manquants, script arrêté.")
        return

    if not se_connecter():
        return

    data = charger_donnees()
    deja_accueillis = set(data["users"])
    last_rcid = data["last_rcid"]

    while True:
        try:
            nouvelles, toutes = get_recent_changes(last_rcid)

            if toutes:
                last_rcid = max(c["rcid"] for c in toutes)

            utilisateurs_vus = {c["user"] for c in nouvelles}
            csrf_token = None

            for username in utilisateurs_vus:
                if username in deja_accueillis:
                    continue

                editcount = get_editcount(username)
                if editcount != 1:
                    continue

                if not pdd_est_vide(username):
                    deja_accueillis.add(username)
                    continue

                if csrf_token is None:
                    csrf_token = obtenir_csrf_token()

                if souhaiter_bienvenue(username, csrf_token):
                    deja_accueillis.add(username)
                    time.sleep(PAUSE_APRES_MODIF)

            data["users"] = list(deja_accueillis)
            data["last_rcid"] = last_rcid
            sauver_donnees(data)

        except Exception as e:
            print(f"[bienvenue] ⚠️ Erreur dans la boucle : {e}")

        time.sleep(PAUSE_ENTRE_VERIFS)


if __name__ == "__main__":
    boucle_bienvenue()
