"""La tabella dei segnaposto: la chiave per tornare indietro. Va tenuta in casa, separata dal testo, e cancellata."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Tabella:
    """Collega ogni segnaposto al valore vero. Lo stesso valore riceve sempre lo stesso segnaposto."""

    valori: dict[str, str] = field(default_factory=dict)  # "[PERSONA_1]" -> "Mario Rossi"
    creata: float = field(default_factory=time.time)
    scade: float | None = None  # timestamp oltre il quale la tabella va cancellata

    def __post_init__(self) -> None:
        self._inversa = {self._chiave(v): s for s, v in self.valori.items()}

    @staticmethod
    def _chiave(valore: str) -> str:
        return " ".join(valore.split()).casefold()

    def segnaposto(self, tipo: str, valore: str) -> str:
        k = self._chiave(valore)
        if k in self._inversa:
            return self._inversa[k]
        # Il numero successivo al più alto usato: un segnaposto tolto non viene mai riassegnato a un altro valore.
        usati = [int(s[len(tipo) + 2:-1]) for s in self.valori if s.startswith(f"[{tipo}_") and s[len(tipo) + 2:-1].isdigit()]
        self._ultimo = getattr(self, "_ultimo", {})
        n = max([*usati, self._ultimo.get(tipo, 0)]) + 1
        self._ultimo[tipo] = n
        s = f"[{tipo}_{n}]"
        self.valori[s] = valore
        self._inversa[k] = s
        return s

    def rimuovi(self, valore: str) -> str | None:
        """Toglie un valore (era un falso allarme). Restituisce il segnaposto che aveva, se c'era."""
        s = self._inversa.pop(self._chiave(valore), None)
        if s:
            self.valori.pop(s, None)
        return s

    def scaduta(self) -> bool:
        return self.scade is not None and time.time() > self.scade

    def salva(self, percorso: str | Path) -> None:
        """Salva in JSON con permessi 600: leggibile solo dall'utente che la crea."""
        p = Path(percorso)
        p.write_text(json.dumps({"valori": self.valori, "creata": self.creata, "scade": self.scade}, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(p, 0o600)

    @classmethod
    def carica(cls, percorso: str | Path) -> "Tabella":
        d = json.loads(Path(percorso).read_text(encoding="utf-8"))
        t = cls(valori=d["valori"], creata=d.get("creata", time.time()), scade=d.get("scade"))
        if t.scaduta():
            raise ValueError(f"La tabella {percorso} è scaduta: va cancellata, non usata")
        return t
