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
| 1. Regole | codice fiscale (anche con omocodia), partita IVA, IBAN, email, telefoni, targhe | forma fissa e **controllo delle cifre di verifica**, così un numero a caso non viene scambiato per un IBAN |
| 1. Anagrafica e codici tuoi | i nomi dei tuoi clienti e fornitori, i codici di commesse e ordini | un CSV esportato dal gestionale, espressioni regolari tue |
| 2. Riconoscitore di entità | persone, aziende, luoghi | modello spaCy italiano tramite [Presidio](https://github.com/data-privacy-stack/presidio) |
| 3. Controllo finale (facoltativo) | quello che è sfuggito: «il figlio del titolare», un soprannome | una funzione tua, per esempio un modello piccolo in casa |

Lo stesso valore riceve sempre lo stesso segnaposto nella stessa pratica, così il modello capisce che si parla della stessa persona.

## Scarica l'app (Mac e Windows)

Per usarlo ogni giorno con ChatGPT, Claude o Copilot, senza installare niente: scarica l'app dalla pagina
[Releases](https://github.com/Fabrika-06-Academy/segnaposto/releases), su Mac apri il file `.dmg` e trascina segnaposto in Applicazioni, su Windows decomprimi lo zip e apri `segnaposto.exe`. Si apre nel browser, gira solo sul tuo computer.

1. Incolli il testo e premi **Pseudonimizza**: copi il risultato nella chat.
2. Incolli la risposta della chat e premi **Rimetti i valori veri**: l'app sostituisce i segnaposto e ti avvisa se la chat
   ne ha persi o inventati.
3. **Nuova pratica** cancella la tabella; chiudendo l'app si cancella comunque.

**Primo avvio su Mac.** L'app non è firmata con un certificato Apple a pagamento, quindi la prima volta macOS la blocca
(«non è possibile verificare lo sviluppatore»). Aprila una volta con doppio clic, poi vai in *Impostazioni di Sistema →
Privacy e sicurezza* e premi **Apri comunque**. In alternativa, da Terminale: `xattr -dr com.apple.quarantine segnaposto.app`.
Il codice è tutto qui: se preferisci, puoi installarlo con Python come descritto sotto.

**Primo avvio su Windows.** SmartScreen può mostrare «Windows ha protetto il PC»: *Ulteriori informazioni → Esegui comunque*.

## Installazione con Python

```bash
python -m venv .venv && . .venv/bin/activate
pip install segnaposto   # oppure, dal repository: pip install -e .
pip install https://github.com/explosion/spacy-models/releases/download/it_core_news_sm-3.8.0/it_core_news_sm-3.8.0-py3-none-any.whl
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
segnaposto app            # apre l'interfaccia nel browser, su 127.0.0.1 con una chiave casuale
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

- Il riconoscitore di entità `it_core_news_sm` è piccolo e veloce, ma sbaglia sui cognomi che sono anche parole comuni (Ferro, Costa) e sui nomi in minuscolo. Per testi difficili usa `it_core_news_lg` o aggiungi lo strato 3.
- Indirizzi, date di nascita e importi non vengono sostituiti di proposito: spesso servono al modello per fare il lavoro. Se nel tuo caso vanno tolti, aggiungi un riconoscitore.
- I PDF vanno prima convertiti in testo.

## Licenza

MIT. © 2026 Andrea Prando, [Fabrika 06](https://fabrika06.com).

---

### In English

`segnaposto` ("placeholder") pseudonymises Italian text before it is sent to a cloud LLM, and restores the original values in
the answer. It is built on Microsoft's Presidio with Italian recognisers that check the codes (fiscal code with *omocodia*,
VAT number, IBAN, number plates), a customer list exported from the ERP, your own business codes, spaCy's Italian NER, and an
optional final check by a local model. The placeholder table stays on your machine (JSON, mode 600, with an expiry date). It also
checks that the LLM did not drop or invent placeholders, and includes an evaluation command to measure leaks on your own test set.
Pseudonymised data is still personal data under the GDPR: this tool lowers the risk, it does not remove your obligations.
