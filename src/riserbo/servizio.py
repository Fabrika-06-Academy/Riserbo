"""Un piccolo servizio HTTP locale, per usare Riserbo da altri programmi (un'automazione, un sito, n8n).

    riserbo servi --porta 8765

POST /pseudonimizza  {"testo": "..."}  ->  {"testo": "...", "trovati": [{"tipo", "valore", "inizio", "fine"}], "segnaposto": {...}}
GET  /salute                           ->  {"ok": true}

Ascolta solo su 127.0.0.1 per impostazione: non va esposto su internet. Non salva e non registra i testi.
La tabella dei segnaposto viene restituita al chiamante, che decide se e dove conservarla.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .motore import Segnaposto

MAX_CARATTERI = 20000


def crea_gestore(sp: Segnaposto, max_caratteri: int = MAX_CARATTERI):
    class Gestore(BaseHTTPRequestHandler):
        server_version = "riserbo"

        def log_message(self, *args) -> None:  # niente registro delle richieste: i testi possono contenere dati personali
            pass

        def _rispondi(self, codice: int, dati: dict) -> None:
            corpo = json.dumps(dati, ensure_ascii=False).encode("utf-8")
            self.send_response(codice)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)

        def do_GET(self) -> None:
            if self.path == "/salute":
                self._rispondi(200, {"ok": True})
            else:
                self._rispondi(404, {"errore": "non trovato"})

        def do_POST(self) -> None:
            if self.path != "/pseudonimizza":
                return self._rispondi(404, {"errore": "non trovato"})
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > max_caratteri * 4 + 1000:
                return self._rispondi(413, {"errore": f"testo vuoto o oltre {max_caratteri} caratteri"})
            try:
                testo = json.loads(self.rfile.read(n).decode("utf-8")).get("testo", "")
            except (ValueError, AttributeError):
                return self._rispondi(400, {"errore": "serve un JSON con il campo testo"})
            if not isinstance(testo, str) or not testo.strip() or len(testo) > max_caratteri:
                return self._rispondi(413, {"errore": f"testo vuoto o oltre {max_caratteri} caratteri"})
            r = sp.pseudonimizza(testo)
            self._rispondi(200, {"testo": r.testo, "trovati": r.trovati, "segnaposto": r.tabella.valori})

    return Gestore


def servi(host: str = "127.0.0.1", porta: int = 8765, sp: Segnaposto | None = None, max_caratteri: int = MAX_CARATTERI) -> None:
    sp = sp or Segnaposto()
    sp.pseudonimizza("Prova di avvio, Mario Rossi.")  # carica il modello prima della prima richiesta vera
    httpd = ThreadingHTTPServer((host, porta), crea_gestore(sp, max_caratteri))
    print(f"Riserbo in ascolto su http://{host}:{porta}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
