"""Google OAuth ID token verification.

The flow: the client obtains a Google ID token via the Google Sign-In SDK
(web or mobile) and POSTs it to ``/auth/google``. This module verifies the
token against Google's public keys and extracts user info.

No redirect-based OAuth here — the API never talks to Google's authorize
endpoint. That is the client's job.
"""

from __future__ import annotations

from typing import NamedTuple

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token


class GoogleUserInfo(NamedTuple):
    email: str
    google_id: str
    name: str


def verify_google_id_token(token: str, client_id: str) -> GoogleUserInfo:
    """Verify a Google ID token and return extracted user info.

    Raises ``ValueError`` if the token is invalid, expired, or was not
    issued for ``client_id``.
    """
    idinfo = id_token.verify_oauth2_token(  # type: ignore[no-untyped-call]
        token, google_requests.Request(), client_id
    )

    email = idinfo.get("email")
    if not email:
        raise ValueError("Google ID token does not contain an email address")

    return GoogleUserInfo(
        email=email,
        google_id=idinfo["sub"],
        name=idinfo.get("name", email.split("@")[0]),
    )
