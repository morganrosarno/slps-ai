# Comando offline per la verifica aziendale

`scripts/company_verification_operator.py` è l'interfaccia locale protetta per
consultare le pratiche pendenti, registrare una decisione codificata e verificare
la relativa catena audit. Non avvia il server, non espone rotte HTTP, non usa la
rete e non invia messaggi. Il comando non acquisisce né mostra le prove usate
dall'operatore: la verifica umana resta un processo separato.

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
  --decision-fd 4 3</run/secrets/operator 4</run/operator/decision.json
```

I codici ammessi dipendono dal tipo di pratica e dalla decisione:

| Pratica | Decisione | Codici ammessi |
|---|---|---|
| `company_representative` | approva | `identity_and_authority_confirmed` |
| `company_representative` | rifiuta | `company_identity_unverified`, `representative_authority_unverified`, `conflicting_company_record`, `insufficient_evidence` |
| `membership` | approva | `membership_confirmed` |
| `membership` | rifiuta | `membership_unverified`, `insufficient_evidence` |

L'approvazione `membership` viene rifiutata finché l'azienda non è verificata.
La decisione, l'aggiornamento dei flag e l'evento audit avvengono nella stessa
transazione SQLite. Ripetere la stessa decisione con identici codice,
riferimento operatore e chiave restituisce lo stesso risultato senza aggiungere
eventi; riusare la chiave per un'altra decisione fallisce.

## Audit e output

```sh
python scripts/company_verification_operator.py \
  --db /percorso/privato/accounts.sqlite3 --secret-fd 3 \
  audit REVIEW_ID 3</run/secrets/operator
```

`audit` ricalcola tutta la catena nel medesimo snapshot e restituisce
`chain_valid: true` con sequenza, tipo evento, codice decisione e tempo. I digest
interni, compreso quello dell'operatore, non vengono proiettati. Anche `list` e
la decisione validano la catena; una catena incoerente blocca ogni operazione.

Ogni invocazione scrive una sola riga JSON su standard output, anche in caso di
errore. Gli exit code sono:

| Exit | Significato |
|---:|---|
| 0 | operazione completata |
| 2 | argomenti o input operativi non validi |
| 3 | capacità assente, non predisposta, invalida o non autorizzata |
| 4 | database o catena audit non affidabili |
| 5 | conflitto sullo stato della pratica o sull'idempotenza |
| 6 | errore interno chiuso |

Gli errori usano solo codici fissi e non includono percorso, valori di input o
dettagli SQLite. Prima di ritentare, conservare la stessa chiave idempotente se
si tratta della stessa decisione logica. Su exit 4 non modificare direttamente
il database: isolare la copia, verificare il supporto durevole e ripristinare da
un backup validato prima di riprendere le decisioni.
