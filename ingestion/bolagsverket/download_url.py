"""Bolagsverket bulk download URL resolution."""
from __future__ import annotations

import logging
import os
from urllib.parse import urlparse

log = logging.getLogger(__name__)

DEFAULT_DIRECT_DOWNLOAD_URL = (
    "https://vardefulla-datamangder.bolagsverket.se/bolagsverket/"
    "bolagsverket_bulkfil.zip"
)


def direct_download_url() -> str:
    """Return a safe HTTP(S) bulk URL.

    The public Bolagsverket URL is stable and is the default. A configured
    override is accepted only when it is an HTTP(S) URL. This keeps a swapped
    secret such as DATABASE_URL from being handed to httpx.
    """
    configured = os.environ.get("BOLAGSVERKET_DIRECT_URL", "").strip()
    if not configured:
        return DEFAULT_DIRECT_DOWNLOAD_URL

    parsed = urlparse(configured)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return configured

    log.error(
        "Ignoring invalid BOLAGSVERKET_DIRECT_URL: expected an HTTP(S) URL, got scheme %r",
        parsed.scheme or "<missing>",
    )
    return DEFAULT_DIRECT_DOWNLOAD_URL
