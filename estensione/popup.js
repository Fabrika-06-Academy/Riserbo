const $ = (i) => document.getElementById(i);

function chiedi(percorso, dati) {
  return new Promise((ok, ko) => chrome.runtime.sendMessage({ tipo: "app", percorso, dati }, (r) =>
    r && r.ok ? ok(r.dati) : ko(new Error(r ? r.errore : "nessuna risposta"))));
}

async function aggiorna() {
  const imp = Object.assign({ porta: 8789, codice: "", guardia: true, mostra: true },
    await chrome.storage.local.get(["porta", "codice", "guardia", "mostra"]));
  $("guardia").checked = imp.guardia;
  $("mostra").checked = imp.mostra;
  $("porta").value = imp.porta;
  $("collega").hidden = !!imp.codice;
  $("scollega").hidden = !imp.codice;
  const st = $("stato");
  if (!imp.codice) {
    st.className = "stato ko";
    st.textContent = "Non collegata all'app.";
    return;
  }
  try {
    const d = await chiedi("/stato");
    st.className = "stato ok";
    st.textContent = d.pronto
      ? `Collegata a Riserbo ${d.versione}. Nella pratica: ${d.segnaposto} segnaposto.`
      : "Collegata: l'app sta caricando il modello italiano…";
  } catch (e) {
    st.className = "stato ko";
    st.textContent = e.message;
    if (/codice/i.test(e.message)) $("collega").hidden = false;
  }
}

$("salva").onclick = async () => {
  const codice = $("codice").value.trim();
  if (codice) await chrome.storage.local.set({ codice });
  $("codice").value = "";
  aggiorna();
};
$("scollega").onclick = async () => { await chrome.storage.local.remove("codice"); aggiorna(); };
$("guardia").onchange = (e) => chrome.storage.local.set({ guardia: e.target.checked });
$("mostra").onchange = (e) => chrome.storage.local.set({ mostra: e.target.checked });
$("porta").onchange = (e) => { const p = parseInt(e.target.value, 10); if (p >= 1024 && p <= 65535) chrome.storage.local.set({ porta: p }).then(aggiorna); };
$("nuova").onclick = async () => {
  try {
    await chiedi("/nuova");
    const schede = await chrome.tabs.query({});
    for (const t of schede) chrome.tabs.sendMessage(t.id, { tipo: "nuova-pratica" }).catch(() => {});
    $("stato").textContent = "Nuova pratica: la tabella precedente è stata cancellata.";
  } catch (e) {
    $("stato").textContent = e.message;
  }
};
aggiorna();
