# Rehearsal delivery offline

Eseguire dalla radice del repository:

```bash
python scripts/delivery_activation_rehearsal.py
python -m pytest -q tests/test_delivery_activation_rehearsal.py tests/test_delivery_preflight.py tests/test_preflight.py
```

Il comando è una prova sintetica dei prerequisiti locali, non un comando di
attivazione. Non importa il server, non legge le variabili dell'ambiente reale,
non modifica configurazioni, non usa credenziali o SDK e non invia messaggi.
Socket, connessioni e tutti i resolver `getaddrinfo`, `gethostbyname`,
`gethostbyname_ex`, `gethostbyaddr` e `getnameinfo` sono bloccati per tutta la prova. Ogni tentativo
fa fallire la prova ed è conteggiato, senza ripetizioni o fallback.

La prova crea un registro SQLite delivery e un checkpoint sintetici, privati,
in una nuova directory temporanea sorella del repository. La directory deve
essere già esistente, canonica, appartenere all'utente del processo e non essere
scrivibile da gruppo/altri (0755 è ammesso). Sono rifiutati symlink nel percorso,
directory sotto il codice e le radici `/tmp`, `/var/tmp` e `/dev/shm`. La
validazione avviene prima di qualsiasi creazione: un parent non valido non viene
creato, modificato o corretto automaticamente. Il figlio temporaneo è 0700.
Un descriptor mantiene il parent aperto: su Linux `/proc/self/fd` ancora creazione
e cleanup al descriptor. Store e preflight condivisi conservano i controlli
originari e usano il percorso lessicale; una guardia di identità/ancestry viene
eseguita come prima istruzione del rehearsal, immediatamente prima e dopo lo
Store, ogni snapshot e ciascuna fase preflight. Una sostituzione osservata arresta
la prova prima della fase successiva. Senza queste primitive la prova fallisce.
Il cleanup verifica l'assenza sia del child pinnato sia del child lessicale.
Rimuove un child lessicale residuo solo se nome, inode ancora pinnato, owner e
permessi 0700 corrispondono all'originale; un sostituto sconosciuto resta intatto
e `temporary_state_removed` è falso. Il descriptor del child verifica inoltre
che l'inode originale sia stato scollegato, evitando un esito positivo se è
stato spostato in una posizione diversa da entrambi i percorsi noti.

Questa è una prova offline in un processo fidato, senza codice concorrente che
modifichi i percorsi. Non è una sandbox contro codice ostile dello stesso UID che
ignora le guardie o cambiamenti concorrenti durante una singola operazione dello
Store. Antenati scrivibili, come la radice workspace del runtime, non concedono
un permesso di alterare la catena durante la prova: la directory selezionata
appartiene all'utente ed è protetta da scritture di gruppo/altri; descriptor e
guardie verificano la sua identità. In un ambiente con writer non fidati o una
catena di percorsi contendibile non va usato questo rehearsal come prova di
isolamento o sicurezza del filesystem.
Non viene allentato alcun controllo per far passare la simulazione.
Il comando tenta la rimozione dei soli file identificati come propri anche in
caso di errore; il riepilogo dichiara se la rimozione è avvenuta. Un esito falso
non va interpretato come cleanup riuscito. Non usa o modifica file di
un'installazione esistente.

Il preflight condiviso verifica sette prerequisiti delivery: formato del segreto,
percorsi separati e sicuri di registro e checkpoint, corrispondenza del segreto
con il registro, retention e capability adapter esplicita. La retention deriva
dalla formula condivisa `required_dispatch_marker_retention_seconds`, senza
duplicarne le costanti. L'adapter finto espone soltanto il contratto: ogni chiamata
a `send` fa fallire la prova. Nessun esito di recapito viene fabbricato.

La baseline ha tutti i prerequisiti locali validi e mantiene la registrazione
chiusa. Una valutazione ipotetica con severità di apertura dimostra che la
verifica del provider resta un blocco, anche con tutti gli altri prerequisiti
validi. Sette guasti, uno per prerequisito, vengono valutati sia con registrazioni
chiuse sia con severità di apertura: ciascun guasto resta un avviso nel primo
caso e un blocco nel secondo. Nessuna impostazione di registrazione viene aperta.
La prova confronta anche contenuto e metadati dei soli due file prima e dopo i
controlli: non ammette sidecar SQLite o mutazioni del preflight.

Il JSON contiene solo ambito, esiti, booleani e conteggi. Non include segreti,
impronte, percorsi, identificativi di adapter o messaggi di eccezione. Exit code
`0` significa rehearsal riuscito; `1` significa errore depurato. Nessun campo
`ready` autorizza un rilascio. Un errore di scrittura/flush su stdout produce exit
code `2`, senza dettagli su stderr, secondo invio o flush ripetuto alla chiusura.

Una prova riuscita non dimostra persistenza del volume, correttezza completa
degli archivi reali, backup, autenticazione o recapito di un fornitore. Non apre
registrazioni, non collega il confine delivery all'app e non sostituisce un
collaudo autorizzato dell'infrastruttura reale.
