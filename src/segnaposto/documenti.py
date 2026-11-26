"""Leggere i documenti di tutti i giorni e riscriverli dopo la pseudonimizzazione.

Ingresso: .txt .md, .docx, .pdf (anche scansionati, con l'OCR), immagini (.png .jpg .tif), .eml e .msg (con gli
          allegati leggibili), .xlsx, .csv.
Uscita:   .txt, .md, .docx, .xlsx, .csv.

Le tabelle (Excel, CSV, tabelle di Word) diventano righe con le celle separate da tabulazione: il motore lavora
sul testo e all'uscita le celle tornano al loro posto. Nelle tabelle si leggono anche le intestazioni: una colonna
«Nome», «Email» o «Codice fiscale» viene nascosta tutta, anche dove il riconoscitore da solo non basterebbe.
"""

from __future__ import annotations

import csv
import email
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from email import policy
from html.parser import HTMLParser
from pathlib import PurePath

FOGLIO = "### Foglio: "  # riga che separa i fogli di un Excel nel testo
IMMAGINI = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp")
LEGGIBILI = (".txt", ".md", ".text", ".log", ".docx", ".pdf", ".eml", ".msg", ".xlsx", ".xlsm", ".csv", ".tsv") + IMMAGINI
FORMATI_USCITA = ("txt", "md", "docx", "xlsx", "csv")
MAX_BYTE = 25 * 1024 * 1024

# Intestazione di colonna (normalizzata) -> tipo di segnaposto per tutta la colonna.
COLONNE = {
    "PERSONA": ("nome", "cognome", "nominativo", "nome e cognome", "cognome e nome", "nome cognome", "referente",
                "contatto", "persona", "intestatario", "titolare", "destinatario", "mittente", "paziente", "studente"),
    "CLIENTE": ("cliente", "clienti", "ragione sociale cliente", "denominazione cliente"),
    "FORNITORE": ("fornitore", "fornitori", "ragione sociale fornitore"),
    "DIPENDENTE": ("dipendente", "dipendenti", "lavoratore", "collaboratore", "operatore"),
    "AZIENDA": ("ragione sociale", "azienda", "societa", "ditta", "denominazione", "impresa", "ente"),
    "EMAIL": ("email", "e-mail", "mail", "pec", "indirizzo email", "posta elettronica"),
    "TELEFONO": ("telefono", "tel", "cellulare", "cell", "mobile", "numero di telefono", "recapito", "fax"),
    "INDIRIZZO": ("indirizzo", "via", "residenza", "domicilio", "sede", "sede legale", "indirizzo di consegna"),
    "LUOGO": ("citta", "comune", "localita", "luogo di nascita", "paese"),
    "CODICE_FISCALE": ("codice fiscale", "cf", "c.f.", "cod. fiscale", "cod fiscale"),
    "PARTITA_IVA": ("partita iva", "p.iva", "piva", "p. iva", "p iva", "partita i.v.a."),
    "IBAN": ("iban", "conto", "coordinate bancarie"),
    "DATA_NASCITA": ("data di nascita", "nato il", "data nascita", "nascita"),
    "TARGA": ("targa",),
}
_COLONNE = {v: k for k, vs in COLONNE.items() for v in vs}


@dataclass
class Documento:
    nome: str
    formato: str                    # testo, docx, pdf, immagine, email, tabella
    testo: str
    forzati: dict[str, str] = field(default_factory=dict)  # valori da nascondere comunque (colonne riconosciute)
    colonne: list[str] = field(default_factory=list)       # intestazioni riconosciute, per dirlo a chi usa l'app
    avvisi: list[str] = field(default_factory=list)
    ocr_pagine: int = 0             # pagine o immagini lette con l'OCR: vanno rilette con più attenzione


