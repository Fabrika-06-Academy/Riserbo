"""Il riconoscitore di entità italiano: un BERT addestrato su oltre 50 categorie di dati, eseguito con ONNX Runtime.

Modello: DeepMount00/Italian_NER_XXL_v2 (Apache 2.0), convertito in ONNX int8 dal workflow «modello» e pubblicato
nella release `modello-ner-1` del repository. Nessun PyTorch sul computer di chi lo usa, nessun dato mandato fuori:
il modello si scarica una volta (o è già dentro l'app) e gira in locale.

Sul set di prova esempi/ner-prova.txt (88 entità in testi di PMI): 1 fuga contro le 6 del modello spaCy piccolo,
nessuna copertura parziale, 2 falsi allarmi contro 9.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import urllib.request
from importlib.resources import files
from pathlib import Path

import numpy as np
from presidio_analyzer import EntityRecognizer, RecognizerResult

VERSIONE_MODELLO = "modello-ner-1"
URL_BASE = f"https://github.com/Fabrika-06-Academy/segnaposto/releases/download/{VERSIONE_MODELLO}/"
FILE = ("modello.onnx", "tokenizer.json", "etichette.json", "LEGGIMI.txt")
SHA256 = {
    "LEGGIMI.txt": "b4a6ba7df1382959b7cca5ae4529a64bd3c38cd33cd5837386a96786b7236845",
    "etichette.json": "24c639cb1f6eba7cacc01e3f434dfcdcf33ae241a7672f3a3cd2af31da893507",
    "modello.onnx": "749f46cc35be0799e002863366ceffa79a76ed9b72f0edc289e239617e1532c5",
    "tokenizer.json": "a11cdf9238141003953d18767b2b4dfa9cd2b5ba86bff93066c81a7a48d9f56a",
}  # impronte dei file della release: un file alterato viene rifiutato

# Etichetta del modello -> entità Presidio / tipo di segnaposto. Le etichette assenti non vengono sostituite
# (date, importi, orari, leggi, valute: servono al modello in cloud per fare il lavoro).
MAPPA = {
    "NOME": "PERSON", "COGNOME": "PERSON", "AVV_NOTAIO": "PERSON",
    "RAGIONE_SOCIALE": "ORGANIZATION", "BANCA": "ORGANIZATION",
    "LUOGO": "LOCATION",
    "INDIRIZZO": "INDIRIZZO", "CODICE_POSTALE": "INDIRIZZO",
    "NUMERO_TELEFONO": "PHONE_NUMBER", "EMAIL": "EMAIL_ADDRESS",
    "CODICE_FISCALE": "IT_FISCAL_CODE", "P_IVA": "IT_VAT_CODE", "IBAN": "IBAN", "BIC": "CONTO",
    "TARGA_VEICOLO": "TARGA",
    "DATA_NASCITA": "DATA_NASCITA", "DATA_MORTE": "DATA_NASCITA", "ETA": "ETA",
    "NUMERO_DOCUMENTO": "DOCUMENTO", "N_LICENZA": "DOCUMENTO",
    "NUMERO_CONTO": "CONTO", "NUM_ASSEGNO_BANCARIO": "CONTO", "NUMERO_CARTA": "CARTA",
    "CVV": "SEGRETO", "PIN": "SEGRETO", "PASSWORD": "SEGRETO",
    "MALATTIA": "SALUTE", "MEDICINA": "SALUTE", "CARTELLA_CLINICA": "SALUTE", "STORIA_CLINICA": "SALUTE", "DOSAGGIO": "SALUTE",
    "IP": "ID_TECNICO", "IPV6_1": "ID_TECNICO", "MAC": "ID_TECNICO", "IMEI": "ID_TECNICO",
    "FOGLIO": "CATASTO", "MAPPALE": "CATASTO", "SUBALTERNO": "CATASTO", "PARTICELLA": "CATASTO",
    "STATO_CIVILE": "STATO_CIVILE", "REGIME_PATRIMONIALE": "STATO_CIVILE",
    "PROFESSIONE": "PROFESSIONE",
    "URL": "SITO",
}
ENTITA = sorted(set(MAPPA.values()))
MAX_TOKEN = 510


def cartella_cache() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    elif os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "segnaposto" / VERSIONE_MODELLO


def trova_modello() -> Path | None:
    """Dove sta il modello: variabile SEGNAPOSTO_MODELLO, dentro l'app impacchettata, o nella cache dell'utente."""
    candidati = []
    if os.environ.get("SEGNAPOSTO_MODELLO"):
        candidati.append(Path(os.environ["SEGNAPOSTO_MODELLO"]))
    try:
        candidati.append(Path(str(files("segnaposto").joinpath("modello"))))
    except Exception:
        pass
    candidati.append(cartella_cache())
    for c in candidati:
        if all((c / f).exists() for f in FILE[:3]):
            return c
    return None


def scarica_modello(avanzamento=print) -> Path:
    """Scarica il modello (circa 110 MB) dalla release del repository e controlla l'impronta SHA-256 di ogni file."""
    dest = cartella_cache()
    dest.mkdir(parents=True, exist_ok=True)
    attese = SHA256 or json.loads(urllib.request.urlopen(URL_BASE + "sha256.json", timeout=60).read())
    for f in FILE:
        finale = dest / f
        if finale.exists() and hashlib.sha256(finale.read_bytes()).hexdigest() == attese.get(f):
            continue
        avanzamento(f"segnaposto: scarico il riconoscitore di entità ({f})…")
        tmp = dest / (f + ".parziale")
        with urllib.request.urlopen(URL_BASE + f, timeout=120) as r, open(tmp, "wb") as out:
            h = hashlib.sha256()
            while blocco := r.read(1 << 20):
                h.update(blocco)
                out.write(blocco)
        if attese.get(f) and h.hexdigest() != attese[f]:
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"Il file {f} scaricato non corrisponde all'impronta attesa: scaricamento interrotto?")
        tmp.replace(finale)
    return dest


