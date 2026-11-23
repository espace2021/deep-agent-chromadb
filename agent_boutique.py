import os
import sqlite3

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from deepagents.middleware.filesystem import FilesystemPermission

from dotenv import load_dotenv
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain.chat_models import init_chat_model
from langchain.embeddings import init_embeddings
from langchain_chroma import Chroma
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from indexer import COLLECTION, DOSSIER_INDEX, EMBEDDINGS  # mêmes réglages que l'indexation

from pathlib import Path

load_dotenv()  # charge GOOGLE_API_KEY (et les variables LangSmith) depuis .env

MODELE = os.getenv("MODELE", "google_genai:gemini-3.5-flash-lite")

 
RACINE = Path(__file__).resolve().parent   # dossier qui contient ce fichier
 
BASE = str(RACINE / "boutique.db")
DOSSIER_SKILLS = str(RACINE / "skills")



if os.name == "nt":
    os.system("")  # active les couleurs ANSI dans le terminal Windows


class C:
    RESET, GRAS = "\033[0m", "\033[1m"
    CYAN = "\033[96m"     # question de l'utilisateur
    JAUNE = "\033[93m"    # appel d'outil décidé par l'agent
    BLEU = "\033[94m"     # résultat d'un outil
    MAGENTA = "\033[95m"  # validation humaine
    ROUGE = "\033[91m"    # action refusée
    VERT = "\033[92m"     # réponse finale de l'agent
    GRIS = "\033[90m"     # informations


def couleur(texte, *styles):
    return "".join(styles) + str(texte) + C.RESET

# ---------- Base SQLite ----------

def creer_base():
    with sqlite3.connect(BASE) as con:
        con.executescript("""
            DROP TABLE IF EXISTS retours;
            DROP TABLE IF EXISTS commandes;
            CREATE TABLE commandes (
                id INTEGER PRIMARY KEY, client TEXT, produit TEXT,
                montant REAL, statut TEXT, date_livraison TEXT);
            CREATE TABLE retours (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                commande_id INTEGER REFERENCES commandes(id),
                motif TEXT, date_demande TEXT DEFAULT (date('now')));
            INSERT INTO commandes VALUES
            (1001, 'Amine Trabelsi', 'Clavier mécanique', 120.0, 'en préparation', NULL),
            (1002, 'Sarra Ben Ali', 'Écran 24 pouces', 450.0, 'expédiée', NULL),
            (1003, 'Yassine Kammoun', 'Souris sans fil', 35.0, 'livrée', date('now', '-10 days')),
            (1004, 'Mariem Gargouri', 'Casque audio', 89.0, 'livrée', date('now', '-30 days'));
        """)


def sql(requete, *params):
    """Exécute une requête paramétrée (commit automatique) et renvoie la première ligne."""
    con = sqlite3.connect(BASE)
    try:
        with con:
            return con.execute(requete, params).fetchone()
    finally:
        con.close()

# ---------- RAG ----------

vector_store = None  # chargé dans construire_agent()


def charger_index(embeddings):
    """Rouvre la base Chroma créée par indexer.py."""
    if not os.path.isdir(DOSSIER_INDEX):
        raise SystemExit(f"Index introuvable ({DOSSIER_INDEX}/) : lancez d'abord python indexer.py")
    base = Chroma(collection_name=COLLECTION, embedding_function=embeddings,
                  persist_directory=DOSSIER_INDEX)
    if not base.get(limit=1)["ids"]:  # mauvais nom de collection = collection vide
        raise SystemExit("Index Chroma vide : relancez python indexer.py")
    return base


@tool
def chercher_politique(question: str) -> str:
    """Cherche dans les règles de la boutique : livraison, retour, annulation, paiement."""
    docs = vector_store.similarity_search(question, k=2)
    return "\n".join(d.page_content for d in docs)

# ---------- Outils SQL ----------

@tool
def consulter_commande(numero: int) -> str:
    """Donne le client, le produit, le montant, le statut et la date de livraison d'une commande."""
    ligne = sql("SELECT id, client, produit, montant, statut, date_livraison, "
                "CAST(julianday('now') - julianday(date_livraison) AS INTEGER) "
                "FROM commandes WHERE id = ?", numero)
    if ligne is None:
        return f"Aucune commande n° {numero}."
    texte = (f"Commande {ligne[0]} : client {ligne[1]}, produit {ligne[2]}, "
             f"montant {ligne[3]:.3f} DT, statut '{ligne[4]}'")
    if ligne[5]:
        texte += f", livrée le {ligne[5]} (il y a {ligne[6]} jours)"
    return texte + "."


@tool
def annuler_commande(numero: int) -> str:
    """Annule une commande. Possible seulement si son statut est 'en préparation'."""
    ligne = sql("SELECT statut FROM commandes WHERE id = ?", numero)
    if ligne is None:
        return f"Aucune commande n° {numero}."
    if ligne[0] != "en préparation":
        return f"Impossible : la commande {numero} a le statut '{ligne[0]}'."
    sql("UPDATE commandes SET statut = 'annulée' WHERE id = ?", numero)
    return f"La commande {numero} a été annulée."


@tool
def creer_retour(numero: int, motif: str) -> str:
    """Enregistre une demande de retour pour une commande livrée, avec le motif du client."""
    ligne = sql("SELECT statut FROM commandes WHERE id = ?", numero)
    if ligne is None:
        return f"Aucune commande n° {numero}."
    if ligne[0] != "livrée":
        return f"Impossible : la commande {numero} a le statut '{ligne[0]}'."
    sql("INSERT INTO retours (commande_id, motif) VALUES (?, ?)", numero, motif)
    sql("UPDATE commandes SET statut = 'retour demandé' WHERE id = ?", numero)
    return f"Demande de retour enregistrée pour la commande {numero} (motif : {motif})."


