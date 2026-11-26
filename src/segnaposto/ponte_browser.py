"""Il canale locale per l'estensione del browser: 127.0.0.1:8789, con un codice di collegamento.

L'estensione (ChatGPT, Claude, Gemini…) non contiene il modello: chiede all'app aperta di pseudonimizzare il messaggio
prima dell'invio e i valori dei segnaposto da mostrare nelle risposte. Usa la stessa pratica della finestra e delle
scorciatoie, e le stesse scelte di «Cosa nascondere».

Regole: solo 127.0.0.1; il codice di collegamento in ogni richiesta; le pagine web non possono usarlo (accettiamo solo
richieste senza Origin o con Origin di un'estensione).

POST /stato    {}                         -> {ok, versione, pronto, segnaposto}
POST /proteggi {testo}                    -> {testo, trovati, tipi}
POST /valori   {segnaposto: ["[PERSONA_1]"]} -> {valori: {"[PERSONA_1]": "Mario Rossi"}}
POST /nuova    {}                         -> {ok}
"""

from __future__ import annotations

import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__
from .motore import SEGNAPOSTO

PORTA_PREDEFINITA = 8789
ORIGINI_AMMESSE = ("chrome-extension://", "moz-extension://", "safari-web-extension://")
MAX_TESTO = 200_000


def nuovo_codice() -> str:
    return secrets.token_urlsafe(18)


def crea_gestore(stato, codice: str):
    class Gestore(BaseHTTPRequestHandler):
        server_version = "segnaposto-browser"

        def log_message(self, *a) -> None:
            pass

        def _json(self, n: int, d: dict) -> None:
            corpo = json.dumps(d, ensure_ascii=False).encode("utf-8")
            self.send_response(n)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)

        def do_GET(self) -> None:
            self._json(404, {"errore": "non trovato"})

        def do_POST(self) -> None:
            origine = self.headers.get("Origin") or ""
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
            if (origine and not origine.startswith(ORIGINI_AMMESSE)) or host not in ("127.0.0.1", "localhost"):
                return self._json(403, {"errore": "Richiesta rifiutata."})
            if not secrets.compare_digest(self.headers.get("X-Segnaposto-Token", ""), codice):
                return self._json(401, {"errore": "Codice di collegamento sbagliato: copialo di nuovo dall'app (Automazioni → Browser)."})
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_TESTO * 4:
                return self._json(413, {"errore": "Testo troppo lungo."})
            try:
                dati = json.loads(self.rfile.read(n) or b"{}")
                return self._json(200, self._instrada(self.path, dati if isinstance(dati, dict) else {}))
            except ValueError as e:
                return self._json(400, {"errore": str(e)})

        def _instrada(self, percorso: str, dati: dict) -> dict:
            if percorso == "/stato":
                return {"ok": True, "versione": __version__, "pronto": stato.sp is not None,
                        "segnaposto": len(stato.tabella.valori)}
            if percorso == "/proteggi":
                testo = str(dati.get("testo", ""))[:MAX_TESTO]
                if stato.sp is None:
                    raise ValueError("segnaposto sta ancora caricando il modello italiano: riprova tra qualche secondo.")
                with stato.lock:
                    stato.ultimo_uso = time.time()
                    r = stato.sp.pseudonimizza(testo, stato.tabella, forzati=stato.forzati,
                                               ignora=stato.ignora | stato.in_chiaro, escludi=stato.escludi)
                    stato.inviati = {s for s in stato.tabella.valori if s in r.testo}
                    stato.versione_pratica += 1
                tipi: dict[str, int] = {}
                for t in r.trovati:
                    tipi[t["tipo"]] = tipi.get(t["tipo"], 0) + 1
                return {"testo": r.testo, "trovati": len(r.trovati), "tipi": tipi}
            if percorso == "/valori":
                chiesti = [s for s in dati.get("segnaposto") or [] if isinstance(s, str) and SEGNAPOSTO.fullmatch(s)][:500]
                with stato.lock:
                    stato.ultimo_uso = time.time()
                    return {"valori": {s: stato.tabella.valori[s] for s in chiesti if s in stato.tabella.valori}}
            if percorso == "/nuova":
                with stato.lock:
                    stato.nuova_pratica()
                return {"ok": True}
            raise ValueError("Percorso sconosciuto.")

    return Gestore


def avvia_ponte(stato, codice: str, porta: int = PORTA_PREDEFINITA) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer(("127.0.0.1", porta), crea_gestore(stato, codice))
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True, name="ponte-browser").start()
    return httpd
