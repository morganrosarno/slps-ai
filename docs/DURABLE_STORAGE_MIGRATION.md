# Migrazione dello storage prima dei dati reali

Il servizio Render free osservato usa un filesystem effimero. SQLite e media
locali sono quindi adatti soltanto a test sintetici: un deploy, riavvio o cambio
istanza può eliminarli. Il checkout sandbox non cambia questo limite e non deve
essere usato come prova di persistenza produttiva.

Il servizio dichiara questa separazione con `SLPS_DATA_MODE`: `synthetic` è il
default e conserva il comportamento del pilota. `real` richiede il profilo
`SLPS_DURABLE_PROFILE=single-instance`, una radice montata già esistente e una
riserva minima di capacità. Account e billing condividono un SQLite; limiti e
casi usano due SQLite distinti; i media hanno una cartella distinta. Ogni
percorso deve essere assoluto, sotto la radice risolta, senza symlink e senza
sovrapposizioni. Una configurazione incompleta si arresta prima di creare file.
Anche una configurazione completa non abilita oggi `real`: manca ancora
l'evidenza operativa di restart, redeploy e ripristino sul provider, che non può
essere auto-certificata da una variabile d'ambiente.

Questo profilo supporta esclusivamente un processo applicativo e una singola
istanza. La sua convalida locale non certifica il mount del provider, restart,
redeploy, cifratura o conservazione. Queste prove restano condizioni di
accettazione prima dell'uso commerciale.

## Snapshot e ripristino del profilo single-instance

1. Arrestare servizio, worker e ogni altro writer. Lo snapshot rifiuta di
   procedere senza `--confirm-quiesced`; il flag è un'attestazione operativa,
   non un meccanismo che arresta processi.
2. Eseguire `python scripts/durable_snapshot.py backup /backup/assoluto
   --confirm-quiesced`. La destinazione deve essere nuova e fuori dalla radice
   sorgente.
3. Conservare la directory completa. Il manifest include layout relativo,
   dimensione e SHA-256 di ogni SQLite e media. Ogni SQLite è copiato tramite
   la sua API di backup e sottoposto a `PRAGMA integrity_check`.
4. Provare `python scripts/durable_snapshot.py restore /backup/assoluto
   /radice/vuota`. Il restore rifiuta file inattesi, checksum alterati, symlink,
   path traversal, database mancanti, spazio insufficiente e destinazioni non
   vuote; prepara tutto in una directory privata e la rinomina solo a verifica
   completa.
5. Avviare una copia isolata sulla radice ripristinata e verificare login,
   contatori, casi, media e isolamento aziendale. Registrare la prova di restart
   e restore del provider separatamente: il repository non la dichiara.

Le impronte SHA-256 rilevano corruzioni o differenze rispetto al manifesto. Non
autenticano il backup contro chi può modificare sia i file sia il manifesto;
la custodia e il controllo accessi del backup restano responsabilità operativa.

## Contratti e migrazioni locali

- `AccountIdentityPort` e `BillingSandboxPort` separano identità e checkout
  simulato, pur usando oggi la stessa istanza `AccountStore` e lo stesso SQLite.
- `CaseArchivePort` usa `BlobStore`; `LocalBlobStore` confina scritture,
  sostituzioni e cancellazioni nella cartella privata configurata.
- Ogni database locale, incluso quello dei limiti e delle lease, mantiene
  `schema_migrations(namespace, version, name,
  checksum, applied_at)`. Ogni versione usa una transazione `BEGIN IMMEDIATE` e
  registra la versione nella stessa transazione della modifica. Versioni future
  sconosciute o checksum diversi bloccano l'avvio.
- I database storici vengono riconciliati da migrazioni idempotenti prima di
  registrare le rispettive versioni, senza cancellare record esistenti.

Questi contratti non risolvono ancora la durabilità: account e checkout
condividono un file SQLite; `LocalBlobStore` usa rinomina atomica locale e non è
un object store; download e backup rimangono legati a `Path`, `send_file` e al
filesystem locale. La migrazione verso provider esterni richiederà adapter e
contract test dedicati, senza riutilizzare tali assunzioni locali.

## Confine di lancio

Prima di acquisire dati reali occorre scegliere e verificare:

1. database durevole per account, limiti, casi, audit e simulazioni;
2. object storage privato per foto, video, audio e derivati;
3. cifratura, chiavi, ruoli, MFA amministrativa e accessi minimi;
4. backup automatici con conservazione dichiarata;
5. prova di ripristino e prova di cancellazione, incluse le copie;
6. separazione tra staging e produzione e migrazione transazionale;
7. inventario di fornitori, Paesi, sub-responsabili e accordi;
8. DPIA completa sull'architettura finale.

## Sequenza tecnica proposta

- Definire un'interfaccia repository per account/casi/audit senza cambiare il
  comportamento osservabile dell'applicazione.
- Portare prima i dati strutturati su un database gestito e collaudare
  isolamento per azienda, concorrenza, backup e rollback.
- Portare i media su object storage con chiavi casuali, URL brevi firmati e
  nessun accesso pubblico.
- Eseguire una migrazione con manifest, conteggi, impronte SHA-256 e verifica
  di leggibilità; conservare il vecchio storage in sola lettura per la finestra
  approvata e poi cancellarlo con prova.
- Provare ripristino completo, cancellazione di un caso, revoca di un account e
  indisponibilità temporanea del provider prima del pilota con dati reali.

Non sono scelti provider, piani o costi in questo documento. La migrazione non
autorizza un upgrade, un deploy, dati cliente, pagamenti o il lancio.
