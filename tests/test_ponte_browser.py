"""Il canale per l'estensione del browser: codice di collegamento, niente pagine web, stessa pratica dell'app."""

import json
import urllib.error
import urllib.request

import pytest

from riserbo.app import Stato
from riserbo.ponte_browser import avvia_ponte


@pytest.fixture(scope="module")
def ponte(sp):
    st = Stato(sp)
    h = avvia_ponte(st, "codice-giusto", 0)
    yield st, f"http://127.0.0.1:{h.server_address[1]}"
    h.shutdown()


def post(base, percorso, dati=None, codice="codice-giusto", **intest):
    req = urllib.request.Request(base + percorso, data=json.dumps(dati or {}).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-Segnaposto-Token": codice, **intest})
    return json.loads(urllib.request.urlopen(req, timeout=20).read())


def test_proteggi_e_valori(ponte):
    st, base = ponte
    d = post(base, "/proteggi", {"testo": "Scrivi a Mario Rossi, tel. 347 123 4567."}, Origin="chrome-extension://abc")
    assert "Mario Rossi" not in d["testo"] and d["trovati"] == 2 and d["tipi"]["PERSONA"] == 1
    s = next(x for x in st.tabella.valori if st.tabella.valori[x] == "Mario Rossi")  # stessa pratica della finestra
    v = post(base, "/valori", {"segnaposto": [s, "[PERSONA_99]", "non un segnaposto"]})
    assert v["valori"] == {s: "Mario Rossi"}
    assert post(base, "/stato")["segnaposto"] == len(st.tabella.valori)
    post(base, "/nuova")
    assert st.tabella.valori == {}


@pytest.mark.parametrize("codice, intest, atteso", [
    ("sbagliato", {}, 401),
    ("codice-giusto", {"Origin": "https://sito-qualunque.example"}, 403),
])
def test_rifiuti(ponte, codice, intest, atteso):
    _, base = ponte
    with pytest.raises(urllib.error.HTTPError) as e:
        post(base, "/valori", {"segnaposto": ["[PERSONA_1]"]}, codice=codice, **intest)
    assert e.value.code == atteso


def test_dall_app(monkeypatch, tmp_path):
    from riserbo import app as modulo, ponte_browser
    monkeypatch.setattr(modulo, "_file_impostazioni", lambda: tmp_path / "impostazioni.json")
    monkeypatch.setattr(ponte_browser, "PORTA_PREDEFINITA", 0)
    st = Stato(None)
    modulo.accendi_ponte(st)
    d = modulo.stato_ponte(st)
    assert d["attivo"] and len(d["codice"]) > 16
    vecchio = d["codice"]
    modulo.accendi_ponte(st)  # al riavvio il codice resta quello
    assert modulo.stato_ponte(st)["codice"] == vecchio
    modulo.accendi_ponte(st, rigenera=True)
    assert modulo.stato_ponte(st)["codice"] != vecchio
    modulo.spegni_ponte(st)
    assert not modulo.stato_ponte(st)["attivo"]
