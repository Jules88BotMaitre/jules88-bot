import os
import json
import time
import threading
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

PAUSE_ENTRE_VERIFS =  7200     # on regarde les nouvelles modifs toutes les 60s
PAUSE_APRES_MODIF = 600    # pause de sécurité après avoir posté une bienvenue

# ------------------------------------------------------------
# CONFIGURATION DES SITES À SURVEILLER
# ------------------------------------------------------------
SITES = [
    {
        "nom": "fr",
        "api_url": "https://fr.vikidia.org/w/api.php",
        "username": os.environ.get("VIKIDIA_BOT_USERNAME_FR"),
        "password": os.environ.get("VIKIDIA_BOT_PASSWORD_FR"),
        "welcomed_file": "welcomed_users_fr.json",
        "modele_compte": "{{subst:Bienvenue}} ~~~~",
        "modele_ip": "{{subst:Bienvenue IP}} ~~~~",
    },
    {
        "nom": "en",
        "api_url": "https://en.vikidia.org/w/api.php",
        "username": os.environ.get("VIKIDIA_BOT_USERNAME_EN"),
        "password": os.environ.get("VIKIDIA_BOT_PASSWORD_EN"),
        "welcomed_file": "welcomed_users_en.json",
        "modele_compte": "{{subst:Welcome}} ~~~~",
        "modele_ip": "{{subst:Welcome IP}} ~~~~",
    },
]


def charger_donnees(fichier):
    if not os.path.exists(fichier):
        return {"users": [], "last_rcid": 0}
    with open(fichier, "r") as f:
        return json.load(f)


def sauver_donnees(fichier, data):
    with open(fichier, "w") as f:
        json.dump(data, f, indent=2)


def se_connecter(session, api_url, username, password, nom_site):
    r = session.get(api_url, params={
        "action": "query", "meta": "tokens", "type": "login", "format": "json"
    })
    login_token = r.json()["query"]["tokens"]["logintoken"]

    r = session.post(api_url, data={
        "action": "login",
        "lgname": username,
        "lgpassword": password,
        "lgtoken": login_token,
        "format": "json",
    })
    result = r.json().get("login", {}).get("result")
    if result != "Success":
        print(f"[bienvenue-{nom_site}] ❌ Échec de connexion : {result}")
        return False
    print(f"[bienvenue-{nom_site}] ✅ Bot connecté")
    return True


def obtenir_csrf_token(session, api_url):
    r = session.get(api_url, params={
        "action": "query", "meta": "tokens", "format": "json"
    })
    return r.json()["query"]["tokens"]["csrftoken"]


def get_recent_changes(session, api_url, last_rcid):
    r = session.get(api_url, params={
        "action": "query",
        "list": "recentchanges",
        "rcprop": "ids|user|userid|timestamp|title",
        "rctype": "new|edit",
        "rclimit": 50,
        "rcdir": "older",
        "format": "json",
    })
    changes = r.json().get("query", {}).get("recentchanges", [])
    nouvelles = [c for c in changes if c["rcid"] > last_rcid]
    return nouvelles, changes


def pdd_est_vide(session, api_url, username):
    titre = f"Discussion utilisateur:{username}" if "fr." in api_url else f"User talk:{username}"
    r = session.get(api_url, params={
        "action": "query",
        "titles": titre,
        "prop": "info",
        "format": "json",
    })
    pages = r.json().get("query", {}).get("pages", {})
    for page in pages.values():
        return "missing" in page
    return True


def souhaiter_bienvenue(session, api_url, username, csrf_token, nom_site, modele):
    titre = f"Discussion utilisateur:{username}" if "fr." in api_url else f"User talk:{username}"
    contenu = f"\n{modele}"
    r = session.post(api_url, data={
        "action": "edit",
        "title": titre,
        "appendtext": contenu,
        "token": csrf_token,
        "bot": True,
        "format": "json",
    })
    reponse = r.json()
    if "edit" in reponse and reponse["edit"].get("result") == "Success":
        print(f"[bienvenue-{nom_site}] 🎉 Bienvenue posée sur la PDD de {username}")
        return True
    print(f"[bienvenue-{nom_site}] ❌ Erreur en postant la bienvenue à {username} : {reponse}")
    return False


def boucle_bienvenue_site(config):
    """Boucle pour un site donné (fr ou en), à lancer dans son propre thread."""
    nom_site = config["nom"]
    api_url = config["api_url"]
    username = config["username"]
    password = config["password"]
    fichier = config["welcomed_file"]
    modele_compte = config["modele_compte"]
    modele_ip = config["modele_ip"]

    if not username or not password:
        print(f"[bienvenue-{nom_site}] ❌ Identifiants manquants, ce site ne sera pas surveillé.")
        return

    session = requests.Session()
    if not se_connecter(session, api_url, username, password, nom_site):
        return

    data = charger_donnees(fichier)
    deja_accueillis = set(data["users"])
    last_rcid = data["last_rcid"]

    while True:
        try:
            nouvelles, toutes = get_recent_changes(session, api_url, last_rcid)

            if toutes:
                last_rcid = max(c["rcid"] for c in toutes)

            # Pour chaque auteur vu dans les modifs, on note si c'est une IP (userid == 0) ou un compte
            auteurs_vus = {}
            for c in nouvelles:
                auteurs_vus[c["user"]] = (c.get("userid", 0) == 0)

            csrf_token = None

            for username_vu, est_ip in auteurs_vus.items():
                if username_vu in deja_accueillis:
                    continue

                # Le seul critère : sa page de discussion est encore vide
                if not pdd_est_vide(session, api_url, username_vu):
                    deja_accueillis.add(username_vu)
                    continue

                modele = modele_ip if est_ip else modele_compte

                if csrf_token is None:
                    csrf_token = obtenir_csrf_token(session, api_url)

                if souhaiter_bienvenue(session, api_url, username_vu, csrf_token, nom_site, modele):
                    deja_accueillis.add(username_vu)
                    time.sleep(PAUSE_APRES_MODIF)

            data["users"] = list(deja_accueillis)
            data["last_rcid"] = last_rcid
            sauver_donnees(fichier, data)

        except Exception as e:
            print(f"[bienvenue-{nom_site}] ⚠️ Erreur dans la boucle : {e}")

        time.sleep(PAUSE_ENTRE_VERIFS)


def boucle_bienvenue():
    """Point d'entrée : lance un thread par site configuré."""
    threads = []
    for config in SITES:
        t = threading.Thread(target=boucle_bienvenue_site, args=(config,), daemon=True)
        t.start()
        threads.append(t)

    for t in threads:
        t.join()


if __name__ == "__main__":
    boucle_bienvenue()
