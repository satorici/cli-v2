import os
from pathlib import Path

SATORI_HOME = Path.home() / ".satori"
SATORI_HOME.mkdir(exist_ok=True)

PLAYBOOKS_API_URL = os.getenv(
    "SATORI_PLAYBOOKS_ENDPOINT",
    "https://h71qr5shr9.execute-api.us-east-1.amazonaws.com",
)

DASHBOARD_URL = os.getenv("SATORI_DASHBOARD_URL", "https://dashboard.satori.ci")


def report_url(execution_id: int) -> str:
    return f"{DASHBOARD_URL}/reports/{execution_id}"
