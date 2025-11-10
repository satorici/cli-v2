import os
from typing import Generator

from httpx import Auth, Request, Response

from .config import config
from .exceptions import AuthError


def get_token() -> str:
    if token := os.getenv("SATORI_TOKEN"):
        return token

    if token := config.get("token"):
        return token

    raise AuthError("Login required")


class SatoriAuth(Auth):
    def auth_flow(self, request: Request) -> Generator[Request, Response, None]:
        request.headers["Authorization"] = f"Bearer {get_token()}"
        yield request
