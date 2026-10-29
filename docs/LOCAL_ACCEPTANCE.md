# Collaudo integrato locale, senza consumo API

Eseguire dalla radice del repository:

```sh
python -m pytest -q tests/test_acceptance_journeys.py
```

Servono le dipendenze Python di sviluppo e gli eseguibili `ffmpeg` e `ffprobe`.
I test video non vengono saltati se questi strumenti mancano: il collaudo deve
fallire e segnalare la dipendenza assente. Il materiale video viene generato
localmente con un colore uniforme e un tono; nessun file cliente è necessario.

| Percorso verificato | Risultato richiesto |
| --- | --- |
| Sito, registrazione e accesso | Registrazione in attesa; email confermata da sola insufficiente; azienda e rappresentante approvati dalla fixture prima dell'app. |
| Prima foto e chiarimento | Errore senza consumo; successo con consumo; seconda foto respinta prima del fornitore; un chiarimento sulla stessa foto; sostituzione della foto respinta. |
| Riapertura dell'applicazione | Nuove istanze dei database riaprono storico, media e contatori; nuovo collega della stessa azienda non riceve una seconda prova. |
| Backup e ripristino sintetici a servizio fermo | Snapshot dei tre database tramite API SQLite e dei media; ripristino in percorsi nuovi; originale, prova consumata e consulenza prenotata recuperati anche dopo la cancellazione nel vecchio archivio. |
| Riservatezza e cancellazione | Originale accessibile al proprietario, respinto per anonimo e altra azienda; cancellazione rende i file inaccessibili e non ripristina la prova. |
| Video con audio | Elaborazione FFmpeg reale, fotogrammi e WAV conservati; nessuna trascrizione o analisi AI dichiarata; prova fotografica invariata. |
| Specialista e checkout | Una richiesta sintetica e idempotente; simulazione di acquisto persistente senza addebito, abbonamento attivo o ripristino delle quote. |

Questi sono percorsi HTTP integrati tramite il client di test Flask: routing,
sessioni, controlli di accesso, migrazioni SQLite e file locali sono quelli
dell'applicazione. Il motore AI è sostituito da una risposta deterministica e
il client del fornitore reale è bloccato. La verifica dell'azienda, l'approvazione
del rappresentante e la consegna del codice email sono simulate esplicitamente
attraverso operazioni fidate della fixture. Non esiste un endpoint che le aggira.
La politica di consulenza usata nel test è un dato sintetico, non un'offerta
commerciale approvata.

Il superamento non prova la grafica in un browser, la correttezza SLPS delle
risposte, la trascrizione/comprensione audio, l'invio email o l'inoltro a uno
specialista. La riapertura e il ripristino locali non provano persistenza dopo un
redeploy né backup/ripristino nel cloud di destinazione. Il test di snapshot
non comprende scritture concorrenti: in produzione occorre fermarle o usare
una strategia che garantisca coerenza tra database e media. Queste verifiche, insieme al percorso
con fornitore reale e all'autorizzazione di consumo, restano nel collaudo
riservato descritto in `docs/STAGING_ACCEPTANCE.md`.
