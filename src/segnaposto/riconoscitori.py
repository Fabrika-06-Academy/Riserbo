"""Riconoscitori Presidio per i dati che una PMI italiana tratta ogni giorno.

Codice fiscale e partita IVA usano i riconoscitori già presenti in Presidio; qui si aggiungono IBAN italiani,
targhe, l'anagrafica clienti/fornitori esportata dal gestionale e i codici aziendali (commesse, ordini, clienti).
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Iterable

from presidio_analyzer import EntityRecognizer, Pattern, PatternRecognizer, RecognizerResult

from .validatori import iban_valido, targa_valida


class IbanItRecognizer(PatternRecognizer):
    """IBAN con o senza spazi, validato con il controllo mod 97."""

    def __init__(self) -> None:
        super().__init__(
            supported_entity="IBAN",
            supported_language="it",
            patterns=[Pattern("iban", r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]){11,30}\b", 0.5)],
            context=["iban", "conto", "bonifico", "coordinate", "bancarie", "c/c"],
        )

    def validate_result(self, pattern_text: str) -> bool:
        return iban_valido(pattern_text)


class TargaItRecognizer(PatternRecognizer):
    """Targhe italiane (AA 000 AA). Punteggio basso: senza contesto può essere un codice qualsiasi."""

    def __init__(self) -> None:
        super().__init__(
            supported_entity="TARGA",
            supported_language="it",
            patterns=[Pattern("targa", r"\b[A-HJ-NPR-TV-Z]{2}\s?-?\d{3}\s?-?[A-HJ-NPR-TV-Z]{2}\b", 0.3)],
            context=["targa", "targato", "targata", "veicolo", "automezzo", "furgone", "camion", "mezzo"],
        )

    def validate_result(self, pattern_text: str) -> bool:
        return targa_valida(pattern_text)


def riconoscitore_anagrafica(nomi: Iterable[str], entita: str = "CLIENTE") -> PatternRecognizer:
    """Riconosce i nomi di un elenco (clienti, fornitori, dipendenti), senza distinguere maiuscole.

    È lo strato più affidabile per i nomi delle aziende con cui lavori: li conosci già, sono nel gestionale.
    """
    voci = sorted({n.strip() for n in nomi if n and len(n.strip()) >= 3}, key=len, reverse=True)
    if not voci:
        raise ValueError("L'anagrafica è vuota")
    pattern = r"(?i)\b(?:" + "|".join(re.escape(v) for v in voci) + r")\b"
    return PatternRecognizer(supported_entity=entita, supported_language="it", patterns=[Pattern(entita.lower(), pattern, 0.85)])


def carica_anagrafica(percorso: str | Path, colonna: str | None = None, entita: str = "CLIENTE") -> PatternRecognizer:
    """Legge un CSV esportato dal gestionale (separatore ; o ,). Senza `colonna` usa la prima."""
    testo = Path(percorso).read_text(encoding="utf-8-sig")
    dialetto = csv.Sniffer().sniff(testo.splitlines()[0], delimiters=";,\t")
    righe = list(csv.DictReader(testo.splitlines(), dialect=dialetto))
    if not righe:
        raise ValueError(f"Nessuna riga in {percorso}")
    col = colonna or next(iter(righe[0]))
    return riconoscitore_anagrafica((r.get(col, "") for r in righe), entita)


def riconoscitore_codice(entita: str, regex: str, contesto: Iterable[str] = ()) -> PatternRecognizer:
    """Un codice aziendale con forma fissa: commessa, ordine, codice cliente. Es. ("COMMESSA", r"\\bC-\\d{4}-\\d{3}\\b")."""
    return PatternRecognizer(
        supported_entity=entita.upper(),
        supported_language="it",
        patterns=[Pattern(entita.lower(), regex, 0.8)],
        context=list(contesto),
    )


class TitoloPersonaRecognizer(EntityRecognizer):
    """Il nome che segue un titolo (Sig.ra Pellizzari, Ing. Marco Dal Santo): il modello piccolo spesso lo perde."""

    TITOLI = r"(?:Sig\.(?:ra|na)?|Sigg\.|Signor(?:a|ina)?|Dott\.(?:ssa)?|Dr\.|Ing\.|Geom\.|Avv\.|Rag\.|Arch\.|Prof\.(?:ssa)?|Per\.\s?Ind\.)"
    NOME = r"((?:[A-ZÀ-Ý][a-zà-ÿ'’]+|(?:De|Del|Della|Dal|Dalla|Di|Da|Lo|La)\s(?=[A-Z]))(?:\s(?:[A-ZÀ-Ý][a-zà-ÿ'’]+|De|Del|Della|Dal|Dalla|Di|Da))*)"

    def __init__(self) -> None:
        super().__init__(supported_entities=["PERSON"], supported_language="it", name="TitoloPersonaRecognizer")
        self._re = re.compile(self.TITOLI + r"\s*" + self.NOME)

    def load(self) -> None:  # niente da caricare
        pass

    def analyze(self, text, entities, nlp_artifacts=None):
        return [RecognizerResult("PERSON", m.start(1), m.end(1), 0.9) for m in self._re.finditer(text)]


class FormaGiuridicaRecognizer(PatternRecognizer):
    """Ragioni sociali con forma giuridica (Bianchi Srl, F.lli Rossi S.p.A., Coop. Agricola Sas): segnale fortissimo."""

    FORMA = r"(?:S\.?r\.?l\.?s?|S\.?p\.?A\.?|S\.?n\.?c\.?|S\.?a\.?s\.?|S\.?s\.?|Soc\.?\s?[Cc]oop\.?(?:\s?a\s?r\.?l\.?)?|[Ss]\.?c\.?a\.?r\.?l\.?)(?![\w])"
    NOME = r"(?:(?:F\.lli|Fratelli|Officine|Officina|Industrie|Costruzioni)\s)?[A-ZÀ-Ý0-9][\w&'’.-]*(?:\s(?:&\s)?[A-ZÀ-Ý0-9][\w&'’.-]*){0,3}"

    def __init__(self) -> None:
        super().__init__(
            supported_entity="ORGANIZATION",
            supported_language="it",
            patterns=[Pattern("forma_giuridica", r"\b" + self.NOME + r"\s" + self.FORMA, 0.75)],
            global_regex_flags=re.DOTALL | re.MULTILINE,  # niente IGNORECASE: le maiuscole distinguono i nomi
        )


class IndirizzoRecognizer(PatternRecognizer):
    """Indirizzi italiani: «Via G. Garibaldi 12», «p.zza dei Mille, 3/b», «Corso XX Settembre 45, 36100 Vicenza (VI)».

    Serve il numero civico: senza, «via Roma» è troppo spesso un modo di dire o un luogo generico.
    """

    TIPO = r"(?i:via|viale|v\.le|piazza|p\.zza|piazzale|corso|c\.so|largo|vicolo|strada|contrada|c\.da|localit[àa]|loc\.|borgo|riviera|lungomare|galleria|traversa)"
    PAROLA = r"(?:[A-ZÀ-Ý0-9][\w'’.]*|(?:di|del|dello|della|dei|degli|delle|d'|de|da|e|san|santa|s\.)(?=\s?[A-ZÀ-Ý]))"
    CIVICO = r"\d{1,4}\s?(?:[a-zA-Z]\b|/\s?[a-zA-Z0-9]{1,3}|bis\b)?"
    CITTA = r"(?:\s*[,-]?\s*\d{5}\s+[A-ZÀ-Ý][\w'’]*(?:\s+(?:[A-ZÀ-Ý][\w'’]*|di|del|sul|in))*(?:\s*\(\s?[A-Z]{2}\s?\))?)?"

    def __init__(self) -> None:
        regex = r"\b" + self.TIPO + r"\s+" + self.PAROLA + r"(?:\s+" + self.PAROLA + r"){0,5}?\s*,?\s*(?:n\.?\s?)?" + self.CIVICO + self.CITTA
        super().__init__(
            supported_entity="INDIRIZZO",
            supported_language="it",
            patterns=[Pattern("indirizzo", regex, 0.6)],
            global_regex_flags=re.MULTILINE,
        )
