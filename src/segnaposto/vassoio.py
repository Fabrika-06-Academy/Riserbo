"""L'icona vicino all'orologio: segnaposto resta attivo anche a finestra chiusa.

  Mac:      icona nella barra dei menu in alto (AppKit, già presente con pywebview); a finestra chiusa sparisce dal Dock.
  Windows:  icona nell'area di notifica in basso a destra (WinForms NotifyIcon via pythonnet, già presente con pywebview).

Dal menu dell'icona: aprire la finestra, proteggere o ripristinare gli appunti, iniziare una nuova pratica,
scegliere se aprire segnaposto all'accensione, uscire davvero.
"""

from __future__ import annotations

import json
import os
import plistlib
import sys
import threading
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

MAC = sys.platform == "darwin"
WIN = os.name == "nt"
QUI = Path(__file__).parent
ETICHETTA_MAC = "com.fabrika06.segnaposto"
ARGOMENTO_SOTTOFONDO = "--in-sottofondo"


@dataclass
class Voce:
    titolo: str
    azione: Callable[[], None] | None = None     # eseguita su un thread a parte
    spunta: Callable[[], bool] | None = None     # voce con il segno di spunta: stato attuale
    cambia: Callable[[bool], None] | None = None  # ... e cosa fare quando la si clicca
    tasto: str = ""                              # "proteggi" / "ripristina": mostra la scorciatoia accanto


def _lancia(f: Callable[[], None]) -> None:
    threading.Thread(target=f, daemon=True).start()


# ---------------------------------------------------------------- avvio all'accensione

def avvio_possibile() -> bool:
    """Solo dall'app impacchettata: dal terminale non c'è un programma stabile da far partire."""
    return bool(getattr(sys, "frozen", False)) and (MAC or WIN)


def _plist_mac() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{ETICHETTA_MAC}.plist"


def avvio_automatico() -> bool:
    try:
        if MAC:
            return _plist_mac().exists()
        if WIN:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
                winreg.QueryValueEx(k, "segnaposto")
                return True
    except OSError:
        pass
    return False


def imposta_avvio(attivo: bool) -> None:
    if MAC:
        p = _plist_mac()
        if attivo:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(plistlib.dumps({"Label": ETICHETTA_MAC, "ProgramArguments": [sys.executable, ARGOMENTO_SOTTOFONDO],
                                          "RunAtLoad": True, "ProcessType": "Interactive",
                                          "LimitLoadToSessionType": "Aqua"}))
        elif p.exists():
            p.unlink()
    elif WIN:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                            winreg.KEY_SET_VALUE) as k:
            if attivo:
                winreg.SetValueEx(k, "segnaposto", 0, winreg.REG_SZ, f'"{sys.executable}" {ARGOMENTO_SOTTOFONDO}')
            else:
                try:
                    winreg.DeleteValue(k, "segnaposto")
                except FileNotFoundError:
                    pass


# ---------------------------------------------------------------- Mac

_GESTORI: dict[int, Callable] = {}
_CLASSE = None


def _classe_bersaglio():
    """La classe Objective-C che riceve i clic sul menu (si può definire una sola volta per processo)."""
    global _CLASSE
    if _CLASSE is None:
        from Foundation import NSObject

        class SegnapostoBersaglioVassoio(NSObject):
            def esegui_(self, mittente):
                f = _GESTORI.get(int(mittente.tag()))
                if f:
                    f(mittente)

        _CLASSE = SegnapostoBersaglioVassoio
    return _CLASSE


def mostra_nel_dock(visibile: bool) -> None:
    """Mac: a finestra chiusa segnaposto vive solo nella barra dei menu, senza icona nel Dock."""
    if not MAC:
        return
    try:
        from AppKit import NSApplication
        from PyObjCTools import AppHelper
        AppHelper.callAfter(NSApplication.sharedApplication().setActivationPolicy_, 0 if visibile else 1)
    except Exception:
        pass


