# Comando offline per la verifica aziendale

`scripts/company_verification_operator.py` è l'interfaccia locale protetta per
consultare le pratiche pendenti, registrare una ricevuta delle prove esaminate,
registrare una decisione codificata e verificare la relativa catena audit. Non
avvia il server, non espone rotte HTTP, non usa la rete e non invia messaggi. La
verifica umana e l'acquisizione dei documenti restano processi separati: la CLI
legge i byte da un descrittore, conserva soltanto SHA-256 e metadati tecnici e
non archivia il contenuto.

## Prerequisiti

- usare una copia esistente del database account, file regolare non vuoto con
  permessi `0600`;
- arrestare l'operazione se il controllo SQLite, lo schema, la capacità o la
  catena audit non sono validi;
- fornire la stessa capacità di almeno 32 byte associata in precedenza al
  database;
- predisporre un riferimento operatore non personale e una chiave idempotente
  nuova per ogni decisione logica.

Il file descriptor è la fonte consigliata per la capacità. Il suo contenuto può
terminare con una singola nuova riga. In alternativa il comando legge
`SLPS_VERIFICATION_OPERATOR_SECRET`. Il valore della capacità non è mai accettato
come argomento CLI. Il percorso database proviene da `SLPS_ACCOUNT_DB_PATH` o da
`--db`; una capacità mancante, corta, ambigua o diversa da quella associata al
database blocca l'operazione.

L'associazione iniziale, la rotazione e il recupero della capacità appartengono
alla procedura fidata separata descritta in
[`COMPANY_VERIFICATION_CAPABILITY.md`](COMPANY_VERIFICATION_CAPABILITY.md) e non
sono implementate da questa CLI. Prima di
costruire lo store, ogni comando richiede in sola lettura la tabella
`account_verification_operator_meta`, la riga `singleton=1` e un fingerprint
valido corrispondente alla capacità fornita. Se tabella o riga mancano, il
database account usato normalmente dal server resta invariato e `list`,
`audit`, `approve` e `reject` falliscono. Il comando non crea la tabella, non
inserisce la riga e non associa o ruota implicitamente una capacità.

Esempio con descrittore ereditato da un secret store locale:

```sh
python scripts/company_verification_operator.py \
  --db /percorso/privato/accounts.sqlite3 --secret-fd 3 list 3</run/secrets/operator
```

La coda restituisce soltanto l'identificatore casuale della pratica, tipo,
stato, codice decisione, tempi e versione. Non restituisce identificatori di
azienda o utente, nomi, email, domini, ruoli, capacità, digest audit o chiavi
idempotenti. `--limit` accetta da 1 a 200 e la coda include solo pratiche
`pending`.

## Ricevute delle prove

`evidence` richiede una pratica ancora pendente, una categoria ammessa, un
descrittore contenente il documento già acquisito in modo autorizzato e un
secondo descrittore con metadati JSON. Il documento non viene scritto su disco;
il comando calcola SHA-256 mentre opera offline. Il JSON contiene esattamente:

```json
{"verifier_ref":"operator-code","idempotency_key":"verification:receipt:unique-0001","observed_at_utc":"2026-10-01T09:00:00Z","verified_at_utc":"2026-10-01T09:10:00Z","expires_at_utc":"2027-01-01T00:00:00Z"}
```

```sh
python scripts/company_verification_operator.py \
  --db /percorso/privato/accounts.sqlite3 --secret-fd 3 \
  evidence REVIEW_ID --category commercial_register_extract \
  --evidence-fd 4 --receipt-fd 5 \
  3</run/secrets/operator 4</run/evidence/documento \
  5</run/operator/receipt.json
```

Le categorie sono circoscritte al tipo di pratica:

| Pratica | Categorie ammesse |
|---|---|
| `company_representative` | `commercial_register_extract`, `representative_authority_record` |
| `membership` | `membership_authority_record` |

