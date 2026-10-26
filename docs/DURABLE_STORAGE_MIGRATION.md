# Migrazione dello storage prima dei dati reali

Il servizio Render free osservato usa un filesystem effimero. SQLite e media
locali sono quindi adatti soltanto a test sintetici: un deploy, riavvio o cambio
istanza può eliminarli. Il checkout sandbox non cambia questo limite e non deve
essere usato come prova di persistenza produttiva.

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
