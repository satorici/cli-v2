import os

from httpx import Client

from .auth import SatoriAuth

client = Client(
    base_url=os.environ.get("SATORI_ENDPOINT", "https://api.satori.ci"),
    auth=SatoriAuth(),
)
