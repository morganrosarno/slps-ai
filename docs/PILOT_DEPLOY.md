# Pubblicazione del pilota privato

Questa procedura prepara una prova riservata. Non autorizza il lancio commerciale,
non effettua addebiti e non esegue chiamate al fornitore AI durante il controllo.

## Configurazione del servizio esistente

Prima del deploy annotare il commit sorgente e l'ultimo deploy funzionante. Usare
il ramo pilota soltanto per il collaudo riservato; non unire il ramo principale.

- Build: `pip install -r requirements.txt`
- Avvio: `gunicorn server:app --bind 0.0.0.0:$PORT --workers 1 --threads 1 --timeout 120`
- Health check: `/healthz`
- Regione e piano: mantenere quelli già approvati.

Configurare come segreti, senza copiarne il valore in ticket, chat o log:
`OPENAI_API_KEY`, `OPENAI_MODEL` e `SLPS_SESSION_SECRET`. Nel profilo
`SLPS_AUTH_MODE=pilot` è obbligatoria anche `SLPS_PILOT_PASSWORD`; nel profilo
`accounts` non viene richiesta né usata. Il modello va scelto e il budget
approvato prima della prima analisi reale.

Caricare il master approvato come **file segreto** nel percorso
`/etc/secrets/SLPS_AI_Prompt_Master_v1.8.txt` e impostare
`SLPS_PROMPT_PATH` sullo stesso percorso. Il file non deve entrare nel
repository. Se viene usato un registro privato delle fonti, caricarlo come file
segreto e indicarlo con `SLPS_SOURCES_PATH`.

Impostare inoltre:

- `SLPS_COOKIE_SECURE=true`
- `SLPS_ANALYSES_PER_HOUR` al limite autorizzato
- `SLPS_RATE_DB_PATH` su un volume persistente, se disponibile
- `SLPS_CASE_DB_PATH` sullo stesso volume persistente, se disponibile
- `SLPS_HISTORY_ROOT` su una cartella privata dello stesso ambiente persistente
- `SLPS_MAX_HISTORY_BYTES_PER_TENANT` al limite approvato; il superamento blocca
  nuovi salvataggi senza cancellare casi esistenti
- `SLPS_PILOT_TENANT_ID` e `SLPS_PILOT_OWNER_ID` con identificativi interni stabili

Per il profilo account impostare invece:

- `SLPS_AUTH_MODE=accounts`
- `SLPS_ACCOUNT_DB_PATH` su un volume persistente, fuori dal codice
- `SLPS_ACCOUNT_REGISTRATION_OPEN=false` finché verifica email e recupero
  password non dispongono di un canale di consegna reale

Il preflight account richiede inoltre almeno un account attivo già verificato
per il collaudo. Non apre il database in scrittura e non crea utenti. La
registrazione aperta senza consegna è segnalata come blocco, non come servizio
pronto. Il flusso completo è descritto in `docs/ACCOUNTS_LOCAL.md`.

Senza volume persistente il pilota può funzionare, ma contatori, rapporti e file dello storico
possono azzerarsi dopo riavvio o deploy. Non presentare quindi l'archivio come
duraturo finché persistenza, backup e ripristino non sono stati provati.

## Controllo senza chiamate AI

Con le variabili e i file disponibili al processo:

```sh
python scripts/preflight.py
python scripts/preflight.py --json
```

Il comando mostra soltanto presenza, validità e blocchi; non stampa valori
segreti, indirizzi email o percorsi configurati. Codice di uscita `0`: nessun
blocco. Codice `1`: configurazione da correggere; `2`: uso non valido del
comando. Nel JSON, `auth_profile` dichiara se è stato controllato `pilot`,
`accounts` o un valore non valido. Gli avvisi non provano la persistenza del
volume né la disponibilità di credito o modello.

Verificare poi `/healthz` e il login. Questi controlli non inviano fotografie.
La prima analisi reale si esegue soltanto dopo approvazione del tetto di spesa.

## Collaudo e ripristino

Il collaudo completo è: login → foto autorizzata → analisi → chiarimenti →
riesame → esportazione e stampa. Registrare commit, modello, esito e consumo
reale senza conservare la fotografia nei log.

Se il deploy non supera health check o login:

1. non avviare analisi reali;
2. ripristinare dall'interfaccia del provider l'ultimo deploy funzionante già
   annotato, oppure ricollegare il servizio al ramo precedente;
3. verificare nuovamente `/healthz` e login;
4. non sostituire modello, piano o provider per aggirare un errore di quota.

Un health check positivo non dimostra che API, credito o analisi fotografica
funzionino. Il pilota diventa collaudato solo dopo la prova completa documentata.
