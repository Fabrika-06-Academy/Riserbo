# Riserbo per sviluppatori

Come è fatto, come si installa con Python e come si collega ad altri programmi. La presentazione per chi lo usa è nel
[README](../README.md).

## Come funziona: tre strati

| Strato | Cosa trova | Come |
|---|---|---|
| 1. Regole | codice fiscale (anche con omocodia), partita IVA, IBAN, email, telefoni, targhe, indirizzi con civico | forma fissa e **controllo delle cifre di verifica**, così un numero a caso non viene scambiato per un IBAN |
| 1. Anagrafica e codici tuoi | i nomi dei tuoi clienti e fornitori, i codici di commesse e ordini | un CSV esportato dal gestionale, espressioni regolari tue |
| 1. Colonne riconosciute | in Excel e CSV, intere colonne «Nome», «Ragione sociale», «Email», «Codice fiscale», «Indirizzo»… | l'intestazione dice cosa c'è sotto: il valore viene nascosto anche dove compare nel resto del documento |
| 2. Riconoscitore di entità | persone, aziende, luoghi, e poi età, date di nascita, dati sanitari, documenti, conti, password, IP, dati catastali | un BERT italiano con oltre 50 categorie ([DeepMount00/Italian_NER_XXL_v2](https://huggingface.co/DeepMount00/Italian_NER_XXL_v2), Apache 2.0) eseguito in locale con ONNX Runtime, dentro [Presidio](https://github.com/data-privacy-stack/presidio) |
| 3. Controllo finale (facoltativo) | quello che è sfuggito: «il figlio del titolare», un soprannome | una funzione tua, per esempio un modello piccolo in casa |

Lo stesso valore riceve sempre lo stesso segnaposto nella stessa pratica, così il modello capisce che si parla della stessa persona.

## Installazione con Python

```bash
python -m venv .venv && . .venv/bin/activate
# Non è (ancora) su PyPI: si installa direttamente da GitHub
pip install "riserbo @ git+https://github.com/Fabrika-06-Academy/riserbo"
# con documenti, OCR e finestra dell'app:
# pip install "riserbo[app] @ git+https://github.com/Fabrika-06-Academy/riserbo"
# oppure, da una copia del repository: pip install -e ".[app]"
riserbo scarica-modello   # il riconoscitore di entità, circa 110 MB, una volta sola (altrimenti lo scarica al primo uso)
```

Tutto gira sul tuo computer o sul tuo server. Nessun dato viene mandato fuori.

## Uso da terminale

```bash
# Pseudonimizzare: la tabella va in un file a parte (permessi 600, scade dopo 30 giorni)
riserbo pseudonimizza email.txt --tabella pratica-123.tabella.json --anagrafica clienti.csv --mostra > email-pulita.txt

# ... email-pulita.txt va al modello in cloud, la risposta torna in risposta.txt ...

# Ripristinare: esce con codice 2 se il modello ha inventato segnaposto
riserbo ripristina risposta.txt --tabella pratica-123.tabella.json > risposta-vera.txt

# Misurare le fughe sul tuo set di prova
riserbo valuta esempi/set-di-prova.jsonl --anagrafica esempi/anagrafica.csv
```

## Uso da Python

```python
from riserbo import Segnaposto, Tabella, ripristina
from riserbo.riconoscitori import carica_anagrafica, riconoscitore_codice

sp = Segnaposto(riconoscitori=[
    carica_anagrafica("clienti.csv", entita="CLIENTE"),
    riconoscitore_codice("COMMESSA", r"\bC-\d{4}-\d{3}\b", contesto=["commessa"]),
])
tabella = Tabella()
pulito = sp.pseudonimizza(testo, tabella)          # pulito.testo va in cloud
risposta = chiama_il_modello(pulito.testo)
esito = ripristina(risposta, tabella, attesi=set(tabella.valori))
if esito.inventati:
    ...  # il modello ha creato segnaposto suoi: la risposta va riletta da una persona
```

Strato 3, con un modello in casa (per esempio con Ollama):

```python
def controllo(testo: str) -> list[str]:
    # chiedi al modello locale: «elenca, parola per parola, i dati che identificano una persona o un cliente»
    return [...]

sp = Segnaposto(controllo_finale=controllo)
```

## L'app dal terminale

```bash
pip install "riserbo[app] @ git+https://github.com/Fabrika-06-Academy/riserbo"   # documenti, OCR e finestra nativa
riserbo app            # finestra nativa; senza pywebview, o con --browser, si apre nel browser (127.0.0.1, chiave casuale)
```

## Il cancello: per n8n, Make e i programmi che usano ChatGPT o Claude

Un proxy locale compatibile con le API di OpenAI e Anthropic. Il programma parla con Riserbo invece che con il fornitore:
ogni richiesta esce pseudonimizzata, la risposta torna con i nomi veri, anche in streaming. La protezione non dipende più da
chi si ricorda di usarla.

Nell'app: pannello **Automazioni → Attiva il cancello** (o dal menu dell'icona). Da terminale, anche su un server:

```bash
riserbo cancello                     # 127.0.0.1:8788
riserbo cancello --openai https://openrouter.ai/api     # un servizio compatibile con OpenAI
```

| Programma | Base URL |
|---|---|
| OpenAI e compatibili (OpenRouter, Mistral, Ollama…) | `http://127.0.0.1:8788/openai/v1` |
| Anthropic (Claude) | `http://127.0.0.1:8788/anthropic` |

In n8n è il campo **Base URL** della credenziale OpenAI o Anthropic. In Python:

```python
from openai import OpenAI
client = OpenAI(base_url="http://127.0.0.1:8788/openai/v1")   # la chiave API resta la tua, passa com'è
```

Copre Chat Completions, Responses, Messages (anche `count_tokens`), Embeddings e gli argomenti degli strumenti. Regole:

- si rimettono solo i segnaposto nati dalla stessa richiesta: un segnaposto scritto apposta non tira fuori dati di altre conversazioni;
- immagini e file allegati sono **rifiutati** (non sappiamo ancora pseudonimizzarli), salvo `--consenti-allegati`;
- le richieste che arrivano da pagine web sono rifiutate; fuori da 127.0.0.1 serve `--chiave` (finisce nel percorso:
  `…/k/CHIAVE/openai/v1`);
- il **registro** (nel pannello) tiene ora, fornitore, modello e quanti dati di che tipo: mai i valori;
- la tabella dei segnaposto resta in memoria e si azzera dopo un'ora senza richieste.

## Claude Desktop e gli agenti MCP

Riserbo è anche un **server MCP**: Claude Desktop legge i tuoi documenti *attraverso* Riserbo e vede solo i segnaposto,
nomi dei file compresi («Contratto [PERSONA_1].docx»). Quando gli chiedi di salvare la risposta o di copiarla negli appunti,
i nomi veri li rimette Riserbo sul tuo computer: il testo con i dati veri non torna mai al modello.

Nell'app: **Automazioni → Claude Desktop**, scegli le cartelle e premi **Collega a Claude Desktop** (la configurazione di
Claude Desktop viene aggiornata con una copia di sicurezza accanto). Poi chiudi e riapri Claude Desktop.

