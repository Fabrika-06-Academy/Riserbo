"""Pseudonimizzare e ripristinare un testo italiano.

Strato 1: regole con controllo delle cifre (codice fiscale, partita IVA, IBAN, targhe, email, telefoni, codici tuoi)
          e anagrafica dal gestionale.
Strato 2: riconoscitore di entità italiano (BERT, oltre 50 categorie) per persone, aziende, luoghi e altri dati.
Strato 3 (facoltativo): un controllo finale con un modello in casa, tramite `controllo_finale`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Iterable

from presidio_analyzer import AnalyzerEngine, EntityRecognizer, RecognizerRegistry
from presidio_analyzer.nlp_engine import SlimSpacyNlpEngine
from presidio_analyzer.predefined_recognizers import (
    EmailRecognizer,
    ItFiscalCodeRecognizer,
    ItVatCodeRecognizer,
    PhoneRecognizer,
)

from .ner import RiconoscitoreItaliano
from .riconoscitori import (FormaGiuridicaRecognizer, IbanItRecognizer, IndirizzoRecognizer, TargaItRecognizer,
                            SitoRecognizer, TitoloPersonaRecognizer)
from .tabella import Tabella

# Nome dell'entità Presidio -> nome del segnaposto (in italiano, leggibile da chi rilegge).
NOMI = {
    "PERSON": "PERSONA", "ORGANIZATION": "AZIENDA", "LOCATION": "LUOGO",
    "IT_FISCAL_CODE": "CODICE_FISCALE", "IT_VAT_CODE": "PARTITA_IVA", "IBAN": "IBAN",
    "EMAIL_ADDRESS": "EMAIL", "PHONE_NUMBER": "TELEFONO", "TARGA": "TARGA", "INDIRIZZO": "INDIRIZZO",
}  # gli altri tipi (DATA_NASCITA, ETA, SALUTE, DOCUMENTO, CONTO...) hanno già il nome italiano
# Tipi che il riconoscitore trova ma che di solito non si nascondono: servono al modello in cloud per lavorare.
ESCLUSI_PREDEFINITI = frozenset({"PROFESSIONE"})
# Precedenza quando due riconoscitori trovano lo stesso pezzo: vince il più specifico.
PRIORITA = {"IT_FISCAL_CODE": 9, "IT_VAT_CODE": 9, "IBAN": 9, "EMAIL_ADDRESS": 8, "PHONE_NUMBER": 7, "TARGA": 6,
            "CLIENTE": 8, "FORNITORE": 8, "DIPENDENTE": 8, "INDIRIZZO": 7, "SITO": 6, "PERSON": 3, "ORGANIZATION": 4, "LOCATION": 2}
SEGNAPOSTO = re.compile(r"\[[A-Z_]+_\d+\]")
# Parole che il modello piccolo scambia per nomi o luoghi, soprattutto a inizio frase nelle email.
PAROLE_COMUNI = {
    "buongiorno", "buonasera", "salve", "gentile", "gentili", "egregio", "spettabile", "spett.le", "cordiali", "saluti",
    "distinti", "grazie", "ciao", "allegato", "allegati", "oggetto", "re", "fw", "fwd", "ps", "p.s.", "nb", "cordialmente",
}
# Marchi e servizi che compaiono in ogni documento di lavoro e non identificano nessuno: il modello li prende spesso
# per aziende. Restano in chiaro se trovati dal riconoscitore (non se li nascondi tu a mano o da una colonna).
MARCHI_NOTI = {
    "paypal", "amazon", "google", "microsoft", "apple", "meta", "facebook", "instagram", "linkedin", "whatsapp", "telegram",
    "youtube", "tiktok", "x", "twitter", "yandex", "bing", "chatgpt", "openai", "claude", "anthropic", "gemini", "copilot",
    "mistral", "perplexity", "excel", "word", "powerpoint", "outlook", "teams", "zoom", "skype", "gmail", "office", "windows",
    "macos", "iphone", "android", "wordpress", "woocommerce", "elementor", "shopify", "wix", "joomla", "drupal", "magento",
    "aruba", "register", "godaddy", "cloudflare", "hostinger", "siteground", "dropbox", "onedrive", "icloud", "salesforce",
    "hubspot", "mailchimp", "brevo", "stripe", "satispay", "nexi", "visa", "mastercard", "american express", "n8n", "make",
    "zapier", "notion", "slack", "trello", "asana", "canva", "adobe", "photoshop", "acrobat", "sap", "oracle", "ibm",
    "github", "gitlab", "docker", "linux", "ubuntu", "android", "chrome", "firefox", "safari", "edge", "buddyboss",
    "learndash", "rank math", "yoast", "fatture in cloud", "danea", "teamsystem", "zucchetti", "agenzia delle entrate",
    "inps", "inail", "pec", "spid", "cie", "sdi", "pagopa", "poste italiane", "unicredit", "intesa sanpaolo",
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


class _MotoreLeggero(SlimSpacyNlpEngine):
    """Solo divisione in parole (spaCy senza modello addestrato): le entità le trova il riconoscitore italiano.

    Il «lemma» è la parola in minuscolo: basta per le parole di contesto dei riconoscitori («iban», «targa», «conto»).
    """

    def __init__(self) -> None:
        super().__init__(models=[{"lang_code": "it", "model_name": "blank"}], auto_download=False)

    def load(self) -> None:
        import spacy
        self.nlp = {"it": spacy.blank("it")}

    def _doc_to_nlp_artifact(self, doc, language):
        art = super()._doc_to_nlp_artifact(doc, language)
        art.lemmas = [t.lower_ for t in doc]
        return art


class Segnaposto:
    """Uso tipico:

    >>> sp = Segnaposto()
    >>> r = sp.pseudonimizza("Mario Rossi, IBAN IT60X0542811101000000123456")
    >>> r.testo
    '[PERSONA_1], IBAN [IBAN_1]'
    """

    def __init__(
        self,
        riconoscitori: Iterable[EntityRecognizer] = (),
        riconoscitore_entita: EntityRecognizer | None = None,
        soglia: float = 0.35,
        entita_ner: Iterable[str] = ("PERSON", "ORGANIZATION", "LOCATION"),
        controllo_finale: Callable[[str], list[str]] | None = None,
    ) -> None:
        nlp = _MotoreLeggero()
        reg = RecognizerRegistry(supported_languages=["it"])
        for r in (ItFiscalCodeRecognizer(), ItVatCodeRecognizer(), EmailRecognizer(supported_language="it"),
                  PhoneRecognizer(supported_language="it", supported_regions=("IT",)), IbanItRecognizer(), TargaItRecognizer(),
                  TitoloPersonaRecognizer(), FormaGiuridicaRecognizer(), IndirizzoRecognizer(), SitoRecognizer(),
                  riconoscitore_entita or RiconoscitoreItaliano(), *riconoscitori):
            reg.add_recognizer(r)
        self.analyzer = AnalyzerEngine(registry=reg, nlp_engine=nlp, supported_languages=["it"])
        self.soglia = soglia
        self.entita_ner = set(entita_ner)
        self.controllo_finale = controllo_finale

    def trova(self, testo: str, forzati: dict[str, str] | None = None, ignora: Iterable[str] = (),
              escludi: Iterable[str] | None = None) -> list[dict]:
        """Trova i dati da sostituire.

        `forzati`: valore -> tipo, da sostituire sempre (colonne «Nome» di un Excel, correzioni a mano, anagrafica).
        `ignora`: valori che chi rilegge ha indicato come non personali (falsi allarmi).
        `escludi`: tipi di segnaposto da lasciare in chiaro (es. {"LUOGO"} se le città servono al modello);
                   None = ESCLUSI_PREDEFINITI.
        """
        ner = ("PERSON", "ORGANIZATION", "LOCATION")
        no = {_chiave(v) for v in ignora}
        marchi = MARCHI_NOTI | no
        candidati = []  # (tipo, inizio, fine, punteggio, priorità)
        for g in self.analyzer.analyze(text=testo, language="it", score_threshold=self.soglia):
            dal_modello = (g.recognition_metadata or {}).get("recognizer_name") == "RiconoscitoreItaliano"
            if dal_modello:
                g = _rifinisci(testo, g)
                if g is None or (g.entity_type in ner and _chiave(testo[g.start:g.end]) in marchi):
                    continue
            if g.entity_type in ner:
                if g.entity_type not in self.entita_ner:
                    continue
                # Un nome non attraversa una cella o una riga: si spezza sui tab e sugli a capo.
                pezzi = [(g.start + m.start(), g.start + m.end()) for m in re.finditer(r"[^\t\n]+", testo[g.start:g.end])]
            else:
                pezzi = [(g.start, g.end)]
            for a, b in pezzi:
                if g.entity_type in ner:
                    a = _salta_cortesie(testo, a, b)
                while a < b and testo[a] in " ,.:;": a += 1
                while b > a and testo[b - 1] in " ,:;": b -= 1
                if b - a < 2 or (g.entity_type in ner and testo[a:b].casefold().rstrip(".") in PAROLE_COMUNI):
                    continue
                if dal_modello and g.entity_type in FORMA_FISSA:
                    prio = 1
                elif dal_modello and g.entity_type not in PRIORITA:
                    prio = 3  # categorie in più del modello (segreti, documenti...): non scavalcano nomi e aziende
                else:
                    prio = PRIORITA.get(g.entity_type, 5)
                candidati.append((g.entity_type, a, b, g.score, prio))
        for valore, tipo in (forzati or {}).items():
            v = valore.strip()
            if len(v) < 2:
                continue
            for m in re.finditer(r"(?<![\w])" + re.escape(v) + r"(?![\w])", testo, flags=re.IGNORECASE):
                candidati.append((tipo, m.start(), m.end(), 1.0, 10))
        candidati = [c for c in candidati if _chiave(testo[c[1]:c[2]]) not in no]
        scelti = _scegli(candidati)
        # Coerenza: un dato trovato in un punto si nasconde ovunque compaia (intestazioni, piè di pagina, firme).
        # Il modello a volte lo riconosce solo in alcuni punti, e un nome in chiaro altrove vanifica tutto il resto.
        propagati = []
        for tipo, a, b, punteggio, prio in scelti:
            v = testo[a:b]
            if len(v.strip()) < 3 or not re.search(r"[A-Za-zÀ-ÿ]", v) or _chiave(v) in no:
                continue
            for m in re.finditer(r"(?<![\w@.])" + re.escape(v) + r"(?![\w])", testo, flags=re.IGNORECASE):
                if (m.start(), m.end()) != (a, b):
                    propagati.append((tipo, m.start(), m.end(), punteggio, prio))
        propagati += _nomi_dai_domini(testo, scelti)
        if propagati:
            scelti = _scegli(candidati + propagati)
        fuori = ESCLUSI_PREDEFINITI if escludi is None else set(escludi)
        scelti = [c for c in scelti if NOMI.get(c[0], c[0]) not in fuori]
        trovati = [{"tipo": NOMI.get(c[0], c[0]), "valore": testo[c[1]:c[2]],
                    "inizio": c[1], "fine": c[2], "punteggio": round(c[3], 2)} for c in scelti]
        # Strato 3: il modello in casa segnala cosa è sfuggito (stringhe esatte presenti nel testo).
        if self.controllo_finale:
            occupati = [(t["inizio"], t["fine"]) for t in trovati]
            for valore in self.controllo_finale(testo):
                if _chiave(valore) in no:
                    continue
                for m in re.finditer(re.escape(valore), testo):
                    if all(m.end() <= a or m.start() >= b for a, b in occupati):
                        trovati.append({"tipo": "DATO", "valore": valore, "inizio": m.start(), "fine": m.end(), "punteggio": 0.5})
                        occupati.append((m.start(), m.end()))
            trovati.sort(key=lambda t: t["inizio"])
        return trovati

    def pseudonimizza(self, testo: str, tabella: Tabella | None = None, forzati: dict[str, str] | None = None,
                      ignora: Iterable[str] = (), escludi: Iterable[str] | None = None) -> Risultato:
        tabella = tabella or Tabella()
        trovati = self.trova(testo, forzati, ignora, escludi)
        parti, pos = [], 0
        for t in trovati:
            parti.append(testo[pos:t["inizio"]])
            parti.append(tabella.segnaposto(t["tipo"], t["valore"]))
            pos = t["fine"]
        parti.append(testo[pos:])
        return Risultato("".join(parti), tabella, trovati)


# Parole all'inizio di un nome che non fanno parte del nome: «Gentile Ing. Marco Dal Santo», «Spett.le Bianchi Srl».
TITOLI = {"sig", "sig.ra", "sig.na", "sigg", "signor", "signora", "signorina", "dott", "dott.ssa", "dr", "ing", "geom", "avv",
          "rag", "arch", "prof", "prof.ssa", "spett", "spett.le", "spettabile", "egr", "egr.", "gent", "gent.mo", "gent.ma",
          "on", "mons", "per", "ind"}


# Dati a forma fissa: le regole con il controllo delle cifre sono più affidabili del modello, che vince solo dove
# le regole non trovano nulla (per esempio un codice fiscale letto male dall'OCR).
FORMA_FISSA = {"IBAN", "IT_FISCAL_CODE", "IT_VAT_CODE", "PHONE_NUMBER", "EMAIL_ADDRESS", "TARGA"}
_ETICHETTA = re.compile(r"^(?:iban|c\.?\s?f\.?|cod(?:ice|\.)?\s?fiscale|p\.?\s?iva|partita\s+iva|tel(?:efono)?\.?|"
                        r"cell(?:ulare)?\.?|e-?mail|pec|targa(?:ta|to)?)\b[\s:.]*", re.IGNORECASE)


def _rifinisci(testo: str, g):
    """Corregge le risposte del modello sui casi che sbaglia: l'etichetta dentro il dato, i numeri presi per indirizzi."""
    a, b = g.start, g.end
    if g.entity_type in FORMA_FISSA:
        m = _ETICHETTA.match(testo[a:b])
        if m:
            a += m.end()
    valore = testo[a:b]
    if g.entity_type == "ID_TECNICO" and not any(r.fullmatch(valore.strip()) for r in _TECNICI):
        return None  # «1.6.0» è una versione, non un indirizzo IP
    if g.entity_type == "EMAIL_ADDRESS" and "@" not in valore:
        if not _DOMINIO.fullmatch(valore.strip()):
            return None
        g.entity_type = "SITO"  # «didatticafacile.it»: il sito del cliente, non un'email
    if g.entity_type == "SITO" and (not _DOMINIO.fullmatch(valore.strip()) or valore[:1] in "-._"
                                    or (a > 0 and (testo[a - 1].isalnum() or testo[a - 1] in "-_"))
                                    or valore.rsplit(".", 1)[-1].split("/")[0].lower() in _ESTENSIONI):
        return None  # «wp-login.php» è un file, non un sito
    if not re.search(r"[A-Za-zÀ-ÿ]", valore):  # solo cifre e segni: va bene per un CAP o un numero, non per un nome
        if g.entity_type in ("PERSON", "ORGANIZATION", "LOCATION"):
            return None
        if g.entity_type == "INDIRIZZO" and not re.fullmatch(r"\d{5}", valore.strip()):
            return None
    if g.entity_type in ("DOCUMENTO", "CONTO", "CARTA", "ID_TECNICO", "CATASTO") and not re.search(r"\d", valore):
        return None  # «Carta d'» identità: un numero di documento ha almeno una cifra
    if b - a < 2:
        return None
    if (a, b) != (g.start, g.end):
        g.start, g.end = a, b
    return g


