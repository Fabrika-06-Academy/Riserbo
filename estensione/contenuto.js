// Riserbo nelle pagine dei chatbot.
// Andata: quando premi Invio (o il pulsante di invio), il testo del riquadro viene controllato dall'app; se ci sono dati
//   personali, nel riquadro compare la versione con i segnaposto e si preme Invio una seconda volta. Vedi cosa parte.
// Ritorno: nelle risposte (e nei tuoi messaggi già inviati) i segnaposto diventano i nomi veri, solo sul tuo schermo.
//   Il riquadro dove scrivi non viene mai toccato da questa parte: lì restano i segnaposto.
// I valori veri restano in questo script (mondo isolato dell'estensione): gli script del sito non vedono queste variabili.
(() => {
  "use strict";
  const SEGNAPOSTO = /\[[A-Z_]+_\d+\]/g;
  const CE = /\[[A-Z_]+_\d+\]/;
  const INVIO = [
    'button[data-testid="send-button"]', 'button[aria-label="Send message"]', 'button[aria-label="Invia messaggio"]',
    'button[aria-label*="Send" i]', 'button[aria-label*="Invia" i]', "button.send-button", 'button[type="submit"]',
  ];
  let imp = { guardia: true, mostra: true };
  const valori = new Map();       // segnaposto -> valore vero
  const sconosciuti = new Map();  // segnaposto -> quando l'abbiamo chiesto senza risposta (non richiederlo di continuo)
  const originali = new WeakMap(); // nodo di testo -> testo con i segnaposto, per tornare indietro
  let pronto = null;   // testo (normalizzato) già controllato: il prossimo invio passa
  let forza = null;    // testo da mandare comunque (app non raggiungibile, la persona ha premuto di nuovo Invio)
  let ultimoRiquadro = null;
  let ultimoInviato = null; // il riquadro da cui è partito l'ultimo messaggio protetto
  let lasciaPassare = false;

  const norm = (s) => String(s || "").replace(/\s+/g, " ").trim();

  function chiedi(percorso, dati) {
    return new Promise((ok, ko) => {
      try {
        chrome.runtime.sendMessage({ tipo: "app", percorso, dati }, (r) => {
          if (chrome.runtime.lastError) return ko(new Error(chrome.runtime.lastError.message));
          r && r.ok ? ok(r.dati) : ko(new Error(r ? r.errore : "nessuna risposta"));
        });
      } catch (e) {
        ko(new Error("estensione aggiornata: ricarica la pagina"));
      }
    });
  }

  // ------------------------------------------------------------ avvisi (in un shadow root chiuso: il sito non li legge)
  let ospite = null, scatola = null, timer = null;
  function avviso(testo, ms, grave) {
    if (!ospite) {
      ospite = document.createElement("div");
      ospite.style.cssText = "position:fixed;left:50%;bottom:110px;transform:translateX(-50%);z-index:2147483647;pointer-events:none";
      const radice = ospite.attachShadow({ mode: "closed" });
      scatola = document.createElement("div");
      scatola.style.cssText = "font:14px/1.4 -apple-system,Segoe UI,sans-serif;background:#121116;color:#fff;padding:10px 14px;" +
        "border-radius:10px;box-shadow:0 6px 24px rgba(0,0,0,.3);max-width:520px;border-left:4px solid #FFC700";
      radice.appendChild(scatola);
      document.documentElement.appendChild(ospite);
    }
    scatola.textContent = "Riserbo · " + testo;
    scatola.style.borderLeftColor = grave ? "#e5484d" : "#FFC700";
    ospite.hidden = false;
    clearTimeout(timer);
    if (ms) timer = setTimeout(() => { ospite.hidden = true; }, ms);
  }

  // ------------------------------------------------------------ il riquadro dove si scrive
  function riquadro(el) {
    if (!el || el.nodeType !== 1) return null;
    if (el.tagName === "TEXTAREA") return el;
    let r = null;
    for (let x = el; x && x !== document.body; x = x.parentElement) if (x.isContentEditable) r = x;
    return r; // il contenteditable più esterno
  }
  function trovaRiquadro() {
    const a = riquadro(document.activeElement);
    if (a) return a;
    if (ultimoRiquadro && ultimoRiquadro.isConnected) return ultimoRiquadro;
    return riquadro(document.querySelector('#prompt-textarea, div[contenteditable="true"], textarea'));
  }
  const leggi = (c) => (c.tagName === "TEXTAREA" ? c.value : c.innerText);

  function scrivi(c, testo) {
    c.focus();
    if (c.tagName === "TEXTAREA") {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set.call(c, testo);
      c.dispatchEvent(new Event("input", { bubbles: true }));
      return;
    }
    const sel = window.getSelection();
    const tutto = document.createRange();
    tutto.selectNodeContents(c);
    sel.removeAllRanges();
    sel.addRange(tutto);
    // Gli editor (ProseMirror, Quill) gestiscono l'incolla: gli a capo restano paragrafi
    const dt = new DataTransfer();
    dt.setData("text/plain", testo);
    const ev = new ClipboardEvent("paste", { clipboardData: dt, bubbles: true, cancelable: true });
    c.dispatchEvent(ev);
    if (!ev.defaultPrevented || norm(leggi(c)) !== norm(testo)) {
      sel.removeAllRanges();
      const r2 = document.createRange();
      r2.selectNodeContents(c);
      sel.addRange(r2);
      document.execCommand("insertText", false, testo);
    }
  }

  function pulsanteInvio(c) {
    const vicino = c && c.closest("form, fieldset, [data-testid], main") || document;
    for (const s of INVIO) {
      const b = vicino.querySelector(s) || document.querySelector(s);
      if (b && !b.disabled) return b;
    }
    return null;
  }

  function invia(c, comeTasto) {
    if (ospite) ospite.hidden = true; // il messaggio parte: l'avviso non serve più
    lasciaPassare = true;
    try {
      const b = pulsanteInvio(c);
      if (b && !comeTasto) b.click();
      else c.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true, cancelable: true }));
    } finally {
      lasciaPassare = false;
    }
  }

  async function controlla(c, comeTasto) {
    ultimoInviato = c;
    const testo = leggi(c);
    avviso("controllo i dati…");
    let r;
    try {
      r = await chiedi("/proteggi", { testo });
    } catch (e) {
      forza = norm(testo);
      avviso(e.message + ". Il messaggio NON è partito: premi di nuovo Invio per mandarlo senza protezione.", 9000, true);
      return;
    }
    if (norm(leggi(c)) !== norm(testo)) return; // nel frattempo la persona ha continuato a scrivere
    if (!r.trovati) {
      pronto = norm(testo);
      avviso("nessun dato personale trovato.", 1800);
      return invia(c, comeTasto);
    }
    scrivi(c, r.testo);
    pronto = norm(leggi(c));
    const tipi = Object.entries(r.tipi || {}).map(([k, n]) => `${n} ${k.toLowerCase().replace(/_/g, " ")}`).join(", ");
    avviso(`${r.trovati === 1 ? "1 dato sostituito" : r.trovati + " dati sostituiti"} (${tipi}). Controlla il testo e premi Invio.`, 7000);
  }

  function daControllare(c) {
    if (!imp.guardia || lasciaPassare || !c) return false;
    const t = norm(leggi(c));
    if (!t) return false;
    if (t === pronto) return false;
    if (t === forza) { forza = null; return false; }
    return true;
  }

  window.addEventListener("focusin", (e) => { const c = riquadro(e.target); if (c) ultimoRiquadro = c; }, true);

  window.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" || e.shiftKey || e.isComposing || e.altKey) return;
    const c = riquadro(e.target);
    if (!daControllare(c)) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    controlla(c, true);
  }, true);

  window.addEventListener("click", (e) => {
    if (lasciaPassare || !e.isTrusted) return;
    const b = e.target.closest && e.target.closest(INVIO.join(","));
    if (!b) return;
    const c = trovaRiquadro();
    if (!daControllare(c)) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    controlla(c, false);
  }, true);

  // ------------------------------------------------------------ ritorno: i nomi veri nelle risposte
  // Nei testi normali della pagina i segnaposto diventano i nomi veri. Nei testi MODIFICABILI (il riquadro dove scrivi,
  // ma anche la bozza di email di ChatGPT o un documento in modifica) non si scrive mai: l'editor del sito prenderebbe i
  // nomi veri come se li avessi scritti tu e potrebbe salvarli sui suoi server. Per quei testi c'è il pulsante
  // «[–] Nomi veri», che li mostra in un riquadro privato con il tasto Copia.
  const dentroRiquadro = (n) => { const p = n.parentElement; return !p || p.isContentEditable || p.closest("textarea,input,script,style"); };
  const èCompositore = (el) => el.id === "prompt-textarea" || !!el.closest("form, fieldset, rich-textarea") || el === ultimoInviato;

  function testiModificabili() {
    const fuori = [];
    for (const el of document.querySelectorAll('[contenteditable="true"], [contenteditable=""], [contenteditable="plaintext-only"], textarea')) {
      if (el.tagName !== "TEXTAREA" && el.parentElement && el.parentElement.isContentEditable) continue; // solo il più esterno
      if (èCompositore(el)) continue;
      const t = leggi(el);
      if (CE.test(t)) fuori.push(t);
    }
    return fuori;
  }

  function nodiConSegnaposto() {
    const fuori = [];
    const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
      acceptNode: (n) => (CE.test(n.data) && !dentroRiquadro(n) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP),
    });
    while (w.nextNode()) fuori.push(w.currentNode);
    return fuori;
  }

  let inAttesa = false;
  async function rimetti() {
    if (!imp.mostra) return;
    const nodi = nodiConSegnaposto();
    const modificabili = testiModificabili();
    if (!nodi.length && !modificabili.length) { pulsanteNomi([]); return; }
    const ora = Date.now();
    const mancanti = new Set();
    for (const t of [...nodi.map((n) => n.data), ...modificabili]) for (const s of t.match(SEGNAPOSTO) || [])
      if (!valori.has(s) && !(ora - (sconosciuti.get(s) || 0) < 15000)) mancanti.add(s);
    if (mancanti.size && !inAttesa) {
      inAttesa = true;
      try {
        const r = await chiedi("/valori", { segnaposto: [...mancanti] });
        for (const s of mancanti) r.valori[s] !== undefined ? valori.set(s, r.valori[s]) : sconosciuti.set(s, ora);
      } catch (e) {
        for (const s of mancanti) sconosciuti.set(s, ora);
      } finally {
        inAttesa = false;
      }
    }
    for (const n of nodiConSegnaposto()) {
      const nuovo = n.data.replace(SEGNAPOSTO, (s) => (valori.has(s) ? valori.get(s) : s));
      if (nuovo !== n.data) {
        originali.set(n, n.data);
        n.data = nuovo;
      }
    }
    pulsanteNomi(testiModificabili().filter((t) => (t.match(SEGNAPOSTO) || []).some((s) => valori.has(s))));
  }

  // Il pulsante e il riquadro privato (shadow root chiuso: gli script del sito non ne leggono il contenuto)
  let pOspite = null, pRadice = null, pTesti = [];
  const conNomi = (t) => t.replace(SEGNAPOSTO, (s) => (valori.has(s) ? valori.get(s) : s));
  function pulsanteNomi(testi) {
    pTesti = testi;
    if (!testi.length) { if (pOspite) pOspite.hidden = true; return; }
    if (!pOspite) {
      pOspite = document.createElement("div");
      pOspite.style.cssText = "position:fixed;right:18px;bottom:18px;z-index:2147483646";
      pRadice = pOspite.attachShadow({ mode: "closed" });
      document.documentElement.appendChild(pOspite);
    }
    pOspite.hidden = false;
    if (pRadice.querySelector(".pannello")) return; // aperto: non lo ridisegno sotto le mani
    pRadice.innerHTML = '<style>' + STILE + '</style><button class="nomi">[–] Nomi veri</button>';
    pRadice.querySelector(".nomi").onclick = apriPannello;
  }
  function apriPannello() {
    pRadice.innerHTML = '<style>' + STILE + '</style><div class="pannello"><div class="testa"><b>Riserbo · con i nomi veri</b>' +
      '<button class="chiudi">Chiudi</button></div><p class="nota">Solo qui, sul tuo schermo: il sito non vede questo riquadro.</p></div>';
    const pan = pRadice.querySelector(".pannello");
    pTesti.forEach((t) => {
      const blocco = document.createElement("div"); blocco.className = "blocco";
      const pre = document.createElement("pre"); pre.textContent = conNomi(t);
      const b = document.createElement("button"); b.className = "copia"; b.textContent = "Copia";
      b.onclick = async () => {
        try { await navigator.clipboard.writeText(pre.textContent); }
        catch (e) { const ta = document.createElement("textarea"); ta.value = pre.textContent; blocco.appendChild(ta); ta.select(); document.execCommand("copy"); ta.remove(); }
        b.textContent = "Copiato";
        setTimeout(() => { b.textContent = "Copia"; }, 1500);
      };
      blocco.append(pre, b); pan.appendChild(blocco);
    });
    pRadice.querySelector(".chiudi").onclick = () => { pRadice.innerHTML = ""; pulsanteNomi(pTesti); };
  }
  const STILE = ".nomi{font:600 14px -apple-system,Segoe UI,sans-serif;background:#121116;color:#FFC700;border:0;border-radius:999px;" +
    "padding:10px 16px;box-shadow:0 8px 24px rgba(0,0,0,.3);cursor:pointer}" +
    ".pannello{font:14px/1.5 -apple-system,Segoe UI,sans-serif;background:#fff;color:#121116;width:min(520px,calc(100vw - 36px));" +
    "max-height:70vh;overflow:auto;border-radius:14px;box-shadow:0 18px 50px rgba(0,0,0,.35);padding:14px 16px;border-top:4px solid #FFC700}" +
    ".testa{display:flex;justify-content:space-between;align-items:center;gap:10px}.nota{margin:4px 0 10px;color:#666;font-size:12.5px}" +
    ".blocco{border:1px solid #e2e0da;border-radius:10px;padding:10px 12px;margin-bottom:10px}" +
    "pre{white-space:pre-wrap;font:inherit;margin:0 0 8px}button.copia,button.chiudi{font:inherit;border:1px solid #d8d6cf;background:#fff;" +
    "border-radius:8px;padding:5px 12px;cursor:pointer}button.copia{background:#FFC700;border-color:#FFC700;font-weight:600}" +
    "@media (prefers-color-scheme:dark){.pannello{background:#1b1a20;color:#eee}.blocco{border-color:#3a3a44}.nota{color:#aaa}" +
    "button.chiudi{background:transparent;color:#eee;border-color:#3a3a44}}";

  function nascondi() { // «Mostra i nomi veri» spento: tornano i segnaposto
    const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    while (w.nextNode()) { const n = w.currentNode; if (originali.has(n)) { n.data = originali.get(n); originali.delete(n); } }
  }

  let attesa = null;
  const programma = () => { clearTimeout(attesa); attesa = setTimeout(rimetti, 250); };
  new MutationObserver(programma).observe(document.body, { childList: true, subtree: true, characterData: true });

  chrome.storage.onChanged.addListener((cambi) => {
    for (const [k, v] of Object.entries(cambi)) imp[k] = v.newValue;
    if ("mostra" in cambi) imp.mostra ? rimetti() : nascondi();
    if ("codice" in cambi) { sconosciuti.clear(); programma(); }
  });
  chrome.runtime.onMessage.addListener((msg) => {
    if (msg && msg.tipo === "nuova-pratica") { valori.clear(); sconosciuti.clear(); nascondi(); pronto = null; }
  });
  chrome.runtime.sendMessage({ tipo: "impostazioni" }, (r) => {
    if (chrome.runtime.lastError || !r || !r.ok) return;
    imp = r.dati;
    programma();
  });
})();