class Vassoio:
    def __init__(self, voci: list[Voce | None], apri: Callable[[], None]) -> None:
        self.voci, self.apri = voci, apri
        self.attivo = False
        self.errore = ""
        self._rif: list = []
        self._ni = None

    # -- Mac: da chiamare sul thread principale
    def _mac(self) -> None:
        from AppKit import NSImage, NSMenu, NSMenuItem, NSStatusBar, NSVariableStatusItemLength
        from .scorciatoie import Scorciatoie
        bersaglio = _classe_bersaglio().alloc().init()
        menu = NSMenu.alloc().init()
        menu.setAutoenablesItems_(False)
        for i, voce in enumerate(self.voci):
            if voce is None:
                menu.addItem_(NSMenuItem.separatorItem())
                continue
            it = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(voce.titolo, "esegui:", "")
            it.setTarget_(bersaglio)
            it.setTag_(1000 + i)
            if voce.tasto:  # solo per mostrarla: la scorciatoia vera è quella globale
                it.setKeyEquivalent_({0x23: "p", 0x0F: "r"}[Scorciatoie.TASTI_MAC[voce.tasto]])
                it.setKeyEquivalentModifierMask_((1 << 18) | (1 << 19))  # Control | Option
            if voce.spunta:
                it.setState_(1 if voce.spunta() else 0)
            menu.addItem_(it)
            _GESTORI[1000 + i] = self._gestore_mac(voce)
        item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
        img = NSImage.alloc().initWithContentsOfFile_(str(QUI / "vassoio-mac.png"))
        img.setSize_((18, 18))
        img.setTemplate_(True)  # bianca o nera secondo il tema della barra
        item.button().setImage_(img)
        item.button().setToolTip_("segnaposto")
        item.setMenu_(menu)
        self._rif += [bersaglio, menu, item, img]
        self.attivo = True

    @staticmethod
    def _gestore_mac(voce: Voce) -> Callable:
        def gestore(mittente) -> None:
            if voce.cambia and voce.spunta:
                nuovo = not voce.spunta()
                try:
                    voce.cambia(nuovo)
                except Exception:
                    pass
                mittente.setState_(1 if voce.spunta() else 0)
            elif voce.azione:
                _lancia(voce.azione)
        return gestore

    # -- Windows: un thread STA con il suo ciclo di messaggi
    def _win(self) -> None:
        import clr  # pythonnet, già usato da pywebview
        clr.AddReference("System.Windows.Forms")
        clr.AddReference("System.Drawing")
        from System.Drawing import Bitmap, Icon
        from System.Threading import ApartmentState, Thread, ThreadStart
        from System.Windows.Forms import (Application, ContextMenuStrip, MouseButtons, NotifyIcon, ToolStripMenuItem,
                                          ToolStripSeparator)
        from .scorciatoie import DESCRIZIONE
        pronto = threading.Event()

        def corpo() -> None:
            try:
                ni = NotifyIcon()
                ni.Icon = Icon.FromHandle(Bitmap(str(QUI / "vassoio-win.png")).GetHicon())
                ni.Text = "segnaposto"
                menu = ContextMenuStrip()
                for voce in self.voci:
                    if voce is None:
                        menu.Items.Add(ToolStripSeparator())
                        continue
                    it = ToolStripMenuItem(voce.titolo)
                    if voce.tasto:
                        it.ShortcutKeyDisplayString = DESCRIZIONE[voce.tasto]
                        it.ShowShortcutKeys = True
                    if voce.spunta:
                        it.Checked = bool(voce.spunta())
                    it.Click += self._gestore_win(voce, it)
                    menu.Items.Add(it)
                ni.ContextMenuStrip = menu

                def clic(_s, e) -> None:
                    if e.Button == MouseButtons.Left:
                        _lancia(self.apri)

                ni.MouseClick += clic
                ni.Visible = True
                self._ni = ni
                self._rif += [menu, clic]
                self.attivo = True
            except Exception as e:
                self.errore = str(e)
            pronto.set()
            if self.attivo:
                Application.Run()

        t = Thread(ThreadStart(corpo))
        t.SetApartmentState(ApartmentState.STA)
        t.IsBackground = True
        t.Start()
        self._rif.append(t)
        pronto.wait(5)

    @staticmethod
    def _gestore_win(voce: Voce, it) -> Callable:
        def gestore(_s, _e) -> None:
            if voce.cambia and voce.spunta:
                try:
                    voce.cambia(not voce.spunta())
                except Exception:
                    pass
                it.Checked = bool(voce.spunta())
            elif voce.azione:
                _lancia(voce.azione)
        return gestore

    # -- per tutti
    def mostra(self) -> None:
        """Mac: va chiamata sul thread principale. Non solleva mai: senza icona l'app funziona come prima."""
        try:
            if MAC:
                self._mac()
            elif WIN:
                self._win()
        except Exception as e:
            self.errore = str(e)

    def avviso(self, titolo: str, testo: str) -> bool:
        """Windows: la notifica di sistema che parte dall'icona. False se non è disponibile."""
        if not (WIN and self._ni is not None):
            return False
        try:
            from System.Windows.Forms import ToolTipIcon
            self._ni.ShowBalloonTip(3000, titolo, testo, ToolTipIcon.Info)
            return True
        except Exception:
            return False

    def togli(self) -> None:
        """Windows: senza questo l'icona resta lì finché non ci passi sopra il mouse."""
        if self._ni is not None:
            try:
                self._ni.Visible = False
                self._ni.Dispose()
            except Exception:
                pass
            self._ni = None


def al_riaprire_mac(apri: Callable[[], None]) -> None:
    """Mac: doppio clic sull'app già aperta (solo nella barra dei menu) → riapre la finestra."""
    try:
        import objc
        from webview.platforms.cocoa import BrowserView

        def riapri(self, app, visibili):
            if not visibili:
                _lancia(apri)
            return True

        sel = objc.selector(riapri, selector=b"applicationShouldHandleReopen:hasVisibleWindows:", signature=b"Z@:@Z")
        objc.classAddMethods(BrowserView.AppDelegate, [sel])
    except Exception:
        pass


# ---------------------------------------------------------------- una sola istanza

def _file_istanza() -> Path:
    from .ner import cartella_cache
    return cartella_cache().parent / "istanza.json"


def segna_istanza(porta: int, chiave: str) -> None:
    try:
        f = _file_istanza()
        f.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # la chiave è solo per te
        with os.fdopen(fd, "w") as h:
            json.dump({"porta": porta, "chiave": chiave}, h)
    except OSError:
        pass


def togli_istanza(chiave: str) -> None:
    try:
        f = _file_istanza()
        if json.loads(f.read_text()).get("chiave") == chiave:
            f.unlink()
    except (OSError, ValueError):
        pass


def risveglia_istanza() -> bool:
    """True se segnaposto è già aperto: gli chiede di mostrare la finestra."""
    try:
        d = json.loads(_file_istanza().read_text())
        req = urllib.request.Request(f"http://127.0.0.1:{int(d['porta'])}/api/mostra", data=b"{}", method="POST",
                                     headers={"X-Chiave": str(d["chiave"]), "Content-Type": "application/json"})
        senza_proxy = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # i proxy aziendali non vedono 127.0.0.1
        with senza_proxy.open(req, timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def sta_uscendo_mac() -> bool:
    """⌘Q (o «Esci» dal Dock) passa per applicationShouldTerminate_: lì la finestra si chiude davvero."""
    f = sys._getframe()
    while f is not None:
        if f.f_code.co_name == "applicationShouldTerminate_":
            return True
        f = f.f_back
    return False
