"""L'app locale: `segnaposto app` apre nel browser un'interfaccia che gira solo sul tuo computer.

Il flusso di ogni giorno:
  1. incolli un testo e lo pseudonimizzi;
  2. lo copi nella chat (ChatGPT, Claude, Copilot...);
  3. incolli la risposta e l'app rimette i valori veri, segnalando i segnaposto persi o inventati.

La tabella dei segnaposto vive solo in memoria, per la pratica in corso: «Nuova pratica» o la chiusura la cancellano.
Sicurezza: ascolta solo su 127.0.0.1, su una porta casuale, e ogni richiesta deve portare una chiave generata all'avvio
(così un altro sito aperto nel browser non può usare il servizio). Si chiude da sola dopo un'ora senza uso.
"""

from __future__ import annotations

import json
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files

from .motore import Segnaposto, ripristina
from .tabella import Tabella

INATTIVITA_MAX = 3600  # secondi


class Stato:
    def __init__(self, sp: Segnaposto) -> None:
        self.sp = sp
        self.tabella = Tabella()
        self.inviati: set[str] = set()  # segnaposto mandati al modello: servono per trovare i mancanti
        self.ultimo_uso = time.time()
        self.lock = threading.Lock()

    def nuova_pratica(self) -> None:
        self.tabella = Tabella()
        self.inviati = set()


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
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'")
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
                return self._invia(200, pagina.replace("__CHIAVE__", chiave).encode("utf-8"), "text/html; charset=utf-8")
            self._json(404, {"errore": "non trovato"})

        def do_POST(self) -> None:
            if not self._host_ok() or not secrets.compare_digest(self.headers.get("X-Chiave", ""), chiave):
                return self._json(403, {"errore": "non autorizzato"})
            n = int(self.headers.get("Content-Length") or 0)
            if n > 400_000:
                return self._json(413, {"errore": "testo troppo lungo"})
            try:
                dati = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
            except ValueError:
                return self._json(400, {"errore": "JSON non valido"})
            testo = dati.get("testo", "") if isinstance(dati, dict) else ""
            with stato.lock:
                stato.ultimo_uso = time.time()
                if self.path == "/api/pseudonimizza":
                    r = stato.sp.pseudonimizza(testo, stato.tabella)
                    stato.inviati |= {s for s in stato.tabella.valori if s in r.testo}
                    return self._json(200, {"testo": r.testo, "trovati": r.trovati, "tabella": stato.tabella.valori})
                if self.path == "/api/ripristina":
                    e = ripristina(testo, stato.tabella, attesi=stato.inviati)
                    return self._json(200, {"testo": e.testo, "mancanti": e.mancanti, "inventati": e.inventati})
                if self.path == "/api/nuova":
                    stato.nuova_pratica()
                    return self._json(200, {"ok": True})
                if self.path == "/api/chiudi":
                    self._json(200, {"ok": True})
                    threading.Thread(target=ferma, daemon=True).start()
                    return None
            self._json(404, {"errore": "non trovato"})

    return Gestore


def avvia(sp: Segnaposto | None = None, apri_browser: bool = True, porta: int = 0) -> None:
    print("segnaposto: carico il modello italiano...", flush=True)
    sp = sp or Segnaposto()
    sp.pseudonimizza("Avvio, Mario Rossi.")
    stato, chiave, porta_ref = Stato(sp), secrets.token_urlsafe(24), [0]
    httpd: ThreadingHTTPServer | None = None

    def ferma() -> None:
        time.sleep(0.3)
        httpd.shutdown()

    httpd = ThreadingHTTPServer(("127.0.0.1", porta), crea_gestore(stato, chiave, porta_ref, ferma))
    porta_ref[0] = httpd.server_address[1]
    url = f"http://127.0.0.1:{porta_ref[0]}/?t={chiave}"

    def sorveglia() -> None:
        while True:
            time.sleep(30)
            if time.time() - stato.ultimo_uso > INATTIVITA_MAX:
                httpd.shutdown()
                return

    threading.Thread(target=sorveglia, daemon=True).start()
    print(f"segnaposto è aperto nel browser: {url}\nPer chiuderlo usa il pulsante «Chiudi» nella pagina (o Ctrl+C qui).", flush=True)
    if apri_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    print("segnaposto chiuso. La tabella della pratica è stata cancellata.", flush=True)


def main() -> None:
    """Punto d'ingresso dell'app impacchettata (doppio clic su Mac e Windows)."""
    import os
    avvia(apri_browser=not os.environ.get("SEGNAPOSTO_NO_BROWSER"))


if __name__ == "__main__":
    main()