Strumenti: `elenca_documenti`, `leggi_documento` (Word, PDF anche scansionati, Excel, CSV, email, foto), `salva_documento`
(docx, txt, md, csv, xlsx: non sovrascrive), `copia_negli_appunti`. Fuori dalle cartelle scelte non legge nulla.

Da terminale, per qualunque client MCP via stdio:

```json
{"mcpServers": {"riserbo": {"command": "python", "args": ["-m", "riserbo", "mcp", "--cartella", "/Users/io/Clienti"]}}}
```

## Come servizio locale

Per usarlo da un'automazione (n8n, Make in locale), da un gestionale o da un sito:

```bash
riserbo servi --porta 8765          # ascolta solo su 127.0.0.1
curl -X POST localhost:8765/pseudonimizza -d '{"testo": "Scrive Mario Rossi della Bianchi Srl"}'
```

Risponde con il testo pseudonimizzato, i dati trovati e la tabella dei segnaposto, che resta al chiamante. Non salva e non
registra i testi. Un esempio di servizio systemd è in `deploy/riserbo.service`. Non esporlo direttamente su internet.

## Misurare prima di fidarsi

Nessuno strumento trova tutto. Prima di usarlo su un processo vero:

1. prendi **cento testi veri** del processo (email, reclami, schede) e annota a mano cosa va tolto;
2. scrivili in un file JSONL come `esempi/set-di-prova.jsonl`;
3. lancia `riserbo valuta` e guarda due numeri: le **fughe** (quello che resta leggibile) e le **sostituzioni non annotate** (il testo rovinato, che fa lavorare peggio il modello).