_GENERICI = {"gmail", "libero", "hotmail", "outlook", "yahoo", "icloud", "alice", "tiscali", "virgilio", "pec", "legalmail",
             "aruba", "fastwebnet", "tim", "live", "me", "mac", "proton", "protonmail", "email", "mail", "info"}


def _nomi_dai_domini(testo: str, scelti: list) -> list:
    """Il nome scritto nel dominio: «didatticafacile.it» → anche «Didattica Facile», ovunque compaia nel testo.

    Il dominio di un sito o di un'email aziendale è quasi sempre il nome del cliente senza spazi: se nel testo c'è una
    sequenza di 1-4 parole che, unite, dà quel nome, è il nome del cliente anche se il riconoscitore non l'ha visto.
    """
    nomi = set()
    for tipo, a, b, _, _ in scelti:
        if tipo not in ("SITO", "EMAIL_ADDRESS"):
            continue
        dominio = testo[a:b].split("@")[-1].lower()
        dominio = re.sub(r"^(?:https?://)?(?:www\.)?", "", dominio).split("/")[0]
        nome = dominio.rsplit(".", 1)[0].split(".")[-1].replace("-", "")
        if len(nome) >= 5 and nome not in _GENERICI:
            nomi.add(nome)
    if not nomi:
        return []
    out = []
    parole = list(re.finditer(r"[A-Za-zÀ-ÿ0-9]+", testo))
    for i in range(len(parole)):
        unite = ""
        for j in range(i, min(i + 4, len(parole))):
            if j > i and testo[parole[j - 1].end():parole[j].start()] not in (" ", "-", "", "'"):
                break
            unite += parole[j].group(0).lower()
            a, b = parole[i].start(), parole[j].end()
            dentro_dominio = (a > 0 and testo[a - 1] in "@./") or (testo[b:b + 1] in (".", "@") and testo[b + 1:b + 2].isalnum())
            if unite in nomi and not dentro_dominio:
                out.append(("ORGANIZATION", parole[i].start(), parole[j].end(), 0.95, 9))  # segnale fortissimo
                break
            if len(unite) > max(map(len, nomi)):
                break
    return out


