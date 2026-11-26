"""Il documento oscurato: le pagine originali con i dati coperti da rettangoli neri, e sopra il segnaposto.

Ogni pagina diventa un'immagine: nel file finale non resta nessun testo nascosto sotto i rettangoli, che è l'errore
classico degli oscuramenti fatti male (il rettangolo nero disegnato sopra un testo che si può ancora copiare).
Le posizioni dei dati vengono dallo strato di testo del PDF quando c'è, altrimenti dall'OCR.
"""

from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import PurePath

from . import ocr

IMMAGINI = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp")


@dataclass
class Oscurato:
    pdf: bytes
    pagine: int
    coperti: int = 0                                    # rettangoli disegnati
    non_trovati: list[str] = field(default_factory=list)  # valori della tabella non localizzati sulle pagine


def _base(c: str) -> str:
    """Un carattere senza accento e in minuscolo, sempre lungo uno: l'OCR scambia spesso «i» e «í», «e» ed «è»."""
    d = unicodedata.normalize("NFKD", c)
    return (d[0] if d else c).lower()


def _compatta(s: str) -> str:
    return "".join(_base(c) for c in s if not c.isspace())


def _cerca(compatto: str, valori: dict[str, str]) -> list[tuple[int, int, str]]:
    """Occorrenze dei valori (senza spazi, senza maiuscole) nella stringa compatta: (inizio, fine, segnaposto)."""
    trovate = []
    for valore, segnaposto in sorted(valori.items(), key=lambda kv: -len(kv[0])):
        v = _compatta(valore)
        if len(v) < 2:
            continue
        for m in re.finditer(re.escape(v), compatto):
            if all(m.end() <= a or m.start() >= b for a, b, _ in trovate):
                trovate.append((m.start(), m.end(), segnaposto))
    return trovate


def _unisci_per_riga(box: list[tuple[float, float, float, float]]) -> list[tuple[float, float, float, float]]:
    """Unisce i rettangoli dei singoli caratteri o parole in un rettangolo per riga."""
    righe: list[list[float]] = []
    for x0, y0, x1, y1 in sorted(box, key=lambda b: ((b[1] + b[3]) / 2, b[0])):
        cy = (y0 + y1) / 2
        if righe and abs(cy - (righe[-1][1] + righe[-1][3]) / 2) < 0.5 * max(y1 - y0, righe[-1][3] - righe[-1][1]):
            r = righe[-1]
            r[0], r[1], r[2], r[3] = min(r[0], x0), min(r[1], y0), max(r[2], x1), max(r[3], y1)
        else:
            righe.append([x0, y0, x1, y1])
    return [tuple(r) for r in righe]


def _da_testo_pdf(pagina, scala: float, valori: dict[str, str]) -> list[tuple[tuple, str]]:
    tp = pagina.get_textpage()
    n = tp.count_chars()
    if n == 0:
        return []
    testo = tp.get_text_range(0, n)
    _, altezza = pagina.get_size()
    indici = [i for i, c in enumerate(testo) if not c.isspace()]
    compatto = "".join(_base(testo[i]) for i in indici)
    out = []
    for a, b, s in _cerca(compatto, valori):
        box = []
        for k in range(a, b):
            x0, y0, x1, y1 = tp.get_charbox(indici[k], loose=True)
            box.append((x0 * scala, (altezza - y1) * scala, x1 * scala, (altezza - y0) * scala))
        out += [(r, s) for r in _unisci_per_riga(box)]
    return out


def _da_ocr(img, valori: dict[str, str]) -> list[tuple[tuple, str]]:
    out = []
    for riga in ocr.leggi_immagine(img):
        mappa: list[int] = []  # carattere compatto -> indice della parola
        compatto = ""
        for j, p in enumerate(riga.parole):
            c = _compatta(p.testo)
            compatto += c
            mappa += [j] * len(c)
        for a, b, s in _cerca(compatto, valori):
            parole = sorted(set(mappa[a:b]))
            box = [riga.parole[j].box for j in parole]
            # Una parola presa in parte (es. «Rossi,») si copre tutta: meglio un carattere in più che uno in meno.
            out += [(r, s) for r in _unisci_per_riga(box)]
    return out


def _disegna(img, coperture: list[tuple[tuple, str]]):
    from PIL import ImageDraw, ImageFont

    d = ImageDraw.Draw(img)
    for (x0, y0, x1, y1), segnaposto in coperture:
        h = y1 - y0
        m = max(2, h * 0.12)
        d.rectangle([x0 - m, y0 - m, x1 + m, y1 + m], fill=(17, 16, 19))
        dim = int(h * 0.62)
        if dim >= 8:
            try:
                font = ImageFont.load_default(size=dim)
            except TypeError:  # Pillow vecchio
                font = ImageFont.load_default()
            larg = d.textlength(segnaposto, font=font)
            if larg <= (x1 - x0) + 2 * m:
                d.text((x0 + ((x1 - x0) - larg) / 2, y0 + (h - dim) / 2 - dim * 0.1), segnaposto, font=font, fill=(255, 199, 0))
    return img


def oscura(nome: str, dati: bytes, valori: dict[str, str], dpi: int = ocr.DPI) -> Oscurato:
    """`valori`: valore vero -> segnaposto (la tabella della pratica, rovesciata). Restituisce un PDF di sole immagini."""
    est = PurePath(nome).suffix.lower()
    pagine = []
    tutte: list[tuple[tuple, str]] = []
    if est == ".pdf":
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(dati)
        for i in range(len(pdf)):
            p = pdf[i]
            img = ocr.rendi_pagina(p, dpi)
            con_testo = len(p.get_textpage().get_text_range().strip()) >= 20 and p.get_rotation() == 0
            cop = _da_testo_pdf(p, dpi / 72, valori) if con_testo else _da_ocr(img, valori)
            pagine.append(_disegna(img, cop))
            tutte += cop
    elif est in IMMAGINI:
        img = ocr.apri_immagine(dati)
        cop = _da_ocr(img, valori)
        pagine.append(_disegna(img, cop))
        tutte += cop
    else:
        raise ValueError("Il documento oscurato si fa da un PDF o da un'immagine.")
    if not pagine:
        raise ValueError("Il documento non ha pagine.")
    usati = {s for _, s in tutte}
    non_trovati = sorted(v for v, s in valori.items() if s not in usati and len(_compatta(v)) >= 2)
    buf = io.BytesIO()
    pagine[0].save(buf, "PDF", resolution=dpi, save_all=True, append_images=pagine[1:], quality=85)
    return Oscurato(buf.getvalue(), len(pagine), len(tutte), non_trovati)
