# SLPS AI — pilota privato
Stato del 25 ottobre 2026. Base recuperata: commit 1006d83. Metodo approvato: 1.8.

Questa versione prepara una prova riservata al proprietario. Non è ancora il servizio commerciale multi-azienda.

## Cosa è stato corretto
- La fotografia viene realmente inviata al modello, insieme al contesto.
- Il master 1.8 è caricato da un file privato e verificato tramite SHA-256.
- Il file originale non viene modificato; solo il changelog storico è escluso dalla richiesta al modello.
- Risultato strutturato con evidenze, incertezze, azioni, termini, domande e ritagli della foto.
- Accesso con password, CSRF, quota oraria e una sola analisi simultanea.
- Modalità account aziendali opzionale, con registrazione chiusa per default,
  credenziali personali e verifiche distinte di email, azienda e rappresentanza.
  Le nuove schermate di registrazione e stato account sono in IT/DE/FR/EN;
  il resto del sito e dell'app non è ancora interamente tradotto.
- Fondazione della prova gratuita: una sola analisi riuscita totale per azienda/proprietario,
  bloccata atomicamente prima della chiamata al fornitore; gli errori non consumano la prova.
  In modalità account la prova è condivisa da tutti gli utenti autorizzati della stessa
  azienda, indipendentemente dalle vecchie impostazioni del pilota.
- Un ciclo di chiarimento sul caso salvato è incluso e conteggiato separatamente. Ulteriori
  chiarimenti e nuove analisi sono bloccati prima della chiamata al fornitore. Il chiarimento
  accetta soltanto la stessa immagine normalizzata: l'archivio lega impronta
  SHA-256, originale e copia normalizzata allo stesso caso.
- Upload foto elaborato inizialmente in memoria, controllo coerente di MIME, estensione e contenuto, limite
  configurabile (10 MB per default), 25 megapixel e rimozione dei metadati.
- Verifica tecnica locale dei video MP4, WebM e MOV (50 MB e 30 secondi per default):
  `ffprobe` valida contenuto e durata, mentre `ffmpeg` estrae un numero adattivo di
  fotogrammi uniformi con timestamp e la prima traccia audio. L'audio viene distinto tra
  assente, privo di segnale, a basso livello, pronto per una futura trascrizione o in
  errore. Non vengono ancora interpretate tracce audio multiple e il campionamento non
  equivale al rilevamento di ogni scena o evento. La verifica non chiama un
  fornitore AI e non consuma la prova gratuita. Dopo una verifica riuscita, l'endpoint
  archivia il contenitore originale e, quando presente, mantiene la sua traccia audio;
  conserva inoltre i fotogrammi campionati e l'estratto WAV quando l'estrazione riesce.
  Trascrizione, comprensione audio
  e analisi dei rischi restano indicate chiaramente come non eseguite.
- Storico privato dei casi: rapporto in SQLite e file originali/derivati fuori
  dal database, sempre filtrati per azienda e proprietario.
- Nessun risultato inventato in caso di errore o quota esaurita; nessuna ripetizione automatica.
- Sito di presentazione su `/` e interfaccia autenticata su `/app/`, nello stesso servizio.
- Navigazione tra nuova analisi e archivio, passaggi foto/contesto/risultato e rapporto operativo.
- Checkout locale di prova, disattivato per default e separato sotto
  `/api/sandbox/billing`: catalogo non approvato, snapshot immutabile,
  idempotenza e isolamento azienda/proprietario. Non accetta carte, non chiama
  provider, non addebita e non modifica piano o quote di analisi.
- Vista riservata `/account/checkout`, disponibile soltanto a un account e a
  un'azienda verificati quando il sandbox è abilitato. Il confronto in quattro
  lingue indica esplicitamente ciò che resta da definire; conferma e annulla
  soltanto la simulazione. Le richieste aperte sono limitate atomicamente con
  `SLPS_BILLING_SANDBOX_MAX_OPEN_INTENTS` (default 5) e le scadenze diventano
  uno stato registrato e verificabile.

## Avvio locale
Python 3.12, `ffmpeg` e `ffprobe` sono richiesti e verificati durante lo sviluppo.

Il default `SLPS_DATA_MODE=synthetic` conserva gli adapter locali non
certificati. Il profilo esplicito `single-instance` prepara un volume già
montato, un solo processo, tutti i database e i media confinati sotto una
radice risolta. Percorsi relativi, esterni, sovrapposti o con symlink bloccano
l'avvio prima della creazione dei file; viene controllata anche una riserva
minima di spazio. Il profilo configurato non prova che il provider mantenga il
volume dopo restart o redeploy: per questo `SLPS_DATA_MODE=real` resta bloccato
finché l'accettazione operativa del provider non viene integrata nel runtime.