def leggi(nome: str, dati: bytes, profondita: int = 0) -> Documento:
    """Trasforma un file in testo. Solleva ValueError con un messaggio chiaro se il formato non è leggibile."""
    if len(dati) > MAX_BYTE:
        raise ValueError("Il file è troppo grande (massimo 25 MB).")
    est = PurePath(nome).suffix.lower()
    if est in (".docx",):
        return _docx(nome, dati)
    if est == ".pdf":
        return _pdf(nome, dati)
    if est == ".eml":
        return _eml(nome, dati, profondita)
    if est in (".xlsx", ".xlsm"):
        return _xlsx(nome, dati)
    if est in (".csv", ".tsv"):
        return _csv(nome, dati)
    if est in (".txt", ".md", ".text", ".log", ""):
        return Documento(nome, "testo", _decodifica(dati))
    if est == ".doc":
        raise ValueError("I .doc del vecchio Word non si leggono: aprilo e salvalo come .docx.")
    if est == ".msg":
        return _msg(nome, dati, profondita)
    if est == ".xls":
        raise ValueError("I .xls del vecchio Excel non si leggono: salvalo come .xlsx.")
    if est in IMMAGINI:
        return _immagine(nome, dati)
    if est in (".heic", ".heif"):
        raise ValueError("Le foto HEIC dell'iPhone non si leggono: esportale come JPG (su Mac: Anteprima → Esporta).")
    raise ValueError(f"Formato {est} non supportato. Si leggono: {', '.join(LEGGIBILI)}.")


def _decodifica(dati: bytes) -> str:
    for cod in ("utf-8-sig", "cp1252"):
        try:
            return dati.decode(cod)
        except UnicodeDecodeError:
            continue
    return dati.decode("latin-1")


def _cella(v) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.strftime("%d/%m/%Y %H:%M") if (v.hour or v.minute) else v.strftime("%d/%m/%Y")
    if isinstance(v, date):
        return v.strftime("%d/%m/%Y")
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return " ".join(str(v).split())  # niente tab o a capo dentro una cella: romperebbero la tabella


def _norma(s: str) -> str:
    s = s.strip().casefold().replace("à", "a").replace("è", "e").replace("é", "e").replace("ì", "i").replace("ò", "o").replace("ù", "u")
    return re.sub(r"\s+", " ", s.strip(" :*"))


def _tabella(righe: list[list[str]], doc: Documento) -> list[str]:
    """Righe → testo a tabulazioni; se la prima riga ha intestazioni note, le colonne diventano valori forzati."""
    righe = [r for r in righe if any(c for c in r)]
    if not righe:
        return []
    tipi = {i: _COLONNE[_norma(c)] for i, c in enumerate(righe[0]) if _norma(c) in _COLONNE}
    for i, tipo in tipi.items():
        doc.colonne.append(f"{righe[0][i].strip()} → {tipo}")
        for r in righe[1:]:
            if i < len(r) and len(r[i].strip()) >= 2:
                doc.forzati.setdefault(r[i].strip(), tipo)
    return ["\t".join(r).rstrip("\t") for r in righe]


def _docx(nome: str, dati: bytes) -> Documento:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    d = Document(io.BytesIO(dati))
    doc = Documento(nome, "docx", "")
    righe: list[str] = []
    for el in d.element.body.iterchildren():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "p":
            righe.append(Paragraph(el, d).text)
        elif tag == "tbl":
            t = Table(el, d)
            righe += [""] + _tabella([[_cella(c.text) for c in r.cells] for r in t.rows], doc) + [""]
    for s in d.sections:  # intestazioni e piè di pagina: spesso c'è la ragione sociale con indirizzo e P.IVA
        for parte in (s.header, s.footer):
            testo = "\n".join(p.text for p in parte.paragraphs if p.text.strip())
            if testo and testo not in "\n".join(righe):
                righe += ["", testo]
    doc.testo = re.sub(r"\n{3,}", "\n\n", "\n".join(righe)).strip()
    return doc


