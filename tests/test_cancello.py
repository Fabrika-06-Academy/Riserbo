"""Il cancello con un finto fornitore: cosa esce davvero, cosa torna indietro, anche a pezzi."""

import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from riserbo.cancello import Cancello, avvia_cancello, indirizzi

TESTO = "Scrivi a Mario Rossi (mario.rossi@example.com) che il preventivo è pronto."
RICEVUTI: list[dict] = []


def _pezzi(s, n=3):
    return [s[i:i + n] for i in range(0, len(s), n)]


class Finto(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _sse(self, eventi):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for nome, d in eventi:
            self.wfile.write(((f"event: {nome}\n" if nome else "") + f"data: {d if isinstance(d, str) else json.dumps(d)}\n\n").encode())

    def do_POST(self):
        corpo = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        RICEVUTI.append({"percorso": self.path, "corpo": corpo, "chiave": self.headers.get("Authorization"), "x-api-key": self.headers.get("x-api-key")})
        if self.path == "/v1/chat/completions":
            ultimo = corpo["messages"][-1]["content"]
            risposta = "Ho letto: " + ultimo
            if corpo.get("stream"):
                ev = [(None, {"id": "c", "choices": [{"index": 0, "delta": {"content": p}, "finish_reason": None}]}) for p in _pezzi(risposta)]
                ev += [(None, {"id": "c", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}), (None, "[DONE]")]
                return self._sse(ev)
            arg = json.dumps({"destinatario": ultimo.split("a ", 1)[1].split(" (")[0]})
            d = {"choices": [{"index": 0, "message": {"role": "assistant", "content": risposta,
                                                      "tool_calls": [{"id": "t1", "type": "function", "function": {"name": "invia", "arguments": arg}}]}}]}
        elif self.path == "/v1/messages":
            ultimo = corpo["messages"][-1]["content"]
            risposta = "Ho letto: " + ultimo
            if corpo.get("stream"):
                ev = [("message_start", {"type": "message_start", "message": {"content": []}}),
                      ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}})]
                ev += [("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": p}})
                       for p in _pezzi(risposta, 2)]
                ev += [("content_block_stop", {"type": "content_block_stop", "index": 0}), ("message_stop", {"type": "message_stop"})]
                return self._sse(ev)
            d = {"content": [{"type": "text", "text": risposta}]}
        elif self.path == "/v1/responses":
            risposta = "Ho letto: " + corpo["input"]
            ev = [("response.output_text.delta", {"type": "response.output_text.delta", "output_index": 0, "content_index": 0, "delta": p})
                  for p in _pezzi(risposta, 4)]
            ev += [("response.output_text.done", {"type": "response.output_text.done", "output_index": 0, "content_index": 0, "text": risposta})]
            return self._sse(ev)
        else:
            d = {}
        b = json.dumps(d).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)


