from httpx import Client, Response

from .auth import SatoriAuth
from .config import config


def raise_for_status(response: Response):
    if response.is_error:
        response.raise_for_status()


client = Client(
    base_url=config["endpoint"],
    auth=SatoriAuth(),
    event_hooks={"response": [raise_for_status]},
)
