# Registro locale delle richieste allo specialista

Questa fondazione tecnica è disponibile soltanto in modalità `accounts` per utenti
la cui email, appartenenza e azienda sono verificate. Il registro SQLite è separato
dai contatori delle analisi e da qualsiasi futura fatturazione.

Una procedura fidata lato server assegna la disponibilità alla singola azienda; non
esiste un endpoint amministrativo pubblico. Senza assegnazione il valore predefinito
è zero richieste incluse. Aziende diverse possono conservare contemporaneamente le
due ipotesi verificabili: una richiesta ogni dodici mesi oppure una richiesta ogni
mese. Non sono definiti nomi di piano, prezzi o regole di riporto.

Una prenotazione richiede un caso visibile allo stesso utente e il canale `phone` o
`whatsapp`. Il server registra azienda, utente, caso, canale, stato e date. Il
contatore aziendale viene aggiornato in una transazione e una chiave di idempotenza
impedisce che un retry identico consumi due disponibilità. Logout, riavvio o una
nuova registrazione non azzerano il registro.

Gli stati sono `reserved`, `used` e `cancelled`. Solo il codice operativo fidato può
marcare una richiesta come utilizzata; non esiste un endpoint utente per farlo.
L'utente può annullare una propria prenotazione. Per evitare di anticipare una
politica commerciale non approvata, l'annullamento non restituisce automaticamente
la disponibilità nel periodo corrente. La cronologia resta dopo il rinnovo.

L'interfaccia mostra incluse, prenotate, utilizzate, saldo e prossimo rinnovo. Non
contiene un numero privato, non crea link telefonici o WhatsApp, non invia messaggi,
non effettua chiamate e non genera addebiti. La richiesta è soltanto registrata per
la gestione successiva. Non è previsto un limite massimo alla durata di una futura
chiamata, né viene promessa una tempistica di risposta.

La consegna reale del contatto, le notifiche interne, i prezzi, i nomi commerciali,
il riporto e l'eventuale trattamento delle cancellazioni devono essere approvati e
implementati prima del rilascio commerciale.