def _pdf(nome: str, dati: bytes) -> Documento:
    import pypdfium2 as pdfium

    from . import ocr

    try:
        pdf = pdfium.PdfDocument(dati)
    except pdfium.PdfiumError as e:
        raise ValueError("Il PDF non si apre: è protetto da password o danneggiato.") from e
    doc = Documento(nome, "pdf", "")
    pagine, scansioni = [], []
    for i in range(len(pdf)):
        t = pdf[i].get_textpage().get_text_range().replace("\r\n", "\n").replace("\r", "\n").strip()
        if len(t) < 20:
            scansioni.append(i)
        pagine.append(t)
    if scansioni:
        if not ocr.disponibile():
            if len(scansioni) == len(pagine):
                raise ValueError("Questo PDF è una scansione (immagini, niente testo): serve il riconoscimento del testo (OCR), "
                                 "che non è installato. Installa segnaposto con l'opzione [ocr].")
            doc.avvisi.append(f"{len(scansioni)} pagine su {len(pagine)} sembrano scansioni e non sono state lette (OCR non installato).")
        else:
            for i in scansioni:
                pagine[i] = ocr.testo_da_righe(ocr.leggi_immagine(ocr.rendi_pagina(pdf[i])))
            doc.ocr_pagine = len(scansioni)
            doc.avvisi.append(("Tutte le pagine sono state lette" if len(scansioni) == len(pagine) else
                               f"{len(scansioni)} pagine su {len(pagine)} sono state lette") +
                              " con il riconoscimento del testo (OCR): confronta il risultato con l'originale.")
    doc.testo = "\n\n".join(p for p in pagine if p)
    if not doc.testo.strip():
        raise ValueError("Nel PDF non c'è testo leggibile.")
    return doc


def _immagine(nome: str, dati: bytes) -> Documento:
    from . import ocr

    if not ocr.disponibile():
        raise ValueError("Per leggere le immagini serve il riconoscimento del testo (OCR), che non è installato.")
    try:
        img = ocr.apri_immagine(dati)
    except Exception as e:
        raise ValueError("L'immagine non si apre: formato non riconosciuto o file danneggiato.") from e
    testo = ocr.testo_da_righe(ocr.leggi_immagine(img))
    if not testo:
        raise ValueError("Nell'immagine non è stato trovato testo.")
    return Documento(nome, "immagine", testo, ocr_pagine=1,
                     avvisi=["Testo letto con il riconoscimento del testo (OCR): confronta il risultato con l'immagine."])


class _Html(HTMLParser):
    BLOCCHI = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "table", "blockquote"}

    def __init__(self) -> None:
        super().__init__()
        self.parti: list[str] = []
        self._salta = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script", "head"):
            self._salta += 1
        elif tag in self.BLOCCHI:
            self.parti.append("\n")
        elif tag == "td":
            self.parti.append("\t")

    def handle_endtag(self, tag):
        if tag in ("style", "script", "head"):
            self._salta = max(0, self._salta - 1)
        elif tag in self.BLOCCHI:
            self.parti.append("\n")

    def handle_data(self, data):
        if not self._salta:
            self.parti.append(data)


def html_in_testo(html: str) -> str:
    p = _Html()
    p.feed(html)
    testo = re.sub(r"[ \xa0]+", " ", "".join(p.parti))
    return re.sub(r"\n\s*\n+", "\n\n", testo).strip()


