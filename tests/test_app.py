import re
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


def test_stato_pronto(app):
    assert post(app, "/api/stato", {})["pronto"] is True


def test_documento_correzioni_ed_esportazione(app):
    import base64
    post(app, "/api/nuova", {})
    csv = "Referente;Note\nGino Pilotto;cliente storico di Schio\n".encode()
    d = post(app, "/api/leggi", {"nome": "contatti.csv", "dati": base64.b64encode(csv).decode()})
    assert d["tabellare"] and any("Referente" in c for c in d["colonne"])
    r = post(app, "/api/pseudonimizza", {"testo": d["testo"] + "\nRichiamare Gino Pilotto. Magazzino Ovest."})
    assert "Pilotto" not in r["testo"] and r["conta"]["PERSONA"] == 2
    post(app, "/api/correggi", {"azione": "nascondi", "valore": "Magazzino Ovest", "tipo": "dato"})
    post(app, "/api/correggi", {"azione": "mostra", "valore": "Schio"})
    r = post(app, "/api/pseudonimizza", {"testo": d["testo"] + "\nRichiamare Gino Pilotto. Magazzino Ovest."})
    assert "Magazzino Ovest" not in r["testo"] and "Schio" in r["testo"]
    r2 = post(app, "/api/pseudonimizza", {"testo": "Consegna al deposito Sud."})
    post(app, "/api/correggi", {"azione": "nascondi", "valore": "deposito Sud", "tipo": "dato"})
    r2 = post(app, "/api/pseudonimizza", {"testo": "Consegna al deposito Sud."})
    # Nascosto, con un segnaposto suo: [DATO_n], o quello che aveva già se il modello l'aveva riconosciuto.
    assert re.fullmatch(r"Consegna al \[[A-Z_]+_\d+\]\.", r2["testo"])
    e = post(app, "/api/esporta", {"testo": r["testo"], "formato": "xlsx", "nome": "contatti.csv", "suffisso": "pseudonimizzato"})
    assert e["nome"] == "contatti-pseudonimizzato.xlsx" and base64.b64decode(e["dati"])[:2] == b"PK"


def test_formato_non_leggibile_spiega(app):
    import base64
    with pytest.raises(urllib.error.HTTPError) as e:
        post(app, "/api/leggi", {"nome": "vecchio.doc", "dati": base64.b64encode(b"x").decode()})
    assert e.value.code == 422 and "docx" in json.loads(e.value.read())["errore"]


def test_pdf_oscurato_dall_app(app):
    import base64
    import sys
    sys.path.insert(0, __import__("os").path.dirname(__file__))
    from test_documenti import _pdf
    post(app, "/api/nuova", {})
    with pytest.raises(urllib.error.HTTPError) as e:
        post(app, "/api/oscura", {})
    assert e.value.code == 422
    d = post(app, "/api/leggi", {"nome": "c.pdf", "dati": base64.b64encode(_pdf(["Contratto con Mario Rossi,", "CF RSSMRA80A01L840J."])).decode()})
    assert d["oscurabile"]
    post(app, "/api/pseudonimizza", {"testo": "Altro testo: Giovanna Brun."})  # un'altra persona nella pratica
    post(app, "/api/pseudonimizza", {"testo": d["testo"]})
    o = post(app, "/api/oscura", {})
    assert o["nome"] == "c-oscurato.pdf" and o["coperti"] >= 2
    assert o["non_trovati"] == []  # Giovanna Brun è nella pratica ma non nel PDF: non va cercata lì


def test_sempre_in_chiaro(app):
    post(app, "/api/nuova", {})
    r = post(app, "/api/pseudonimizza", {"testo": "Ho parlato con Giulia Ferro di Fabrika 06 e di PayPal.", "in_chiaro": ["Fabrika 06"]})
    assert "Fabrika 06" in r["testo"] and "PayPal" in r["testo"] and "Ferro" not in r["testo"]


def test_aggiornamento_e_link(app, monkeypatch):
    import segnaposto.app as modulo
    monkeypatch.setattr(modulo, "controlla_aggiornamento", lambda: {"nuova": True, "versione": "9.9.9", "url": "https://github.com/Fabrika-06-Academy/x"})
    assert post(app, "/api/aggiornamento", {})["versione"] == "9.9.9"
    with pytest.raises(urllib.error.HTTPError) as e:
        post(app, "/api/apri", {"url": "https://sito-qualsiasi.example/"})
    assert e.value.code == 422
    assert modulo._versione("v0.10.0") > modulo._versione("0.9.12")