def _scegli(candidati: list) -> list:
    """Sovrapposizioni: si ordina per priorità, poi per lunghezza, e si tiene il primo che non tocca gli altri."""
    scelti: list = []
    for c in sorted(candidati, key=lambda c: (-c[4], -(c[2] - c[1]), -c[3])):
        if all(c[2] <= s[1] or c[1] >= s[2] for s in scelti):
            scelti.append(c)
    return sorted(scelti, key=lambda c: c[1])


_IPV4 = re.compile(r"(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)")
_TECNICI = (_IPV4, re.compile(r"[0-9A-Fa-f]{0,4}(?::[0-9A-Fa-f]{0,4}){2,7}"),  # IPv6
            re.compile(r"[0-9A-Fa-f]{2}(?:[:-][0-9A-Fa-f]{2}){5}"), re.compile(r"\d{15}"))  # MAC, IMEI
_ESTENSIONI = {"php", "html", "htm", "js", "css", "json", "xml", "txt", "pdf", "doc", "docx", "xls", "xlsx", "csv", "png",
               "jpg", "jpeg", "gif", "svg", "zip", "exe", "py", "md", "log", "sql", "msg", "eml"}
_DOMINIO = re.compile(r"(?:https?://)?(?:www\.)?[\w-]+(?:\.[\w-]+)*\.[a-z]{2,}(?:/\S*)?", re.IGNORECASE)


