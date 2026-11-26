"""Le poche richieste in uscita (ultima versione, parere, modello): HTTPS verificato con i certificati di certifi.

Nell'app impacchettata Python non vede i certificati di sistema (soprattutto su Mac): senza certifi ogni richiesta
HTTPS fallirebbe con CERTIFICATE_VERIFY_FAILED.
"""

from __future__ import annotations

import ssl
import urllib.request
from functools import lru_cache


@lru_cache(maxsize=1)
def contesto_ssl() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:  # pragma: no cover
        return ssl.create_default_context()


def apri(req: urllib.request.Request | str, timeout: float):
    return urllib.request.urlopen(req, timeout=timeout, context=contesto_ssl())
