# PyInstaller: pyinstaller packaging/segnaposto.spec  (da lanciare nella radice del progetto)
import sys
from PyInstaller.utils.hooks import collect_all, collect_data_files, copy_metadata

datas, binaries, hidden = [], [], []
for pkg in ("spacy", "it_core_news_sm", "presidio_analyzer", "thinc", "phonenumbers", "spacy_legacy", "spacy_loggers", "en_core_web_sm"):
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hidden += h
    except Exception:
        pass
datas += collect_data_files("tldextract") + collect_data_files("segnaposto")
for pkg in ("spacy", "it_core_news_sm", "presidio_analyzer", "thinc", "segnaposto"):
    try:
        datas += copy_metadata(pkg)
    except Exception:
        pass

a = Analysis(["avvia.py"], pathex=["../src"], binaries=binaries, datas=datas, hiddenimports=hidden,
             excludes=["tkinter", "matplotlib", "IPython", "pytest"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="segnaposto", console=(sys.platform.startswith("linux")), upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name="segnaposto", upx=False)
if sys.platform == "darwin":
    app = BUNDLE(coll, name="segnaposto.app", bundle_identifier="com.fabrika06.segnaposto",
                 info_plist={"CFBundleShortVersionString": "0.2.0", "NSHighResolutionCapable": True, "LSUIElement": False})
