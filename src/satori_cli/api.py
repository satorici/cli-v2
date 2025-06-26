import os

from httpx import Client, Response

from .auth import SatoriAuth


def raise_for_status(response: Response):
    if response.is_error:
        response.read()
        response.raise_for_status()


client = Client(
    base_url=os.getenv("SATORI_ENDPOINT", "https://api-v2.satori.ci"),
    auth=SatoriAuth(),
    event_hooks={"response": [raise_for_status]},
)
