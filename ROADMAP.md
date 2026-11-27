# Dove va Riserbo

L'idea: i dati personali non devono uscire dal computer, **qualunque sia lo strumento** con cui si lavora. All'inizio era
un'app in cui incollare il testo; ora sta in mezzo, senza farsi notare, tra le app di tutti i giorni e i modelli
in cloud: browser, appunti, automazioni, agenti. Un passo alla volta, ognuno usabile da subito.

## Fatto

- **v0.2**: motore italiano (codice fiscale con omocodia, P.IVA, IBAN con controllo delle cifre, targhe, nomi, aziende),
  app locale, pacchetti per Mac e Windows, servizio HTTP locale.
- **v0.3**: finestra nativa. Documenti in ingresso: Word, PDF con testo, Excel, CSV, email .eml con allegati. Colonne
  riconosciute dall'intestazione, indirizzi, correzioni a mano (clic e selezione), salvataggio nel formato d'origine.
- **v0.13**: Pausa (15 minuti, un'ora, finché non la riattivi) dalla finestra, dal menu dell'icona e dall'estensione: si
  riattiva da sola, l'icona cambia aspetto, il cancello resta acceso.
- **v0.12**: modalità automatica per le app di AI sul computer (ChatGPT, Claude, Copilot, Perplexity): gli appunti si
  proteggono entrando nell'app e tornano veri uscendo. Guida nell'app, aperta al primo avvio, con lo stato di ogni modo
  d'uso. Le preferenze della pagina si salvano sul computer (prima si perdevano a ogni chiusura).
- **v0.11.1**: estensione, le risposte modificabili (bozza di email di ChatGPT) si leggono con i nomi veri in un riquadro privato.
- **v0.11**: il nome diventa **Riserbo** (prima *segnaposto*: la parola resta per i segnaposto). README e pagine nuove,
  con schema, esempi e immagini; parte tecnica in `docs/sviluppatori.md`.
- **v0.10**: estensione per il browser (ChatGPT, Claude, Gemini, Copilot, Mistral, Perplexity, DeepSeek): protegge il
  messaggio al momento dell'invio mostrando cosa parte, rimette i nomi veri nelle risposte sul tuo schermo. Parla con l'app
  su 127.0.0.1 con un codice di collegamento.
- **v0.9**: server MCP per Claude Desktop e gli altri agenti: elenca, legge (nomi dei file compresi, solo segnaposto),
  salva e copia negli appunti rimettendo i nomi veri sul computer. Collegamento a Claude Desktop in un clic dall'app.
- **v0.8**: il cancello, proxy locale compatibile con OpenAI e Anthropic (Chat Completions, Responses, Messages,
  Embeddings, streaming compreso): pseudonimizza all'andata, rimette i nomi al ritorno, registro di cosa è uscito senza i
  valori. Nell'app (pannello Automazioni, icona) e da terminale (`riserbo cancello`). Allegati rifiutati.
- **v0.7.2**: avviso di aggiornamento e pareri funzionanti anche nell'app impacchettata (certificati HTTPS inclusi),
  pulsante «Controlla adesso».
- **v0.7.1**: icona [–] nella barra dei menu (Mac) e nell'area di notifica (Windows): chiudendo la finestra l'app resta
  attiva, con le scorciatoie. Apri all'accensione, una sola istanza alla volta, tabella cancellata dopo un'ora senza uso.
- **v0.7**: da qualunque programma: ⌃⌥P / Ctrl+Alt+P protegge il testo copiato, ⌃⌥R / Ctrl+Alt+R rimette i nomi, con
  notifica di conferma; pannello «Appunti» con gli stessi comandi come pulsanti. Nessun permesso di Accessibilità su Mac.
- **v0.6.5**: avviso di nuova versione con scaricamento in un clic, pannello Parere (arriva all'Academy), elenco «sempre in
  chiaro» e marchi noti non nascosti, spazi mancanti nei PDF ricostruiti dalle posizioni dei caratteri.
- **v0.6**: nuovo riconoscitore di entità: BERT italiano con oltre 50 categorie (DeepMount00/Italian_NER_XXL_v2, Apache 2.0)
  in ONNX int8, senza PyTorch. Sul set di prova le fughe scendono da 6 a 1-2 su 88 e i falsi allarmi da 9 a 0. Via il
  modello spaCy, che aveva licenza non commerciale. Nuove categorie: età, dati sanitari, documenti, conti, password, IP, catasto.
- **v0.5**: interfaccia rifatta: schede Proteggi / Rimetti i nomi, segnaposto colorati per tipo, anteprima del PDF oscurato,
  scelta di cosa nascondere, valori rimessi evidenziati nella risposta.
- **v0.4**: OCR di PDF scansionati, foto e screenshot. Abbiamo valutato [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR):
  i suoi modelli PP-OCRv6 multilingua leggono benissimo l'italiano, accenti compresi, ma il framework PaddlePaddle pesa
  centinaia di MB. Usiamo quindi gli stessi modelli con ONNX Runtime tramite [RapidOCR](https://github.com/RapidAI/RapidOCR).
  Il classificatore dell'orientamento delle righe è spento perché girava per errore righe dritte. PDF oscurato fatto di sole
  immagini, con il segnaposto sopra ogni dato (niente PyMuPDF: AGPL). Email .msg di Outlook lette con olefile (BSD).
  Saluti e titoli («Gentile Ing.», «Spett.le») restano fuori dai nomi.

## Prossimi passi

### Dopo la v0.7
- Menu *Servizi* di macOS e *Invia a* di Windows per i file.
- Scorciatoie configurabili.

### Subito
- Banco di prova più ampio e pubblico (centinaia di testi di PMI annotati), con i numeri sulla pagina.
- Video dimostrativo dell'estensione su ChatGPT e Claude.

### v1.0
- Estensione sul Chrome Web Store e su Firefox; allegati (PDF e immagini) pseudonimizzati prima del caricamento.
- **Nodo per n8n**.

### Sempre
- Anagrafica clienti e fornitori dal gestionale, salvata cifrata con il portachiavi di sistema.
- Pratiche salvabili e riprendibili, cifrate.
- Modello di riconoscimento più grande, scaricato al primo uso solo da chi lo vuole.
- Firma e notarizzazione Apple quando l'app avrà una diffusione ampia.

## Una famiglia di strumenti

Riserbo è il primo strumento della [Fabrika 06 Academy](https://academy.fabrika06.com). I prossimi (fattura elettronica
XML in tabella, controllo «questo Excel è leggibile da un modello?», calcolatore del costo reale di un flusso con l'AI) useranno
la stessa base: finestra nativa, tutto in locale, pacchetti per Mac e Windows, stessa grafica.
