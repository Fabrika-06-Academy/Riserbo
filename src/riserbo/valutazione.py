"""Misurare le fughe: il set di prova della pseudonimizzazione.

Il set è un file JSONL, una riga per testo:
    {"testo": "...", "entita": [{"valore": "Mario Rossi", "tipo": "PERSONA"}, ...]}

Due misure:
- fughe: entità annotate che restano leggibili nel testo pseudonimizzato (il rischio);
- testo rovinato: pezzi sostituiti che nessuno aveva annotato (il costo: il modello in cloud lavora peggio).
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from .motore import Segnaposto


def valuta(sp: Segnaposto, percorso: str | Path) -> dict:
    righe = [json.loads(r) for r in Path(percorso).read_text(encoding="utf-8").splitlines() if r.strip()]
    tot, fughe = Counter(), Counter()
    esempi_fughe: dict[str, list[str]] = defaultdict(list)
    rovinati, sostituiti = 0, 0
    for r in righe:
        ris = sp.pseudonimizza(r["testo"])
        attese = [e["valore"].casefold() for e in r["entita"]]
        for e in r["entita"]:
            tot[e["tipo"]] += 1
            if e["valore"].casefold() in ris.testo.casefold():
                fughe[e["tipo"]] += 1
                if len(esempi_fughe[e["tipo"]]) < 5:
                    esempi_fughe[e["tipo"]].append(e["valore"])
        for t in ris.trovati:
            sostituiti += 1
            v = t["valore"].casefold()
            if not any(v in a or a in v for a in attese):
                rovinati += 1
    per_tipo = {k: {"annotate": tot[k], "sfuggite": fughe[k], "percentuale_fughe": round(100 * fughe[k] / tot[k], 1)} for k in sorted(tot)}
    n = sum(tot.values())
    return {
        "testi": len(righe),
        "entita_annotate": n,
        "fughe_totali": sum(fughe.values()),
        "percentuale_fughe": round(100 * sum(fughe.values()) / n, 1) if n else 0.0,
        "sostituzioni": sostituiti,
        "sostituzioni_non_annotate": rovinati,
        "per_tipo": per_tipo,
        "esempi_fughe": dict(esempi_fughe),
    }
