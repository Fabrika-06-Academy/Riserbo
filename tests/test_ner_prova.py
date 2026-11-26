"""Non regressione sul set esempi/ner-prova.txt: 88 entità in testi tipici di PMI (cognomi comuni, piccoli comuni,
minuscole, aziende senza forma giuridica). Con il riconoscitore italiano: 1-2 fughe, nessun falso allarme."""
import re
from pathlib import Path

SET = Path(__file__).parent.parent / "esempi" / "ner-prova.txt"


def _carica():
    for r in SET.read_text(encoding="utf-8").splitlines():
        if not r.strip() or r.startswith("#"):
            continue
        testo, oro, pos = "", [], 0
        for m in re.finditer(r"\[\[(\w+)\|(.+?)\]\]", r):
            testo += r[pos:m.start()]
            oro.append((len(testo), len(testo) + len(m.group(2))))
            testo += m.group(2)
            pos = m.end()
        yield testo + r[pos:], oro


def test_fughe_e_falsi_allarmi(sp):
    fughe, falsi = [], []
    for testo, oro in _carica():
        trovati = sp.trova(testo)
        coperto = set()
        for t in trovati:
            coperto |= set(range(t["inizio"], t["fine"]))
        for a, b in oro:
            if not all(i in coperto for i in range(a, b) if not testo[i].isspace()):
                fughe.append(testo[a:b])
        for t in trovati:
            if t["tipo"] in ("PERSONA", "AZIENDA", "LUOGO") and all(t["fine"] <= a or t["inizio"] >= b for a, b in oro):
                falsi.append(t["valore"])
    assert len(fughe) <= 3, fughe
    assert len(falsi) <= 3, falsi
