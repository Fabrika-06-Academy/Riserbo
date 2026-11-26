"""L'app: `segnaposto app` apre una finestra (o, se manca pywebview, il browser) che gira solo sul tuo computer.

Il flusso di ogni giorno:
  1. incolli un testo o trascini un documento (Word, PDF, Excel, email) e lo pseudonimizzi;
  2. correggi a mano se serve: clic su un segnaposto per toglierlo, selezione per nascondere altro;
  3. copi o salvi il risultato e lo usi nella chat (ChatGPT, Claude, Copilot...);
  4. incolli la risposta e l'app rimette i valori veri, segnalando i segnaposto persi o inventati.

La tabella dei segnaposto vive solo in memoria, per la pratica in corso: «Nuova pratica» o la chiusura la cancellano.
Sicurezza: ascolta solo su 127.0.0.1, su una porta casuale, e ogni richiesta deve portare una chiave generata all'avvio
(così un altro sito aperto nel browser non può usare il servizio). Si chiude da sola dopo un'ora senza uso.
"""

from __future__ import annotations

import base64
import json
import os
import re
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import PurePath

from . import __version__
from .documenti import FORMATI_USCITA, esporta, leggi
from .motore import SEGNAPOSTO, Segnaposto, ripristina
from .oscura import _compatta, oscura
from .tabella import Tabella

INATTIVITA_MAX = 3600  # secondi
MAX_RICHIESTA = 36 * 1024 * 1024  # un file da 25 MB in base64


class Stato:
    def __init__(self, sp: Segnaposto | None = None) -> None:
        self.sp = sp                    # None finché il modello si carica
        self.errore_avvio = ""
        self.ultimo_uso = time.time()
        self.lock = threading.Lock()
        self.nuova_pratica()

    def nuova_pratica(self) -> None:
        self.tabella = Tabella()
        self.inviati: set[str] = set()  # segnaposto mandati al modello: servono per trovare i mancanti
        self.forzati: dict[str, str] = {}  # valori da nascondere comunque (colonne riconosciute, aggiunte a mano)
        self.ignora: set[str] = set()      # falsi allarmi indicati da chi rilegge
        self.documento: tuple[str, bytes, str] | None = None  # PDF o immagine originale, per l'oscuramento

    def carica_modello(self) -> None:
        try:
            sp = Segnaposto()
            sp.pseudonimizza("Avvio, Mario Rossi.")  # scalda il modello: la prima richiesta vera è subito veloce
            self.sp = sp
        except Exception as e:  # pragma: no cover - si vede nella finestra
            self.errore_avvio = f"Il modello italiano non si è caricato: {e}"


