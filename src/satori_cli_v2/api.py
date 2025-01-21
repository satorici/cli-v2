from httpx import Client

from .auth import SatoriAuth
from .config import config

client = Client(base_url=config["endpoint"], auth=SatoriAuth())
