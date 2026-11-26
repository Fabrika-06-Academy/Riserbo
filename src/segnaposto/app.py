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
import urllib.error
import urllib.request
import os
import re
import secrets
import sys
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
REPO_API = "https://api.github.com/repos/Fabrika-06-Academy/segnaposto/releases/latest"
URL_PARERI = "https://academy.fabrika06.com/wp-json/f06/v1/segnaposto-parere"
LINK_AMMESSI = ("https://github.com/Fabrika-06-Academy/", "https://academy.fabrika06.com/")


def _versione(t: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", t)[:3])


def _sistema() -> str:
    import platform
    return f"{platform.system()} {platform.machine()}".strip()


def controlla_aggiornamento() -> dict:
    """Chiede a GitHub il numero dell'ultima versione. Non manda nulla: è una lettura pubblica, come aprire la pagina."""
    import sys
    import urllib.request
    req = urllib.request.Request(REPO_API, headers={"User-Agent": f"segnaposto/{__version__}", "Accept": "application/vnd.github+json"})
    from .rete import apri
    d = json.loads(apri(req, 6).read())
    tag = str(d.get("tag_name", ""))
    file = {a["name"]: a["browser_download_url"] for a in d.get("assets", [])}
    if sys.platform == "darwin":
        url = file.get("segnaposto-mac-apple-silicon.dmg") or file.get("segnaposto-mac-apple-silicon.zip")
    elif os.name == "nt":
        url = file.get("segnaposto-windows.zip")
    else:
        url = None
    note = re.sub(r"\s+", " ", str(d.get("body") or ""))[:400]
    return {"nuova": _versione(tag) > _versione(__version__), "versione": tag.lstrip("v"), "attuale": __version__,
            "url": url or d.get("html_url"), "pagina": d.get("html_url"), "note": note}


def invia_parere(dati: dict) -> None:
    """Manda all'Academy solo quello che la persona ha scritto nel riquadro del parere, più versione e sistema."""
    import urllib.request
    corpo = {"voto": int(dati.get("voto") or 0), "testo": str(dati.get("testo") or "")[:3000],
             "email": str(dati.get("email") or "")[:200], "versione": __version__, "sistema": _sistema(), "sito": ""}
    req = urllib.request.Request(URL_PARERI, data=json.dumps(corpo).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": f"segnaposto/{__version__}"})
    try:
        from .rete import apri
        apri(req, 10).read()
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("errore")
        except Exception:
            msg = None
        raise ValueError(msg or f"L'Academy ha risposto con un errore ({e.code}).") from e
    except OSError as e:
        raise ValueError("Non riesco a raggiungere l'Academy: sei collegato a internet?") from e
MAX_RICHIESTA = 36 * 1024 * 1024  # un file da 25 MB in base64


class Stato:
    def __init__(self, sp: Segnaposto | None = None) -> None:
        self.sp = sp                    # None finché il modello si carica
        self.errore_avvio = ""
        self.ultimo_uso = time.time()
        self.lock = threading.Lock()
        self.escludi: set[str] | None = None   # preferenze della pagina («Cosa nascondere»), usate anche dalle scorciatoie
        self.in_chiaro: set[str] = set()
        self.versione_pratica = 0              # cresce a ogni cambiamento: la pagina si aggiorna se cambia
        self.ultimo_appunti = ""               # cosa è successo con l'ultima scorciatoia
        self.scorciatoie = None
        self.vassoio = None
        self.mostra_finestra = None
        self.cancello = None                   # il proxy per le automazioni (cancello.py), se acceso
        self.cancello_httpd = None
        self.cancello_errore = ""
        self.nuova_pratica()

    def nuova_pratica(self) -> None:
        self.tabella = Tabella()
        self.inviati: set[str] = set()  # segnaposto mandati al modello: servono per trovare i mancanti
        self.forzati: dict[str, str] = {}  # valori da nascondere comunque (colonne riconosciute, aggiunte a mano)
        self.ignora: set[str] = set()      # falsi allarmi indicati da chi rilegge
        self.versione_pratica = getattr(self, "versione_pratica", 0) + 1
        self.documento: tuple[str, bytes, str] | None = None  # PDF o immagine originale, per l'oscuramento

    def carica_modello(self) -> None:
        try:
            sp = Segnaposto()
            sp.pseudonimizza("Avvio, Mario Rossi.")  # scalda il modello: la prima richiesta vera è subito veloce
            self.sp = sp
        except Exception as e:  # pragma: no cover - si vede nella finestra
            self.errore_avvio = f"Il modello italiano non si è caricato: {e}"


def _file_impostazioni():
    from pathlib import Path
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "segnaposto" / "impostazioni.json"


def leggi_impostazioni() -> dict:
    try:
        return json.loads(_file_impostazioni().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def salva_impostazioni(**valori) -> None:
    try:
        f = _file_impostazioni()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({**leggi_impostazioni(), **valori}, indent=2), encoding="utf-8")
    except OSError:
        pass


def accendi_cancello(stato: Stato, porta: int | None = None) -> None:
    """Il proxy per le automazioni dentro l'app: stesso motore, stesse scelte di «Cosa nascondere», tabella sua."""
    from .cancello import PORTA_PREDEFINITA, Cancello, avvia_cancello
    spegni_cancello(stato)
    porta = int(porta or leggi_impostazioni().get("porta_cancello") or PORTA_PREDEFINITA)
    c = Cancello(lambda: stato.sp, lock=stato.lock, escludi=lambda: stato.escludi, in_chiaro=lambda: stato.in_chiaro)
    try:
        stato.cancello_httpd = avvia_cancello(c, porta=porta)
    except OSError:
        stato.cancello_errore = f"La porta {porta} è già usata da un altro programma (o da un'altra copia di segnaposto)."
        return
    stato.cancello, stato.cancello_errore = c, ""


def spegni_cancello(stato: Stato) -> None:
    if stato.cancello_httpd is not None:
        h, stato.cancello_httpd, stato.cancello = stato.cancello_httpd, None, None
        threading.Thread(target=h.shutdown, daemon=True).start()
    stato.cancello_errore = ""


def stato_cancello(stato: Stato) -> dict:
    from .cancello import PORTA_PREDEFINITA, indirizzi
    porta = stato.cancello_httpd.server_address[1] if stato.cancello_httpd else \
        int(leggi_impostazioni().get("porta_cancello") or PORTA_PREDEFINITA)
    c = stato.cancello
    return {"attivo": c is not None, "porta": porta, "indirizzi": indirizzi(porta), "errore": stato.cancello_errore,
            "registro": list(c.registro)[:40] if c else [], "protetti": sum(sum(v["dati"].values()) for v in c.registro) if c else 0}


def proteggi_appunti(stato: Stato, avvisa=None) -> str:
    """Scorciatoia ⌃⌥P / Ctrl+Alt+P: il testo copiato torna negli appunti con i segnaposto."""
    from .scorciatoie import leggi_appunti, notifica, scrivi_appunti
    avvisa = avvisa or notifica
    try:
        testo = leggi_appunti()
        if not testo.strip():
            msg = "Gli appunti sono vuoti: prima copia il testo da proteggere."
        elif stato.sp is None:
            msg = "Sto ancora caricando il modello italiano: riprova tra qualche secondo."
        else:
            with stato.lock:
                stato.ultimo_uso = time.time()
                r = stato.sp.pseudonimizza(testo, stato.tabella, forzati=stato.forzati, ignora=stato.ignora | stato.in_chiaro,
                                           escludi=stato.escludi)
                stato.inviati = {s for s in stato.tabella.valori if s in r.testo}
                stato.versione_pratica += 1
            scrivi_appunti(r.testo)
            n = len(r.trovati)
            msg = (f"{n} dati sostituiti" if n != 1 else "1 dato sostituito") + ": incolla nella chat." if n else \
                "Nessun dato trovato: rileggi comunque prima di incollare."
    except Exception as e:
        msg = f"Non riesco a usare gli appunti: {e}"
    stato.ultimo_appunti = msg
    avvisa("segnaposto · proteggi", msg)
    return msg


def ripristina_appunti(stato: Stato, avvisa=None) -> str:
    """Scorciatoia ⌃⌥R / Ctrl+Alt+R: la risposta copiata torna negli appunti con i nomi veri."""
    from .scorciatoie import leggi_appunti, notifica, scrivi_appunti
    avvisa = avvisa or notifica
    try:
        testo = leggi_appunti()
        with stato.lock:
            stato.ultimo_uso = time.time()
            e = ripristina(testo, stato.tabella, attesi=stato.inviati)
        rimessi = len(SEGNAPOSTO.findall(testo)) - len([x for x in SEGNAPOSTO.findall(testo) if x in e.inventati])
        if not SEGNAPOSTO.search(testo):
            msg = "Negli appunti non ci sono segnaposto: copia prima la risposta della chat."
        else:
            scrivi_appunti(e.testo)
            msg = (f"{rimessi} valori rimessi" if rimessi != 1 else "1 valore rimesso") + ": incolla dove ti serve."
            if e.inventati:
                msg += f" Attenzione: {', '.join(e.inventati)} non esistono in questa pratica."
    except Exception as ex:
        msg = f"Non riesco a usare gli appunti: {ex}"
    stato.ultimo_appunti = msg
    avvisa("segnaposto · rimetti i nomi", msg)
    return msg


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
                sc = stato.scorciatoie
                return self._json(200, {"pronto": stato.sp is not None, "errore": stato.errore_avvio, "versione": __version__,
                                        "pratica": stato.versione_pratica, "appunti": stato.ultimo_appunti,
                                        "scorciatoie": {"attive": sc.attive, "errore": sc.errore} if sc else None,
                                        "vassoio": bool(stato.vassoio and stato.vassoio.attivo)})
            if percorso == "/api/cancello":
                azione = dati.get("azione")
                if dati.get("porta") and not 1024 <= int(dati["porta"]) <= 65535:
                    raise ValueError("La porta va scelta tra 1024 e 65535.")
                if azione in ("accendi", "spegni"):
                    if azione == "accendi":
                        accendi_cancello(stato, dati.get("porta"))
                    else:
                        spegni_cancello(stato)
                    salva_impostazioni(cancello=stato.cancello is not None,
                                       **({"porta_cancello": int(dati["porta"])} if dati.get("porta") else {}))
                return self._json(200, stato_cancello(stato))
            if percorso == "/api/mcp":
                from .server_mcp import cartelle_predefinite, collega_claude_desktop, scollega_claude_desktop, stato_claude_desktop
                azione = dati.get("azione")
                if azione == "collega":
                    cartelle = [str(c) for c in dati.get("cartelle") or [] if isinstance(c, str)]
                    mancanti = [c for c in cartelle if not os.path.isdir(os.path.expanduser(c))]
                    if not cartelle or mancanti:
                        raise ValueError("Scegli almeno una cartella esistente." if not cartelle else f"Non trovo la cartella {mancanti[0]}.")
                    collega_claude_desktop([os.path.abspath(os.path.expanduser(c)) for c in cartelle])
                    salva_impostazioni(cartelle_mcp=cartelle)
                elif azione == "scollega":
                    scollega_claude_desktop()
                st = stato_claude_desktop()
                st["proposte"] = leggi_impostazioni().get("cartelle_mcp") or st["cartelle"] or [str(c) for c in cartelle_predefinite()]
                return self._json(200, st)
            if percorso == "/api/mostra":  # un secondo avvio dell'app chiede a questa di farsi vedere
                if stato.mostra_finestra:
                    threading.Thread(target=stato.mostra_finestra, daemon=True).start()
                return self._json(200, {"ok": True})
            if percorso == "/api/tabella":
                return self._json(200, {"tabella": stato.tabella.valori, "pratica": stato.versione_pratica})
            if percorso == "/api/preferenze":
                esc = dati.get("escludi")
                stato.escludi = {str(x) for x in esc if isinstance(x, str)} if isinstance(esc, list) else None
                stato.in_chiaro = {str(x).strip() for x in dati.get("in_chiaro", []) if isinstance(x, str) and str(x).strip()}
                return self._json(200, {"ok": True})
            if percorso == "/api/appunti":
                azione = proteggi_appunti if dati.get("azione") == "proteggi" else ripristina_appunti
                return self._json(200, {"messaggio": azione(stato, avvisa=lambda *_: None)})
            if percorso == "/api/aggiornamento":
                try:
                    return self._json(200, controlla_aggiornamento())
                except Exception as e:  # il motivo serve: «Controlla adesso» lo mostra
                    motivo = getattr(e, "reason", None) or e
                    return self._json(200, {"nuova": False, "errore": f"GitHub non raggiungibile ({motivo})"[:200]})
            if percorso == "/api/apri":
                url = str(dati.get("url", ""))
                if not url.startswith(LINK_AMMESSI):
                    raise ValueError("Link non ammesso.")
                webbrowser.open(url)
                return self._json(200, {"ok": True})
            if percorso == "/api/parere":
                invia_parere(dati)
                return self._json(200, {"ok": True})
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
                    sempre = {str(x).strip() for x in dati.get("in_chiaro", []) if isinstance(x, str) and str(x).strip()}
                    stato.escludi, stato.in_chiaro = escludi, sempre
                    r = stato.sp.pseudonimizza(testo, stato.tabella, forzati=stato.forzati, ignora=stato.ignora | sempre, escludi=escludi)
                    # I segnaposto attesi nella risposta sono quelli dell'ultimo testo mandato, non di tutta la pratica.
                    stato.inviati = {s for s in stato.tabella.valori if s in r.testo}
                    stato.versione_pratica += 1
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

    def scegli_cartella(self) -> str:
        scelta = self.finestra.create_file_dialog(_dialogo("FOLDER"))
        if not scelta:
            return ""
        return scelta if isinstance(scelta, str) else scelta[0]

    def apri(self) -> dict:
        tipi = ("Documenti (*.txt;*.md;*.docx;*.pdf;*.eml;*.msg;*.xlsx;*.csv;*.png;*.jpg;*.jpeg;*.tif;*.tiff)", "Tutti i file (*.*)")
        scelta = self.finestra.create_file_dialog(_dialogo("OPEN"), file_types=tipi)
        if not scelta:
            return {}
        percorso = scelta if isinstance(scelta, str) else scelta[0]
        with open(percorso, "rb") as f:
            return {"nome": os.path.basename(percorso), "dati": base64.b64encode(f.read()).decode("ascii")}


def avvia(sp: Segnaposto | None = None, apri_browser: bool = True, porta: int = 0, finestra: bool | None = None,
          nascosta: bool = False) -> None:
    """Apre l'app. `finestra=None`: finestra nativa se pywebview c'è, altrimenti il browser.
    `nascosta`: parte solo con l'icona vicino all'orologio (avvio all'accensione)."""
    stato, chiave, porta_ref = Stato(sp), secrets.token_urlsafe(24), [0]
    httpd: ThreadingHTTPServer | None = None
    win = None
    uscendo, in_finestra = [False], [False]

    def ferma() -> None:
        uscendo[0] = True
        time.sleep(0.3)
        if win is not None:
            win.destroy()
        httpd.shutdown()

    httpd = ThreadingHTTPServer(("127.0.0.1", porta), crea_gestore(stato, chiave, porta_ref, ferma))
    porta_ref[0] = httpd.server_address[1]
    url = f"http://127.0.0.1:{porta_ref[0]}/?t={chiave}"
    if sp is None:
        threading.Thread(target=stato.carica_modello, daemon=True).start()
    if leggi_impostazioni().get("cancello"):
        accendi_cancello(stato)

    def sorveglia() -> None:
        while True:
            time.sleep(30)
            if stato.cancello is not None:  # le automazioni contano come uso
                stato.ultimo_uso = max(stato.ultimo_uso, stato.cancello.ultimo_uso)
            if time.time() - stato.ultimo_uso > INATTIVITA_MAX:
                if not in_finestra[0]:  # nel browser: nessuno chiude il server al posto tuo
                    ferma()
                    return
                with stato.lock:  # nell'app resta aperta (scorciatoie, icona), ma la tabella non resta in memoria
                    if stato.tabella.valori or stato.documento:
                        stato.nuova_pratica()
                    stato.ultimo_uso = time.time()

    threading.Thread(target=sorveglia, daemon=True).start()

    webview = None
    if finestra is not False and (apri_browser or nascosta):
        try:
            import webview  # type: ignore
        except ImportError:
            if finestra:
                raise
    if webview is not None:
        in_finestra[0] = True
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        ponte = Ponte()
        win = webview.create_window("segnaposto", url, js_api=ponte, width=1280, height=860, min_size=(820, 600),
                                    text_select=True, hidden=nascosta)
        ponte.finestra = win
        from .scorciatoie import Scorciatoie, notifica
        from .vassoio import (Voce, Vassoio, al_riaprire_mac, avvio_automatico, avvio_possibile, imposta_avvio, mostra_nel_dock,
                              segna_istanza, sta_uscendo_mac, togli_istanza)

        def piccola_notifica(titolo: str, testo: str) -> None:
            """Windows: la notifica dell'icona; se manca, un riquadro in basso a destra che non prende il fuoco."""
            if vassoio.avviso(titolo, testo):
                return
            html = ("<body style='margin:0;font:14px Segoe UI,sans-serif;background:#121116;color:#fff;padding:12px 16px'>"
                    f"<b style='color:#FFC700'>{titolo}</b><br>{testo.replace('<', '&lt;')}</body>")
            try:
                try:
                    schermo = webview.screens[0]
                    x, y = schermo.width - 380, schermo.height - 170
                except Exception:
                    x = y = None
                w = webview.create_window("", html=html, width=360, height=96, frameless=True, on_top=True, focus=False,
                                          resizable=False, x=x, y=y)
                threading.Timer(3.0, w.destroy).start()
            except Exception:
                pass

        def avvisa_fn(titolo: str, testo: str) -> None:
            notifica(titolo, testo, piccola_notifica)

        def apri_finestra() -> None:
            mostra_nel_dock(True)
            win.show()
            try:
                win.restore()
            except Exception:
                pass

        def nuova() -> None:
            with stato.lock:
                stato.nuova_pratica()
            avvisa_fn("segnaposto", "Nuova pratica: la tabella precedente è stata cancellata.")

        def cancello_da_menu(acceso: bool) -> None:
            accendi_cancello(stato) if acceso else spegni_cancello(stato)
            salva_impostazioni(cancello=stato.cancello is not None)
            if acceso and stato.cancello is None:
                avvisa_fn("segnaposto · cancello", stato.cancello_errore)

        def esci() -> None:
            vassoio.togli()
            ferma()

        voci: list = [Voce("Apri segnaposto", apri_finestra), None,
                      Voce("Proteggi gli appunti", lambda: proteggi_appunti(stato, avvisa_fn), tasto="proteggi"),
                      Voce("Rimetti i nomi negli appunti", lambda: ripristina_appunti(stato, avvisa_fn), tasto="ripristina"),
                      Voce("Nuova pratica", nuova), None,
                      Voce("Cancello per le automazioni", spunta=lambda: stato.cancello is not None, cambia=cancello_da_menu), None]
        if avvio_possibile():
            voci += [Voce("Apri all'accensione", spunta=avvio_automatico, cambia=imposta_avvio), None]
        voci.append(Voce("Esci da segnaposto", esci))
        vassoio = Vassoio(voci, apri_finestra)
        stato.vassoio, stato.mostra_finestra = vassoio, apri_finestra
        segna_istanza(porta_ref[0], chiave)
        avvisato = [False]

        def chiudendo() -> bool:
            """Con l'icona attiva, chiudere la finestra la nasconde: le scorciatoie continuano a funzionare."""
            if uscendo[0] or not vassoio.attivo or sta_uscendo_mac():
                vassoio.togli()
                return True
            win.hide()
            mostra_nel_dock(False)
            if not avvisato[0]:
                avvisato[0] = True
                avvisa_fn("segnaposto resta attivo",
                          "Lo trovi nell'icona vicino all'orologio. Per uscire: icona → Esci da segnaposto.")
            return False

        win.events.closing += chiudendo
        sc = Scorciatoie({"proteggi": lambda: proteggi_appunti(stato, avvisa_fn),
                          "ripristina": lambda: ripristina_appunti(stato, avvisa_fn)})
        stato.scorciatoie = sc

        def all_avvio() -> None:
            sc.registra()
            if sys.platform == "darwin":
                from PyObjCTools import AppHelper
                fatto = threading.Event()
                AppHelper.callAfter(lambda: (vassoio.mostra(), fatto.set()))
                fatto.wait(5)
            else:
                vassoio.mostra()
            if sys.platform == "darwin":
                al_riaprire_mac(apri_finestra)
            if nascosta:
                if vassoio.attivo:
                    mostra_nel_dock(False)
                else:  # senza icona una finestra nascosta sarebbe irraggiungibile
                    apri_finestra()

        webview.start(func=all_avvio, private_mode=True)  # niente cache né cookie su disco
        vassoio.togli()
        togli_istanza(chiave)
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
    """Controllo del pacchetto costruito (in CI): tutto quello che serve c'è dentro? Esce con errore se manca qualcosa.
    Le righe vanno anche nel file SEGNAPOSTO_PROVA_ESITO: l'app per Windows non ha una console su cui stampare."""
    def nota(msg: str) -> None:
        print(msg, flush=True)
        if os.environ.get("SEGNAPOSTO_PROVA_ESITO"):
            with open(os.environ["SEGNAPOSTO_PROVA_ESITO"], "a", encoding="utf-8") as f:
                f.write(msg + "\n")

    from .documenti import _scrivi_docx, _scrivi_xlsx

    from .ner import cartella_cache, trova_modello
    dove = trova_modello()
    assert dove is not None and dove != cartella_cache(), f"il riconoscitore di entità non è dentro il pacchetto: {dove}"
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
    from .cancello import Cancello, Richiesta, avvia_cancello
    canc, ric = Cancello(sp), Richiesta()
    uscita = canc.proteggi_corpo("/v1/messages", {"messages": [{"role": "user", "content": "Scrive Mario Rossi."}]}, ric)
    assert "Mario Rossi" not in json.dumps(uscita) and ric.mappa and \
        canc.rimetti(f"Ciao {next(iter(ric.mappa))}", ric) == "Ciao Mario Rossi", uscita
    h = avvia_cancello(canc, porta=0)
    assert json.loads(urllib.request.urlopen(f"http://127.0.0.1:{h.server_address[1]}/salute", timeout=5).read())["ok"]
    h.shutdown()
    nota("::notice::cancello: ok")
    from .rete import apri as _apri  # HTTPS con i certificati inclusi: senza, niente avviso di aggiornamento né pareri
    try:
        _apri(urllib.request.Request(REPO_API, headers={"User-Agent": f"segnaposto/{__version__}"}), 20).read()
    except urllib.error.HTTPError:
        pass  # GitHub ha risposto (anche con un limite di richieste): la connessione HTTPS funziona
    nota("::notice::HTTPS verso GitHub: ok")
    import webview  # noqa: F401
    import sys as _sys
    if _sys.platform == "darwin" or os.name == "nt":
        from .scorciatoie import Scorciatoie, leggi_appunti, scrivi_appunti
        try:
            prima = leggi_appunti()
        except Exception:
            prima = ""
        scrivi_appunti("prova segnaposto àè €")
        assert leggi_appunti() == "prova segnaposto àè €", "appunti non funzionanti"
        scrivi_appunti(prima)
        sc = Scorciatoie({"proteggi": lambda: None, "ripristina": lambda: None})
        try:
            sc.registra_mac() if _sys.platform == "darwin" else sc.registra_win()
        except Exception as e:
            sc.errore = str(e)
        nota(f"::notice::scorciatoie registrate: {sc.attive} {sc.errore}")
        from . import vassoio as _v
        assert (_v.QUI / "vassoio-mac.png").exists() and (_v.QUI / "vassoio-win.png").exists(), "mancano le icone"
        if os.name == "nt":  # l'icona di Windows vive su un suo thread: si può provare anche qui
            vs = _v.Vassoio([_v.Voce("Prova", lambda: None), None, _v.Voce("Esci", lambda: None)], lambda: None)
            vs.mostra()
            nota(f"::notice::icona nell'area di notifica: {'ok' if vs.attivo else vs.errore}")
            vs.togli()
        else:
            from AppKit import NSMenu, NSStatusBar  # noqa: F401
            import objc  # noqa: F401
        nota(f"::notice::avvio all'accensione possibile: {_v.avvio_possibile()}")
    nota(f"segnaposto {__version__}: pacchetto completo")


def main() -> None:
    """Punto d'ingresso dell'app impacchettata (doppio clic su Mac e Windows)."""
    if os.environ.get("SEGNAPOSTO_PROVA"):
        return prova_pacchetto()
    if len(sys.argv) > 1 and sys.argv[1] == "mcp":  # avviato da Claude Desktop: niente finestra, solo stdin/stdout
        from .server_mcp import main_mcp
        sys.exit(main_mcp(sys.argv[2:]))
    from .vassoio import ARGOMENTO_SOTTOFONDO, risveglia_istanza
    if risveglia_istanza():  # è già aperta (magari solo nell'icona): mostra quella invece di aprirne un'altra
        return
    avvia(apri_browser=not os.environ.get("SEGNAPOSTO_NO_BROWSER"),
          finestra=False if os.environ.get("SEGNAPOSTO_BROWSER") else None, nascosta=ARGOMENTO_SOTTOFONDO in sys.argv)


if __name__ == "__main__":
    main()