Una soglia ragionevole: zero fughe sui dati a forma fissa, sotto l'uno per cento su nomi e aziende, e un controllo a campione in produzione.

## Il canale per l'estensione del browser

L'estensione (cartella `estensione/`, Manifest V3) non contiene il modello: parla con l'app su `127.0.0.1:8789`
(`ponte_browser.py`) con l'intestazione `X-Riserbo-Token`. Le pagine web non possono usare il canale: l'app accetta solo
richieste senza `Origin` o con `Origin` di un'estensione. Percorsi: `/stato`, `/proteggi`, `/valori`, `/nuova`.

## La modalità automatica per le app di AI

`automatica.py`: un thread guarda ogni 0,2 secondi l'app in primo piano (Mac: `NSWorkspace.frontmostApplication`,
Windows: `GetForegroundWindow` e il nome dell'eseguibile) e il contatore degli appunti (`NSPasteboard.changeCount`,
`GetClipboardSequenceNumber`). Entrando in ChatGPT, Claude, Copilot o Perplexity, se gli appunti contengono dati
personali li sostituisce con la versione protetta; uscendo, se dentro l'app è stato copiato qualcosa rimette i nomi veri,
altrimenti rimette il testo di prima. Le app riconosciute sono in `APP_AI`. Si accende dalla Guida, dal menu dell'icona o
con `"automatica": true` nelle impostazioni.

## La pausa

`metti_in_pausa(stato, minuti)` / `riprendi(stato)` in `app.py`: in pausa la modalità automatica non tocca gli appunti e il
canale dell'estensione risponde a `/proteggi` con il testo com'è e `"pausa": {...}`, così l'estensione lo dice a chi scrive.
Scorciatoie e finestra funzionano (agiscono solo se le usi), il **cancello no**: le automazioni non vanno in pausa per
sbaglio. La pausa non si salva: riaprendo l'app si riparte protetti. Allo scadere si riattiva da sola, con una notifica.

## Le impostazioni

Sul computer, in un file JSON: Mac `~/Library/Application Support/riserbo/impostazioni.json`, Windows
`%APPDATA%\riserbo\impostazioni.json`, Linux `~/.config/riserbo/impostazioni.json`. Contiene le scelte della pagina
(«Cosa nascondere», «Sempre in chiaro»: la finestra cambia porta a ogni avvio, quindi il suo localStorage non basterebbe),
cancello, estensione, modalità automatica, cartelle di Claude Desktop. Mai testi né tabelle.

## Il nome

Fino alla versione 0.10 lo strumento si chiamava **segnaposto**: il comando `segnaposto` funziona ancora come alias di
`riserbo`, e al primo avvio l'app sposta da sola impostazioni, avvio all'accensione e voce di Claude Desktop.

## Licenza dei componenti

**Modello del riconoscitore di entità.** [DeepMount00/Italian_NER_XXL_v2](https://huggingface.co/DeepMount00/Italian_NER_XXL_v2),
licenza Apache 2.0, convertito in ONNX int8 dal workflow `modello` e pubblicato nella release
[modello-ner-1](https://github.com/Fabrika-06-Academy/riserbo/releases/tag/modello-ner-1) con le impronte SHA-256 dei file.
Fino alla versione 0.5 si usava il modello spaCy `it_core_news_sm`, che ha licenza CC BY-NC-SA 3.0 (non commerciale):
dalla 0.6 non è più usato né distribuito. OCR: modelli PP-OCRv6 di [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR)
(Apache 2.0) tramite [RapidOCR](https://github.com/RapidAI/RapidOCR). PDF: pypdfium2 (Apache 2.0 / BSD), niente PyMuPDF
(AGPL), così anche le app scaricabili restano MIT.