def _eml(nome: str, dati: bytes, profondita: int) -> Documento:
    m = email.message_from_bytes(dati, policy=policy.default)
    righe = []
    for campo, etichetta in (("From", "Da"), ("To", "A"), ("Cc", "Cc"), ("Date", "Data"), ("Subject", "Oggetto")):
        if m[campo]:
            righe.append(f"{etichetta}: {m[campo]}")
    corpo = m.get_body(preferencelist=("plain", "html"))
    testo = ""
    if corpo is not None:
        testo = corpo.get_content()
        if corpo.get_content_type() == "text/html":
            testo = html_in_testo(testo)
    doc = Documento(nome, "email", "")
    parti = ["\n".join(righe), testo.strip()]
    for a in m.iter_attachments():
        fn = a.get_filename() or "allegato"
        if profondita >= 2 or not fn.lower().endswith(LEGGIBILI):
            doc.avvisi.append(f"Allegato non letto: {fn}")
            continue
        try:
            sotto = leggi(fn, a.get_payload(decode=True) or b"", profondita + 1)
        except Exception as e:  # un allegato illeggibile non deve fermare l'email
            doc.avvisi.append(f"Allegato {fn}: {e}")
            continue
        parti.append(f"--- Allegato: {fn} ---\n{sotto.testo}")
        doc.forzati.update(sotto.forzati)
        doc.colonne += sotto.colonne
        doc.ocr_pagine += sotto.ocr_pagine
        doc.avvisi += [f"{fn}: {x}" for x in sotto.avvisi]
    doc.testo = "\n\n".join(p for p in parti if p)
    return doc


def _msg(nome: str, dati: bytes, profondita: int) -> Documento:
    """Email di Outlook (.msg): un file OLE. Si leggono intestazioni, corpo (testo o HTML) e allegati."""
    import olefile

    try:
        ole = olefile.OleFileIO(io.BytesIO(dati))
    except OSError as e:
        raise ValueError("Il file .msg non si apre: non sembra un'email di Outlook.") from e

    def campo(radice: str, codice: str) -> str:
        for suff, cod in (("001F", "utf-16-le"), ("001E", "cp1252")):
            percorso = f"{radice}__substg1.0_{codice}{suff}"
            if ole.exists(percorso):
                return ole.openstream(percorso).read().decode(cod, "replace").rstrip("\x00")
        return ""

    def binario(radice: str, codice: str) -> bytes:
        percorso = f"{radice}__substg1.0_{codice}0102"
        return ole.openstream(percorso).read() if ole.exists(percorso) else b""

    righe = []
    mitt, mail = campo("", "0C1A"), campo("", "0C1F") or campo("", "5D01")
    if mitt or mail:
        righe.append(f"Da: {mitt} <{mail}>" if mitt and mail and mail not in mitt else f"Da: {mitt or mail}")
    for cod, etichetta in (("0E04", "A"), ("0E03", "Cc"), ("0037", "Oggetto")):
        v = campo("", cod)
        if v:
            righe.append(f"{etichetta}: {v}")
    doc = Documento(nome, "email", "")
    corpo = campo("", "1000")
    if not corpo.strip():
        html = binario("", "1013")
        if html:
            corpo = html_in_testo(_decodifica(html))
        else:
            doc.avvisi.append("Il corpo di questa email è solo in formato RTF e non è stato letto: copia il testo dall'email.")
    parti = ["\n".join(righe), corpo.strip()]
    allegati = sorted({e[0] for e in ole.listdir() if e and e[0].startswith("__attach_version1.0_")})
    for a in allegati:
        radice = a + "/"
        fn = campo(radice, "3707") or campo(radice, "3704") or campo(radice, "3001") or "allegato"
        contenuto = binario(radice, "3701")
        if profondita >= 2 or not fn.lower().endswith(LEGGIBILI) or not contenuto:
            doc.avvisi.append(f"Allegato non letto: {fn}")
            continue
        try:
            sotto = leggi(fn, contenuto, profondita + 1)
        except Exception as e:
            doc.avvisi.append(f"Allegato {fn}: {e}")
            continue
        parti.append(f"--- Allegato: {fn} ---\n{sotto.testo}")
        doc.forzati.update(sotto.forzati)
        doc.colonne += sotto.colonne
        doc.ocr_pagine += sotto.ocr_pagine
        doc.avvisi += [f"{fn}: {x}" for x in sotto.avvisi]
    ole.close()
    doc.testo = "\n\n".join(p for p in parti if p)
    return doc