def crea_gestore(stato: Stato, chiave: str, porta_ref: list[int], ferma):
    pagina = files("segnaposto").joinpath("app.html").read_text(encoding="utf-8")

    class Gestore(BaseHTTPRequestHandler):
        server_version = "segnaposto-app"

        def log_message(self, *args) -> None:
            pass

        def _host_ok(self) -> bool:
            return self.headers.get("Host", "") in (f"127.0.0.1:{porta_ref[0]}", f"localhost:{porta_ref[0]}")

        def _invia(self, codice: int, corpo: bytes, tipo: str) -> None:
            self.send_response(codice)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(corpo)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' data:")
            self.end_headers()
            self.wfile.write(corpo)

        def _json(self, codice: int, dati: dict) -> None:
            self._invia(codice, json.dumps(dati, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def do_GET(self) -> None:
            if not self._host_ok():
                return self._json(403, {"errore": "host non ammesso"})
            if self.path.split("?")[0] == "/":
                if f"t={chiave}" not in self.path:
                    return self._invia(403, "Apri l'app dal programma segnaposto.".encode("utf-8"), "text/plain; charset=utf-8")
                html = pagina.replace("__CHIAVE__", chiave).replace("__VERSIONE__", __version__)
                return self._invia(200, html.encode("utf-8"), "text/html; charset=utf-8")
            self._json(404, {"errore": "non trovato"})

        def do_POST(self) -> None:
            if not self._host_ok() or not secrets.compare_digest(self.headers.get("X-Chiave", ""), chiave):
                return self._json(403, {"errore": "non autorizzato"})
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_RICHIESTA:
                return self._json(413, {"errore": "Il file è troppo grande (massimo 25 MB)."})
            try:
                dati = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
            except ValueError:
                return self._json(400, {"errore": "JSON non valido"})
            if not isinstance(dati, dict):
                dati = {}
            try:
                return self._instrada(dati)
            except ValueError as e:
                return self._json(422, {"errore": str(e)})

        def _instrada(self, dati: dict) -> None:
            percorso, testo = self.path, str(dati.get("testo", ""))
            if percorso == "/api/stato":
                return self._json(200, {"pronto": stato.sp is not None, "errore": stato.errore_avvio, "versione": __version__})
            if percorso == "/api/chiudi":
                self._json(200, {"ok": True})
                threading.Thread(target=ferma, daemon=True).start()
                return None
            if percorso == "/api/esporta":
                formato = str(dati.get("formato", "txt"))
                corpo, _ = esporta(testo, formato)
                nome = PurePath(str(dati.get("nome") or "documento")).stem or "documento"
                nome = re.sub(r"[^\w\- .]", "_", nome)[:80] + ("-" + str(dati["suffisso"]) if dati.get("suffisso") else "") + "." + formato
                return self._json(200, {"nome": nome, "dati": base64.b64encode(corpo).decode("ascii")})
            if percorso == "/api/leggi":
                nome, grezzo = str(dati.get("nome", "")), base64.b64decode(str(dati.get("dati", "")))
                doc = leggi(nome, grezzo)
                with stato.lock:
                    stato.ultimo_uso = time.time()
                    stato.forzati.update(doc.forzati)
                    stato.documento = (nome, grezzo, doc.testo) if doc.formato in ("pdf", "immagine") else None
                return self._json(200, {"testo": doc.testo, "formato": doc.formato, "colonne": doc.colonne,
                                        "avvisi": doc.avvisi, "tabellare": doc.formato == "tabella",
                                        "oscurabile": stato.documento is not None, "ocr": doc.ocr_pagine})
            if percorso == "/api/oscura":
                with stato.lock:
                    if stato.documento is None:
                        raise ValueError("Il documento oscurato si fa da un PDF o da un'immagine: aprine uno.")
                    nome, grezzo, testo_doc = stato.documento
                    nel_doc = _compatta(testo_doc)
                    valori = {v: s for s, v in stato.tabella.valori.items() if _compatta(v) in nel_doc}
                if not valori:
                    raise ValueError("Prima pseudonimizza il documento: non ci sono dati da coprire.")
                o = oscura(nome, grezzo, valori)
                return self._json(200, {"nome": re.sub(r"[^\w\- .]", "_", PurePath(nome).stem)[:80] + "-oscurato.pdf",
                                        "dati": base64.b64encode(o.pdf).decode("ascii"), "pagine": o.pagine,
                                        "coperti": o.coperti, "non_trovati": [valori[v] for v in o.non_trovati],
                                        "anteprime": [base64.b64encode(a).decode("ascii") for a in o.anteprime]})
            with stato.lock:
                stato.ultimo_uso = time.time()
                if percorso == "/api/correggi":
                    valore = " ".join(str(dati.get("valore", "")).split())
                    if len(valore) < 2:
                        raise ValueError("Seleziona almeno due caratteri.")
                    if dati.get("azione") == "mostra":  # falso allarme: il valore torna in chiaro
                        stato.ignora.add(valore)
                        stato.forzati = {k: v for k, v in stato.forzati.items() if k.casefold() != valore.casefold()}
                        s = stato.tabella.rimuovi(valore)
                        stato.inviati.discard(s or "")
                    else:
                        stato.forzati[valore] = re.sub(r"[^A-Z_]", "", str(dati.get("tipo", "DATO")).upper()) or "DATO"
                        stato.ignora = {v for v in stato.ignora if v.casefold() != valore.casefold()}
                    return self._json(200, {"ok": True})
                if percorso == "/api/nuova":
                    stato.nuova_pratica()
                    return self._json(200, {"ok": True})
                if percorso == "/api/ripristina":
                    e = ripristina(testo, stato.tabella, attesi=stato.inviati)
                    # Pezzi del testo ripristinato: [testo, segnaposto d'origine o ""], per evidenziare i valori rimessi.
                    pezzi, pos = [], 0
                    for m in SEGNAPOSTO.finditer(testo):
                        pezzi.append([testo[pos:m.start()], ""])
                        s = m.group(0)
                        pezzi.append([stato.tabella.valori.get(s, s), s])
                        pos = m.end()
                    pezzi.append([testo[pos:], ""])
                    return self._json(200, {"testo": e.testo, "mancanti": e.mancanti, "inventati": e.inventati,
                                            "pezzi": [x for x in pezzi if x[0]]})
                if percorso == "/api/pseudonimizza":
                    if stato.sp is None:
                        return self._json(503, {"errore": stato.errore_avvio or "Sto ancora caricando il modello italiano, un attimo…"})
                    escludi = {str(x) for x in dati.get("escludi", []) if isinstance(x, str)}
                    r = stato.sp.pseudonimizza(testo, stato.tabella, forzati=stato.forzati, ignora=stato.ignora, escludi=escludi)
                    # I segnaposto attesi nella risposta sono quelli dell'ultimo testo mandato, non di tutta la pratica.
                    stato.inviati = {s for s in stato.tabella.valori if s in r.testo}
                    conta: dict[str, int] = {}
                    for t in r.trovati:
                        conta[t["tipo"]] = conta.get(t["tipo"], 0) + 1
                    return self._json(200, {"testo": r.testo, "trovati": r.trovati, "conta": conta,
                                            "tabella": stato.tabella.valori})
            self._json(404, {"errore": "non trovato"})

    return Gestore


def _dialogo(nome: str):
    import webview
    fd = getattr(webview, "FileDialog", None)  # pywebview 6
    return getattr(fd, nome) if fd else getattr(webview, nome + "_DIALOG")


class Ponte:
    """Funzioni che la pagina può chiamare quando gira nella finestra nativa (window.pywebview.api)."""

    def __init__(self) -> None:
        self.finestra = None

    def salva(self, nome: str, dati_b64: str) -> str:
        scelta = self.finestra.create_file_dialog(_dialogo("SAVE"), save_filename=nome)
        if not scelta:
            return ""
        percorso = scelta if isinstance(scelta, str) else scelta[0]
        with open(percorso, "wb") as f:
            f.write(base64.b64decode(dati_b64))
        return percorso

    def apri(self) -> dict:
        tipi = ("Documenti (*.txt;*.md;*.docx;*.pdf;*.eml;*.msg;*.xlsx;*.csv;*.png;*.jpg;*.jpeg;*.tif;*.tiff)", "Tutti i file (*.*)")
        scelta = self.finestra.create_file_dialog(_dialogo("OPEN"), file_types=tipi)
        if not scelta:
            return {}
        percorso = scelta if isinstance(scelta, str) else scelta[0]
        with open(percorso, "rb") as f:
            return {"nome": os.path.basename(percorso), "dati": base64.b64encode(f.read()).decode("ascii")}


def avvia(sp: Segnaposto | None = None, apri_browser: bool = True, porta: int = 0, finestra: bool | None = None) -> None:
    """Apre l'app. `finestra=None`: finestra nativa se pywebview c'è, altrimenti il browser."""
    stato, chiave, porta_ref = Stato(sp), secrets.token_urlsafe(24), [0]
    httpd: ThreadingHTTPServer | None = None
    win = None

    def ferma() -> None:
        time.sleep(0.3)
        if win is not None:
            win.destroy()
        httpd.shutdown()

    httpd = ThreadingHTTPServer(("127.0.0.1", porta), crea_gestore(stato, chiave, porta_ref, ferma))
    porta_ref[0] = httpd.server_address[1]
    url = f"http://127.0.0.1:{porta_ref[0]}/?t={chiave}"
    if sp is None:
        threading.Thread(target=stato.carica_modello, daemon=True).start()

    def sorveglia() -> None:
        while True:
            time.sleep(30)
            if time.time() - stato.ultimo_uso > INATTIVITA_MAX:
                ferma()
                return

    threading.Thread(target=sorveglia, daemon=True).start()

    webview = None
    if finestra is not False and apri_browser:
        try:
            import webview  # type: ignore
        except ImportError:
            if finestra:
                raise
    if webview is not None:
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        ponte = Ponte()
        win = webview.create_window("segnaposto", url, js_api=ponte, width=1280, height=860, min_size=(820, 600),
                                    text_select=True)
        ponte.finestra = win
        webview.start(private_mode=True)  # niente cache né cookie su disco
        httpd.shutdown()
        return

    print(f"segnaposto è aperto nel browser: {url}\nPer chiuderlo usa il pulsante «Chiudi» nella pagina (o Ctrl+C qui).", flush=True)
    if apri_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    print("segnaposto chiuso. La tabella della pratica è stata cancellata.", flush=True)


def prova_pacchetto() -> None:
    """Controllo del pacchetto costruito (in CI): tutto quello che serve c'è dentro? Esce con errore se manca qualcosa."""
    from .documenti import _scrivi_docx, _scrivi_xlsx

    sp = Segnaposto()
    r = sp.pseudonimizza("Scrive Mario Rossi, via Roma 12, CF RSSMRA80A01L840J.")
    assert "Mario Rossi" not in r.testo and "[CODICE_FISCALE_1]" in r.testo, r.testo
    assert "Mario Rossi" in leggi("a.docx", _scrivi_docx("Offerta per Mario Rossi\nNome\tEmail")).testo
    assert leggi("a.xlsx", _scrivi_xlsx("Nome\tEmail\nMario Rossi\tm@r.it")).forzati["Mario Rossi"] == "PERSONA"
    import pypdfium2  # noqa: F401  (la libreria binaria pdfium)
    pypdfium2.PdfDocument.new()
    from PIL import Image, ImageDraw, ImageFont

    from .oscura import oscura as _oscura
    im = Image.new("RGB", (900, 160), "white")
    ImageDraw.Draw(im).text((30, 50), "Referente: Lucia Ferretti, tel. 347 123 4567", font=ImageFont.load_default(size=32), fill="black")
    buf = __import__("io").BytesIO(); im.save(buf, "PNG")
    letto = leggi("prova.png", buf.getvalue())
    assert "Ferrett" in letto.testo, letto.testo
    o = _oscura("prova.png", buf.getvalue(), {"347 123 4567": "[TELEFONO_1]"})
    assert o.coperti == 1 and o.pdf[:4] == b"%PDF", o
    import webview  # noqa: F401
    print(f"segnaposto {__version__}: pacchetto completo", flush=True)


def main() -> None:
    """Punto d'ingresso dell'app impacchettata (doppio clic su Mac e Windows)."""
    if os.environ.get("SEGNAPOSTO_PROVA"):
        return prova_pacchetto()
    avvia(apri_browser=not os.environ.get("SEGNAPOSTO_NO_BROWSER"),
          finestra=False if os.environ.get("SEGNAPOSTO_BROWSER") else None)


if __name__ == "__main__":
    main()
