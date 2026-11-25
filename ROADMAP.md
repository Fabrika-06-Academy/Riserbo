# Dove va segnaposto

L'idea: i dati personali non devono uscire dal computer, **qualunque sia lo strumento** con cui si lavora. Oggi segnaposto è
un'app in cui incollare il testo. Domani deve stare in mezzo, senza farsi notare, tra le app di tutti i giorni e i modelli
in cloud. Un passo alla volta, ognuno usabile da subito.

## Fatto

- **v0.2**: motore italiano (codice fiscale con omocodia, P.IVA, IBAN con controllo delle cifre, targhe, nomi, aziende),
  app locale, pacchetti per Mac e Windows, servizio HTTP locale.
- **v0.3**: finestra nativa. Documenti in ingresso: Word, PDF con testo, Excel, CSV, email .eml con allegati. Colonne
  riconosciute dall'intestazione, indirizzi, correzioni a mano (clic e selezione), salvataggio nel formato d'origine.

## Prossimi passi

### v0.4: scansioni, foto e PDF oscurati
- **OCR** per PDF scansionati e foto di documenti. Valutazione:
  - [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) ha i modelli migliori tra quelli aperti (PP-OCRv5, Apache 2.0) e
    legge bene l'alfabeto latino. Però il framework PaddlePaddle pesa centinaia di MB e complica i pacchetti per Mac e Windows.
  - La strada scelta: **gli stessi modelli PP-OCR** eseguiti con ONNX Runtime tramite [RapidOCR](https://github.com/RapidAI/RapidOCR)
    (Apache 2.0). Qualità di PaddleOCR, poche decine di MB, stesso risultato su Mac e Windows.
  - Da misurare su documenti italiani veri (fatture, carte d'identità, moduli scritti a mano in stampatello) contro
    Apple Vision, che su Mac è già nel sistema e non pesa nulla.
- **PDF oscurato**: ogni pagina diventa immagine e i dati vengono coperti da rettangoli neri. Nel file finale non resta
  testo nascosto sotto i rettangoli, che è l'errore classico degli oscuramenti fatti male. Niente PyMuPDF: la sua licenza
  AGPL non è compatibile con MIT.
- Email **.msg** di Outlook.

### v0.5: ovunque, dagli appunti
- Icona nella barra dei menu (Mac) e nell'area di notifica (Windows), con l'app sempre pronta.
- **Scorciatoia globale**: copi un testo in qualunque app (Outlook, gestionale, WhatsApp Web), premi la scorciatoia e negli
  appunti trovi la versione pseudonimizzata. Copi la risposta della chat, premi l'altra scorciatoia e torna con i nomi veri.
- Menu *Servizi* di macOS e *Invia a* di Windows per i file.

### v0.6: il cancello per i modelli
- Un **proxy locale compatibile con le API di OpenAI e Anthropic**. n8n, Make, script Python, Open WebUI e gli editor di
  codice puntano a `http://127.0.0.1` invece che al fornitore. segnaposto pseudonimizza ogni richiesta in uscita, rimette i
  valori nella risposta (anche in streaming) e tiene un **registro di cosa è uscito**, utile per il registro dei trattamenti.
- Per le automazioni è il passo decisivo: la protezione non dipende più da chi si ricorda di usarla.

### v0.7: agenti e browser
- **Server MCP**: Claude Desktop e gli altri agenti chiamano `pseudonimizza` e `ripristina` come strumenti, e leggono i file
  locali solo attraverso segnaposto.
- **Estensione per il browser** su ChatGPT, Claude e Gemini: pseudonimizza prima dell'invio e mostra i nomi veri nella
  risposta solo sul tuo schermo.
- **Nodo per n8n**.

### Sempre
- Anagrafica clienti e fornitori dal gestionale, salvata cifrata con il portachiavi di sistema.
- Pratiche salvabili e riprendibili, cifrate.
- Modello di riconoscimento più grande, scaricato al primo uso solo da chi lo vuole.
- Firma e notarizzazione Apple quando l'app avrà una diffusione ampia.

## Una famiglia di strumenti

segnaposto è il primo strumento della [Fabrika 06 Academy](https://academy.fabrika06.com). I prossimi (fattura elettronica
XML in tabella, controllo «questo Excel è leggibile da un modello?», calcolatore del costo reale di un flusso con l'AI) useranno
la stessa base: finestra nativa, tutto in locale, pacchetti per Mac e Windows, stessa grafica.
