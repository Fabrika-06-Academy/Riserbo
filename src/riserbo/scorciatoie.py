"""Appunti e scorciatoie da tastiera globali: Riserbo funziona da qualunque programma.

Il flusso: selezioni il testo in Outlook (o nel gestionale, o in WhatsApp Web), copi, premi la scorciatoia e negli
appunti c'è la versione con i segnaposto; incolli nella chat. Copi la risposta, premi l'altra scorciatoia e negli
appunti tornano i nomi veri.

  Mac:      ⌃⌥P proteggi, ⌃⌥R rimetti i nomi   (hot key di Carbon: nessun permesso di Accessibilità richiesto)
  Windows:  Ctrl+Alt+P, Ctrl+Alt+R              (RegisterHotKey: nessun permesso richiesto)

Tutto con le librerie di sistema (ctypes e AppKit, già presenti con pywebview): niente dipendenze in più.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import threading
from typing import Callable

MAC = sys.platform == "darwin"
WIN = os.name == "nt"

DESCRIZIONE = {
    "proteggi": "⌃⌥P" if MAC else "Ctrl+Alt+P",
    "ripristina": "⌃⌥R" if MAC else "Ctrl+Alt+R",
}


class AppuntiNonDisponibili(RuntimeError):
    pass


# ---------------------------------------------------------------- appunti

def leggi_appunti() -> str:
    if MAC:
        from AppKit import NSPasteboard, NSPasteboardTypeString
        return str(NSPasteboard.generalPasteboard().stringForType_(NSPasteboardTypeString) or "")
    if WIN:
        return _win_leggi()
    raise AppuntiNonDisponibili("Gli appunti di sistema si usano dall'app per Mac e Windows.")


def scrivi_appunti(testo: str) -> None:
    if MAC:
        from AppKit import NSPasteboard, NSPasteboardTypeString
        pb = NSPasteboard.generalPasteboard()
        pb.clearContents()
        pb.setString_forType_(testo, NSPasteboardTypeString)
        return
    if WIN:
        return _win_scrivi(testo)
    raise AppuntiNonDisponibili("Gli appunti di sistema si usano dall'app per Mac e Windows.")


def _win_api():
    from ctypes import wintypes
    u = ctypes.WinDLL("user32", use_last_error=True)
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    u.OpenClipboard.argtypes = [wintypes.HWND]
    u.OpenClipboard.restype = wintypes.BOOL
    u.GetClipboardData.argtypes = [wintypes.UINT]
    u.GetClipboardData.restype = wintypes.HANDLE
    u.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    u.SetClipboardData.restype = wintypes.HANDLE
    u.EmptyClipboard.restype = wintypes.BOOL
    u.CloseClipboard.restype = wintypes.BOOL
    k.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    k.GlobalAlloc.restype = wintypes.HGLOBAL
    k.GlobalLock.argtypes = [wintypes.HGLOBAL]
    k.GlobalLock.restype = ctypes.c_void_p
    k.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    return u, k


def _win_apri(u) -> None:
    import time
    for _ in range(20):  # un altro programma può tenere gli appunti aperti per un attimo
        if u.OpenClipboard(None):
            return
        time.sleep(0.03)
    raise AppuntiNonDisponibili("Gli appunti sono occupati da un altro programma: riprova.")


def _win_leggi() -> str:
    u, k = _win_api()
    _win_apri(u)
    try:
        h = u.GetClipboardData(13)  # CF_UNICODETEXT
        if not h:
            return ""
        p = k.GlobalLock(h)
        try:
            return ctypes.wstring_at(p) if p else ""
        finally:
            k.GlobalUnlock(h)
    finally:
        u.CloseClipboard()


def _win_scrivi(testo: str) -> None:
    u, k = _win_api()
    dati = (testo + "\0").encode("utf-16-le")
    h = k.GlobalAlloc(0x0002, len(dati))  # GMEM_MOVEABLE
    p = k.GlobalLock(h)
    ctypes.memmove(p, dati, len(dati))
    k.GlobalUnlock(h)
    _win_apri(u)
    try:
        u.EmptyClipboard()
        if not u.SetClipboardData(13, h):
            raise AppuntiNonDisponibili("Non riesco a scrivere negli appunti.")
    finally:
        u.CloseClipboard()


# ---------------------------------------------------------------- notifiche

def notifica(titolo: str, testo: str, finestra_notifica: Callable[[str, str], None] | None = None) -> None:
    """Una conferma che non ruba il fuoco al programma in cui si sta lavorando."""
    try:
        if MAC:
            def q(s: str) -> str:
                return s.replace("\\", "\\\\").replace('"', '\\"')
            subprocess.Popen(["osascript", "-e", f'display notification "{q(testo)}" with title "{q(titolo)}" sound name "Tink"'],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif finestra_notifica:
            finestra_notifica(titolo, testo)
        elif WIN:
            ctypes.windll.user32.MessageBeep(0x40)
    except Exception:
        pass


# ---------------------------------------------------------------- scorciatoie globali

class Scorciatoie:
    """Registra ⌃⌥P / ⌃⌥R (Mac) o Ctrl+Alt+P / Ctrl+Alt+R (Windows). `azioni`: nome -> funzione senza argomenti."""

    TASTI_MAC = {"proteggi": 0x23, "ripristina": 0x0F}  # kVK_ANSI_P, kVK_ANSI_R
    TASTI_WIN = {"proteggi": 0x50, "ripristina": 0x52}  # 'P', 'R'

    def __init__(self, azioni: dict[str, Callable[[], None]]) -> None:
        self.azioni = azioni
        self.per_id = {i + 1: nome for i, nome in enumerate(azioni)}
        self.attive: list[str] = []
        self.errore = ""
        self._rif: list = []  # riferimenti da tenere vivi (callback C, handle)

    def _esegui(self, ident: int) -> None:
        nome = self.per_id.get(int(ident))
        if nome:
            threading.Thread(target=self.azioni[nome], daemon=True).start()

    # -- Mac: Carbon RegisterEventHotKey, da chiamare sul thread principale (quello di Cocoa)
    def registra_mac(self) -> None:
        from ctypes import POINTER, CFUNCTYPE, Structure, byref, c_int32, c_uint32, c_void_p

        carbon = ctypes.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")

        class EventHotKeyID(Structure):
            _fields_ = [("signature", c_uint32), ("id", c_uint32)]

        class EventTypeSpec(Structure):
            _fields_ = [("eventClass", c_uint32), ("eventKind", c_uint32)]

        def fourcc(s: str) -> int:
            return int.from_bytes(s.encode("ascii"), "big")

        GESTORE = CFUNCTYPE(c_int32, c_void_p, c_void_p, c_void_p)
        carbon.GetEventDispatcherTarget.restype = c_void_p
        carbon.InstallEventHandler.argtypes = [c_void_p, GESTORE, c_uint32, POINTER(EventTypeSpec), c_void_p, POINTER(c_void_p)]
        carbon.InstallEventHandler.restype = c_int32
        carbon.RegisterEventHotKey.argtypes = [c_uint32, c_uint32, EventHotKeyID, c_void_p, c_uint32, POINTER(c_void_p)]
        carbon.RegisterEventHotKey.restype = c_int32
        carbon.GetEventParameter.argtypes = [c_void_p, c_uint32, c_uint32, c_void_p, c_uint32, c_void_p, c_void_p]
        carbon.GetEventParameter.restype = c_int32

        def gestore(_chiamata, evento, _dati):
            hk = EventHotKeyID()
            if carbon.GetEventParameter(evento, fourcc("----"), fourcc("hkid"), None, ctypes.sizeof(hk), None, byref(hk)) == 0:
                self._esegui(hk.id)
            return 0

        cb = GESTORE(gestore)
        destinatario = carbon.GetEventDispatcherTarget()
        spec = EventTypeSpec(fourcc("keyb"), 5)  # kEventClassKeyboard, kEventHotKeyPressed
        rif_gestore = c_void_p()
        err = carbon.InstallEventHandler(destinatario, cb, 1, byref(spec), None, byref(rif_gestore))
        if err:
            raise OSError(f"InstallEventHandler: {err}")
        self._rif += [cb, spec, rif_gestore, carbon]
        controllo, opzione = 0x1000, 0x0800  # controlKey, optionKey
        for ident, nome in self.per_id.items():
            rif = c_void_p()
            err = carbon.RegisterEventHotKey(self.TASTI_MAC[nome], controllo | opzione, EventHotKeyID(fourcc("sgnp"), ident),
                                             destinatario, 0, byref(rif))
            if err == 0:
                self.attive.append(nome)
                self._rif.append(rif)
            else:
                self.errore = f"{DESCRIZIONE[nome]} è già usata da un altro programma"

    # -- Windows: RegisterHotKey su un thread con il suo ciclo di messaggi
    def registra_win(self) -> None:
        from ctypes import byref, wintypes
        pronto = threading.Event()

        def ciclo() -> None:
            u = ctypes.WinDLL("user32", use_last_error=True)
            u.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
            u.RegisterHotKey.restype = wintypes.BOOL
            for ident, nome in self.per_id.items():
                if u.RegisterHotKey(None, ident, 0x0002 | 0x0001 | 0x4000, self.TASTI_WIN[nome]):  # CTRL|ALT|NOREPEAT
                    self.attive.append(nome)
                else:
                    self.errore = f"{DESCRIZIONE[nome]} è già usata da un altro programma"
            pronto.set()
            msg = wintypes.MSG()
            while u.GetMessageW(byref(msg), None, 0, 0) > 0:
                if msg.message == 0x0312:  # WM_HOTKEY
                    self._esegui(msg.wParam)

        threading.Thread(target=ciclo, daemon=True, name="scorciatoie").start()
        pronto.wait(3)

    def registra(self) -> None:
        try:
            if MAC:
                from PyObjCTools import AppHelper
                fatto = threading.Event()

                def sul_principale() -> None:
                    try:
                        self.registra_mac()
                    except Exception as e:
                        self.errore = str(e)
                    fatto.set()

                AppHelper.callAfter(sul_principale)
                fatto.wait(5)
            elif WIN:
                self.registra_win()
            else:
                self.errore = "scorciatoie globali disponibili su Mac e Windows"
        except Exception as e:  # non deve mai impedire all'app di funzionare
            self.errore = str(e)