def _xlsx(nome: str, dati: bytes) -> Documento:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(dati), read_only=True, data_only=True)
    doc = Documento(nome, "tabella", "")
    blocchi = []
    for ws in wb.worksheets:
        righe = _tabella([[_cella(c) for c in r] for r in ws.iter_rows(values_only=True)], doc)
        if righe:
            blocchi.append((FOGLIO + ws.title + "\n" if len(wb.worksheets) > 1 else "") + "\n".join(righe))
    wb.close()
    doc.testo = "\n\n".join(blocchi)
    if not doc.colonne:
        doc.avvisi.append("Nessuna intestazione di colonna riconosciuta (Nome, Email, Codice fiscale…): controlla bene il risultato.")
    return doc


def _csv(nome: str, dati: bytes) -> Documento:
    testo = _decodifica(dati)
    try:
        dialetto = csv.Sniffer().sniff(testo[:5000], delimiters=";,\t|")
    except csv.Error:
        dialetto = csv.excel
    doc = Documento(nome, "tabella", "")
    doc.testo = "\n".join(_tabella([[_cella(c) for c in r] for r in csv.reader(io.StringIO(testo), dialetto)], doc))
    return doc


# ---------------------------------------------------------------- uscita

def esporta(testo: str, formato: str) -> tuple[bytes, str]:
    """Restituisce (byte del file, tipo MIME)."""
    if formato in ("txt", "md"):
        return testo.encode("utf-8"), "text/plain; charset=utf-8"
    if formato == "csv":
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")  # il separatore che l'Excel italiano apre senza chiedere
        for riga in testo.splitlines():
            if not riga.startswith(FOGLIO):
                w.writerow(riga.split("\t"))
        return buf.getvalue().encode("utf-8-sig"), "text/csv; charset=utf-8"
    if formato == "xlsx":
        return _scrivi_xlsx(testo), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if formato == "docx":
        return _scrivi_docx(testo), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    raise ValueError(f"Formato di uscita {formato} non previsto. Si può salvare in: {', '.join(FORMATI_USCITA)}.")


def _scrivi_xlsx(testo: str) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Foglio1"
    primo, nuovo_foglio = True, False
    for riga in testo.splitlines():
        if riga.startswith(FOGLIO):
            titolo = re.sub(r"[\[\]:*?/\\]", "", riga[len(FOGLIO):])[:31] or "Foglio"
            if primo:
                ws.title = titolo
            else:
                ws = wb.create_sheet(titolo)
            primo, nuovo_foglio = False, True
            continue
        primo = False
        if not riga.strip() and ws.max_row == 1 and ws.cell(1, 1).value is None:
            continue
        ws.append([_numero(c) for c in riga.split("\t")])
        if nuovo_foglio or ws.max_row == 1:
            for c in ws[ws.max_row]:
                c.font = Font(bold=True)
            nuovo_foglio = False
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _numero(c: str):
    """I numeri tornano numeri (somme e filtri funzionano); i codici con zeri iniziali restano testo."""
    s = c.strip()
    if re.fullmatch(r"-?(?:0|[1-9]\d{0,14})", s):
        return int(s)
    if re.fullmatch(r"-?(?:0|[1-9]\d{0,14})[.,]\d+", s):
        return float(s.replace(",", "."))
    return c


def _scrivi_docx(testo: str) -> bytes:
    from docx import Document

    d = Document()
    righe = testo.splitlines()
    i = 0
    while i < len(righe):
        if "\t" in righe[i]:
            blocco = []
            while i < len(righe) and "\t" in righe[i]:
                blocco.append(righe[i].split("\t"))
                i += 1
            n = max(len(r) for r in blocco)
            t = d.add_table(rows=len(blocco), cols=n)
            t.style = "Table Grid"
            for r, celle in zip(t.rows, blocco):
                for c, v in zip(r.cells, celle):
                    c.text = v
            continue
        d.add_paragraph(righe[i])
        i += 1
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()
