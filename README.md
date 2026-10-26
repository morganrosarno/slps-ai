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
  accetta soltanto la stessa immagine normalizzata: nell'archivio resta la sua impronta
  SHA-256, non la fotografia.
- Upload foto solo in memoria, controllo coerente di MIME, estensione e contenuto, limite
  configurabile (10 MB per default), 25 megapixel e rimozione dei metadati.
- Contratto di caricamento video separato (MP4, WebM, MOV; 50 MB e 30 secondi previsti
  per default): la UI lo
  identifica come «in preparazione» e il backend lo rifiuta senza inviarlo al motore AI
  né consumare la prova. Durata, estrazione fotogrammi e analisi video non sono ancora
  validate o implementate.
- Archivio SQLite dei risultati, senza fotografia, sempre filtrato per azienda e proprietario.
- Nessun risultato inventato in caso di errore o quota esaurita; nessuna ripetizione automatica.
- Sito di presentazione su `/` e interfaccia autenticata su `/app/`, nello stesso servizio.
- Navigazione tra nuova analisi e archivio, passaggi foto/contesto/risultato e rapporto operativo.

## Avvio locale
Python 3.12 verificato durante lo sviluppo.

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
SLPS_SOURCES_PATH può indicare un registro JSON mantenuto e verificato dal proprietario:
lista di oggetti con id, title, url HTTPS, verified_at ISO e excerpt pertinente.
Nessuna fonte è inclusa per default. La data indica la verifica dichiarata nel registro;
non dimostra un nuovo controllo online a ogni analisi.
Il server elimina riferimenti del modello non presenti nel registro.
Questo controllo non dimostra da solo la pertinenza o correttezza legale dei testi generati.

## Dati e limiti
Le foto non vengono conservate sul server. Il risultato strutturato e il contesto fornito
vengono archiviati in SQLite per l'azienda e il proprietario configurati.
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
sono rimossi alle richieste successive. SLPS_RATE_DB_PATH e SLPS_CASE_DB_PATH devono stare
su un volume persistente se limiti e casi devono sopravvivere ai redeploy. Un solo server
applicativo è supportato in questa fase.
L'isolamento applicativo per azienda/proprietario è implementato e coperto da test.
La modalità predefinita conserva l'accesso singolo del pilota. La modalità opzionale
account aggiunge identità aziendali e personali, ma l'archivio dei casi resta anche
separato per proprietario: la condivisione dei casi fra colleghi non è ancora implementata.
Mancano assegnazione e chiusura delle misure, backup/ripristino e verifica di persistenza sul provider.
Non usarlo ancora come archivio aziendale di produzione.

La fondazione della registrazione self-service è descritta in `docs/ACCOUNTS_LOCAL.md`.
È disattivata per default; nel collaudo locale l'invio email e la verifica reale
dell'azienda non sono collegati. Nessun account in attesa può accedere ad analisi o casi.
Token di conferma e recupero sono a scadenza e a uso singolo, conservati solo come hash;
il reset della password invalida tutte le sessioni precedenti. Nessuna risposta HTTP
espone un token o finge di aver inviato un'email. Il questionario
azienda e l'eventuale escalation a uno specialista restano una struttura di prodotto da
validare; non è codificata alcuna determinazione legale automatica CFSL 6508.

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
Il collaudo della versione reale è definito in `docs/STAGING_ACCEPTANCE.md`.
Le viste e i test con dati sintetici non soddisfano la verifica del motore AI reale.

## Prima del rilascio commerciale
1. Prova completa con API attiva e modello scelto: foto → analisi → chiarimento → riesame.
2. Fonti normative controllate e tracciabili, con verifica di pertinenza.
3. Collaudo della cronologia; assegnazione delle misure, evidenze e conferma della chiusura.
4. Gestione account, cancellazione e backup/ripristino verificati sull'hosting.
5. Casi di accettazione definiti dal responsabile SLPS, inclusi alcuni casi reali non usati per modificare il metodo.
6. Prezzo sulla base di costi misurati, condizioni, informativa e assistenza.
7. Prova con pochi clienti prima di ampliare l'accesso.

Le correzioni dei clienti non cambiano automaticamente il metodo.

