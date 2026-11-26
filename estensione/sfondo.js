// Lo script di sfondo: l'unico che parla con l'app segnaposto su 127.0.0.1.
// Le pagine dei chatbot non possono raggiungerlo: chiedono a questo script, che aggiunge il codice di collegamento.

const PREDEFINITE = { porta: 8789, codice: "", guardia: true, mostra: true };
const PERCORSI = new Set(["/stato", "/proteggi", "/valori", "/nuova"]);

async function impostazioni() {
  return Object.assign({}, PREDEFINITE, await chrome.storage.local.get(Object.keys(PREDEFINITE)));
}

async function app(percorso, dati) {
  if (!PERCORSI.has(percorso)) throw new Error("percorso non previsto");
  const imp = await impostazioni();
  if (!imp.codice) throw new Error("estensione non collegata: incolla il codice dall'app (icona di segnaposto nella barra del browser)");
  let r;
  try {
    r = await fetch(`http://127.0.0.1:${imp.porta}${percorso}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Segnaposto-Token": imp.codice },
      body: JSON.stringify(dati || {}),
    });
  } catch (e) {
    throw new Error("l'app segnaposto non risponde: è aperta, con «Collega l'estensione» attivo?");
  }
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.errore || `errore ${r.status}`);
  return j;
}

chrome.runtime.onMessage.addListener((msg, _mittente, rispondi) => {
  (async () => {
    try {
      if (msg.tipo === "impostazioni") return rispondi({ ok: true, dati: await impostazioni() });
      if (msg.tipo === "app") return rispondi({ ok: true, dati: await app(msg.percorso, msg.dati) });
      rispondi({ ok: false, errore: "messaggio sconosciuto" });
    } catch (e) {
      rispondi({ ok: false, errore: String((e && e.message) || e) });
    }
  })();
  return true; // risposta asincrona
});
