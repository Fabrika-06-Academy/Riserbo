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
    const p = d.pausa || { attiva: false };
    st.className = p.attiva ? "stato ko" : "stato ok";
    st.textContent = p.attiva
      ? `Riserbo è ${p.testo}: i messaggi partono così come sono.`
      : d.pronto
        ? `Collegata a Riserbo ${d.versione}. Nella pratica: ${d.segnaposto} segnaposto.`
        : "Collegata: l'app sta caricando il modello italiano…";
    $("rigaPausa").hidden = false;
    $("pausa").hidden = p.attiva;
    $("riattiva").hidden = !p.attiva;
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
$("pausa").onclick = () => chiedi("/pausa", { minuti: 60 }).then(aggiorna, (e) => { $("stato").textContent = e.message; });
$("riattiva").onclick = () => chiedi("/riprendi").then(aggiorna, (e) => { $("stato").textContent = e.message; });
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
