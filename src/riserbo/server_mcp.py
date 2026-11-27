"""Server MCP: Claude Desktop (e gli altri agenti MCP) leggono i tuoi documenti attraverso Riserbo.

Il modello vede solo i segnaposto: nomi dei file compresi. Quando scrive la risposta, Riserbo rimette i valori veri
e la salva sul tuo disco o la mette negli appunti: il testo con i dati veri non torna mai al modello.

    riserbo mcp --cartella ~/Documenti/Clienti [--cartella ...]

Claude Desktop lo avvia da sé (stdio, JSON-RPC una riga per messaggio): l'app scrive la configurazione con un clic.
Il protocollo è scritto qui, senza la libreria `mcp`: poche righe, nessuna dipendenza in più nell'app.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Callable

from . import __version__
from .motore import SEGNAPOSTO, Segnaposto
from .tabella import Tabella

VERSIONI_PROTOCOLLO = ("2025-06-18", "2025-03-26", "2024-11-05")
MAX_TESTO = 120_000
MAX_ELENCO = 300
INATTIVITA = 4 * 3600

ISTRUZIONI = (
    "Riserbo protegge i dati personali: i documenti che leggi hanno nomi, codici fiscali, IBAN, indirizzi e simili "
    "sostituiti da segnaposto come [PERSONA_1] o [IBAN_2]. Usa i segnaposto esattamente come li trovi, senza "
    "inventarne di nuovi e senza chiedere i valori veri. Per consegnare un testo con i dati veri usa salva_documento "
    "o copia_negli_appunti: Riserbo li rimette sul computer della persona e tu non li vedrai."
)

STRUMENTI = [
    {"name": "elenca_documenti",
     "description": "Elenca cartelle e documenti leggibili (Word, PDF anche scansionati, Excel, CSV, email, foto, testo) "
                    "nelle cartelle permesse. I nomi con dati personali sono pseudonimizzati: per aprire un documento "
                    "usa il suo identificativo (d1, d2…), per entrare in una cartella il suo (c1, c2…).",
     "inputSchema": {"type": "object", "properties": {
         "cartella": {"type": "string", "description": "Identificativo di cartella (c1…). Vuoto: le cartelle permesse."}}}},
    {"name": "leggi_documento",
     "description": "Legge un documento e restituisce il testo con i dati personali sostituiti da segnaposto.",
     "inputSchema": {"type": "object", "required": ["documento"], "properties": {
         "documento": {"type": "string", "description": "Identificativo (d1…) da elenca_documenti, oppure percorso del file."}}}},
    {"name": "salva_documento",
     "description": "Salva un testo sul computer della persona dopo aver rimesso i valori veri al posto dei segnaposto. "
                    "Formati: .docx, .txt, .md, .csv, .xlsx (per le tabelle: colonne separate da tabulazioni). "
                    "Non sovrascrive: se il nome esiste aggiunge un numero.",
     "inputSchema": {"type": "object", "required": ["testo", "nome_file"], "properties": {
         "testo": {"type": "string"},
         "nome_file": {"type": "string", "description": "Per esempio «Risposta a [PERSONA_1].docx»."},
         "cartella": {"type": "string", "description": "Identificativo di cartella (c1…). Vuoto: la prima cartella permessa."}}}},
    {"name": "copia_negli_appunti",
     "description": "Mette negli appunti del computer il testo con i valori veri al posto dei segnaposto, pronto da "
                    "incollare in un'email o in un documento.",
     "inputSchema": {"type": "object", "required": ["testo"], "properties": {"testo": {"type": "string"}}}},
]


def cartelle_predefinite() -> list[Path]:
    casa = Path.home()
    return [p for p in (casa / "Documents", casa / "Documenti", casa / "Desktop", casa / "Downloads") if p.is_dir()]


class ServerMCP:
    def __init__(self, cartelle: list[Path], motore: Segnaposto | Callable[[], Segnaposto] | None = None,
                 scrivi_appunti: Callable[[str], None] | None = None) -> None:
        self.radici = [Path(c).expanduser().resolve() for c in cartelle]
        self._motore = motore
        self._sp: Segnaposto | None = motore if isinstance(motore, Segnaposto) else None
        self._pronto = threading.Event()
        if self._sp is not None:
            self._pronto.set()
        self._errore_modello = ""
        self.scrivi_appunti = scrivi_appunti
        self.lock = threading.Lock()
        self.nuova_tabella()

    def nuova_tabella(self) -> None:
        self.tabella = Tabella()
        self.ids: dict[str, Path] = {}
        self.per_percorso: dict[Path, str] = {}
        self.ultimo_uso = time.time()

    # ------------------------------------------------------------ modello

    def carica(self) -> None:
        if self._pronto.is_set():
            return
        try:
            self._sp = self._motore() if callable(self._motore) else Segnaposto()
        except Exception as e:  # pragma: no cover
            self._errore_modello = str(e)
        self._pronto.set()

    @property
    def sp(self) -> Segnaposto:
        if not self._pronto.wait(180) or self._sp is None:
            raise ValueError(f"Il modello italiano non è pronto: {self._errore_modello or 'riprova tra poco.'}")
        return self._sp

    # ------------------------------------------------------------ percorsi

    def _id(self, p: Path, prefisso: str) -> str:
        if p in self.per_percorso:
            return self.per_percorso[p]
        i = f"{prefisso}{sum(1 for k in self.ids if k[0] == prefisso) + 1}"
        self.ids[i], self.per_percorso[p] = p, i
        return i

    def _dentro(self, p: Path) -> Path:
        p = p.expanduser().resolve()
        if not any(p == r or r in p.parents for r in self.radici):
            raise ValueError("Questo percorso è fuori dalle cartelle permesse a Riserbo.")
        return p

    def _risolvi(self, rif: str, prefisso: str) -> Path:
        rif = (rif or "").strip()
        if rif in self.ids and rif[0] == prefisso:
            return self.ids[rif]
        vero = SEGNAPOSTO.sub(lambda m: self.tabella.valori.get(m.group(0), m.group(0)), rif)
        if not vero:
            raise ValueError("Indica un identificativo (d1, c1…) o un percorso.")
        p = Path(vero).expanduser()
        if not p.is_absolute():
            p = self.radici[0] / p
        return self._dentro(p)

    def _nomi(self, nomi: list[str]) -> list[str]:
        """I nomi di file e cartelle con i dati personali sostituiti («Contratto Mario_Rossi.pdf»), in una passata sola."""
        if not nomi:
            return []
        basi = [os.path.splitext(n) for n in nomi]
        righe = [b.replace("_", " ").replace("-", " ").replace(";", ",").replace("\n", " ") for b, _ in basi]
        # « ; » tra un nome e l'altro: con gli a capo il modello scambiava parole come «note» per nomi di persona
        uscita = self.sp.pseudonimizza(" ; ".join(righe), self.tabella).testo.split(" ; ")
        if len(uscita) != len(righe):  # non dovrebbe succedere: per prudenza un nome alla volta
            uscita = [self.sp.pseudonimizza(r, self.tabella).testo for r in righe]
        return [(u if u != r else b) + e for u, r, (b, e) in zip(uscita, righe, basi)]

    def _nome(self, nome: str) -> str:
        return self._nomi([nome])[0]

    # ------------------------------------------------------------ strumenti

    def elenca_documenti(self, cartella: str = "") -> str:
        from .documenti import LEGGIBILI
        if not cartella:
            nomi = self._nomi([r.name for r in self.radici])
            return "\n".join(["Cartelle permesse:"] + [f"- {self._id(r, 'c')}  {n or r}" for r, n in zip(self.radici, nomi)])
        p = self._risolvi(cartella, "c")
        if not p.is_dir():
            raise ValueError("Non è una cartella.")
        cartelle, documenti = [], []
        for x in sorted(p.iterdir(), key=lambda x: x.name.casefold()):
            if x.name.startswith("."):
                continue
            if x.is_dir():
                cartelle.append(x)
            elif x.suffix.lower() in LEGGIBILI:
                documenti.append(x)
        voci = (cartelle + documenti)[:MAX_ELENCO]
        nomi = self._nomi([p.name] + [x.name for x in voci])
        righe = [f"Cartella {self._id(p, 'c')} {nomi[0]}: {len(cartelle)} cartelle, {len(documenti)} documenti."]
        for x, n in zip(voci, nomi[1:]):
            righe.append(f"- {self._id(x, 'c' if x.is_dir() else 'd')}  {n}{'/' if x.is_dir() else ''}")
        if len(cartelle) + len(documenti) > MAX_ELENCO:
            righe.append(f"(mostrati i primi {MAX_ELENCO})")
        return "\n".join(righe)

    def leggi_documento(self, documento: str) -> str:
        from .documenti import leggi
        p = self._risolvi(documento, "d")
        if not p.is_file():
            raise ValueError("Il documento non esiste.")
        doc = leggi(p.name, p.read_bytes())
        r = self.sp.pseudonimizza(doc.testo, self.tabella, forzati=doc.forzati)
        testo = r.testo
        tagliato = len(testo) > MAX_TESTO
        intest = [f"Documento {self._id(p, 'd')} «{self._nome(p.name)}» ({doc.formato}): {len(r.trovati)} dati sostituiti."]
        if doc.ocr_pagine:
            intest.append(f"Letto con l'OCR ({doc.ocr_pagine} pagine o immagini): qualche parola può essere sbagliata.")
        if tagliato:
            intest.append(f"Il testo è lungo: qui ci sono i primi {MAX_TESTO} caratteri.")
        return "\n".join(intest) + "\n\n" + testo[:MAX_TESTO]

    def _rimetti(self, testo: str) -> tuple[str, int]:
        n = [0]

        def sost(m):
            v = self.tabella.valori.get(m.group(0))
            if v is None:
                return m.group(0)
            n[0] += 1
            return v
        return SEGNAPOSTO.sub(sost, testo), n[0]

    def salva_documento(self, testo: str, nome_file: str, cartella: str = "") -> str:
        from .documenti import FORMATI_USCITA, esporta
        dove = self._risolvi(cartella, "c") if cartella else self.radici[0]
        if not dove.is_dir():
            raise ValueError("La cartella non esiste.")
        nome_vero, _ = self._rimetti(Path(nome_file).name)
        base, est = os.path.splitext(nome_vero)
        formato = est.lower().lstrip(".") or "docx"
        if formato not in FORMATI_USCITA:
            raise ValueError(f"Si può salvare in: {', '.join(FORMATI_USCITA)}.")
        base = "".join(c for c in base if c not in '<>:"/\\|?*').strip() or "documento"
        vero, n = self._rimetti(testo)
        dati, _ = esporta(vero, formato)
        p, k, extra = dove / f"{base}.{formato}", 2, ""
        while p.exists():
            extra = f" ({k})"
            p, k = dove / f"{base}{extra}.{formato}", k + 1
        self._dentro(p).write_bytes(dati)
        nome_visto = f"{os.path.splitext(Path(nome_file).name)[0]}{extra}.{formato}"  # con i segnaposto: il modello non vede i nomi
        return f"Salvato come «{nome_visto}» nella cartella {self._id(dove, 'c')}, con {n} valori veri rimessi al posto dei segnaposto."

    def copia_negli_appunti(self, testo: str) -> str:
        vero, n = self._rimetti(testo)
        if self.scrivi_appunti is None:
            from .scorciatoie import scrivi_appunti
            self.scrivi_appunti = scrivi_appunti
        self.scrivi_appunti(vero)
        return f"Copiato negli appunti, con {n} valori veri rimessi. La persona può incollarlo dove le serve."

    # ------------------------------------------------------------ JSON-RPC

    def gestisci(self, msg: dict) -> dict | None:
        metodo, ident = msg.get("method"), msg.get("id")
        if ident is None:  # notifica: nessuna risposta
            return None
        try:
            if metodo == "initialize":
                chiesta = (msg.get("params") or {}).get("protocolVersion")
                threading.Thread(target=self.carica, daemon=True).start()  # il modello si scalda mentre si parla
                return {"jsonrpc": "2.0", "id": ident, "result": {
                    "protocolVersion": chiesta if chiesta in VERSIONI_PROTOCOLLO else VERSIONI_PROTOCOLLO[0],
                    "capabilities": {"tools": {}}, "serverInfo": {"name": "riserbo", "version": __version__},
                    "instructions": ISTRUZIONI}}
            if metodo == "ping":
                return {"jsonrpc": "2.0", "id": ident, "result": {}}
            if metodo == "tools/list":
                return {"jsonrpc": "2.0", "id": ident, "result": {"tools": STRUMENTI}}
            if metodo == "tools/call":
                p = msg.get("params") or {}
                nome, arg = p.get("name"), p.get("arguments") or {}
                if nome not in {s["name"] for s in STRUMENTI}:
                    return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32602, "message": f"Strumento sconosciuto: {nome}"}}
                try:
                    with self.lock:
                        if time.time() - self.ultimo_uso > INATTIVITA:
                            self.nuova_tabella()
                        self.ultimo_uso = time.time()
                        testo, errore = getattr(self, nome)(**{k: v for k, v in arg.items() if isinstance(v, str)}), False
                except (ValueError, OSError, TypeError) as e:
                    testo, errore = str(e), True
                return {"jsonrpc": "2.0", "id": ident, "result": {"content": [{"type": "text", "text": testo}], "isError": errore}}
            return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32601, "message": f"Metodo non previsto: {metodo}"}}
        except Exception as e:  # pragma: no cover
            return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32603, "message": str(e)}}

    def servi(self, ingresso, uscita) -> None:
        for riga in ingresso:
            riga = riga.strip()
            if not riga:
                continue
            try:
                msg = json.loads(riga)
            except ValueError:
                risposta = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "JSON non valido"}}
            else:
                risposta = self.gestisci(msg) if isinstance(msg, dict) else None
            if risposta is not None:
                uscita.write(json.dumps(risposta, ensure_ascii=False) + "\n")
                uscita.flush()


def main_mcp(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="riserbo mcp")
    ap.add_argument("--cartella", action="append", default=[], help="cartella che l'agente può leggere (si ripete)")
    a = ap.parse_args(argv)
    cartelle = [Path(c).expanduser() for c in a.cartella] or cartelle_predefinite()
    cartelle = [c for c in cartelle if c.is_dir()]
    if not cartelle:
        print("Nessuna cartella permessa esistente: indicane una con --cartella.", file=sys.stderr)
        return 2
    # stdout è del protocollo: tutto il resto (avvisi delle librerie, stampe) va su stderr
    uscita = open(sys.stdout.fileno(), "w", encoding="utf-8", closefd=False, newline="\n")
    sys.stdout = sys.stderr
    ingresso = open(sys.stdin.fileno(), "r", encoding="utf-8", closefd=False)
    ServerMCP(cartelle).servi(ingresso, uscita)
    return 0


# ---------------------------------------------------------------- configurazione di Claude Desktop

VOCE, VECCHIA_VOCE = "riserbo", "segnaposto"  # il nome del server MCP in Claude Desktop, ora e quando l'app si chiamava segnaposto


def migra_claude_desktop() -> bool:
    """Se Claude Desktop usa ancora la voce «segnaposto» (o un'altra copia dell'app), la riscrive per questa. True se ha scritto."""
    st = stato_claude_desktop()
    if st["collegato"] and not st["aggiornato"] and getattr(sys, "frozen", False) and st["cartelle"]:
        collega_claude_desktop(st["cartelle"])
        return True
    return False


def file_config_claude() -> list[Path]:
    """Dove Claude Desktop legge i server MCP. Su Windows l'app dello Store usa una cartella sua."""
    if sys.platform == "darwin":
        return [Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"]
    if os.name == "nt":
        appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        locale = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        posti = [appdata / "Claude" / "claude_desktop_config.json"]
        posti += [p / "LocalCache" / "Roaming" / "Claude" / "claude_desktop_config.json"
                  for p in (locale / "Packages").glob("Claude_*") if p.is_dir()]
        return posti
    return [Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "Claude" / "claude_desktop_config.json"]


def comando_mcp() -> tuple[str, list[str]]:
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable)
        if os.name == "nt":  # la versione con console: Claude Desktop parla con lei su stdin/stdout
            exe = exe.with_name("riserbo-mcp.exe")
        return str(exe), ["mcp"]
    return sys.executable, ["-m", "riserbo", "mcp"]


