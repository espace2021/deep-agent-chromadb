"""Indexation des règles de la boutique à partir des PDF du dossier politiques/.
 
Lancement : python indexer.py   (une fois, puis à chaque ajout ou modification de PDF)
Résultat  : la base Chroma du dossier chroma_db/, lue ensuite par agent_boutique.py
"""
import os
import shutil
 
from dotenv import load_dotenv
from langchain.embeddings import init_embeddings
from langchain_chroma import Chroma
from langchain_community.document_loaders import PyPDFDirectoryLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

from pathlib import Path

load_dotenv()  # charge GOOGLE_API_KEY depuis le fichier .env
 
EMBEDDINGS = os.getenv("EMBEDDINGS", "google_genai:gemini-embedding-001")

COLLECTION = "politiques"       # nom de la collection dans Chroma

 
RACINE = Path(__file__).resolve().parent
DOSSIER_INDEX = str(RACINE / "chroma_db")       # base Chroma
DOSSIER_PDF = str(RACINE / "politiques")

 
def indexer(embeddings=None):
    """Lit les PDF, les découpe en morceaux, calcule les embeddings et enregistre l'index."""
    pages = PyPDFDirectoryLoader(DOSSIER_PDF).load()  # un Document par page
    if not pages:
        raise SystemExit(f"Aucun PDF trouvé dans le dossier {DOSSIER_PDF}/")
 
    decoupeur = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)
    morceaux = decoupeur.split_documents(pages)
 
    embeddings = embeddings or init_embeddings(EMBEDDINGS)
    shutil.rmtree(DOSSIER_INDEX, ignore_errors=True)  # repartir de zéro : pas de doublons
    Chroma.from_documents(
        morceaux, embeddings,
        collection_name=COLLECTION,
        persist_directory=DOSSIER_INDEX,  # Chroma enregistre tout seul sur le disque
    )
    print(f"{len(pages)} pages, {len(morceaux)} morceaux indexés dans {DOSSIER_INDEX}/")
 
if __name__ == "__main__":
    indexer()
