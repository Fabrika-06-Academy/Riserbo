"""Comando `riserbo` (anche col vecchio nome `segnaposto`).

    riserbo pseudonimizza email.txt --tabella pratica-123.json [--anagrafica clienti.csv] > email-pulita.txt
    riserbo ripristina risposta.txt --tabella pratica-123.json > risposta-vera.txt
    riserbo valuta set-di-prova.jsonl
    riserbo servi --porta 8765
    riserbo app
    riserbo cancello --porta 8788      (proxy compatibile con OpenAI e Anthropic)
    riserbo mcp --cartella ~/Documenti (server MCP per Claude Desktop e gli altri agenti)
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
    ap = argparse.ArgumentParser(prog="riserbo", description="Pseudonimizzare testi italiani prima di mandarli a un modello in cloud.")
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

    sa = sub.add_parser("app", help="apre l'app locale (finestra, o browser): documenti, pseudonimizza e ripristina")
    sa.add_argument("--anagrafica")
    sa.add_argument("--no-browser", action="store_true", help="non aprire nulla (stampa solo l'indirizzo)")
    sa.add_argument("--browser", action="store_true", help="usa il browser anche se la finestra nativa è disponibile")

    sub.add_parser("scarica-modello", help="scarica il riconoscitore di entità (circa 110 MB, una volta sola)")

    s = sub.add_parser("servi", help="servizio HTTP locale (POST /pseudonimizza)")
    s.add_argument("--host", default="127.0.0.1", help="predefinito 127.0.0.1: non esporlo su internet")
    s.add_argument("--porta", type=int, default=8765)
    s.add_argument("--anagrafica")
    s.add_argument("--max-caratteri", type=int, default=20000)

    c = sub.add_parser("cancello", help="proxy locale compatibile con OpenAI e Anthropic: pseudonimizza all'andata, "
                                        "rimette i nomi al ritorno")
    c.add_argument("--host", default="127.0.0.1", help="predefinito 127.0.0.1; un altro indirizzo richiede --chiave")
    c.add_argument("--porta", type=int, default=8788)
    c.add_argument("--chiave", default="", help="segreto nel percorso (…/k/CHIAVE/openai/v1): obbligatorio fuori da 127.0.0.1")
    c.add_argument("--openai", help="indirizzo di un servizio compatibile con OpenAI (OpenRouter, Mistral, Ollama…)")
    c.add_argument("--anthropic", help="indirizzo alternativo per Anthropic")
    c.add_argument("--consenti-allegati", action="store_true", help="lascia passare immagini e file (NON pseudonimizzati)")
    c.add_argument("--anagrafica")

    m = sub.add_parser("mcp", help="server MCP (stdio) per Claude Desktop: legge i documenti attraverso Riserbo")
    m.add_argument("--cartella", action="append", default=[], help="cartella che l'agente può leggere (si ripete)")

    a = ap.parse_args(argv)
    if a.comando == "mcp":
        from .server_mcp import main_mcp
        return main_mcp(sum((["--cartella", c] for c in a.cartella), []))
    if a.comando == "scarica-modello":
        from .ner import scarica_modello
        print(f"Riconoscitore di entità pronto in {scarica_modello()}")
        return 0
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

    if a.comando == "app":
        from .app import avvia
        # Senza anagrafica il modello si carica in background, con la finestra già aperta.
        avvia(Segnaposto(riconoscitori=extra) if extra else None, apri_browser=not a.no_browser,
              finestra=False if a.browser else None)
        return 0

    sp = Segnaposto(riconoscitori=extra)

    if a.comando == "servi":
        from .servizio import servi
        servi(a.host, a.porta, sp, a.max_caratteri)
        return 0

    if a.comando == "cancello":
        from .cancello import Cancello, avvia_cancello, indirizzi
        if a.host not in ("127.0.0.1", "localhost") and len(a.chiave) < 16:
            print("Fuori da 127.0.0.1 serve --chiave con almeno 16 caratteri: chiunque nella rete potrebbe usarlo.", file=sys.stderr)
            return 2
        fornitori = {k: v for k, v in (("openai", a.openai), ("anthropic", a.anthropic)) if v}
        canc = Cancello(sp, fornitori=fornitori, consenti_allegati=a.consenti_allegati)
        httpd = avvia_cancello(canc, a.host, a.porta, a.chiave)
        url = indirizzi(a.porta, a.host if a.host != "0.0.0.0" else "INDIRIZZO-DI-QUESTO-SERVER", a.chiave)
        print(f"Cancello di Riserbo attivo.\n  OpenAI e compatibili  base URL: {url['openai']}\n"
              f"  Anthropic             base URL: {url['anthropic']}\n"
              f"Fornitori: {canc.fornitori['openai']} · {canc.fornitori['anthropic']}\nCtrl+C per fermarlo.", flush=True)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            httpd.shutdown()
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
