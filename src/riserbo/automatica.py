"""Modalità automatica per le app di AI sul desktop (ChatGPT, Claude, Copilot, Perplexity).

Le estensioni non entrano nelle app desktop. Qui Riserbo guarda solo due cose: quale app è in primo piano e gli appunti.

- Quando passi a un'app di AI e negli appunti c'è un testo con dati personali, lo sostituisce con la versione protetta:
  ⌘V / Ctrl+V incolla già i segnaposto. Una notifica lo conferma.
- Quando esci dall'app:
  - se hai copiato qualcosa lì dentro (la risposta), negli appunti tornano i nomi veri;
  - se non hai copiato niente, negli appunti torna il testo che c'era prima, con i dati veri.

Vale per quello che incolli, non per quello che scrivi a mano nell'app. Niente permessi speciali: su Mac NSWorkspace e
NSPasteboard, su Windows GetForegroundWindow e GetClipboardSequenceNumber.
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
from collections import deque
from typing import Callable

from .motore import SEGNAPOSTO

MAC = sys.platform == "darwin"
WIN = os.name == "nt"

# Mac: identificativo del pacchetto o nome; Windows: nome dell'eseguibile (minuscolo, senza .exe)
APP_AI = {
    "ChatGPT": {"com.openai.chat", "com.openai.codex", "chatgpt"},  # l'app recente di ChatGPT per Mac è com.openai.codex
    "Claude": {"com.anthropic.claudefordesktop", "claude"},
    "Copilot": {"com.microsoft.copilot-mac", "com.microsoft.copilot", "copilot", "microsoft.copilot"},
    "Perplexity": {"ai.perplexity.mac", "perplexity"},
}


def riconosci(identificativi: tuple[str, ...]) -> str | None:
    """Da quello che dice il sistema dell'app in primo piano al nome dell'app di AI (o None)."""
    for ident in identificativi:
        k = (ident or "").lower().removesuffix(".exe")
        for nome, chiavi in APP_AI.items():
            if k in chiavi:
                return nome
    return None


ULTIMA_VISTA: dict = {"app": "", "quando": 0.0}  # per la Guida: quale app il sistema dice in primo piano


def _mac_primo_piano() -> tuple[str, str]:
    from AppKit import NSWorkspace
    a = NSWorkspace.sharedWorkspace().frontmostApplication()
    return (str(a.bundleIdentifier() or ""), str(a.localizedName() or "")) if a else ("", "")


def _sul_principale(f):
    """Su Mac l'app in primo piano è aggiornata sul thread principale: chiesta da un thread in sottofondo può essere vecchia."""
    if threading.current_thread() is threading.main_thread():
        return f()
    try:
        from PyObjCTools import AppHelper
        esito, fatto = [], threading.Event()

        def sul_main() -> None:
            try:
                esito.append(f())
            finally:
                fatto.set()

        AppHelper.callAfter(sul_main)
        if fatto.wait(1.0) and esito:
            return esito[0]
    except Exception:
        pass
    return f()


def app_in_primo_piano() -> str | None:
    try:
        if MAC:
            ident = _sul_principale(_mac_primo_piano)
            ULTIMA_VISTA.update(app=" · ".join(x for x in ident if x), quando=time.time())
            return riconosci(ident)
        if WIN:
            from ctypes import wintypes
            u, k = ctypes.windll.user32, ctypes.windll.kernel32
            hwnd = u.GetForegroundWindow()
            pid = wintypes.DWORD()
            u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            h = k.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not h:
                return None
            try:
                buf, n = ctypes.create_unicode_buffer(1024), wintypes.DWORD(1024)
                if not k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                    return None
                ULTIMA_VISTA.update(app=os.path.basename(buf.value), quando=time.time())
                return riconosci((os.path.basename(buf.value),))
            finally:
                k.CloseHandle(h)
    except Exception:
        return None
    return None


def contatore_appunti() -> int:
    """Cresce a ogni copia: serve a capire se dentro l'app hai copiato qualcosa."""
    try:
        if MAC:
            from AppKit import NSPasteboard
            return int(NSPasteboard.generalPasteboard().changeCount())
        if WIN:
            return int(ctypes.windll.user32.GetClipboardSequenceNumber())
    except Exception:
        pass
    return -1