def _salta_cortesie(testo: str, a: int, b: int) -> int:
    while True:
        m = re.match(r"\s*([\w.']+)(?:\s+|\s*$)", testo[a:b])
        if not m or not m.end():
            return a
        parola = m.group(1).casefold()
        if parola.rstrip(".,") in PAROLE_COMUNI or parola in PAROLE_COMUNI or parola.rstrip(".") in TITOLI or parola in TITOLI:
            a += m.end()
        else:
            return a


def _chiave(valore: str) -> str:
    return " ".join(valore.split()).casefold()


def ripristina(testo: str, tabella: Tabella, attesi: Iterable[str] | None = None) -> Ripristino:
    """Rimette i valori veri al posto dei segnaposto e controlla che il testo di ritorno non ne abbia persi o inventati.

    `attesi`: i segnaposto che dovrebbero esserci (di solito quelli del testo mandato). Se None, non si controllano i mancanti.
    """
    presenti = set(SEGNAPOSTO.findall(testo))
    inventati = sorted(s for s in presenti if s not in tabella.valori)
    mancanti = sorted(set(attesi) - presenti) if attesi is not None else []
    ripristinato = SEGNAPOSTO.sub(lambda m: tabella.valori.get(m.group(0), m.group(0)), testo)
    return Ripristino(ripristinato, mancanti, inventati)
