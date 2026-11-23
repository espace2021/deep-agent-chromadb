# ---------- Correctif SQLite pour Chroma (Streamlit Cloud / Linux) ----------
# (TOUT EN HAUT du fichier : avant tout import qui charge Chroma)
try:
    __import__("pysqlite3")
    import sys
    sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")
except ImportError:
    pass  # Windows / macOS : le sqlite3 de Python est assez récent
 
"""Interface web du service client.
Local : streamlit run app.py    Cloud : Streamlit Community Cloud
"""
import hmac
import os
import sqlite3
import uuid
 
import pandas as pd
import streamlit as st
 
st.set_page_config(page_title="Service client", page_icon="🛒")
 
# ---------- Secrets Streamlit -> variables d'environnement ----------
# (AVANT d'importer agent_boutique, qui lit MODELE à l'import)
try:
    for cle, valeur in st.secrets.items():
        if isinstance(valeur, bool):
            valeur = str(valeur).lower()          # true -> "true"
        if isinstance(valeur, (str, int, float)):
            os.environ.setdefault(cle, str(valeur))
except Exception:
    pass  # pas de secrets.toml : en local, le fichier .env suffit
 
from langgraph.types import Command
from agent_boutique import BASE, DOSSIER_SKILLS, construire_agent, creer_base


st.set_page_config(page_title="Service client", page_icon="🛒")


@st.cache_resource  # un seul agent pour toute l'application, créé au premier affichage
def charger_agent():
    creer_base()
    return construire_agent()

# ---------- Accès protégé par mot de passe ----------
def acces_autorise():
    """Affiche un champ mot de passe tant que l'utilisateur n'est pas connecté."""
    if st.session_state.get("connecte"):
        return True
    attendu = os.getenv("MOT_DE_PASSE", "")
    saisi = st.text_input("Mot de passe", type="password")
    if saisi and attendu and hmac.compare_digest(saisi, attendu):
        st.session_state.connecte = True
        st.rerun()
    if saisi:
        st.error("Mot de passe incorrect.")
    return False
 
if not acces_autorise():
    st.stop()   # la suite n'est pas exécutée : ni agent, ni appel à Gemini

agent = charger_agent()

# ---------- Mémoire de la session (survit aux réaffichages de Streamlit) ----------
if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())  # une conversation par onglet
    st.session_state.historique = []                 # messages affichés
    st.session_state.etapes = []                     # étapes de la question en cours
    st.session_state.demande = None                  # validation en attente
config = {"configurable": {"thread_id": st.session_state.thread_id}}

def decrire(msg):
    """Transforme un message d'outil en lignes colorées (couleurs Markdown de Streamlit)."""
    if msg.type == "ai":
        return [f"🔧 :orange[{appel['name']}] `{appel['args']}`" for appel in msg.tool_calls]
    texte = msg.content.replace("\n", " ")[:120]
    couleur = "red" if msg.status == "error" else "blue"
    return [f"↳ :{couleur}[{texte}]"]


def executer(entree):
    """Exécute l'agent : affiche les étapes en direct, garde la réponse ou la pause."""
    with st.status("L'agent travaille…", expanded=True):
        for etape in agent.stream(entree, config, stream_mode="updates"):
            for noeud, sortie in etape.items():
                if noeud == "__interrupt__":
                    st.session_state.demande = sortie[0].value
                    return
                for msg in (sortie or {}).get("messages", []):
                    if msg.type == "ai" and noeud != "model":
                        continue  # message renvoyé par le middleware : déjà traité
                    if msg.type == "ai" and not msg.tool_calls:  # réponse finale
                        st.session_state.historique.append(
                            {"role": "assistant", "texte": msg.text,
                             "etapes": st.session_state.etapes})
                        continue
                    for ligne in decrire(msg):
                        st.markdown(ligne)
                        st.session_state.etapes.append(ligne)

# ---------- Barre latérale : base de données et skills ----------
with st.sidebar:
    st.header("📦 Base de données")
    with sqlite3.connect(BASE) as con:
        st.dataframe(pd.read_sql("SELECT id, statut FROM commandes", con),
                     hide_index=True)
        st.caption("Retours enregistrés")
        st.dataframe(pd.read_sql("SELECT commande_id, motif FROM retours", con),
                     hide_index=True)
    if st.button("🔄 Réinitialiser"):
        creer_base()
        st.session_state.clear()
        st.session_state.connecte = True   # rester connecté après la remise à zéro
        st.rerun()

    st.header("🧩 Skills")
    for nom in sorted(os.listdir(DOSSIER_SKILLS)):
        st.markdown(f"- `{nom}`")
# ---------- Conversation ----------
st.title("🛒 Service client")

for message in st.session_state.historique:
    with st.chat_message(message["role"]):
        if message.get("etapes"):
            with st.expander("Étapes de l'agent"):
                for ligne in message["etapes"]:
                    st.markdown(ligne)
        st.markdown(message["texte"])

demande = st.session_state.demande
if demande:  # l'agent est en pause : on affiche la validation humaine
    with st.chat_message("assistant", avatar="⚠️"):
        with st.expander("Étapes de l'agent"):
            for ligne in st.session_state.etapes:
                st.markdown(ligne)
        st.warning("Action à valider par un responsable")
        for action in demande["action_requests"]:
            st.code(f"{action['name']}({action['args']})", language="python", wrap_lines=True)
        valider, refuser = st.columns(2)
        decision = None
        if valider.button("✅ Valider", width="stretch"):
            decision = {"type": "approve"}
        if refuser.button("❌ Refuser", width="stretch"):
            decision = {"type": "reject", "message": "Action refusée par le responsable."}
    if decision:
        st.session_state.demande = None
        executer(Command(resume={"decisions": [decision] * len(demande["action_requests"])}))
        st.rerun()

if question := st.chat_input("Votre question…", disabled=demande is not None):
    st.session_state.historique.append({"role": "user", "texte": question})
    st.session_state.etapes = []
    with st.chat_message("user"):
        st.markdown(question)
    executer({"messages": [{"role": "user", "content": question}]})
    st.rerun()
