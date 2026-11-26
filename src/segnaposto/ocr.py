"""Riconoscimento del testo (OCR) per scansioni e foto, tutto in locale.

Usa i modelli PP-OCRv6 di PaddleOCR (multilingua, italiano compreso) eseguiti con ONNX Runtime tramite RapidOCR:
la qualità di PaddleOCR senza il framework PaddlePaddle, che peserebbe centinaia di MB. I modelli sono dentro il
pacchetto: niente viene scaricato e niente esce dal computer.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

DPI = 200  # risoluzione a cui si leggono le pagine dei PDF scansionati

_motore = None
_lock = threading.Lock()


@dataclass
class Parola:
    testo: str
    box: tuple[float, float, float, float]  # x0, y0, x1, y1 in pixel dell'immagine


@dataclass
class Riga:
    parole: list[Parola]
    box: tuple[float, float, float, float]

    @property
    def testo(self) -> str:
        return " ".join(p.testo for p in self.parole)


def disponibile() -> bool:
    try:
        import rapidocr  # noqa: F401
        return True
    except ImportError:
        return False


def _ottieni_motore():
    global _motore
    if _motore is None:
        from rapidocr import RapidOCR
        # Classificatore dell'orientamento delle righe spento: sui documenti italiani gira per errore righe dritte
        # (un IBAN letto come «1B 0 10 00...»). Le pagine capovolte intere sono rare e si raddrizzano prima.
        _motore = RapidOCR(params={"Global.log_level": "error", "Global.use_cls": False})
    return _motore


def _rettangolo(punti) -> tuple[float, float, float, float]:
    xs = [float(p[0]) for p in punti]
    ys = [float(p[1]) for p in punti]
    return min(xs), min(ys), max(xs), max(ys)


def leggi_immagine(img) -> list[Riga]:
    """`img`: immagine PIL. Restituisce le righe in ordine di lettura, con le parole e le loro posizioni."""
    import numpy as np

    with _lock:  # il motore non va usato da più thread insieme
        r = _ottieni_motore()(np.asarray(img.convert("RGB")), return_word_box=True)
    if r.txts is None:
        return []
    righe: list[Riga] = []
    parole_per_riga = r.word_results or [()] * len(r.txts)
    for testo, box, parole in zip(r.txts, r.boxes, parole_per_riga):
        b = _rettangolo(box)
        ps = [Parola(str(p[0]), _rettangolo(p[2])) for p in parole if str(p[0]).strip()]
        if not ps:  # senza posizioni delle parole: una sola «parola» grande quanto la riga
            ps = [Parola(str(testo), b)]
        righe.append(Riga(ps, b))
    return _in_ordine(righe)


def _in_ordine(righe: list[Riga]) -> list[Riga]:
    """Ordina dall'alto in basso; i pezzi alla stessa altezza (colonne, tabelle) finiscono sulla stessa riga."""
    if not righe:
        return []
    righe = sorted(righe, key=lambda r: (r.box[1] + r.box[3]) / 2)
    gruppi: list[list[Riga]] = []
    for r in righe:
        cy, h = (r.box[1] + r.box[3]) / 2, r.box[3] - r.box[1]
        if gruppi:
            ult = gruppi[-1][0]
            if abs(cy - (ult.box[1] + ult.box[3]) / 2) < 0.5 * max(h, ult.box[3] - ult.box[1]):
                gruppi[-1].append(r)
                continue
        gruppi.append([r])
    return [r for g in gruppi for r in sorted(g, key=lambda r: r.box[0])]


def testo_da_righe(righe: list[Riga]) -> str:
    """Testo leggibile: i pezzi sulla stessa riga separati da tabulazione se lontani (colonne di una tabella)."""
    out: list[str] = []
    prec: Riga | None = None
    for r in righe:
        if prec is None:
            out.append(r.testo)
        else:
            stessa = abs((r.box[1] + r.box[3]) / 2 - (prec.box[1] + prec.box[3]) / 2) < 0.5 * (r.box[3] - r.box[1])
            if stessa and r.box[0] >= prec.box[2]:
                out.append(("\t" if r.box[0] - prec.box[2] > 1.5 * (r.box[3] - r.box[1]) else " ") + r.testo)
            else:
                out.append("\n" + r.testo)
        prec = r
    return "".join(out).strip()


def apri_immagine(dati: bytes):
    """Apre una foto raddrizzandola secondo l'EXIF (le foto del telefono sono spesso salvate ruotate)."""
    import io

    from PIL import Image, ImageOps

    img = Image.open(io.BytesIO(dati))
    img = ImageOps.exif_transpose(img)
    # Le foto molto grandi si riducono: oltre i 3000 px l'OCR non migliora e rallenta.
    if max(img.size) > 3000:
        img.thumbnail((3000, 3000))
    return img.convert("RGB")


def rendi_pagina(pagina, dpi: int = DPI):
    """Una pagina pypdfium2 come immagine PIL."""
    return pagina.render(scale=dpi / 72).to_pil().convert("RGB")
