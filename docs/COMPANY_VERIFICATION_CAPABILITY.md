# Ciclo di vita della capacità operatore

`scripts/company_verification_capability.py` è l'unico comando locale previsto
per associare, ruotare o recuperare la capacità usata dalla coda di verifica
aziendale. È separato dal comando operativo: non avvia il server, non espone
rotte, non usa la rete e non invia messaggi.

La procedura presuppone accesso amministrativo esclusivo al database e al secret
store. Non sostituisce i controlli del sistema operativo, la custodia separata
dei segreti o i backup gestiti dal provider.

## Condizioni comuni

- arrestare tutti i writer e lavorare su database e directory privati con
  permessi `0600` e `0700`;
- fornire un documento d'intento JSON tramite descrittore ereditato;
- fornire le capacità solo tramite descrittori o variabili d'ambiente;
- indicare un nuovo percorso assoluto, su directory privata, per la copia di
  rollback obbligatoria;
- archiviare insieme la copia SQLite e il relativo file
  `.capability.json`, entrambi `0600`;
- eseguire successivamente il comando operativo `list` con la capacità nuova,
  prima di riaprire i writer.

Il documento d'intento contiene esattamente:

```json
{"operation":"rotate","change_id":"ticket-operativo-univoco-0001","expected_generation":1}
```

`operation` deve coincidere con il comando. `change_id` è una referenza tecnica
non personale di 16–128 caratteri; nel database ne viene conservato soltanto il
digest. `expected_generation` impedisce di applicare un'intenzione obsoleta.
L'associazione iniziale richiede generazione `0`; le altre operazioni usano la
generazione osservata nell'ultima esecuzione riuscita.

La copia di rollback viene creata con l'API backup di SQLite, controllata con
`PRAGMA integrity_check`, resa privata e accompagnata da un manifesto con
dimensione e SHA-256. Il manifesto serve a rilevare errori o manomissioni
accidentali; non autentica il backup contro chi può sostituire sia database sia
manifesto.

## Associazione iniziale

Il database deve avere lo schema della coda ma nessuna associazione preesistente.
Il comando rifiuta un database già associato e non cambia mai una capacità con
`provision`.

```sh
python scripts/company_verification_capability.py \
  --db /percorso/privato/accounts.sqlite3 \
  --intent-fd 3 --new-secret-fd 4 \
  --rollback-db /backup/privato/prima-provision.sqlite3 \
  provision 3</run/operator/provision-intent.json 4</run/secrets/operator-new
```

La capacità deve contenere 32–256 byte. La procedura registra una nuova identità
casuale del database e la generazione `1`. La copia di rollback documenta lo
stato non associato, ma non è accettata come sorgente di recovery.

## Rotazione

`rotate` richiede capacità corrente e nuova, diverse tra loro. Autenticazione e
generazione vengono controllate prima di creare il backup; la sostituzione del
fingerprint e l'incremento della generazione avvengono nella stessa transazione.
Se il database contiene un'associazione della versione precedente ma non i
metadati di ciclo di vita, la prima rotazione assegna la stessa identità casuale
alla copia di rollback e al database corrente. La copia viene verificata prima
di modificare il database corrente e rimane quindi utilizzabile per il recovery.

```sh
python scripts/company_verification_capability.py \
  --db /percorso/privato/accounts.sqlite3 \
  --intent-fd 3 --current-secret-fd 4 --new-secret-fd 5 \
  --rollback-db /backup/privato/prima-rotazione.sqlite3 \
  rotate 3</run/operator/rotate-intent.json \
  4</run/secrets/operator-current 5</run/secrets/operator-new
```

Al termine, la vecchia capacità deve fallire e quella nuova deve superare un
`list`. La copia `prima-rotazione.sqlite3` conserva lo stato precedente e può
essere usata per il recovery soltanto insieme alla capacità precedente.

## Recovery dopo perdita della capacità corrente

`recover` non azzera l'associazione e non accetta un valore arbitrario. Richiede:

1. un backup creato prima di una rotazione, con manifesto integro;
2. la capacità che corrisponde al fingerprint di quel backup;
3. la stessa identità database nel backup e nel database corrente;
4. una generazione del backup strettamente precedente a quella corrente;
5. un nuovo backup dello stato corrente prima della modifica.

```sh
python scripts/company_verification_capability.py \
  --db /percorso/privato/accounts.sqlite3 \
  --intent-fd 3 --new-secret-fd 4 \
  --rollback-db /backup/privato/prima-recovery.sqlite3 \
  recover --source-backup /backup/privato/prima-rotazione.sqlite3 \
  3</run/operator/recovery-intent.json 4</run/secrets/operator-previous
```

Il recovery rende nuovamente valida la capacità del backup, ma incrementa la
generazione corrente: la cronologia non viene riavvolta. Un backup di un altro
database, una copia manomessa, una generazione uguale o futura e una capacità
non corrispondente vengono rifiutati prima di creare il nuovo rollback.

Se non è disponibile nessuna capacità precedente con il relativo backup, la
procedura fallisce chiusa. Non modificare manualmente la tabella: isolare il
database e applicare una procedura forense approvata e verificabile.

## Output e codici

L'output è una sola riga JSON depurata. Conferma operazione, generazione,
controllo dell'associazione e creazione/verifica del rollback. Non contiene
capacità, fingerprint, change id, digest, percorsi o dati dell'azienda.

| Exit | Significato |
|---:|---|
| 0 | operazione e verifiche completate |
| 2 | argomenti, sorgenti o intento non validi |
| 3 | stato, autorizzazione, generazione o backup non compatibili |
| 4 | database, manifesto o storage non affidabili |
| 6 | errore interno chiuso |

Su un esito diverso da zero, non ritentare con una nuova intenzione finché non
è stato verificato se esistono la copia di rollback e il relativo manifesto. Un
ritento della stessa attività conserva lo stesso `change_id` e la stessa
generazione attesa.
