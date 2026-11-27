"""Server MCP: il modello vede solo segnaposto (nomi dei file compresi); i valori veri restano sul computer."""

import json
import subprocess
import sys

import pytest

from riserbo.documenti import _scrivi_docx
from riserbo.server_mcp import ServerMCP, collega_claude_desktop, scollega_claude_desktop, stato_claude_desktop


@pytest.fixture()
def cartella(tmp_path):
    c = tmp_path / "Clienti"
    (c / "Pratiche").mkdir(parents=True)
    (c / "Contratto Mario_Rossi.docx").write_bytes(_scrivi_docx("Contratto tra Mario Rossi, CF RSSMRA80A01L840J, e la Bianchi Srl."))
    (c / "note.txt").write_text("Chiamare Giulia Verdi al 347 123 4567.", encoding="utf-8")
    (c / "note riunione.txt").write_text("Ordine del giorno.", encoding="utf-8")
    (c / "verbale assemblea.txt").write_text("Presenti tutti.", encoding="utf-8")
    (c / "foto.exe").write_bytes(b"x")
    (tmp_path / "segreto.txt").write_text("fuori dalle cartelle permesse")
    return c


def chiama(srv, nome, **arg):
    r = srv.gestisci({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": nome, "arguments": arg}})["result"]
    return r["content"][0]["text"], r["isError"]


def test_protocollo_e_documenti(sp, cartella):
    appunti = []
    srv = ServerMCP([cartella], motore=sp, scrivi_appunti=appunti.append)
    init = srv.gestisci({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
    assert init["result"]["protocolVersion"] == "2025-06-18" and init["result"]["serverInfo"]["name"] == "riserbo"
    assert srv.gestisci({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    nomi = {s["name"] for s in srv.gestisci({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]}
    assert nomi == {"elenca_documenti", "leggi_documento", "salva_documento", "copia_negli_appunti"}

    radici, _ = chiama(srv, "elenca_documenti")
    assert "c1" in radici
    elenco, _ = chiama(srv, "elenca_documenti", cartella="c1")
    assert "Mario" not in elenco and "Rossi" not in elenco and "[PERSONA_" in elenco  # anche i nomi dei file
    assert "foto.exe" not in elenco and "Pratiche/" in elenco
    assert "note riunione.txt" in elenco and "verbale assemblea.txt" in elenco  # parole comuni: restano
    d_contratto = next(r.split()[1] for r in elenco.splitlines() if ".docx" in r)

    testo, err = chiama(srv, "leggi_documento", documento=d_contratto)
    assert not err and "Mario Rossi" not in testo and "RSSMRA80A01L840J" not in testo and "[CODICE_FISCALE_1]" in testo
    persona = next(s for s in srv.tabella.valori if srv.tabella.valori[s] == "Mario Rossi")

    msg, err = chiama(srv, "salva_documento", testo=f"Gentile {persona},\nle confermiamo il contratto.", nome_file=f"Risposta {persona}.txt")
    assert not err and "Mario Rossi" not in msg and persona in msg
    salvato = cartella / "Risposta Mario Rossi.txt"
    assert salvato.read_text(encoding="utf-8") == "Gentile Mario Rossi,\nle confermiamo il contratto."
    msg, _ = chiama(srv, "salva_documento", testo="bis", nome_file=f"Risposta {persona}.txt")
    assert (cartella / "Risposta Mario Rossi (2).txt").exists() and "(2)" in msg and "Mario" not in msg

    msg, err = chiama(srv, "copia_negli_appunti", testo=f"Scrivo a {persona}.")
    assert not err and appunti == ["Scrivo a Mario Rossi."] and "Mario" not in msg


@pytest.mark.parametrize("rif", ["../segreto.txt", "/etc/passwd"])
def test_fuori_dalle_cartelle(sp, cartella, rif):
    srv = ServerMCP([cartella], motore=sp)
    testo, err = chiama(srv, "leggi_documento", documento=rif)
    assert err and "fuori dalle cartelle" in testo


def test_avvio_vero_su_stdio(cartella):
    """Come lo avvia Claude Desktop: una riga JSON per messaggio, su stdout solo il protocollo."""
    ingresso = "\n".join(json.dumps(m) for m in [
        {"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}]) + "\n"
    p = subprocess.run([sys.executable, "-m", "riserbo", "mcp", "--cartella", str(cartella)], input=ingresso,
                       capture_output=True, text=True, timeout=120)
    righe = [json.loads(r) for r in p.stdout.splitlines()]
    assert [r["id"] for r in righe] == [0, 1], p.stdout + p.stderr
    assert righe[0]["result"]["protocolVersion"] == "2025-03-26" and len(righe[1]["result"]["tools"]) == 4


def test_configurazione_claude_desktop(monkeypatch, tmp_path):
    from riserbo import server_mcp
    conf = tmp_path / "Claude" / "claude_desktop_config.json"
    conf.parent.mkdir()
    conf.write_text(json.dumps({"mcpServers": {"altro": {"command": "x"}}, "tema": "scuro"}))
    monkeypatch.setattr(server_mcp, "file_config_claude", lambda: [conf])
    assert stato_claude_desktop()["collegato"] is False
    collega_claude_desktop(["/Users/a/Clienti"])
    d = json.loads(conf.read_text())
    assert d["tema"] == "scuro" and "altro" in d["mcpServers"]  # il resto della configurazione non si tocca
    assert d["mcpServers"]["riserbo"]["args"][-2:] == ["--cartella", "/Users/a/Clienti"]
    assert (tmp_path / "Claude" / "claude_desktop_config.json.prima-di-riserbo").exists()
    st = stato_claude_desktop()
    assert st["collegato"] and st["cartelle"] == ["/Users/a/Clienti"]
    scollega_claude_desktop()
    assert "riserbo" not in json.loads(conf.read_text())["mcpServers"]


def test_la_vecchia_voce_segnaposto_diventa_riserbo(monkeypatch, tmp_path):
    from riserbo import server_mcp
    conf = tmp_path / "claude_desktop_config.json"
    conf.write_text(json.dumps({"mcpServers": {"segnaposto": {"command": "/Applications/segnaposto.app/Contents/MacOS/segnaposto",
                                                              "args": ["mcp", "--cartella", "/Users/a/Clienti"]}}}))
    monkeypatch.setattr(server_mcp, "file_config_claude", lambda: [conf])
    st = stato_claude_desktop()
    assert st["collegato"] and st["aggiornato"] is False and st["cartelle"] == ["/Users/a/Clienti"]
    monkeypatch.setattr(server_mcp.sys, "frozen", True, raising=False)
    assert server_mcp.migra_claude_desktop() is True
    server = json.loads(conf.read_text())["mcpServers"]
    assert list(server) == ["riserbo"] and server["riserbo"]["args"][-1] == "/Users/a/Clienti"
    assert server_mcp.migra_claude_desktop() is False  # una volta sola
