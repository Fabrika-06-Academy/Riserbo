"""Comando `segnaposto`.

    segnaposto pseudonimizza email.txt --tabella pratica-123.json [--anagrafica clienti.csv] > email-pulita.txt
    segnaposto ripristina risposta.txt --tabella pratica-123.json > risposta-vera.txt
    segnaposto valuta set-di-prova.jsonl
    segnaposto servi --porta 8765
    segnaposto app
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def _leggi(p: str) -> str:
    return sys.stdin.read() if p == "-" else Path(p).read_text(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="segnaposto", description="Pseudonimizzare testi italiani prima di mandarli a un modello in cloud.")
    sub = ap.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("pseudonimizza", help="sostituisce i dati con segnaposto e salva la tabella")
    p.add_argument("file", help="file di testo, o - per lo standard input")
    p.add_argument("--tabella", required=True, help="dove salvare la tabella dei segnaposto (JSON, permessi 600)")
    p.add_argument("--anagrafica", help="CSV di clienti/fornitori esportato dal gestionale")
    p.add_argument("--colonna", help="colonna dell'anagrafica con il nome (predefinita: la prima)")
    p.add_argument("--giorni", type=int, default=30, help="dopo quanti giorni la tabella scade (predefinito 30)")
    p.add_argument("--mostra", action="store_true", help="stampa su stderr cosa è stato trovato")

    r = sub.add_parser("ripristina", help="rimette i valori veri e controlla i segnaposto")
    r.add_argument("file")
    r.add_argument("--tabella", required=True)

    v = sub.add_parser("valuta", help="misura le fughe su un set di prova JSONL")
    v.add_argument("file")
    v.add_argument("--anagrafica")

    sa = sub.add_parser("app", help="apre l'app locale nel browser (pseudonimizza e ripristina)")
    sa.add_argument("--anagrafica")
    sa.add_argument("--no-browser", action="store_true", help="non aprire il browser (stampa solo l'indirizzo)")

    s = sub.add_parser("servi", help="servizio HTTP locale (POST /pseudonimizza)")
    s.add_argument("--host", default="127.0.0.1", help="predefinito 127.0.0.1: non esporlo su internet")
    s.add_argument("--porta", type=int, default=8765)
    s.add_argument("--anagrafica")
    s.add_argument("--max-caratteri", type=int, default=20000)

    a = ap.parse_args(argv)
    from .motore import Segnaposto, ripristina
    from .riconoscitori import carica_anagrafica
    from .tabella import Tabella

    if a.comando == "ripristina":
        t = Tabella.carica(a.tabella)
        esito = ripristina(_leggi(a.file), t)
        sys.stdout.write(esito.testo)
        if esito.inventati:
            print(f"ATTENZIONE: segnaposto non presenti nella tabella: {', '.join(esito.inventati)}", file=sys.stderr)
            return 2
        return 0

    extra = [carica_anagrafica(a.anagrafica, getattr(a, "colonna", None))] if a.anagrafica else []
    sp = Segnaposto(riconoscitori=extra)

    if a.comando == "app":
        from .app import avvia
        avvia(sp, apri_browser=not a.no_browser)
        return 0

    if a.comando == "servi":
        from .servizio import servi
        servi(a.host, a.porta, sp, a.max_caratteri)
        return 0

    if a.comando == "valuta":
        from .valutazione import valuta
        print(json.dumps(valuta(sp, a.file), ensure_ascii=False, indent=2))
        return 0

    tab_path = Path(a.tabella)
    t = Tabella.carica(tab_path) if tab_path.exists() else Tabella(scade=time.time() + a.giorni * 86400)
    ris = sp.pseudonimizza(_leggi(a.file), t)
    t.salva(tab_path)
    sys.stdout.write(ris.testo)
    if a.mostra:
        for x in ris.trovati:
            print(f"{x['tipo']:<15} {x['punteggio']:.2f}  {x['valore']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
