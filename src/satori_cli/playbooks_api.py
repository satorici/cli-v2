from httpx import Client

from .api import raise_for_status
from .constants import PLAYBOOKS_API_URL

client = Client(
    base_url=PLAYBOOKS_API_URL,
    event_hooks={"response": [raise_for_status]},
)
