import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

from segnaposto.motore import Segnaposto
from segnaposto.servizio import crea_gestore


def test_servizio_pseudonimizza():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), crea_gestore(Segnaposto(), max_caratteri=500))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        req = urllib.request.Request(base + "/pseudonimizza", data=json.dumps({"testo": "Scrive Mario Rossi, IBAN IT60X0542811101000000123456"}).encode(), method="POST")
        d = json.loads(urllib.request.urlopen(req).read())
        assert "Mario Rossi" not in d["testo"] and "[IBAN_1]" in d["testo"]
        assert d["segnaposto"]["[IBAN_1]"] == "IT60X0542811101000000123456"
        try:
            urllib.request.urlopen(urllib.request.Request(base + "/pseudonimizza", data=json.dumps({"testo": "x" * 600}).encode(), method="POST"))
            assert False, "doveva rifiutare"
        except urllib.error.HTTPError as e:
            assert e.code == 413
    finally:
        httpd.shutdown()
