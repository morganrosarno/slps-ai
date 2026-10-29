# Guardia offline per budget e ricevute AI

`ai_budget_guard.py` definisce un contratto provider-neutral e persistente per
impedire che una futura integrazione AI superi i limiti tecnici configurati.
Non contiene prezzi commerciali, endpoint, SDK, credenziali o chiamate di rete.

## Sequenza obbligatoria

1. creare o riaprire un lavoro con `start_job`;
2. calcolare una `SubrequestPlan` con un digest SHA-256 del binding canonico e
   l'uso massimo previsto;
3. chiamare `reserve` prima di qualsiasi adapter;
4. chiamare `begin_dispatch` immediatamente prima dell'unico tentativo;
5. registrare `receipt_id` e consumo con `settle`, oppure `mark_uncertain` se
   l'esito fatturabile non è noto;
6. usare `reconcile_uncertain` solo quando esiste una ricevuta d'uso stabile.

Il passaggio `dispatched` è durevole. Un crash tra quel passaggio e la risposta
mantiene l'intera riserva come costo potenziale. Una ripetizione richiede un
nuovo ordinale di tentativo e una nuova riserva; il digest del binding resta
uguale se la richiesta logica non cambia. La stessa sotto-richiesta non può
essere riaperta.

Il registro salva il digest del receipt ID e il digest canonico di receipt ID,
sotto-richiesta e consumo. Il replay identico restituisce lo stesso
`ReceiptMetadata`, anche dopo una riapertura, senza cambiare il registro. Un
receipt ID o consumo diverso per una sotto-richiesta già riconciliata produce
un conflitto. `receipt` e `snapshot` restituiscono soltanto identificativi,
digest, stati e aggregati; non espongono capability, receipt ID grezzo o
dettaglio del consumo.

## Limiti e stati

Ogni lavoro lega il proprio profilo immutabile: tetto totale, numero complessivo
di sotto-richieste e limiti separati per visione e trascrizione. Lo stesso
registro può quindi applicare profili diversi a foto e video. I tassi sono
interi in micro-unità definite
dal chiamante; i calcoli arrotondano sempre verso l'alto e non usano float.
`reserved`, `dispatched` e `uncertain` impegnano l'intero massimo. `settled`
usa il consumo ricevuto; un consumo oltre la riserva produce `overage` e blocca
l'intero lavoro.

Il database lega in modo immutabile l'impronta del tariffario al registro e
l'impronta del profilo al singolo lavoro.
Concorrenza, replay, capability errata, cambio di configurazione o stato
incoerente falliscono in modo chiuso. Il token di capacità è restituito solo al
chiamante e nel database è conservato esclusivamente il suo SHA-256.

## Storage e ripristino

Il percorso deve essere assoluto. La directory immediata deve avere modo
`0700`; il file deve essere regolare, con modo `0600` e un solo hard link. La
creazione usa `O_EXCL` e, quando disponibile, `O_NOFOLLOW`. Ogni componente del
percorso deve essere una directory reale, senza symlink. Il processo fissa
device e inode del file e degli antenati e li verifica prima e dopo ogni
connessione: sostituzioni, hard link o cambi di permessi bloccano le operazioni
con un errore depurato.

La capability grezza non è recuperabile dal registro. Chi deve riconciliare
dopo un riavvio deve conservarla in uno storage durevole e riservato insieme
all'outbox del tentativo; perderla lascia prudentemente impegnata la riserva.
Registro, capability/outbox e ricevute dell'adapter devono essere inclusi nello
stesso snapshot coerente del volume. Un rollback del solo database potrebbe
dimenticare un dispatch già eseguito e consentire una ripetizione. Il ripristino
deve quindi avvenire a dispatch fermo, usando lo stesso punto temporale per
tutti questi dati e verificando gli esiti incerti prima di riaprire le chiamate.
La guardia non offre da sola un contatore esterno capace di rilevare rollback
offline non coordinati.

## Confine dell'incremento

La guardia non è collegata a `server.py` né al confine provider esistente. I
test usano valori sintetici e non aprono socket. Prima di un uso reale servono
approvazione del budget, configurazione sicura del provider, storage durevole,
backup verificati e un adapter che rispetti la sequenza sopra.
