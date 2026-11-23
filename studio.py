"""Point d'entrée pour LangGraph Studio : uv run langgraph dev"""
from agent_boutique import construire_agent, creer_base

creer_base()
agent = construire_agent(memoire=False)  # le serveur gère lui-même la persistance