1. Crea un ambiente virtuale e installa requirements.txt.
2. Configura le variabili descritte in .env.example nell'ambiente del processo.
   Il file .env non viene letto automaticamente.
3. Metti il master originale nella cartella private oppure imposta SLPS_PROMPT_PATH.
4. Avvia python server.py per una prova locale su 127.0.0.1:5000.
   SLPS_COOKIE_SECURE=false è ammesso soltanto per questa prova locale HTTP.
5. Per un server HTTPS usa il comando del Procfile; non usare il server di sviluppo Flask.

Il modello è configurato esplicitamente con OPENAI_MODEL: nessuna scelta automatica di modello o costo.
Una chiave API valida non prova la disponibilità di credito o del modello selezionato.
Il controllo configured verifica i dati locali e non esegue richieste a pagamento.

## Master privato
Il repository originale è pubblico. Il master e le credenziali sono esclusi da Git.
Per un servizio ospitato, configura il master come file riservato del server.
Impronta approvata: 88a1077d86f78ee1102031739a5a1d1fcfb3750f2aa81639af528b7db8da97b7.
Un file diverso viene rifiutato; gli aggiornamenti richiedono approvazione e una nuova versione controllata.

## Fonti
Il pilota non naviga sul web. Non contiene ancora il recupero automatico delle fonti normative.
SLPS_SOURCES_PATH può indicare un registro JSON mantenuto e verificato dal proprietario.
Il registro versionato `data/sources.ch.v1.json` contiene sette proposizioni
generali da Fedlex, SECO, CFSL e Suva consultate il 26 ottobre 2026, con ambito, versione
del documento e distinzione tra obbligo e raccomandazione. Il formato supporta
anche ipotesi applicative esplicitamente distinte dalle conclusioni dell'autorità.
Vedi [contratto e limiti delle fonti](docs/SOURCE_REGISTRY.md), inclusa la distinzione
tra testo normativo Fedlex e commenti delle autorità. Sono compatibili anche liste legacy con id, title, url HTTPS,
verified_at ISO e excerpt; senza classificazione normativa verificata.
Nessuna fonte è inclusa per default. La data indica la verifica dichiarata nel registro;
non dimostra un nuovo controllo online a ogni analisi.
Il server elimina riferimenti del modello non presenti nel registro.
Questo controllo non dimostra da solo la pertinenza o correttezza legale dei testi generati.

## Dati e limiti
Il risultato strutturato e il contesto vengono archiviati in SQLite; il file
foto originale e la copia normalizzata vengono conservati nella cartella privata
configurata per lo storico. La verifica video conserva inoltre il contenitore
originale, la traccia audio incorporata quando presente, i fotogrammi e
l'estratto WAV soltanto quando l'estrazione riesce; la pipeline
AI video resta da collegare.
L’interfaccia autenticata consente di elencare, aprire ed eliminare con conferma i propri casi;
usa le API già filtrate per azienda e proprietario.
Un identificativo di caso non consente da solo l'accesso: ogni operazione applica anche
il filtro su azienda e proprietario.

Foto e contesto sono inviati al fornitore AI configurato.
store=false evita la conservazione della risposta per la funzione Responses; non promette
assenza di qualsiasi conservazione da parte del fornitore. Informativa, accordi e flussi
del trattamento vanno completati prima di usare dati dei clienti.
Il browser conserva il caso aperto in memoria fino a chiusura/ricaricamento. Nella prova
gratuita il risultato resta consultabile nell'app, mentre stampa/PDF ed esportazione JSON
non vengono offerte dall'interfaccia. Questo non può impedire screenshot o funzioni del
browser. I piani e i pagamenti non sono ancora implementati. Se il caso iniziale non può
essere archiviato, il risultato resta leggibile ma il chiarimento incluso non è disponibile.
SQLite conserva anche contatori e impronte degli indirizzi per i limiti; i record scaduti
sono rimossi alle richieste successive. SLPS_RATE_DB_PATH, SLPS_CASE_DB_PATH e
SLPS_HISTORY_ROOT devono stare
su un volume persistente se limiti e casi devono sopravvivere ai redeploy. Un solo server
applicativo è supportato in questa fase.
L'isolamento applicativo per azienda/proprietario è implementato e coperto da test.
La modalità predefinita conserva l'accesso singolo del pilota. La modalità opzionale
account aggiunge identità aziendali e personali, ma l'archivio dei casi resta anche
separato per proprietario: la condivisione dei casi fra colleghi non è ancora implementata.
Mancano assegnazione e chiusura delle misure e verifica di persistenza sul provider.
Non usarlo ancora come archivio aziendale di produzione.