OUTILS = [chercher_politique, consulter_commande, annuler_commande, creer_retour]

PROMPT_SYSTEME = (
    "Tu es l'assistant du service client d'une boutique en ligne tunisienne. "
    "Réponds en français, brièvement et poliment. N'invente jamais d'information. "
    "Pour une question sur les règles de la boutique, utilise chercher_politique. "
    "Avant toute annulation ou tout retour : "
    "1) consulte la commande avec consulter_commande ; "
    "2) vérifie la règle correspondante avec chercher_politique ; "
    "3) appelle annuler_commande ou creer_retour seulement si la règle est respectée, "
    "sinon explique au client pourquoi ce n'est pas possible et ce qu'il peut faire."
    "Si une skill correspond à la demande, lis son SKILL.md et suis ses étapes. "
)

# ---------- Agent : Deep Agent + validation humaine ----------

def construire_agent(model=None, embeddings=None, memoire=True):
    global vector_store
    vector_store = charger_index(embeddings or init_embeddings(EMBEDDINGS))

    validation = HumanInTheLoopMiddleware(
        interrupt_on={  # outils sensibles : pause avant exécution
            "annuler_commande": {"allowed_decisions": ["approve", "reject"]},
            "creer_retour": {"allowed_decisions": ["approve", "reject"]},
        },
        description_prefix="Action à valider par un responsable",
    )
    return create_deep_agent(
        model=model or init_chat_model(MODELE, temperature=0),
        tools=OUTILS,
        system_prompt=PROMPT_SYSTEME,
        middleware=[validation],
        # Skills : l'agent voit le dossier skills/ comme sa racine « / » ...
        backend=FilesystemBackend(root_dir=DOSSIER_SKILLS, virtual_mode=True),
        skills=[("/", "Boutique")],
        # ... et ne peut que le lire (write_file et edit_file refusés)
        permissions=[FilesystemPermission(operations=["write"], paths=["/**"], mode="deny")],
        # obligatoire pour mettre en pause puis reprendre (Studio fournit le sien)
        checkpointer=InMemorySaver() if memoire else None,
    )


# ---------- Affichage en couleurs ----------

def executer_et_afficher(agent, entree, config):
    """Exécute l'agent pas à pas et affiche chaque étape en couleur.
    Renvoie la demande de validation si l'agent s'est mis en pause, sinon None."""
    for etape in agent.stream(entree, config, stream_mode="updates"):
        for noeud, sortie in etape.items():
            if noeud == "__interrupt__":
                return sortie[0].value  # HITLRequest : action_requests + review_configs
            for msg in (sortie or {}).get("messages", []):
                if msg.type == "ai" and noeud != "model":
                    continue  # message renvoyé par le middleware : déjà affiché
                if msg.type == "ai" and msg.tool_calls:
                    for appel in msg.tool_calls:
                        print(couleur(f"  → outil {appel['name']} {appel['args']}", C.JAUNE))
                elif msg.type == "tool":
                    style = C.ROUGE if msg.status == "error" else C.BLEU
                    print(couleur(f"  ← {msg.name} : {msg.content}", style))
                elif msg.type == "ai" and msg.text:
                    print(couleur("\nAgent : ", C.VERT, C.GRAS) + couleur(msg.text, C.VERT))
    return None


def demander_decisions(demande):
    """Pose la question oui/non pour chaque action en attente et construit la reprise."""
    print(couleur("\n⚠  VALIDATION REQUISE", C.MAGENTA, C.GRAS))
    decisions = []
    for action in demande["action_requests"]:
        print(couleur(f"   {action['name']} {action['args']}", C.MAGENTA))
        reponse = input(couleur("   Valider cette action ? (oui/non) : ", C.MAGENTA, C.GRAS))
        if reponse.strip().lower() in ("oui", "o", "yes", "y"):
            decisions.append({"type": "approve"})
        else:
            decisions.append({"type": "reject", "message": "Action refusée par le responsable."})
    return Command(resume={"decisions": decisions})

EXEMPLES = [
    "Quels sont les délais de livraison ?                               (RAG)",
    "Où en est la commande 1002 ?                                       (SQL)",
    "Annule ma commande 1001                                            (SQL + validation)",
    "J'ai reçu la commande 1003 mais la souris ne marche pas. "
    "Je peux la retourner ? Si oui, fais la demande.   (RAG + SQL + validation)",
    "Je veux retourner la commande 1004, le casque ne me plaît plus.   (RAG + SQL, refus)",
]


def main():
    creer_base()
    agent = construire_agent()
    config = {"configurable": {"thread_id": "session-1"}}

    print(couleur("=== Service client : Deep Agent (RAG + SQL + validation) ===", C.GRAS))
    print(couleur("Questions à essayer :", C.GRIS))
    for exemple in EXEMPLES:
        print(couleur(f"  • {exemple}", C.GRIS))
    print(couleur("Tapez 'quit' pour sortir.", C.GRIS))

    while True:
        question = input(couleur("\nVous : ", C.CYAN, C.GRAS)).strip()
        if not question:
            continue
        if question.lower() in ("quit", "exit", "q"):
            break
        entree = {"messages": [{"role": "user", "content": question}]}
        demande = executer_et_afficher(agent, entree, config)
        while demande:  # tant que l'agent est en pause, on demande la validation humaine
            demande = executer_et_afficher(agent, demander_decisions(demande), config)


if __name__ == "__main__":
    main()