class Guardiano:
    """`proteggi(testo) -> (testo protetto, quanti dati)`, `rimetti(testo) -> (testo vero, quanti valori)`."""

    def __init__(self, proteggi: Callable[[str], tuple[str, int]], rimetti: Callable[[str], tuple[str, int]],
                 avvisa: Callable[[str, str], None], app_attiva: Callable[[], str | None] = app_in_primo_piano,
                 leggi: Callable[[], str] | None = None, scrivi: Callable[[str], None] | None = None,
                 contatore: Callable[[], int] = contatore_appunti, intervallo: float = 0.2,
                 in_pausa: Callable[[], bool] = lambda: False) -> None:
        if leggi is None or scrivi is None:
            from .scorciatoie import leggi_appunti, scrivi_appunti
            leggi, scrivi = leggi or leggi_appunti, scrivi or scrivi_appunti
        self.proteggi, self.rimetti, self.avvisa = proteggi, rimetti, avvisa
        self.app_attiva, self.leggi, self.scrivi, self.contatore = app_attiva, leggi, scrivi, contatore
        self.intervallo, self.in_pausa = intervallo, in_pausa
        self.dentro: str | None = None
        self.originale: str | None = None   # il testo vero che c'era negli appunti entrando
        self.scritto: str | None = None     # il testo protetto che abbiamo messo noi
        self.contatore_scritto = -2
        self.visto = -3                     # il contatore degli appunti al passo precedente
        self.attivo = False
        self.ultimo = ""                    # cosa è successo l'ultima volta (per la finestra)
        self.registro: deque[str] = deque(maxlen=10)  # le ultime cose fatte, con l'ora (per la Guida)
        self._ferma = threading.Event()

    def _nota(self, msg: str) -> None:
        self.ultimo = msg
        self.registro.appendleft(time.strftime("%H:%M:%S") + " · " + msg)

    # -- un passo: si chiama di continuo (thread) o a mano (prove)
    def passo(self) -> None:
        app = self.app_attiva()
        if self.in_pausa():  # in pausa: si segue solo dove sei, senza toccare gli appunti
            self.dentro, self.originale, self.scritto = app, None, None
            self.visto = self.contatore()
            return
        if app and not self.dentro:
            self.dentro = app
            self._entrando(app)
        elif not app and self.dentro:
            uscita, self.dentro = self.dentro, None
            self._uscendo(uscita)
        elif app and self.dentro and app != self.dentro:  # da un'app di AI all'altra
            self._uscendo(self.dentro)
            self.dentro = app
            self._entrando(app)
        elif app and self.dentro:
            c = self.contatore()
            if c >= 0 and self.visto >= 0 and c != self.visto and c != self.contatore_scritto:
                self._proteggi_appunti(app, "copiato in")  # qualcosa è arrivato negli appunti mentre sei nell'app
        self.visto = self.contatore()

    def _entrando(self, app: str) -> None:
        self.originale = self.scritto = None
        self._proteggi_appunti(app, "entrato in")

    def _proteggi_appunti(self, app: str, come: str) -> None:
        try:
            testo = self.leggi()
        except Exception as e:
            self._nota(f"{come} {app}: appunti non leggibili ({e})")
            return
        if not testo.strip():
            self._nota(f"{come} {app}: appunti vuoti")
            return
        protetto, n = self.proteggi(testo)
        if n < 0:
            self._nota(f"{come} {app}: il riconoscitore non era ancora pronto")
            self.avvisa("Riserbo · aspetta un attimo", "Sto ancora caricando il riconoscitore italiano: gli appunti NON sono "
                        "protetti. Fra qualche secondo ricopia il testo.")
            return
        if not n:
            self._nota(f"{come} {app}: nessun dato personale negli appunti")
            return
        self.originale = testo  # uscendo senza copiare altro, negli appunti torna questo
        self.scrivi(protetto)
        self.scritto, self.contatore_scritto = protetto, self.contatore()
        self._nota(f"{come} {app}: {n} dati sostituiti negli appunti")
        self.avvisa(f"Riserbo · {app}", (f"{n} dati sostituiti" if n != 1 else "1 dato sostituito")
                    + " negli appunti: incolla pure. Uscendo dall'app rimetto i nomi veri.")

    def _uscendo(self, app: str) -> None:
        try:
            testo = self.leggi()
        except Exception:
            return
        non_toccati = self.scritto is not None and (
            self.contatore() == self.contatore_scritto if self.contatore_scritto >= 0 else testo == self.scritto)
        if non_toccati and self.originale is not None:
            self.scrivi(self.originale)  # non hai copiato niente lì dentro: torna il tuo testo
            self._nota(f"uscito da {app}: negli appunti è tornato il tuo testo")
        elif SEGNAPOSTO.search(testo):
            vero, n = self.rimetti(testo)
            if n:
                self.scrivi(vero)
                self._nota(f"uscito da {app}: {n} nomi veri rimessi negli appunti")
                self.avvisa("Riserbo · nomi veri", (f"{n} valori rimessi" if n != 1 else "1 valore rimesso")
                            + " negli appunti: incolla dove ti serve.")
            else:
                self._nota(f"uscito da {app}: segnaposto non di questa pratica, appunti lasciati com'erano")
        else:
            self._nota(f"uscito da {app}: negli appunti non ci sono segnaposto")
        self.originale = self.scritto = None

    # -- il thread
    def avvia(self) -> None:
        if self.attivo or not (MAC or WIN):
            return
        self.attivo = True
        self._ferma.clear()

        def ciclo() -> None:
            while not self._ferma.wait(self.intervallo):
                try:
                    self.passo()
                except Exception:
                    pass

        threading.Thread(target=ciclo, daemon=True, name="automatica").start()

    def ferma(self) -> None:
        self._ferma.set()
        self.attivo = False
