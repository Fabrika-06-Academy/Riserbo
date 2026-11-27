import re
import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from riserbo.app import Stato, crea_gestore
from riserbo.motore import Segnaposto


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
    import riserbo.app as modulo
    monkeypatch.setattr(modulo, "controlla_aggiornamento", lambda: {"nuova": True, "versione": "9.9.9", "url": "https://github.com/Fabrika-06-Academy/x"})
    assert post(app, "/api/aggiornamento", {})["versione"] == "9.9.9"
    with pytest.raises(urllib.error.HTTPError) as e:
        post(app, "/api/apri", {"url": "https://sito-qualsiasi.example/"})
    assert e.value.code == 422
    assert modulo._versione("v0.10.0") > modulo._versione("0.9.12")


def test_scorciatoie_sugli_appunti(app, monkeypatch):
    import riserbo.scorciatoie as sc
    appunti = {"t": "Scrivo a Giulia Ferro di Costruzioni Dalla Pozza, tel. 347 123 4567."}
    monkeypatch.setattr(sc, "leggi_appunti", lambda: appunti["t"])
    monkeypatch.setattr(sc, "scrivi_appunti", lambda t: appunti.__setitem__("t", t))
    post(app, "/api/nuova", {})
    m = post(app, "/api/appunti", {"azione": "proteggi"})["messaggio"]
    assert "sostituiti" in m and "Ferro" not in appunti["t"] and "[PERSONA_1]" in appunti["t"]
    assert post(app, "/api/tabella", {})["tabella"]["[PERSONA_1]"] == "Giulia Ferro"
    appunti["t"] = "Cara [PERSONA_1], confermiamo. Saluti a [PERSONA_7]."
    m = post(app, "/api/appunti", {"azione": "ripristina"})["messaggio"]
    assert appunti["t"].startswith("Cara Giulia Ferro,") and "[PERSONA_7]" in m
    appunti["t"] = ""
    assert "vuoti" in post(app, "/api/appunti", {"azione": "proteggi"})["messaggio"]


def test_seconda_istanza_sveglia_la_prima(monkeypatch, tmp_path):
    """Il secondo avvio (doppio clic, avvio all'accensione) chiede alla prima di mostrare la finestra e si ferma."""
    from riserbo import vassoio
    monkeypatch.setattr(vassoio, "_file_istanza", lambda: tmp_path / "istanza.json")
    assert vassoio.risveglia_istanza() is False  # nessuna istanza aperta
    stato, porta, mostrata = Stato(Segnaposto()), [0], threading.Event()
    stato.mostra_finestra = mostrata.set
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), crea_gestore(stato, "chiave-istanza", porta, lambda: None))
    porta[0] = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        vassoio.segna_istanza(porta[0], "chiave-istanza")
        assert vassoio.risveglia_istanza() is True and mostrata.wait(2)
        vassoio.togli_istanza("un'altra chiave")  # non tocca il file di un'altra istanza
        assert (tmp_path / "istanza.json").exists()
        vassoio.togli_istanza("chiave-istanza")
        assert not (tmp_path / "istanza.json").exists()
    finally:
        httpd.shutdown()
    assert vassoio.risveglia_istanza() is False


def test_cancello_dall_app(app, monkeypatch, tmp_path):
    import socket

    from riserbo import app as modulo
    monkeypatch.setattr(modulo, "_file_impostazioni", lambda: tmp_path / "impostazioni.json")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        libera = s.getsockname()[1]
    d = post(app, "/api/cancello", {"azione": "accendi", "porta": libera})
    assert d["attivo"] and d["indirizzi"]["openai"] == f"http://127.0.0.1:{libera}/openai/v1"
    assert json.loads(urllib.request.urlopen(f"http://127.0.0.1:{libera}/salute").read())["ok"]
    assert json.loads((tmp_path / "impostazioni.json").read_text()) == {"cancello": True, "porta_cancello": libera}
    d = post(app, "/api/cancello", {"azione": "spegni"})
    assert not d["attivo"] and json.loads((tmp_path / "impostazioni.json").read_text())["cancello"] is False
    with pytest.raises(urllib.error.HTTPError):
        post(app, "/api/cancello", {"azione": "accendi", "porta": 80})


def test_collega_claude_desktop_dall_app(app, monkeypatch, tmp_path):
    from riserbo import app as modulo, server_mcp
    conf = tmp_path / "Claude" / "claude_desktop_config.json"
    monkeypatch.setattr(server_mcp, "file_config_claude", lambda: [conf])
    monkeypatch.setattr(modulo, "_file_impostazioni", lambda: tmp_path / "impostazioni.json")
    d = post(app, "/api/mcp", {"azione": "stato"})
    assert d["collegato"] is False and isinstance(d["proposte"], list)
    with pytest.raises(urllib.error.HTTPError):
        post(app, "/api/mcp", {"azione": "collega", "cartelle": [str(tmp_path / "non-esiste")]})
    d = post(app, "/api/mcp", {"azione": "collega", "cartelle": [str(tmp_path)]})
    assert d["collegato"] and d["cartelle"] == [str(tmp_path)]
    assert json.loads(conf.read_text())["mcpServers"]["riserbo"]["args"][-1] == str(tmp_path)
    assert not post(app, "/api/mcp", {"azione": "scollega"})["collegato"]
