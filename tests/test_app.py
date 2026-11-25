import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from segnaposto.app import Stato, crea_gestore
from segnaposto.motore import Segnaposto


@pytest.fixture(scope="module")
def app():
    porta = [0]
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), crea_gestore(Stato(Segnaposto()), "chiave-di-prova", porta, lambda: None))
    porta[0] = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{porta[0]}"
    httpd.shutdown()


def post(base, path, dati, chiave="chiave-di-prova"):
    req = urllib.request.Request(base + path, data=json.dumps(dati).encode(), method="POST", headers={"X-Chiave": chiave})
    return json.loads(urllib.request.urlopen(req).read())


def test_senza_chiave_rifiuta(app):
    with pytest.raises(urllib.error.HTTPError) as e:
        post(app, "/api/pseudonimizza", {"testo": "Mario Rossi"}, chiave="sbagliata")
    assert e.value.code == 403
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(app + "/")
    assert e.value.code == 403


def test_pagina_con_chiave(app):
    html = urllib.request.urlopen(app + "/?t=chiave-di-prova").read().decode()
    assert "segna" in html and "chiave-di-prova" in html


def test_andata_e_ritorno(app):
    post(app, "/api/nuova", {})
    d = post(app, "/api/pseudonimizza", {"testo": "Scrive Mario Rossi della Bianchi Srl, tel. 347 123 4567."})
    assert "Mario Rossi" not in d["testo"]
    risposta = "Gentile [PERSONA_1], confermiamo a [AZIENDA_1] l'offerta. Saluti a [PERSONA_9]."
    r = post(app, "/api/ripristina", {"testo": risposta})
    assert "Mario Rossi" in r["testo"] and "Bianchi Srl" in r["testo"]
    assert r["inventati"] == ["[PERSONA_9]"] and r["mancanti"] == ["[TELEFONO_1]"]
