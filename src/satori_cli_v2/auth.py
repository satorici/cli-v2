import json
import os
import time
from base64 import b64decode
from typing import Generator

from httpx import Auth, Client, Request, Response, post

from .constants import SATORI_HOME
from .exceptions import AuthError

DOMAIN = "https://satorici.us.auth0.com"
CLIENT_ID = "Nf8oTFFRFzUY2BWXlyayvUgmMbf6UEAh"
AUDIENCE = "https://api.satori.ci"


class SatoriAuth(Auth):
    def auth_flow(self, request: Request) -> Generator[Request, Response, None]:
        if token := os.getenv("SATORI_TOKEN"):
            request.headers["Authorization"] = f"Bearer {token}"
            yield request

        try:
            refresh_token = (SATORI_HOME / "refresh-token").read_text()
            access_token = (SATORI_HOME / "access-token").read_text()
        except FileNotFoundError:
            raise AuthError("Login required")

        _, payload, _ = access_token.split(".")
        claims = json.loads(b64decode(payload))

        if claims["exp"] < time.time():
            access_token = refresh_access_token(refresh_token)
            (SATORI_HOME / "access-token").write_text(access_token)

        request.headers["Authorization"] = f"Bearer {access_token}"
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