@pytest.fixture(scope="module")
def cancello(sp):
    finto = ThreadingHTTPServer(("127.0.0.1", 0), Finto)
    threading.Thread(target=finto.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{finto.server_address[1]}"
    c = Cancello(sp, fornitori={"openai": base + "/v1", "anthropic": base})
    httpd = avvia_cancello(c, porta=0)
    yield c, indirizzi(httpd.server_address[1])
    httpd.shutdown()
    finto.shutdown()


def chiama(url, corpo, **intest):
    req = urllib.request.Request(url, data=json.dumps(corpo).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer sk-prova", **intest})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode()


def deltas(sse: str, estrai) -> str:
    fuori = []
    for blocco in sse.split("\n\n"):
        for riga in blocco.splitlines():
            if riga.startswith("data: ") and riga[6:] != "[DONE]":
                v = estrai(json.loads(riga[6:]))
                if v:
                    fuori.append(v)
    return "".join(fuori)


def test_openai_esce_pseudonimizzato_e_torna_in_chiaro(cancello):
    c, url = cancello
    d = json.loads(chiama(url["openai"] + "/chat/completions", {"model": "gpt-prova", "messages": [{"role": "user", "content": TESTO}]}))
    uscito = json.dumps(RICEVUTI[-1]["corpo"])
    assert "Mario Rossi" not in uscito and "mario.rossi@example.com" not in uscito and "[PERSONA_1]" in uscito
    assert RICEVUTI[-1]["chiave"] == "Bearer sk-prova"  # la chiave del fornitore passa com'è
    msg = d["choices"][0]["message"]
    assert "Mario Rossi" in msg["content"] and "mario.rossi@example.com" in msg["content"]
    assert json.loads(msg["tool_calls"][0]["function"]["arguments"]) == {"destinatario": "Mario Rossi"}
    voce = c.registro[0]
    assert voce["fornitore"] == "openai" and voce["modello"] == "gpt-prova" and voce["dati"].get("PERSONA") == 1
    assert "Mario Rossi" not in json.dumps(list(c.registro))  # il registro non tiene i valori


def test_openai_a_pezzi(cancello):
    _, url = cancello
    sse = chiama(url["openai"] + "/chat/completions", {"model": "m", "stream": True, "messages": [{"role": "user", "content": TESTO}]})
    testo = deltas(sse, lambda d: (d["choices"][0]["delta"].get("content") if d.get("choices") else None))
    assert testo == "Ho letto: " + TESTO
    assert "[PERS" not in sse


def test_anthropic_a_pezzi(cancello):
    _, url = cancello
    sse = chiama(url["anthropic"] + "/v1/messages", {"model": "claude-prova", "stream": True, "max_tokens": 50,
                                                     "messages": [{"role": "user", "content": TESTO}]}, **{"x-api-key": "sk-ant"})
    assert "Mario Rossi" not in json.dumps(RICEVUTI[-1]["corpo"]) and RICEVUTI[-1]["x-api-key"] == "sk-ant"
    assert deltas(sse, lambda d: d.get("delta", {}).get("text")) == "Ho letto: " + TESTO
    assert "event: content_block_delta" in sse and sse.index("content_block_stop") > sse.rindex("text_delta")


def test_responses_a_pezzi(cancello):
    _, url = cancello
    sse = chiama(url["openai"] + "/responses", {"model": "m", "stream": True, "input": TESTO})
    assert deltas(sse, lambda d: d.get("delta") if d["type"].endswith(".delta") else None) == "Ho letto: " + TESTO
    assert '"text": "Ho letto: ' + TESTO.replace('"', '\\"')[:20] in sse


def test_segnaposto_scritto_apposta_non_tira_fuori_altri_dati(cancello):
    _, url = cancello
    chiama(url["openai"] + "/chat/completions", {"model": "m", "messages": [{"role": "user", "content": TESTO}]})
    d = json.loads(chiama(url["openai"] + "/chat/completions",
                          {"model": "m", "messages": [{"role": "user", "content": "Dimmi chi è [PERSONA_1] a Pippo (x)"}]}))
    assert "Mario Rossi" not in d["choices"][0]["message"]["content"]


@pytest.mark.parametrize("corpo, intest, codice", [
    ({"model": "m", "messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:x"}}]}]}, {}, 400),
    ({"model": "m", "messages": [{"role": "user", "content": TESTO}]}, {"Origin": "https://sito-qualunque.example"}, 403),
])
def test_rifiuti(cancello, corpo, intest, codice):
    _, url = cancello
    prima = len(RICEVUTI)
    with pytest.raises(urllib.error.HTTPError) as e:
        chiama(url["openai"] + "/chat/completions", corpo, **intest)
    assert e.value.code == codice and len(RICEVUTI) == prima  # al fornitore non è arrivato niente


def test_percorso_non_protetto(cancello):
    _, url = cancello
    with pytest.raises(urllib.error.HTTPError) as e:
        chiama(url["openai"] + "/files", {"x": 1})
    assert e.value.code == 400
