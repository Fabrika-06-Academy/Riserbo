"""Pseudonimizzare e ripristinare un testo italiano.

Strato 1: regole con controllo delle cifre (codice fiscale, partita IVA, IBAN, targhe, email, telefoni, codici tuoi)
          e anagrafica dal gestionale.
Strato 2: riconoscitore di entità (spaCy italiano) per persone, aziende e luoghi.
Strato 3 (facoltativo): un controllo finale con un modello in casa, tramite `controllo_finale`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Iterable

from presidio_analyzer import AnalyzerEngine, EntityRecognizer, RecognizerRegistry
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_analyzer.predefined_recognizers import (
    EmailRecognizer,
    ItFiscalCodeRecognizer,
    ItVatCodeRecognizer,
    PhoneRecognizer,
)

from .riconoscitori import IbanItRecognizer, TargaItRecognizer, TitoloPersonaRecognizer
from .tabella import Tabella

# Nome dell'entità Presidio -> nome del segnaposto (in italiano, leggibile da chi rilegge).
NOMI = {
    "PERSON": "PERSONA", "ORGANIZATION": "AZIENDA", "LOCATION": "LUOGO",
    "IT_FISCAL_CODE": "CODICE_FISCALE", "IT_VAT_CODE": "PARTITA_IVA", "IBAN": "IBAN",
    "EMAIL_ADDRESS": "EMAIL", "PHONE_NUMBER": "TELEFONO", "TARGA": "TARGA",
}
# Precedenza quando due riconoscitori trovano lo stesso pezzo: vince il più specifico.
PRIORITA = {"IT_FISCAL_CODE": 9, "IT_VAT_CODE": 9, "IBAN": 9, "EMAIL_ADDRESS": 8, "PHONE_NUMBER": 7, "TARGA": 6,
            "CLIENTE": 8, "FORNITORE": 8, "DIPENDENTE": 8, "PERSON": 3, "ORGANIZATION": 3, "LOCATION": 2}
SEGNAPOSTO = re.compile(r"\[[A-Z_]+_\d+\]")
# Parole che il modello piccolo scambia per nomi o luoghi, soprattutto a inizio frase nelle email.
PAROLE_COMUNI = {
    "buongiorno", "buonasera", "salve", "gentile", "gentili", "egregio", "spettabile", "spett.le", "cordiali", "saluti",
    "distinti", "grazie", "ciao", "allegato", "allegati", "oggetto", "re", "fw", "fwd", "ps", "p.s.", "nb", "cordialmente",
}


@dataclass
class Risultato:
    testo: str
    tabella: Tabella
    trovati: list[dict] = field(default_factory=list)  # tipo, valore, inizio, fine, punteggio


@dataclass
class Ripristino:
    testo: str
    mancanti: list[str]   # segnaposto spariti nel testo di ritorno: il modello ha perso un pezzo
    inventati: list[str]  # segnaposto che non sono nella tabella: il modello ne ha creati di suoi


class Segnaposto:
    """Uso tipico:

    >>> sp = Segnaposto()
    >>> r = sp.pseudonimizza("Mario Rossi, IBAN IT60X0542811101000000123456")
    >>> r.testo
    '[PERSONA_1], IBAN [IBAN_1]'
    """

    def __init__(
        self,
        modello_spacy: str = "it_core_news_sm",
        riconoscitori: Iterable[EntityRecognizer] = (),
        soglia: float = 0.35,
        entita_ner: Iterable[str] = ("PERSON", "ORGANIZATION", "LOCATION"),
        controllo_finale: Callable[[str], list[str]] | None = None,
    ) -> None:
        nlp = NlpEngineProvider(nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "it", "model_name": modello_spacy}],
            "ner_model_configuration": {
                "model_to_presidio_entity_mapping": {"PER": "PERSON", "ORG": "ORGANIZATION", "LOC": "LOCATION"},
                "labels_to_ignore": ["MISC"],
            },
        }).create_engine()
        reg = RecognizerRegistry(supported_languages=["it"])
        reg.load_predefined_recognizers(languages=["it"], nlp_engine=nlp)
        # Teniamo solo quello che serve: meno falsi allarmi su numeri e date.
        for r in list(reg.recognizers):
            if r.name not in ("SpacyRecognizer",):
                reg.remove_recognizer(r.name)
        for r in (ItFiscalCodeRecognizer(), ItVatCodeRecognizer(), EmailRecognizer(supported_language="it"),
                  PhoneRecognizer(supported_language="it", supported_regions=("IT",)), IbanItRecognizer(), TargaItRecognizer(), TitoloPersonaRecognizer(),
                  *riconoscitori):
            reg.add_recognizer(r)
        self.analyzer = AnalyzerEngine(registry=reg, nlp_engine=nlp, supported_languages=["it"])
        self.soglia = soglia
        self.entita_ner = set(entita_ner)
        self.controllo_finale = controllo_finale

    def trova(self, testo: str) -> list[dict]:
        grezzi = self.analyzer.analyze(text=testo, language="it", score_threshold=self.soglia)
        ner = ("PERSON", "ORGANIZATION", "LOCATION")
        grezzi = [g for g in grezzi if g.entity_type not in ner
                  or (g.entity_type in self.entita_ner and testo[g.start:g.end].strip(" ,.:;").casefold() not in PAROLE_COMUNI)]
        # Sovrapposizioni: si ordina per priorità, poi per lunghezza, e si tiene il primo che non tocca gli altri.
        grezzi.sort(key=lambda g: (-PRIORITA.get(g.entity_type, 5), -(g.end - g.start), -g.score))
        scelti: list = []
        for g in grezzi:
            if all(g.end <= s.start or g.start >= s.end for s in scelti):
                scelti.append(g)
        scelti.sort(key=lambda g: g.start)
        trovati = [{"tipo": NOMI.get(g.entity_type, g.entity_type), "valore": testo[g.start:g.end],
                    "inizio": g.start, "fine": g.end, "punteggio": round(g.score, 2)} for g in scelti]
        # Strato 3: il modello in casa segnala cosa è sfuggito (stringhe esatte presenti nel testo).
        if self.controllo_finale:
            occupati = [(t["inizio"], t["fine"]) for t in trovati]
            for valore in self.controllo_finale(testo):
                for m in re.finditer(re.escape(valore), testo):
                    if all(m.end() <= a or m.start() >= b for a, b in occupati):
                        trovati.append({"tipo": "DATO", "valore": valore, "inizio": m.start(), "fine": m.end(), "punteggio": 0.5})
                        occupati.append((m.start(), m.end()))
            trovati.sort(key=lambda t: t["inizio"])
        return trovati

    def pseudonimizza(self, testo: str, tabella: Tabella | None = None) -> Risultato:
        tabella = tabella or Tabella()
        trovati = self.trova(testo)
        parti, pos = [], 0
        for t in trovati:
            parti.append(testo[pos:t["inizio"]])
            parti.append(tabella.segnaposto(t["tipo"], t["valore"]))
            pos = t["fine"]
        parti.append(testo[pos:])
        return Risultato("".join(parti), tabella, trovati)


def ripristina(testo: str, tabella: Tabella, attesi: Iterable[str] | None = None) -> Ripristino:
    """Rimette i valori veri al posto dei segnaposto e controlla che il testo di ritorno non ne abbia persi o inventati.

    `attesi`: i segnaposto che dovrebbero esserci (di solito quelli del testo mandato). Se None, non si controllano i mancanti.
    """
    presenti = set(SEGNAPOSTO.findall(testo))
    inventati = sorted(s for s in presenti if s not in tabella.valori)
    mancanti = sorted(set(attesi) - presenti) if attesi is not None else []
    ripristinato = SEGNAPOSTO.sub(lambda m: tabella.valori.get(m.group(0), m.group(0)), testo)
    return Ripristino(ripristinato, mancanti, inventati)
