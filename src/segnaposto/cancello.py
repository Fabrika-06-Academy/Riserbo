"""Il cancello: un proxy locale compatibile con le API di OpenAI e Anthropic.

n8n, Make, script Python, Open WebUI, gli editor di codice: invece di parlare direttamente con il fornitore parlano con
segnaposto, che pseudonimizza ogni richiesta in uscita e rimette i valori veri nella risposta (anche in streaming).

    OpenAI e compatibili   base URL  http://127.0.0.1:8788/openai/v1
    Anthropic              base URL  http://127.0.0.1:8788/anthropic

La chiave API del fornitore passa com'è: segnaposto non la conserva. Le regole:
- si rimettono solo i segnaposto nati da *questa* richiesta: un segnaposto scritto apposta nel testo non tira fuori
  il valore di un'altra conversazione;
- immagini e file allegati sono rifiutati (non sappiamo ancora pseudonimizzarli), a meno di `consenti_allegati`;
- le richieste dei siti web (intestazione Origin) sono rifiutate: il cancello è per i programmi, non per le pagine;
- il registro tiene fornitore, modello e quanti dati di che tipo: mai i valori.
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from .motore import SEGNAPOSTO, Segnaposto
from .tabella import Tabella

PORTA_PREDEFINITA = 8788
FORNITORI = {"openai": "https://api.openai.com", "anthropic": "https://api.anthropic.com"}
PROTETTI = ("/v1/chat/completions", "/v1/responses", "/v1/messages", "/v1/messages/count_tokens", "/v1/embeddings",
            "/v1/completions")
INOLTRA = ("authorization", "x-api-key", "anthropic-version", "anthropic-beta", "openai-organization", "openai-project",
           "openai-beta", "content-type", "http-referer", "x-title", "user-agent")
ALLEGATI = {"image_url", "input_audio", "file", "input_image", "input_file", "image", "document"}
PENSIERI = {"thinking", "redacted_thinking"}  # firmati dal fornitore: non si toccano, né all'andata né al ritorno
MAX_CORPO = 32 * 1024 * 1024
_INIZIO = re.compile(r"\[[A-Z_]*\d*")  # un pezzo di segnaposto rimasto a metà alla fine di un frammento


class Rifiuto(Exception):
    def __init__(self, stato: int, messaggio: str) -> None:
        super().__init__(messaggio)
        self.stato, self.messaggio = stato, messaggio


@dataclass
class Richiesta:
    mappa: dict[str, str] = field(default_factory=dict)  # segnaposto -> valore, solo quelli nati da questa richiesta
    rimessi: int = 0

    def conta(self) -> dict[str, int]:
        c: dict[str, int] = {}
        for s in self.mappa:
            tipo = s[1:].rsplit("_", 1)[0]
            c[tipo] = c.get(tipo, 0) + 1
        return c


def normalizza_base(url: str) -> str:
    url = url.strip().rstrip("/")
    return url[:-3] if url.endswith("/v1") else url


class Cancello:
    def __init__(self, motore: Segnaposto | Callable[[], Segnaposto | None], lock: threading.Lock | None = None,
                 fornitori: dict[str, str] | None = None, consenti_allegati: bool = False,
                 escludi: Callable[[], set[str] | None] = lambda: None, in_chiaro: Callable[[], set[str]] = lambda: set(),
                 rinnova: float = 3600) -> None:
        self.motore = motore if callable(motore) and not isinstance(motore, Segnaposto) else (lambda: motore)
        self.lock = lock or threading.Lock()
        self.fornitori = {k: normalizza_base(v) for k, v in {**FORNITORI, **(fornitori or {})}.items()}
        self.consenti_allegati = consenti_allegati
        self.escludi, self.in_chiaro, self.rinnova = escludi, in_chiaro, rinnova
        self.registro: deque[dict] = deque(maxlen=200)
        self.nuova_tabella()

    def nuova_tabella(self) -> None:
        self.tabella = Tabella()
        self.cache: dict[str, tuple[str, set[str]]] = {}
        self.ultimo_uso = time.time()

    # ------------------------------------------------------------ andata: pseudonimizzare la richiesta

    def proteggi(self, testo, ric: Richiesta):
        if not isinstance(testo, str) or not testo.strip():
            return testo
        sp = self.motore()
        if sp is None:
            raise Rifiuto(503, "segnaposto sta ancora caricando il modello italiano: riprova tra qualche secondo.")
        with self.lock:
            if time.time() - self.ultimo_uso > self.rinnova:  # dopo un'ora ferma la tabella non resta in memoria
                self.nuova_tabella()
            self.ultimo_uso = time.time()
            c = self.cache.get(testo)
            if c is None:
                r = sp.pseudonimizza(testo, self.tabella, ignora=self.in_chiaro(), escludi=self.escludi())
                c = (r.testo, {self.tabella.segnaposto(t["tipo"], t["valore"]) for t in r.trovati})
                if len(self.cache) > 5000:
                    self.cache.clear()
                self.cache[testo] = c  # la cronologia torna a ogni richiesta: niente doppio lavoro
            ric.mappa.update({s: self.tabella.valori[s] for s in c[1] if s in self.tabella.valori})
        return c[0]

    def _proteggi_json(self, s, ric: Richiesta):
        """Argomenti degli strumenti: JSON dentro una stringa."""
        if not isinstance(s, str):
            return s
        try:
            v = json.loads(s)
        except ValueError:
            return self.proteggi(s, ric)
        return json.dumps(self._cammina(v, ric), ensure_ascii=False)

    def _cammina(self, v, ric: Richiesta):
        if isinstance(v, str):
            return self.proteggi(v, ric)
        if isinstance(v, list):
            return [self._cammina(x, ric) for x in v]
        if isinstance(v, dict):
            return {k: self._cammina(x, ric) for k, x in v.items()}
        return v

    def _parti(self, contenuto, ric: Richiesta):
        if isinstance(contenuto, str):
            return self.proteggi(contenuto, ric)
        if not isinstance(contenuto, list):
            return contenuto
        for p in contenuto:
            if not isinstance(p, dict):
                continue
            t = p.get("type")
            if t in PENSIERI:
                continue
            if t in ALLEGATI and not self.consenti_allegati:
                raise Rifiuto(400, "segnaposto non sa ancora proteggere immagini e file allegati: la richiesta non è "
                                   "partita. Manda il testo, oppure avvia il cancello con --consenti-allegati.")
            if isinstance(p.get("text"), str):
                p["text"] = self.proteggi(p["text"], ric)
            if t == "tool_result":
                p["content"] = self._parti(p.get("content"), ric)
            if t == "tool_use" and "input" in p:
                p["input"] = self._cammina(p["input"], ric)
        return contenuto

    def proteggi_corpo(self, percorso: str, corpo: dict, ric: Richiesta) -> dict:
        if percorso.endswith("/chat/completions"):
            for m in corpo.get("messages") or []:
                if isinstance(m, dict):
                    m["content"] = self._parti(m.get("content"), ric)
                    for tc in m.get("tool_calls") or []:
                        f = tc.get("function") if isinstance(tc, dict) else None
                        if isinstance(f, dict):
                            f["arguments"] = self._proteggi_json(f.get("arguments"), ric)
        elif percorso.endswith("/responses"):
            corpo["instructions"] = self.proteggi(corpo.get("instructions"), ric) if "instructions" in corpo else None
            if corpo["instructions"] is None:
                corpo.pop("instructions")
            if isinstance(corpo.get("input"), str):
                corpo["input"] = self.proteggi(corpo["input"], ric)
            for it in corpo.get("input") if isinstance(corpo.get("input"), list) else []:
                if not isinstance(it, dict):
                    continue
                if "content" in it:
                    it["content"] = self._parti(it["content"], ric)
                if it.get("type") == "function_call":
                    it["arguments"] = self._proteggi_json(it.get("arguments"), ric)
                if it.get("type") == "function_call_output":
                    it["output"] = self._proteggi_json(it.get("output"), ric)
        elif "/messages" in percorso:
            if "system" in corpo:
                corpo["system"] = self._parti(corpo["system"], ric)
            for m in corpo.get("messages") or []:
                if isinstance(m, dict):
                    m["content"] = self._parti(m.get("content"), ric)
        elif percorso.endswith("/embeddings") or percorso.endswith("/completions"):
            k = "input" if percorso.endswith("/embeddings") else "prompt"
            v = corpo.get(k)
            if isinstance(v, str):
                corpo[k] = self.proteggi(v, ric)
            elif isinstance(v, list):
                corpo[k] = [self.proteggi(x, ric) if isinstance(x, str) else x for x in v]
        return corpo

    # ------------------------------------------------------------ ritorno: rimettere i valori veri

    @staticmethod
    def rimetti(s: str, ric: Richiesta, in_json: bool = False) -> str:
        def sost(m: re.Match) -> str:
            v = ric.mappa.get(m.group(0))
            if v is None:
                return m.group(0)
            ric.rimessi += 1
            return json.dumps(v, ensure_ascii=False)[1:-1] if in_json else v
        return SEGNAPOSTO.sub(sost, s)

    def rimetti_tutto(self, v, ric: Richiesta, chiave: str | None = None):
        if isinstance(v, str):
            return self.rimetti(v, ric, in_json=chiave in ("arguments", "partial_json"))
        if isinstance(v, list):
            return [self.rimetti_tutto(x, ric) for x in v]
        if isinstance(v, dict):
            if v.get("type") in PENSIERI:
                return v
            return {k: (x if k in ("thinking", "signature", "encrypted_content") else self.rimetti_tutto(x, ric, k))
                    for k, x in v.items()}
        return v

    # ------------------------------------------------------------ inoltro

    def instrada(self, percorso: str) -> tuple[str, str]:
        """(fornitore, URL del fornitore) per un percorso del cancello."""
        for nome in self.fornitori:
            if percorso.startswith(f"/{nome}/"):
                return nome, self.fornitori[nome] + percorso[len(nome) + 1:]
        nome = "anthropic" if percorso.startswith("/v1/messages") else "openai"
        return nome, self.fornitori[nome] + percorso

    def annota(self, fornitore: str, modello: str, ric: Richiesta, stato: int, flusso: bool) -> None:
        self.registro.appendleft({"ora": time.strftime("%Y-%m-%d %H:%M:%S"), "fornitore": fornitore,
                                  "modello": str(modello or "")[:60], "dati": ric.conta(), "rimessi": ric.rimessi,
                                  "stato": stato, "flusso": flusso})


class Flusso:
    """Rimette i valori in una risposta a pezzi (SSE). Un segnaposto può arrivare spezzato, «[PERS» + «ONA_1]»:
    la coda incompleta si trattiene finché non arriva il resto."""

    def __init__(self, cancello: Cancello, ric: Richiesta) -> None:
        self.c, self.ric = cancello, ric
        self.sospesi: dict[tuple, str] = {}

    def _passa(self, chiave: tuple, nuovo: str, fine: bool, in_json: bool = False) -> str:
        s = self.sospesi.pop(chiave, "") + (nuovo or "")
        if not fine:
            i = s.rfind("[")
            if i >= 0 and len(s) - i <= 40 and _INIZIO.fullmatch(s, i):
                s, self.sospesi[chiave] = s[:i], s[i:]
        return Cancello.rimetti(s, self.ric, in_json)

    def evento(self, nome: str | None, d: dict) -> list[tuple[str | None, dict]]:
        tipo = d.get("type")
        if "choices" in d and tipo is None:  # OpenAI chat.completion.chunk
            for ch in d.get("choices") or []:
                k, delta = ch.get("index", 0), ch.get("delta") or {}
                fine = ch.get("finish_reason") is not None
                if isinstance(delta.get("content"), str) or (fine and ("c", k) in self.sospesi):
                    delta["content"] = self._passa(("c", k), delta.get("content") or "", fine)
                for tc in delta.get("tool_calls") or []:
                    f = tc.get("function") or {}
                    if isinstance(f.get("arguments"), str):
                        f["arguments"] = self._passa(("t", k, tc.get("index", 0)), f["arguments"], fine, True)
                if fine:  # gli argomenti rimasti in sospeso escono con l'ultimo pezzo
                    for chiave in [x for x in self.sospesi if x[0] == "t" and x[1] == k]:
                        delta.setdefault("tool_calls", []).append(
                            {"index": chiave[2], "function": {"arguments": self._passa(chiave, "", True, True)}})
                if delta:
                    ch["delta"] = delta
            return [(nome, d)]
        if tipo == "content_block_delta":  # Anthropic
            i, delta = d.get("index", 0), d.get("delta") or {}
            if delta.get("type") == "text_delta":
                delta["text"] = self._passa(("a", i), delta.get("text", ""), False)
            elif delta.get("type") == "input_json_delta":
                delta["partial_json"] = self._passa(("aj", i), delta.get("partial_json", ""), False, True)
            return [(nome, d)]
        if tipo == "content_block_stop":
            i, prima = d.get("index", 0), []
            if ("a", i) in self.sospesi:
                prima.append(("content_block_delta", {"type": "content_block_delta", "index": i,
                                                      "delta": {"type": "text_delta", "text": self._passa(("a", i), "", True)}}))
            if ("aj", i) in self.sospesi:
                prima.append(("content_block_delta", {"type": "content_block_delta", "index": i, "delta": {
                    "type": "input_json_delta", "partial_json": self._passa(("aj", i), "", True, True)}}))
            return [*prima, (nome, d)]
        if tipo in ("response.output_text.delta", "response.function_call_arguments.delta"):  # OpenAI Responses
            testo = tipo == "response.output_text.delta"
            k = ("r", d.get("output_index"), d.get("content_index")) if testo else ("rf", d.get("output_index"))
            d["delta"] = self._passa(k, d.get("delta", ""), False, not testo)
            return [(nome, d)]
        if tipo in ("response.output_text.done", "response.function_call_arguments.done"):
            testo = tipo == "response.output_text.done"
            k = ("r", d.get("output_index"), d.get("content_index")) if testo else ("rf", d.get("output_index"))
            prima = []
            if k in self.sospesi:
                tipo_delta = tipo.replace(".done", ".delta")
                e = {x: d[x] for x in ("item_id", "output_index", "content_index", "sequence_number") if x in d}
                prima.append((tipo_delta, {"type": tipo_delta, **e, "delta": self._passa(k, "", True, not testo)}))
            return [*prima, (nome, self.c.rimetti_tutto(d, self.ric))]
        return [(nome, self.c.rimetti_tutto(d, self.ric))]


def crea_gestore(cancello: Cancello, chiave: str = "", host_locale: bool = True):
    class Gestore(BaseHTTPRequestHandler):
        server_version = "segnaposto-cancello"

        def log_message(self, *args) -> None:  # i testi possono contenere dati personali: niente registro HTTP
            pass

        def _errore(self, stato: int, messaggio: str) -> None:
            corpo = json.dumps({"type": "error", "error": {"type": "segnaposto", "message": messaggio}},
                               ensure_ascii=False).encode("utf-8")
            self.send_response(stato)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)

        def _percorso(self) -> str | None:
            if self.headers.get("Origin"):
                return None
            if host_locale:
                h = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
                if h not in ("127.0.0.1", "localhost", "::1"):  # niente DNS rebinding
                    return None
            p = self.path
            if chiave:
                if not p.startswith(f"/k/{chiave}/"):
                    return None
                p = p[len(chiave) + 3:]
            return p

        def do_GET(self) -> None:
            p = self._percorso()
            if p is None:
                return self._errore(403, "Richiesta rifiutata dal cancello di segnaposto.")
            if p in ("/", "/salute"):
                return self._json(200, {"ok": True, "segnaposto": "il cancello è attivo"})
            _f, url = cancello.instrada(p)
            self._inoltra("GET", url, None, Richiesta(), _f, "", False)

        def _json(self, stato: int, d: dict) -> None:
            corpo = json.dumps(d, ensure_ascii=False).encode("utf-8")
            self.send_response(stato)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)

        def do_POST(self) -> None:
            p = self._percorso()
            if p is None:
                return self._errore(403, "Richiesta rifiutata dal cancello di segnaposto.")
            fornitore, url = cancello.instrada(p)
            interno = url[len(cancello.fornitori[fornitore]):].split("?")[0]
            if not interno.endswith(PROTETTI):
                return self._errore(400, f"segnaposto non sa proteggere {interno}: la richiesta non è partita.")
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > MAX_CORPO:
                return self._errore(413, "Richiesta vuota o troppo grande.")
            try:
                corpo = json.loads(self.rfile.read(n).decode("utf-8"))
                if not isinstance(corpo, dict):
                    raise ValueError
            except ValueError:
                return self._errore(400, "La richiesta non è JSON valido.")
            ric = Richiesta()
            try:
                corpo = cancello.proteggi_corpo(interno, corpo, ric)
            except Rifiuto as e:
                cancello.annota(fornitore, corpo.get("model"), ric, e.stato, False)
                return self._errore(e.stato, e.messaggio)
            except Exception as e:  # mai inoltrare una richiesta che non siamo riusciti a proteggere
                return self._errore(500, f"segnaposto non è riuscito a proteggere la richiesta, che non è partita: {e}")
            dati = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
            self._inoltra("POST", url, dati, ric, fornitore, corpo.get("model"), bool(corpo.get("stream")))

        def _inoltra(self, metodo: str, url: str, dati: bytes | None, ric: Richiesta, fornitore: str, modello, flusso: bool) -> None:
            from .rete import apri
            intest = {h: self.headers[h] for h in INOLTRA if self.headers.get(h)}
            intest["Accept-Encoding"] = "identity"
            if dati is not None:
                intest["Content-Type"] = "application/json"
            req = urllib.request.Request(url, data=dati, method=metodo, headers=intest)
            try:
                r = apri(req, 600)
                stato = r.status
            except urllib.error.HTTPError as e:
                r, stato = e, e.code
            except Exception as e:
                cancello.annota(fornitore, modello, ric, 502, flusso)
                return self._errore(502, f"segnaposto non raggiunge {fornitore}: {getattr(e, 'reason', e)}")
            tipo = r.headers.get("Content-Type", "")
            if "text/event-stream" in tipo:
                self._flusso(r, stato, ric)
            else:
                corpo = r.read()
                if "json" in tipo:
                    try:
                        corpo = json.dumps(cancello.rimetti_tutto(json.loads(corpo), ric), ensure_ascii=False).encode("utf-8")
                    except ValueError:
                        pass
                self.send_response(stato)
                self.send_header("Content-Type", tipo or "application/json")
                self.send_header("Content-Length", str(len(corpo)))
                for h in ("request-id", "x-request-id", "openai-processing-ms"):
                    if r.headers.get(h):
                        self.send_header(h, r.headers[h])
                self.end_headers()
                self.wfile.write(corpo)
            if metodo == "POST":
                cancello.annota(fornitore, modello, ric, stato, flusso)

        def _flusso(self, r, stato: int, ric: Richiesta) -> None:
            self.send_response(stato)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            fl, nome, dati = Flusso(cancello, ric), None, []

            def scrivi(n: str | None, testo: str) -> None:
                self.wfile.write(((f"event: {n}\n" if n else "") + f"data: {testo}\n\n").encode("utf-8"))

            try:
                while True:
                    riga = r.readline()
                    if not riga:
                        break
                    riga = riga.decode("utf-8").rstrip("\r\n")
                    if riga.startswith("event:"):
                        nome = riga[6:].strip()
                    elif riga.startswith("data:"):
                        dati.append(riga[5:].lstrip(" "))
                    elif riga == "" and (dati or nome):
                        testo = "\n".join(dati)
                        try:
                            uscita = [(n, json.dumps(d, ensure_ascii=False)) for n, d in fl.evento(nome, json.loads(testo))]
                        except ValueError:  # [DONE] e simili
                            uscita = [(nome, testo)]
                        for n, t in uscita:
                            scrivi(n, t)
                        self.wfile.flush()
                        nome, dati = None, []
                    elif riga.startswith(":"):
                        self.wfile.write((riga + "\n\n").encode("utf-8"))
            except (BrokenPipeError, ConnectionResetError):
                pass

    return Gestore


def avvia_cancello(cancello: Cancello, host: str = "127.0.0.1", porta: int = PORTA_PREDEFINITA,
                   chiave: str = "") -> ThreadingHTTPServer:
    """Avvia il cancello su un thread e restituisce il server (per fermarlo: .shutdown())."""
    locale = host in ("127.0.0.1", "localhost", "::1")
    httpd = ThreadingHTTPServer((host, porta), crea_gestore(cancello, chiave, host_locale=locale))
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True, name="cancello").start()
    return httpd


def indirizzi(porta: int, host: str = "127.0.0.1", chiave: str = "") -> dict[str, str]:
    base = f"http://{host}:{porta}" + (f"/k/{chiave}" if chiave else "")
    return {"openai": f"{base}/openai/v1", "anthropic": f"{base}/anthropic"}
