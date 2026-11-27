"""Pausa: estensione e modalità automatica si fermano per un po' e si riattivano da sole. Il cancello no."""

import json
import time
import urllib.request

from riserbo.app import Stato, in_pausa, metti_in_pausa, proteggi_testo, riprendi, rimetti_testo, stato_pausa
from riserbo.automatica import Guardiano
from riserbo.ponte_browser import avvia_ponte


def test_durata_e_riattivazione(sp):
    st = Stato(sp)
    st.avvisa = lambda *a: None
    assert not in_pausa(st)
    metti_in_pausa(st, 15)
    p = stato_pausa(st)
    assert p["attiva"] and p["testo"].startswith("in pausa fino alle ")
    st.pausa_fino = time.time() - 1  # il tempo è scaduto
    assert not in_pausa(st) and st.pausa_fino is None  # si riattiva da sola
    metti_in_pausa(st, None)
    assert stato_pausa(st)["testo"] == "in pausa finché non la riattivi"
    riprendi(st)
    assert not in_pausa(st)


def test_la_modalita_automatica_non_tocca_gli_appunti(sp):
    st = Stato(sp)
    st.avvisa = lambda *a: None
    appunti, app = ["Scrivi a Laura Ferretti."], [None]
    g = Guardiano(lambda t: proteggi_testo(st, t), lambda t: rimetti_testo(st, t), lambda *a: None,
                  app_attiva=lambda: app[0], leggi=lambda: appunti[0], scrivi=lambda t: appunti.__setitem__(0, t),
                  contatore=lambda: 0, in_pausa=lambda: in_pausa(st))
    metti_in_pausa(st, 60)
    app[0] = "ChatGPT"; g.passo()
    assert appunti[0] == "Scrivi a Laura Ferretti."
    riprendi(st)
    app[0] = None; g.passo(); app[0] = "ChatGPT"; g.passo()  # riattivata: si protegge di nuovo
    assert "Laura" not in appunti[0]


def test_l_estensione_manda_il_testo_com_e(sp):
    st = Stato(sp)
    st.avvisa = lambda *a: None
    h = avvia_ponte(st, "c", 0)
    base = f"http://127.0.0.1:{h.server_address[1]}"

    def post(percorso, dati):
        req = urllib.request.Request(base + percorso, data=json.dumps(dati).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "X-Riserbo-Token": "c"})
        return json.loads(urllib.request.urlopen(req, timeout=20).read())
    try:
        post("/pausa", {"minuti": 15})
        d = post("/proteggi", {"testo": "Scrivi a Laura Ferretti."})
        assert d["trovati"] == 0 and d["testo"] == "Scrivi a Laura Ferretti." and d["pausa"]["attiva"]
        assert post("/stato", {})["pausa"]["attiva"]
        post("/riprendi", {})
        assert "Laura" not in post("/proteggi", {"testo": "Scrivi a Laura Ferretti."})["testo"]
    finally:
        h.shutdown()
