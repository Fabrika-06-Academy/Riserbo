# Dove va segnaposto

L'idea: i dati personali non devono uscire dal computer, **qualunque sia lo strumento** con cui si lavora. Oggi segnaposto è
un'app in cui incollare il testo. Domani deve stare in mezzo, senza farsi notare, tra le app di tutti i giorni e i modelli
in cloud. Un passo alla volta, ognuno usabile da subito.

## Fatto

- **v0.2**: motore italiano (codice fiscale con omocodia, P.IVA, IBAN con controllo delle cifre, targhe, nomi, aziende),
  app locale, pacchetti per Mac e Windows, servizio HTTP locale.
- **v0.3**: finestra nativa. Documenti in ingresso: Word, PDF con testo, Excel, CSV, email .eml con allegati. Colonne
  riconosciute dall'intestazione, indirizzi, correzioni a mano (clic e selezione), salvataggio nel formato d'origine.
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
- Icona nella barra dei menu (Mac) e nell'area di notifica (Windows), per tenere l'app pronta senza finestra.
- Menu *Servizi* di macOS e *Invia a* di Windows per i file.
- Scorciatoie configurabili.

### v0.8: il cancello per i modelli
- Un **proxy locale compatibile con le API di OpenAI e Anthropic**. n8n, Make, script Python, Open WebUI e gli editor di
  codice puntano a `http://127.0.0.1` invece che al fornitore. segnaposto pseudonimizza ogni richiesta in uscita, rimette i
  valori nella risposta (anche in streaming) e tiene un **registro di cosa è uscito**, utile per il registro dei trattamenti.
- Per le automazioni è il passo decisivo: la protezione non dipende più da chi si ricorda di usarla.

### v0.9: agenti e browser
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
