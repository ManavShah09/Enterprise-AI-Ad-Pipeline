"""
Azure AI Foundry client setup.

Initializes the AIProjectClient and exposes a shared OpenAI client
for all agents to use. Configuration is loaded from the .env file.
"""

import os
from pathlib import Path

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Load environment variables from .env at the project root
# ---------------------------------------------------------------------------

# Walk up from this file (src/client_setup.py) to find the workspace root .env
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=_env_path)

PROJECT_ENDPOINT: str = os.getenv("PROJECT_CONNECTION_STRING", "")
MODEL_DEPLOYMENT_NAME: str = os.getenv("MODEL_DEPLOYMENT_NAME", "gpt-4o-mini")

if not PROJECT_ENDPOINT:
    raise RuntimeError(
        "PROJECT_CONNECTION_STRING is not set. "
        "Please configure it in the .env file."
    )

# ---------------------------------------------------------------------------
# Initialize clients (created once, reused across agents)
# ---------------------------------------------------------------------------

project_client = AIProjectClient(
    endpoint=PROJECT_ENDPOINT,
    credential=DefaultAzureCredential(),
)

openai_client = project_client.get_openai_client()
