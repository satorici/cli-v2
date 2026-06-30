import os
from pathlib import Path

SATORI_HOME = Path.home() / ".satori"
SATORI_HOME.mkdir(exist_ok=True)

PLAYBOOKS_API_URL = os.getenv(
    "SATORI_PLAYBOOKS_ENDPOINT",
    "https://h71qr5shr9.execute-api.us-east-1.amazonaws.com",
)
