# Fondazione locale dello storico privato

Questa fondazione conserva ogni caso senza una scadenza automatica: rapporto e
contesto in SQLite, originali foto/video e artefatti derivati in una cartella
privata separata. Il master 1.8 non viene copiato nello storico. Il video con
audio è supportato dal formato dell'archivio, ma l'endpoint di analisi video AI
resta disattivato: la conservazione effettiva del video verrà collegata quando
la relativa pipeline sarà disponibile e collaudata.

## Dati e autorizzazioni

- Ogni file appartiene a un caso, a un'azienda (`tenant_id`) e a un utente
  (`owner_id`). Elenco, apertura, download e cancellazione richiedono la
  sessione valida e applicano entrambi i filtri. L'identificativo del file o del
  caso, da solo, non concede accesso.
- I nomi di percorso sul disco sono generati dal server. Il nome originale è
  soltanto metadato; non decide mai dove scrivere un file.
- Cartelle e file vengono creati rispettivamente con permessi locali `0700` e
  `0600`. Il database contiene impronta SHA-256, tipo, ruolo e dimensione, non i
  contenuti binari.
- I ruoli predisposti sono `original`, `normalized`, `crop`, `frame`, `audio`,
  `transcript` e `derived`. Il rapporto JSON è legato direttamente al caso.
- La condivisione tra colleghi della stessa azienda non è ancora attiva: lo
  storico rimane privato al proprietario, oltre che isolato per azienda.

La cartella indicata da `SLPS_HISTORY_ROOT` e il database indicato da
`SLPS_CASE_DB_PATH` devono essere sullo stesso ambiente privato e persistente.
Il codice applicativo non fornisce cifratura a riposo: disco cifrato, gestione
delle chiavi, snapshot e accessi amministrativi dipendono dall'infrastruttura e
devono essere verificati prima di usare dati reali.

## Capacità senza cancellazione automatica

`SLPS_MAX_HISTORY_BYTES_PER_TENANT` è il limite totale dei file per azienda. Il
valore predefinito locale è 1 GiB. All'80% lo stato dell'archivio espone un
avviso; se il nuovo caso supera il limite, il salvataggio viene rifiutato e i
casi già presenti restano invariati e consultabili. Non vengono acquistati
automaticamente spazio o servizi e non viene eliminato il caso più vecchio.

Il limite di numero casi per proprietario resta separato. La dimensione del
database, gli snapshot e l'eventuale spazio temporaneo non sono inclusi nel
contatore: il dimensionamento commerciale richiede misure sull'ambiente scelto.

## Cancellazione

La cancellazione autorizzata registra prima una richiesta persistente, rende il
caso non consultabile e sposta la directory fuori dallo spazio attivo. Il record
del caso viene eliminato soltanto dopo la rimozione effettiva dei file. Se il
filesystem rifiuta la rimozione, il server restituisce un errore, conserva caso
e richiesta di cancellazione e mostra nello storico l'azione per ritentare. Un
secondo tentativo riprende lo stesso percorso; non viene dichiarato successo
finché la cartella non è scomparsa. Se invece il filesystem è già pulito ma
fallisce l'ultima transazione, la traccia resta ugualmente ritentabile.

Questa è cancellazione logica e fisica dal filesystem attivo. Non garantisce la
sovrascrittura forense su SSD, storage a blocchi o copie del provider. La
politica delle copie deve definire durata, accesso e cancellazione differita
prima dei dati reali.

## Backup e ripristino

`CaseStore.backup(destination)` crea una copia SQLite coerente e copia soltanto
i file elencati nei metadati, verificando dimensione e SHA-256 di database e
file. Il manifesto deve corrispondere esattamente all'indice. Il manifesto non
contiene credenziali. `CaseStore.restore(backup, target_db, target_media_root,
capacity)` rifiuta destinazioni non vuote e file alterati.

I test usano un video sintetico con traccia audio, un estratto audio, un
fotogramma e una trascrizione. Questo prova il ciclo locale del codice, non la
durabilità, la cifratura o il ripristino del provider. Prima dello staging con
dati reali occorre eseguire sul provider: snapshot coordinato di database e
file, ripristino in un ambiente isolato, verifica delle impronte, apertura del
caso con l'account corretto e rifiuto da un'altra azienda.

## Chiusura di un account

La procedura operativa prevista, da approvare prima dell'onboarding esterno, è:

1. sospendere login, nuove analisi e upload dell'utente;
2. verificare identità, azienda, casi condivisi e obblighi contrattuali o legali;
3. offrire l'eventuale esportazione prevista dal piano e registrare la scelta;
4. eseguire il job autorizzato che chiama `delete_owner_history(tenant, owner)`;
5. verificare che casi, metadati e file attivi non siano più accessibili;
6. disattivare l'identità e revocare le sessioni nel registro account;
7. applicare alle copie di sicurezza la politica approvata e registrare il suo
   completamento senza conservare media o dati personali nei log.

La chiusura dell'ultimo utente non deve eliminare implicitamente l'intera
azienda: proprietà, contenziosi, casi di altri utenti e cancellazione aziendale
richiedono una decisione distinta. Non è codificato alcun termine arbitrario di
30 giorni.
