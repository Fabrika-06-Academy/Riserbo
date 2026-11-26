# segnaposto

**Pseudonimizzare testi italiani prima di mandarli a un modello in cloud, e rimettere i valori veri al ritorno.**

```
Buongiorno, sono Mario Rossi della Bianchi Srl. CF RSSMRA80A01L840J, IBAN IT60 X054 2811 1010 0000 0123 456.
                                   ↓ segnaposto pseudonimizza
Buongiorno, sono [PERSONA_1] della [CLIENTE_1]. CF [CODICE_FISCALE_1], IBAN [IBAN_1].
```

Il modello in cloud lavora sul testo con i segnaposto. Quando la risposta torna, `segnaposto ripristina` rimette i nomi veri
e controlla che il modello non abbia perso o inventato segnaposto. La tabella che collega segnaposto e valori resta in casa tua.

Fa parte dei progetti della [Fabrika 06 Academy](https://academy.fabrika06.com), i corsi gratuiti sull'intelligenza
artificiale per le aziende. Il metodo è spiegato nel corso
[Dati protetti e dati dal web](https://academy.fabrika06.com/corso/dati-protetti-dati-dal-web/).

> **Pseudonimizzare non è anonimizzare.** Finché esiste la tabella per tornare indietro, per te quelli restano dati personali:
> il contratto con il fornitore del modello (DPA), il registro dei trattamenti e l'informativa servono comunque.
> `segnaposto` riduce il rischio, non toglie gli obblighi.

## Come funziona: tre strati

| Strato | Cosa trova | Come |
|---|---|---|
| 1. Regole | codice fiscale (anche con omocodia), partita IVA, IBAN, email, telefoni, targhe, indirizzi con civico | forma fissa e **controllo delle cifre di verifica**, così un numero a caso non viene scambiato per un IBAN |
| 1. Anagrafica e codici tuoi | i nomi dei tuoi clienti e fornitori, i codici di commesse e ordini | un CSV esportato dal gestionale, espressioni regolari tue |
| 1. Colonne riconosciute | in Excel e CSV, intere colonne «Nome», «Ragione sociale», «Email», «Codice fiscale», «Indirizzo»… | l'intestazione dice cosa c'è sotto: il valore viene nascosto anche dove compare nel resto del documento |
| 2. Riconoscitore di entità | persone, aziende, luoghi, e poi età, date di nascita, dati sanitari, documenti, conti, password, IP, dati catastali | un BERT italiano con oltre 50 categorie ([DeepMount00/Italian_NER_XXL_v2](https://huggingface.co/DeepMount00/Italian_NER_XXL_v2), Apache 2.0) eseguito in locale con ONNX Runtime, dentro [Presidio](https://github.com/data-privacy-stack/presidio) |
| 3. Controllo finale (facoltativo) | quello che è sfuggito: «il figlio del titolare», un soprannome | una funzione tua, per esempio un modello piccolo in casa |

Lo stesso valore riceve sempre lo stesso segnaposto nella stessa pratica, così il modello capisce che si parla della stessa persona.

## Scarica l'app (Mac e Windows)

Per usarlo ogni giorno con ChatGPT, Claude o Copilot, senza installare Python: scarica l'app dalla pagina
[Releases](https://github.com/Fabrika-06-Academy/segnaposto/releases). Su Mac apri il file `.dmg` e trascina segnaposto in
Applicazioni; su Windows decomprimi lo zip e apri `segnaposto.exe`. Si apre in una finestra sua e gira solo sul tuo computer.

1. **Incolla un testo o trascina un documento**: Word (.docx), PDF anche scansionati, foto di documenti, Excel (.xlsx), CSV,
   email di Outlook (.msg) e di Mail (.eml) con gli allegati, testo semplice. Puoi anche incollare uno screenshot.
   Premi **Pseudonimizza** (⌘/Ctrl + Invio).
2. **Rileggi e correggi**: clic su un segnaposto per rimettere in chiaro un falso allarme, seleziona una parola per nasconderla
   ovunque. Le correzioni valgono per tutta la pratica.
3. **Copia o salva** il risultato nel formato che ti serve (.docx, .xlsx, .csv, .txt): un Excel torna Excel, con le colonne
   al loro posto e i numeri ancora numeri. Da un PDF o da una foto puoi creare il **PDF oscurato**: le pagine originali con i
   dati coperti da rettangoli neri e il segnaposto sopra. È fatto di sole immagini, quindi sotto i rettangoli non resta
   testo da copiare.
4. **Incolla la risposta della chat** e premi **Rimetti i valori veri**: l'app sostituisce i segnaposto e ti avvisa se la
   chat ne ha persi o inventati. Anche la risposta si può salvare come file.
5. **Nuova pratica** cancella la tabella; chiudendo l'app si cancella comunque.

**Da qualunque programma, con gli appunti.** Lascia l'app aperta e lavora dove vuoi (Outlook, il gestionale, WhatsApp Web):
copi il testo, premi **⌃⌥P** su Mac (**Ctrl+Alt+P** su Windows) e negli appunti trovi la versione con i segnaposto, da
incollare nella chat. Copi la risposta, premi **⌃⌥R** (**Ctrl+Alt+R**) e tornano i nomi veri. Una notifica conferma
quanti dati sono stati sostituiti. Su Mac le scorciatoie non richiedono il permesso di Accessibilità. Se un altro
programma le usa già, nel pannello «Appunti» ci sono gli stessi comandi come pulsanti.

**Sempre pronta, senza finestra.** Chiudendo la finestra segnaposto resta nell'icona **[–]** vicino all'orologio (barra dei
menu su Mac, area di notifica su Windows) e le scorciatoie continuano a funzionare. Dall'icona riapri la finestra, proteggi
o ripristini gli appunti, inizi una nuova pratica, scegli **Apri all'accensione** ed esci davvero. Dopo un'ora senza usarla
la tabella della pratica si cancella da sola: i dati veri non restano in memoria per giorni.

**Cosa esce dal computer, e solo se lo vuoi.** I testi e i documenti mai. All'avvio l'app chiede a GitHub il numero
dell'ultima versione, per proporti l'aggiornamento (si spegne in «Cosa nascondere → Aggiornamenti»). Il pannello
**Parere** manda all'Academy solo quello che scrivi lì, con versione e sistema operativo, quando premi «Invia».
Su Mac l'aggiornamento si scarica con un clic ma si installa a mano (trascinando in Applicazioni): l'installazione
automatica richiede la firma Apple, che arriverà quando l'app avrà una diffusione ampia.

**Primo avvio su Mac.** L'app non è firmata con un certificato Apple a pagamento, quindi la prima volta macOS la blocca
(«non è possibile verificare lo sviluppatore»). Aprila una volta con doppio clic, poi vai in *Impostazioni di Sistema →
Privacy e sicurezza* e premi **Apri comunque**. In alternativa, da Terminale: `xattr -dr com.apple.quarantine segnaposto.app`.
Il codice è tutto qui: se preferisci, puoi installarlo con Python come descritto sotto.

**Primo avvio su Windows.** SmartScreen può mostrare «Windows ha protetto il PC»: *Ulteriori informazioni → Esegui comunque*.

## Installazione con Python

```bash
python -m venv .venv && . .venv/bin/activate
# Non è (ancora) su PyPI: si installa direttamente da GitHub
pip install "segnaposto @ git+https://github.com/Fabrika-06-Academy/segnaposto"
# con documenti, OCR e finestra dell'app:
# pip install "segnaposto[app] @ git+https://github.com/Fabrika-06-Academy/segnaposto"
# oppure, da una copia del repository: pip install -e ".[app]"
segnaposto scarica-modello   # il riconoscitore di entità, circa 110 MB, una volta sola (altrimenti lo scarica al primo uso)
```

Tutto gira sul tuo computer o sul tuo server. Nessun dato viene mandato fuori.

## Uso da terminale

```bash
# Pseudonimizzare: la tabella va in un file a parte (permessi 600, scade dopo 30 giorni)
segnaposto pseudonimizza email.txt --tabella pratica-123.tabella.json --anagrafica clienti.csv --mostra > email-pulita.txt

# ... email-pulita.txt va al modello in cloud, la risposta torna in risposta.txt ...

# Ripristinare: esce con codice 2 se il modello ha inventato segnaposto
segnaposto ripristina risposta.txt --tabella pratica-123.tabella.json > risposta-vera.txt

# Misurare le fughe sul tuo set di prova
segnaposto valuta esempi/set-di-prova.jsonl --anagrafica esempi/anagrafica.csv
```

## Uso da Python

```python
from segnaposto import Segnaposto, Tabella, ripristina
from segnaposto.riconoscitori import carica_anagrafica, riconoscitore_codice

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
pip install "segnaposto[app] @ git+https://github.com/Fabrika-06-Academy/segnaposto"   # documenti, OCR e finestra nativa
segnaposto app            # finestra nativa; senza pywebview, o con --browser, si apre nel browser (127.0.0.1, chiave casuale)
```

## Come servizio locale

Per usarlo da un'automazione (n8n, Make in locale), da un gestionale o da un sito:

```bash
segnaposto servi --porta 8765          # ascolta solo su 127.0.0.1
curl -X POST localhost:8765/pseudonimizza -d '{"testo": "Scrive Mario Rossi della Bianchi Srl"}'
```

Risponde con il testo pseudonimizzato, i dati trovati e la tabella dei segnaposto, che resta al chiamante. Non salva e non
registra i testi. Un esempio di servizio systemd è in `deploy/segnaposto.service`. Non esporlo direttamente su internet.

## Misurare prima di fidarsi

Nessuno strumento trova tutto. Prima di usarlo su un processo vero:

1. prendi **cento testi veri** del processo (email, reclami, schede) e annota a mano cosa va tolto;
2. scrivili in un file JSONL come `esempi/set-di-prova.jsonl`;
3. lancia `segnaposto valuta` e guarda due numeri: le **fughe** (quello che resta leggibile) e le **sostituzioni non annotate** (il testo rovinato, che fa lavorare peggio il modello).

Una soglia ragionevole: zero fughe sui dati a forma fissa, sotto l'uno per cento su nomi e aziende, e un controllo a campione in produzione.

## Limiti noti

- Il riconoscitore di entità sbaglia ancora su qualche nome scritto tutto in minuscolo dopo un articolo («la sara») e su aziende senza forma giuridica poco note. Sul set di prova `esempi/ner-prova.txt` (88 entità in testi di PMI) lascia scoperte 1-2 entità e non dà falsi allarmi; il vecchio modello spaCy ne lasciava 6, con 9 falsi allarmi. Le correzioni a mano dell'app coprono il resto.
- Gli indirizzi vengono sostituiti quando hanno il numero civico; una città da sola dipende dal riconoscitore di entità, che sui piccoli comuni sbaglia spesso. Date di nascita e importi restano di proposito (servono al modello), salvo nelle colonne di un Excel intitolate così.
- Scansioni e foto si leggono con l'OCR ([PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) PP-OCRv6 tramite
  [RapidOCR](https://github.com/RapidAI/RapidOCR), in locale): ottimo sui documenti stampati, meno sulla scrittura a mano.
  L'app avvisa quando un testo viene dall'OCR: confrontalo con l'originale. Se un dato non viene ritrovato sulla pagina,
  il PDF oscurato lo dice.
- Le email .msg con il corpo solo in RTF non si leggono: copia il testo dall'email.

## Licenza

MIT. © 2026 Andrea Prando, [Fabrika 06](https://fabrika06.com).

**Modello del riconoscitore di entità.** [DeepMount00/Italian_NER_XXL_v2](https://huggingface.co/DeepMount00/Italian_NER_XXL_v2),
licenza Apache 2.0, convertito in ONNX int8 dal workflow `modello` e pubblicato nella release
[modello-ner-1](https://github.com/Fabrika-06-Academy/segnaposto/releases/tag/modello-ner-1) con le impronte SHA-256 dei file.
Fino alla versione 0.5 segnaposto usava il modello spaCy `it_core_news_sm`, che ha licenza CC BY-NC-SA 3.0 (non
commerciale): dalla 0.6 non è più usato né distribuito.

---

### In English

`segnaposto` ("placeholder") pseudonymises Italian text before it is sent to a cloud LLM, and restores the original values in
the answer. It is built on Microsoft's Presidio with Italian recognisers that check the codes (fiscal code with *omocodia*,
VAT number, IBAN, number plates), a customer list exported from the ERP, your own business codes, spaCy's Italian NER, and an
optional final check by a local model. The placeholder table stays on your machine (JSON, mode 600, with an expiry date). It also
checks that the LLM did not drop or invent placeholders, and includes an evaluation command to measure leaks on your own test set.
Pseudonymised data is still personal data under the GDPR: this tool lowers the risk, it does not remove your obligations.