class RiconoscitoreItaliano(EntityRecognizer):
    """Entità Presidio dal BERT italiano. Il testo lungo si divide in pezzi da al massimo 510 token, sui confini di riga."""

    def __init__(self, cartella: str | Path | None = None, scarica: bool = True) -> None:
        self._cartella = Path(cartella) if cartella else None
        self._scarica = scarica
        self._lock = threading.Lock()
        super().__init__(supported_entities=ENTITA, supported_language="it", name="RiconoscitoreItaliano")

    def load(self) -> None:
        import onnxruntime as ort
        from tokenizers import Tokenizer

        c = self._cartella or trova_modello()
        if c is None:
            if not self._scarica:
                raise RuntimeError("Il riconoscitore di entità non è installato: lancia «segnaposto scarica-modello».")
            c = scarica_modello()
        self.tok = Tokenizer.from_file(str(c / "tokenizer.json"))
        self.tok.no_truncation()
        self.tok.no_padding()
        self.etichette = {int(k): v for k, v in json.loads((c / "etichette.json").read_text(encoding="utf-8")).items()}
        so = ort.SessionOptions()
        so.intra_op_num_threads = min(4, os.cpu_count() or 1)
        so.log_severity_level = 3
        self.sessione = ort.InferenceSession(str(c / "modello.onnx"), so, providers=["CPUExecutionProvider"])
        self.ingressi = {i.name for i in self.sessione.get_inputs()}

    # ------------------------------------------------------------------ divisione in pezzi
    def _pezzi(self, testo: str) -> list[tuple[int, int]]:
        """Pezzi del testo (inizio, fine) che stanno nei 510 token: si accumulano righe, e si spezzano le righe troppo lunghe."""
        righe, pos = [], 0
        for r in testo.splitlines(keepends=True):
            righe.append((pos, pos + len(r)))
            pos += len(r)
        pezzi: list[tuple[int, int]] = []
        a = b = 0
        for x, y in righe:
            if self._token(testo[a:y]) <= MAX_TOKEN:
                b = y
                continue
            if b > a:
                pezzi.append((a, b))
            a = b = x
            if self._token(testo[x:y]) <= MAX_TOKEN:
                b = y
            else:  # una riga enorme: si divide sulle frasi, poi brutalmente
                for p in self._spezza(testo, x, y):
                    pezzi.append(p)
                a = b = y
        if b > a:
            pezzi.append((a, b))
        return pezzi

    def _token(self, s: str) -> int:
        return len(self.tok.encode(s, add_special_tokens=False).ids)

    def _spezza(self, testo: str, x: int, y: int) -> list[tuple[int, int]]:
        out, a = [], x
        while a < y:
            b = min(y, a + 1200)
            while self._token(testo[a:b]) > MAX_TOKEN and b - a > 200:
                b = a + (b - a) * 3 // 4
            if b < y:  # si torna indietro fino a uno spazio, per non tagliare un nome a metà
                s = testo.rfind(" ", a + 100, b)
                b = s if s > 0 else b
            out.append((a, b))
            a = b
        return out

    # ------------------------------------------------------------------ analisi
    def _analizza_pezzo(self, testo: str, base: int) -> list[RecognizerResult]:
        enc = self.tok.encode(testo)
        ids = np.array([enc.ids], np.int64)
        feed = {"input_ids": ids, "attention_mask": np.ones_like(ids)}
        if "token_type_ids" in self.ingressi:
            feed["token_type_ids"] = np.zeros_like(ids)
        with self._lock:
            logits = self.sessione.run(None, feed)[0][0]
        e = np.exp(logits - logits.max(-1, keepdims=True))
        prob = e / e.sum(-1, keepdims=True)
        scelta = prob.argmax(-1)
        # Etichetta per parola: quella del primo sotto-token; la parola si copre per intero.
        parole: dict[int, list] = {}
        for i, (wid, (a, b)) in enumerate(zip(enc.word_ids, enc.offsets)):
            if wid is None or a == b:
                continue
            if wid not in parole:
                parole[wid] = [a, b, self.etichette[int(scelta[i])], float(prob[i, scelta[i]])]
            else:
                parole[wid][1] = b
        risultati: list[RecognizerResult] = []
        cur = None  # [tipo, inizio, fine, punteggi]
        for a, b, lab, p in (parole[k] for k in sorted(parole)):
            tipo = MAPPA.get(lab[2:]) if lab != "O" else None
            nuovo = lab.startswith("B-")
            if tipo and cur and cur[0] == tipo and testo[cur[2]:a].strip() in ("", "-", "'", "’", ".", "&") and (
                    not nuovo or tipo == "PERSON"):  # «Mario» (NOME) + «Rossi» (COGNOME) = una persona
                cur[2], cur[3] = b, cur[3] + [p]
                continue
            if cur:
                risultati.append(RecognizerResult(cur[0], base + cur[1], base + cur[2], round(min(cur[3]), 3)))
                cur = None
            if tipo:
                cur = [tipo, a, b, [p]]
        if cur:
            risultati.append(RecognizerResult(cur[0], base + cur[1], base + cur[2], round(min(cur[3]), 3)))
        return risultati

    def analyze(self, text, entities, nlp_artifacts=None):
        out = []
        for a, b in self._pezzi(text):
            if text[a:b].strip():
                out += [r for r in self._analizza_pezzo(text[a:b], a) if not entities or r.entity_type in entities]
        return out