La fondazione locale di conservazione, quote, cancellazione e backup/ripristino
è descritta in `docs/HISTORY_LOCAL.md`. Non applica scadenze automatiche: al
limite di capacità blocca nuovi salvataggi senza eliminare lo storico esistente.

Il profilo single-instance dispone inoltre di uno snapshot unificato di account
e billing, limiti, casi e media. Arresta prima il servizio e ogni writer, quindi
esegui `python scripts/durable_snapshot.py backup /destinazione/assoluta
--confirm-quiesced`. Il comando usa l'API backup di SQLite, inventaria ogni
media con dimensione e SHA-256 e pubblica la directory solo a snapshot completo.
Il ripristino `python scripts/durable_snapshot.py restore /backup /radice-vuota`
verifica manifest, inventario, checksum, traversal, integrità SQLite e capacità,
poi installa atomicamente la radice. La destinazione del backup deve stare fuori
dal volume sorgente. Una prova locale riuscita non sostituisce la prova di
restart e restore sull'infrastruttura scelta.

La fondazione della registrazione self-service è descritta in `docs/ACCOUNTS_LOCAL.md`.
È disattivata per default; nel collaudo locale la consegna di verifiche email,
recuperi password e inviti aziendali, oltre alla verifica reale dell'azienda,
non è collegata. Nessun account in attesa può accedere ad analisi o casi.
Token di conferma e recupero sono a scadenza e a uso singolo, conservati solo come hash;
il reset della password invalida tutte le sessioni precedenti. Nessuna risposta HTTP
espone un token o finge di aver inviato un'email. Un registro locale separato dalla
fatturazione può riservare una richiesta di contatto legata a un caso autorizzato,
senza mostrare recapiti, inviare messaggi, effettuare chiamate o addebitare importi.
La cadenza resta un'ipotesi configurabile; non è codificata alcuna determinazione
legale automatica CFSL 6508. Dettagli e limiti sono in `docs/CONSULTATIONS_LOCAL.md`.
La migrazione necessaria prima di dati reali è descritta in
`docs/DURABLE_STORAGE_MIGRATION.md`. L'attuale filesystem Render free è
effimero e non costituisce uno storico aziendale durevole.

## Verifica
Installa requirements-dev.txt ed esegui:
python -m pytest -q
node --check static/app.js
node --check static/account.js
node --test tests/test_ui_feedback.cjs tests/test_account_ui.cjs
python -m unittest -q tests.test_preflight
python scripts/preflight.py

I test software simulano il fornitore e non dimostrano la qualità SLPS del modello.
I test Node del feedback usano un DOM simulato, senza dipendenze npm: non sono una prova visiva nel browser.
Coprono anche ordine azione/termine, domande decisive nei singoli rilievi e nella lista generale,
conservazione della foto e del contesto del rapporto precedente dopo un errore, e preparazione della stampa.
Prima del rilascio, verificare nel browser desktop e a 360/390 px (anche con zoom al 200%)
che tutti i comandi siano raggiungibili; controllare l'anteprima A4 multipagina con foto, contesto, date e domande.
La prova reale con API, la verifica grafica nel browser e la configurazione dell'hosting
restano necessarie. Non è stata pubblicata una nuova versione online.

La procedura di configurazione, controllo offline e ripristino del pilota è in
`docs/PILOT_DEPLOY.md`. Il preflight non contatta il fornitore AI e non prova
credito, disponibilità del modello o persistenza effettiva del volume.
Il controllo distingue il profilo `pilot` da `accounts`: nel secondo non
richiede la password pilota e verifica configurazione, schema, permessi e
presenza di un account idoneo al login. Segnala come blocco l'apertura delle
registrazioni finché verifica email e recupero password non hanno un canale di
consegna reale. Non crea né modifica account durante il controllo.
Il collaudo della versione reale è definito in `docs/STAGING_ACCEPTANCE.md`.
Le viste e i test con dati sintetici non soddisfano la verifica del motore AI reale.

## Prima del rilascio commerciale
1. Prova completa con API attiva e modello scelto: foto → analisi → chiarimento → riesame.
2. Fonti normative controllate e tracciabili, con verifica di pertinenza.
3. Collaudo della cronologia; assegnazione delle misure, evidenze e conferma della chiusura.
4. Gestione account, cancellazione e backup/ripristino verificati sull'hosting;
   applicare il ciclo di chiusura account documentato.
5. Casi di accettazione definiti dal responsabile SLPS, inclusi alcuni casi reali non usati per modificare il metodo.
6. Prezzo sulla base di costi misurati, condizioni, informativa e assistenza.
7. Prova con pochi clienti prima di ampliare l'accesso.

Le correzioni dei clienti non cambiano automaticamente il metodo.

