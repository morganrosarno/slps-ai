# Migrazione dello storage prima dei dati reali

Il servizio Render free osservato usa un filesystem effimero. SQLite e media
locali sono quindi adatti soltanto a test sintetici: un deploy, riavvio o cambio
istanza può eliminarli. Il checkout sandbox non cambia questo limite e non deve
essere usato come prova di persistenza produttiva.

Il servizio dichiara questa separazione con `SLPS_DATA_MODE`: `synthetic` è il
default e conserva il comportamento del pilota, mentre `real` si arresta prima
di costruire database o cartelle locali. Anche il preflight segnala il blocco.
La rimozione richiederà adapter durevoli che implementino gli stessi contratti
applicativi e prove di ripristino; il solo uso di un percorso persistente non è
considerato certificazione sufficiente.

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
