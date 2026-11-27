"""Modalità automatica: entrando in un'app di AI gli appunti si proteggono, uscendo tornano i nomi veri."""

from riserbo.app import Stato, proteggi_testo, rimetti_testo
from riserbo.automatica import Guardiano, riconosci


class Finto:
    def __init__(self):
        self.app, self.appunti, self.n, self.avvisi = None, "", 0, []

    def scrivi(self, t):
        self.appunti = t
        self.n += 1

    def copia(self, t):  # la persona copia qualcosa
        self.scrivi(t)


def guardiano(sp):
    st, f = Stato(sp), Finto()
    g = Guardiano(lambda t: proteggi_testo(st, t), lambda t: rimetti_testo(st, t), lambda a, b: f.avvisi.append(b),
                  app_attiva=lambda: f.app, leggi=lambda: f.appunti, scrivi=f.scrivi, contatore=lambda: f.n)
    return st, f, g


def test_riconosce_le_app():
    assert riconosci(("com.openai.chat", "ChatGPT")) == "ChatGPT"
    assert riconosci(("Claude.exe",)) == "Claude"
    assert riconosci(("com.apple.mail", "Mail")) is None


def test_andata_e_ritorno(sp):
    st, f, g = guardiano(sp)
    f.copia("Rispondi a Laura Ferretti, IBAN IT60X0542811101000000123456.")
    g.passo()                                   # in Mail: niente
    assert "Laura" in f.appunti
    f.app = "ChatGPT"; g.passo()                # entra in ChatGPT: appunti protetti
    assert "Laura" not in f.appunti and "[IBAN_1]" in f.appunti and f.avvisi
    persona = next(s for s, v in st.tabella.valori.items() if v == "Laura Ferretti")
    f.copia(f"Gentile {persona}, confermo.")    # copia la risposta dentro ChatGPT
    f.app = None; g.passo()                     # torna in Mail: nomi veri
    assert f.appunti == "Gentile Laura Ferretti, confermo."


def test_uscendo_senza_copiare_torna_il_testo_di_prima(sp):
    st, f, g = guardiano(sp)
    f.copia("Il cliente Marco Dal Santo chiede uno sconto.")
    f.app = "Claude"; g.passo()
    assert "Marco" not in f.appunti
    f.app = None; g.passo()
    assert f.appunti == "Il cliente Marco Dal Santo chiede uno sconto."


def test_testo_senza_dati_non_si_tocca(sp):
    st, f, g = guardiano(sp)
    f.copia("Riassumi in tre punti il testo seguente.")
    prima = f.n
    f.app = "ChatGPT"; g.passo()
    assert f.appunti == "Riassumi in tre punti il testo seguente." and f.n == prima and not f.avvisi


def test_riconosce_la_nuova_app_di_chatgpt_per_mac():
    """Sul Mac di Andrea l'app «ChatGPT» ha l'identificativo com.openai.codex (2026-11)."""
    assert riconosci(("com.openai.codex", "ChatGPT")) == "ChatGPT"
    assert riconosci(("com.openai.codex", "")) == "ChatGPT"


def test_testo_copiato_mentre_sei_gia_nell_app(sp):
    """L'ordine dei gesti non conta: anche se copi quando ChatGPT è già davanti, gli appunti si proteggono."""
    st, f, g = guardiano(sp)
    f.app = "ChatGPT"; g.passo()                 # entri con gli appunti vuoti
    g.passo()
    f.copia("Il cliente Andrea Galli chiede il rimborso sull'IBAN IT60X0542811101000000123456.")
    g.passo()
    assert "Andrea Galli" not in f.appunti and "[IBAN_1]" in f.appunti
    assert "dati sostituiti" in g.registro[0]
    f.app = None; g.passo()                      # esci senza copiare altro: torna il testo vero
    assert f.appunti.startswith("Il cliente Andrea Galli")


def test_riconoscitore_non_pronto_lo_dice(sp):
    from riserbo.app import Stato, proteggi_testo, rimetti_testo
    st, f = Stato(None), Finto()  # il riconoscitore non c'è ancora
    g = Guardiano(lambda t: proteggi_testo(st, t), lambda t: rimetti_testo(st, t), lambda a, b: f.avvisi.append(b),
                  app_attiva=lambda: f.app, leggi=lambda: f.appunti, scrivi=f.scrivi, contatore=lambda: f.n)
    f.copia("Scrivi a Laura Ferretti.")
    f.app = "ChatGPT"; g.passo()
    assert f.appunti == "Scrivi a Laura Ferretti." and "NON sono protetti" in f.avvisi[0]
    assert "non era ancora pronto" in g.registro[0]
