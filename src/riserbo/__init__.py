"""Riserbo: pseudonimizzare testi italiani prima di mandarli a un modello in cloud, e rimettere i valori al ritorno."""

from .tabella import Tabella
from .validatori import codice_fiscale_valido, iban_valido, partita_iva_valida, targa_valida

__version__ = "0.10.0"
__all__ = ["Tabella", "Segnaposto", "ripristina", "codice_fiscale_valido", "partita_iva_valida", "iban_valido", "targa_valida"]


def __getattr__(nome):  # Presidio e spaCy si caricano solo quando servono.
    if nome in ("Segnaposto", "ripristina"):
        from . import motore
        return getattr(motore, nome)
    raise AttributeError(nome)