La ricevuta è append-only e legata a `review_id`; conserva categoria, digest,
tempi, digest del verificatore e chiave idempotente sotto HMAC. L'output mostra
soltanto ID casuale, categoria, tempi e `integrity_verified`. Non mostra digest,
contenuto, riferimenti operatore, percorsi o dati personali. Tempi futuri,
ricevute già scadute, categorie estranee e riuso incoerente della chiave vengono
rifiutati.

## Decisioni

`approve` e `reject` richiedono l'identificatore pratica e `--reason`. Il
riferimento operatore e la chiave idempotente arrivano insieme da un JSON letto
con `--decision-fd`, oppure separatamente dalle variabili
`SLPS_VERIFICATION_OPERATOR_REF` e
`SLPS_VERIFICATION_IDEMPOTENCY_KEY`. Fornire contemporaneamente descrittore e
variabili blocca il comando. Il JSON sul descrittore contiene esattamente:

```json
{"operator_ref":"operator-code","idempotency_key":"verification:unique-operation-key-0001"}
```

Esempio di approvazione, con entrambi i descrittori aperti da un processo
fidato:

```sh
python scripts/company_verification_operator.py \
  --db /percorso/privato/accounts.sqlite3 --secret-fd 3 \
  approve REVIEW_ID --reason identity_and_authority_confirmed \
  --decision-fd 4 \
  --evidence-receipt RECEIPT_REGISTRY \
  --evidence-receipt RECEIPT_AUTHORITY \
  3</run/secrets/operator 4</run/operator/decision.json
```

I codici ammessi dipendono dal tipo di pratica e dalla decisione:

| Pratica | Decisione | Codici ammessi |
|---|---|---|
| `company_representative` | approva | `identity_and_authority_confirmed` |
| `company_representative` | rifiuta | `company_identity_unverified`, `representative_authority_unverified`, `conflicting_company_record`, `insufficient_evidence` |
| `membership` | approva | `membership_confirmed` |
| `membership` | rifiuta | `membership_unverified`, `insufficient_evidence` |

L'approvazione `membership` viene rifiutata finché l'azienda non è verificata.
L'approvazione aziendale richiede entrambe le categorie aziendali; quella di
appartenenza richiede `membership_authority_record`. Anche un rifiuto richiede
almeno una ricevuta pertinente e i motivi specifici richiedono la categoria
corrispondente. Ricevute assenti, scadute, di un'altra pratica o con integrità
incoerente bloccano la decisione.
La decisione, l'aggiornamento dei flag e l'evento audit avvengono nella stessa
transazione SQLite. Il digest del pacchetto e i collegamenti alle ricevute
entrano nella catena audit append-only. Ripetere la stessa decisione con identici codice,
riferimento operatore e chiave restituisce lo stesso risultato senza aggiungere
eventi soltanto con lo stesso insieme di ricevute; riusare la chiave per
un'altra decisione o un altro pacchetto fallisce.

## Audit e output

```sh
python scripts/company_verification_operator.py \
  --db /percorso/privato/accounts.sqlite3 --secret-fd 3 \
  audit REVIEW_ID 3</run/secrets/operator
```

`audit` ricalcola tutta la catena nel medesimo snapshot e restituisce
`chain_valid: true` con sequenza, tipo evento, codice decisione, tempo e
`evidence_bound`. I digest
interni, compreso quello dell'operatore, non vengono proiettati. Anche `list` e
la decisione validano la catena; una catena incoerente blocca ogni operazione.

Ogni invocazione scrive una sola riga JSON su standard output, anche in caso di
errore. Gli exit code sono:

| Exit | Significato |
|---:|---|
| 0 | operazione completata |
| 2 | argomenti o input operativi non validi |
| 3 | capacità assente, non predisposta, invalida o non autorizzata |
| 4 | database, ricevuta o catena audit non affidabili |
| 5 | conflitto sullo stato della pratica o sull'idempotenza |
| 6 | errore interno chiuso |

Gli errori usano solo codici fissi e non includono percorso, valori di input o
dettagli SQLite. Prima di ritentare, conservare la stessa chiave idempotente se
si tratta della stessa decisione logica. Su exit 4 non modificare direttamente
il database: isolare la copia, verificare il supporto durevole e ripristinare da
un backup validato prima di riprendere le decisioni.
