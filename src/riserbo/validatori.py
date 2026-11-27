"""Controlli delle cifre di verifica per i dati italiani con forma fissa.

Funzioni pure, senza dipendenze: si possono usare e provare anche senza Presidio.
"""

from __future__ import annotations

import re

# --- Codice fiscale (persone fisiche), con omocodia -------------------------------------------

_CF_DISPARI = {
    **dict(zip("0123456789", [1, 0, 5, 7, 9, 13, 15, 17, 19, 21])),
    **dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ",
               [1, 0, 5, 7, 9, 13, 15, 17, 19, 21, 2, 4, 18, 20, 11, 3, 6, 8, 12, 14, 16, 10, 22, 25, 24, 23])),
}
_CF_PARI = {**{str(i): i for i in range(10)}, **{c: i for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ")}}
_CF_FORMA = re.compile(r"^[A-Z]{6}[0-9LMNPQRSTUV]{2}[ABCDEHLMPRST][0-9LMNPQRSTUV]{2}[A-Z][0-9LMNPQRSTUV]{3}[A-Z]$")


def carattere_controllo_cf(primi15: str) -> str:
    """Il sedicesimo carattere del codice fiscale, calcolato dai primi quindici."""
    s = primi15.upper()
    tot = sum(_CF_DISPARI[c] if i % 2 == 0 else _CF_PARI[c] for i, c in enumerate(s))
    return chr(ord("A") + tot % 26)


def codice_fiscale_valido(cf: str) -> bool:
    cf = re.sub(r"\s", "", cf).upper()
    return bool(_CF_FORMA.match(cf)) and carattere_controllo_cf(cf[:15]) == cf[15]


# --- Partita IVA (e codice fiscale numerico delle società) -------------------------------------

def partita_iva_valida(piva: str) -> bool:
    p = re.sub(r"[\s.]", "", piva)
    if p.upper().startswith("IT"):
        p = p[2:]
    if not re.fullmatch(r"\d{11}", p) or p == "00000000000":
        return False
    x = sum(int(p[i]) for i in range(0, 10, 2))
    y = 0
    for i in range(1, 10, 2):
        d = int(p[i]) * 2
        y += d - 9 if d > 9 else d
    return (10 - (x + y) % 10) % 10 == int(p[10])


# --- IBAN (controllo mod 97 valido per tutti i paesi, lunghezza per l'Italia) -------------------

_IBAN_LUNGHEZZE = {"IT": 27, "SM": 27, "DE": 22, "FR": 27, "ES": 24, "AT": 20, "CH": 21, "NL": 18, "BE": 16}


def iban_valido(iban: str) -> bool:
    s = re.sub(r"\s", "", iban).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", s):
        return False
    attesa = _IBAN_LUNGHEZZE.get(s[:2])
    if attesa and len(s) != attesa:
        return False
    numero = "".join(str(int(c, 36)) for c in s[4:] + s[:4])
    return int(numero) % 97 == 1


# --- Targa italiana (formato dal 1994: AA 000 AA) ----------------------------------------------

_TARGA = re.compile(r"^[A-HJ-NPR-TV-Z]{2}\d{3}[A-HJ-NPR-TV-Z]{2}$")


def targa_valida(targa: str) -> bool:
    return bool(_TARGA.match(re.sub(r"[\s-]", "", targa).upper()))