def collega_claude_desktop(cartelle: list[str]) -> list[str]:
    """Aggiunge (o aggiorna) Riserbo tra i server MCP di Claude Desktop. Copia di sicurezza prima di scrivere."""
    comando, argomenti = comando_mcp()
    for c in cartelle:
        argomenti += ["--cartella", c]
    scritti = []
    posti = file_config_claude()
    esistenti = [p for p in posti if p.parent.is_dir()] or posti[:1]
    for p in esistenti:
        conf = {}
        if p.exists():
            testo = p.read_text(encoding="utf-8")
            conf = json.loads(testo) if testo.strip() else {}
            p.with_suffix(".json.prima-di-riserbo").write_text(testo, encoding="utf-8")
        server = conf.setdefault("mcpServers", {})
        server.pop(VECCHIA_VOCE, None)
        server[VOCE] = {"command": comando, "args": argomenti}
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(conf, indent=2, ensure_ascii=False), encoding="utf-8")
        scritti.append(str(p))
    return scritti


def scollega_claude_desktop() -> None:
    for p in file_config_claude():
        if p.exists():
            conf = json.loads(p.read_text(encoding="utf-8") or "{}")
            server = conf.get("mcpServers", {})
            if [server.pop(k, None) for k in (VOCE, VECCHIA_VOCE)] != [None, None]:
                p.write_text(json.dumps(conf, indent=2, ensure_ascii=False), encoding="utf-8")


def stato_claude_desktop() -> dict:
    for p in file_config_claude():
        try:
            server = json.loads(p.read_text(encoding="utf-8")).get("mcpServers", {})
            voce = server.get(VOCE) or server.get(VECCHIA_VOCE)
        except (OSError, ValueError):
            continue
        if voce:
            a = voce.get("args", [])
            cartelle = [a[i + 1] for i, x in enumerate(a[:-1]) if x == "--cartella"]
            return {"collegato": True, "cartelle": cartelle, "comando": voce.get("command"),
                    "aggiornato": voce.get("command") == comando_mcp()[0] and VOCE in server}
    return {"collegato": False, "cartelle": [], "installato": any(p.parent.is_dir() for p in file_config_claude())}
