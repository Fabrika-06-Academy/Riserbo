import os
from pathlib import Path

import pytest

from segnaposto import Tabella
from segnaposto.motore import Segnaposto, ripristina
from segnaposto.riconoscitori import carica_anagrafica, riconoscitore_codice

ESEMPI = Path(__file__).parent.parent / "esempi"


@pytest.fixture(scope="module")
def sp():
    return Segnaposto(riconoscitori=[carica_anagrafica(ESEMPI / "anagrafica.csv", entita="CLIENTE"),
                                     riconoscitore_codice("COMMESSA", r"\bC-\d{4}-\d{3}\b", ["commessa"])])


def test_dati_a_forma_fissa(sp):
    r = sp.pseudonimizza("CF RSSMRA80A01L840J, P.IVA 01234567897, IBAN IT60 X054 2811 1010 0000 0123 456, mail a.b@esempio.it")
    for v in ("RSSMRA80A01L840J", "01234567897", "IT60", "a.b@esempio.it"):
        assert v not in r.testo
    assert "[CODICE_FISCALE_1]" in r.testo and "[IBAN_1]" in r.testo


def test_anagrafica_e_codici(sp):
    r = sp.pseudonimizza("Per la commessa C-2026-014 di Ferrari Componenti serve il collaudo.")
    assert "Ferrari Componenti" not in r.testo and "C-2026-014" not in r.testo
    assert "[CLIENTE_1]" in r.testo and "[COMMESSA_1]" in r.testo


def test_stesso_valore_stesso_segnaposto(sp):
    r = sp.pseudonimizza("Bianchi Srl ha scritto. Rispondiamo a Bianchi Srl entro domani.")
    assert r.testo.count("[CLIENTE_1]") == 2


def test_andata_e_ritorno(sp):
    t = Tabella()
    r = sp.pseudonimizza("Mario Rossi chiede il prezzo per Bianchi Srl.", t)
    risposta = r.testo.replace("chiede il prezzo", "riceve l'offerta")
    esito = ripristina(risposta, t, attesi=set(t.valori))
    assert "Mario Rossi" in esito.testo and "Bianchi Srl" in esito.testo
    assert esito.mancanti == [] and esito.inventati == []


def test_ritorno_con_segnaposto_inventato():
    t = Tabella()
    t.segnaposto("PERSONA", "Mario Rossi")
    esito = ripristina("Caro [PERSONA_1], saluti a [PERSONA_2].", t, attesi={"[PERSONA_1]"})
    assert esito.inventati == ["[PERSONA_2]"]


def test_tabella_salvata_con_permessi_stretti(tmp_path):
    t = Tabella()
    t.segnaposto("PERSONA", "Paola")
    p = tmp_path / "x.tabella.json"
    t.salva(p)
    if os.name != "nt":  # su Windows i permessi Unix non esistono
        assert oct(p.stat().st_mode)[-3:] == "600"
    assert Tabella.carica(p).valori == {"[PERSONA_1]": "Paola"}


def test_titoli_e_saluti(sp):
    r = sp.pseudonimizza("Buongiorno, gentile Sig.ra Pellizzari, l'Ing. Marco Dal Santo la richiamerà.")
    assert r.testo.startswith("Buongiorno")
    assert "Pellizzari" not in r.testo and "Dal Santo" not in r.testo


def test_forma_giuridica():
    sp = Segnaposto()
    r = sp.pseudonimizza("La Sig.ra Pellizzari di Bianchi Srl e i F.lli Dal Molin S.p.A. hanno scritto.")
    for v in ("Bianchi Srl", "Dal Molin S.p.A.", "Pellizzari"):
        assert v not in r.testo, r.testo


def test_cortesie_e_titoli_restano(sp):
    r = sp.pseudonimizza("Spett.le Bianchi Srl\nGentile Ing. Marco Dal Santo,\nCordiali saluti, Paolo Zanella")
    assert r.testo.startswith("Spett.le [") and "Gentile Ing. [PERSONA_" in r.testo and "Cordiali saluti, [PERSONA_" in r.testo
