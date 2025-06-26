import json
import os
import time
from base64 import b64decode
from typing import Generator

from httpx import Auth, Client, Request, Response, post

from .config import config
from .constants import SATORI_HOME
from .exceptions import AuthError

DOMAIN = "https://satorici.us.auth0.com"
CLIENT_ID = "Nf8oTFFRFzUY2BWXlyayvUgmMbf6UEAh"
AUDIENCE = "https://api.satori.ci"


def get_token() -> str:
    if token := os.getenv("SATORI_TOKEN"):
        return token
    elif token := os.getenv("SATORI_REFRESH_TOKEN"):
        return refresh_access_token(token)

    if token := config.get("token"):
        return token

    profile_dir = SATORI_HOME / config.profile
    profile_dir.mkdir(exist_ok=True)
    token_path = profile_dir / "access-token"

    try:
        refresh_token = config["refresh_token"]
    except KeyError:
        refresh_token = None

    try:
        access_token = token_path.read_text()
    except FileNotFoundError:
        access_token = None

    if access_token:
        _, payload, _ = access_token.split(".")
        claims = json.loads(b64decode(payload))
        expired = claims["exp"] < int(time.time()) - 10

        if not expired:
            return access_token
        elif refresh_token:
            access_token = refresh_access_token(refresh_token)
            token_path.write_text(access_token)
            return access_token
    elif refresh_token:
        access_token = refresh_access_token(refresh_token)
        token_path.write_text(access_token)
        return access_token

    raise AuthError("Login required")


class SatoriAuth(Auth):
    def auth_flow(self, request: Request) -> Generator[Request, Response, None]:
        request.headers["Authorization"] = f"Bearer {get_token()}"
        yield request


def authenticate():
    with Client(base_url=DOMAIN) as client:
        res = client.post(
            "/oauth/device/code",
            data={
                "client_id": CLIENT_ID,
                "scope": "openid profile offline_access",
                "audience": AUDIENCE,
            },
        )

        res.raise_for_status()

        body = res.json()

        print("Verification URL:", body["verification_uri_complete"])

        device_code = body["device_code"]
        interval = body["interval"]

        while True:
            res = client.post(
                "/oauth/token",
                data={
                    "client_id": CLIENT_ID,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "device_code": device_code,
                },
            )

            if res.is_success:
                return res.json()

            time.sleep(interval)


def refresh_access_token(refresh_token: str):
    res = post(
        f"{DOMAIN}/oauth/token",
        data={
            "client_id": CLIENT_ID,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
    )

    return res.json()["access_token"]
