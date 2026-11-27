# PyInstaller: pyinstaller packaging/riserbo.spec  (da lanciare nella cartella packaging)
import sys
from PyInstaller.utils.hooks import collect_all, collect_data_files, copy_metadata

VERSIONE = "0.11.0"
datas, binaries, hidden = [], [], []
pacchetti = ["spacy", "presidio_analyzer", "tokenizers", "thinc", "phonenumbers", "spacy_legacy", "spacy_loggers",
             "docx", "pypdfium2", "pypdfium2_raw", "openpyxl", "olefile", "webview",
             "rapidocr", "onnxruntime", "cv2", "shapely", "pyclipper", "omegaconf", "antlr4", "certifi"]
if sys.platform == "win32":
    pacchetti += ["clr_loader", "pythonnet"]
for pkg in pacchetti:
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hidden += h
    except Exception:
        pass
datas += collect_data_files("tldextract") + collect_data_files("riserbo")
for pkg in ("spacy", "presidio_analyzer", "tokenizers", "thinc", "riserbo", "pywebview", "rapidocr", "onnxruntime"):
    try:
        datas += copy_metadata(pkg)
    except Exception:
        pass

a = Analysis(["avvia.py"], pathex=["../src"], binaries=binaries, datas=datas, hiddenimports=hidden,
             excludes=["torch", "paddle", "openvino", "tensorrt", "MNN", "tkinter", "matplotlib", "IPython", "pytest", "PyQt5", "PyQt6", "PySide2", "PySide6", "gi"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="riserbo", console=(sys.platform.startswith("linux")), upx=False,
          icon="icona.png")
# Windows: l'app non ha console, quindi niente stdin/stdout. Claude Desktop avvia il server MCP da questa copia con console.
extra = [EXE(pyz, a.scripts, [], exclude_binaries=True, name="riserbo-mcp", console=True, upx=False, icon="icona.png")] \
    if sys.platform == "win32" else []
coll = COLLECT(exe, *extra, a.binaries, a.datas, name="riserbo", upx=False)
if sys.platform == "darwin":
    app = BUNDLE(coll, name="Riserbo.app", icon="icona.png", bundle_identifier="com.fabrika06.riserbo",
                 info_plist={"CFBundleName": "Riserbo", "CFBundleDisplayName": "Riserbo",
                             "CFBundleShortVersionString": VERSIONE, "CFBundleVersion": VERSIONE,
                             "NSHighResolutionCapable": True, "LSUIElement": False,
                             "NSHumanReadableCopyright": "MIT · Fabrika 06 Academy"})
