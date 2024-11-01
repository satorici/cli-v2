import os

from httpx import Client

from .auth import SatoriAuth

client = Client(
    base_url=os.environ.get("SATORI_ENDPOINT", "https://api-v2.satori.ci"),
    auth=SatoriAuth(),
)
