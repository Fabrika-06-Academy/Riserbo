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
  const dentroRiquadro = (n) => { const p = n.parentElement; return !p || p.isContentEditable || p.closest("textarea,input,script,style"); };

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
    if (!nodi.length) return;
    const ora = Date.now();
    const mancanti = new Set();
    for (const n of nodi) for (const s of n.data.match(SEGNAPOSTO) || [])
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
  }

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
