# Ingresso e limite di consumo del collaudo riservato

Il preflight richiede `SLPS_PRIVATE_GATE_ENABLED=true`, una
`SLPS_PRIVATE_GATE_PASSWORD` di 16–256 caratteri e un segreto di sessione valido.
La password di ingresso deve essere diversa sia dal segreto di sessione sia
dalla password del pilota. I valori si configurano esclusivamente sul server;
non vanno inseriti nel repository, negli URL o nei log.

L'ingresso protegge sito, app, account, risorse statiche e API. Restano accessibili
il controllo minimale `/healthz` e la pagina di ingresso `/private-access`.
L'ingresso richiede CSRF e accetta solo destinazioni relative sicure. Superarlo
non sostituisce l'autenticazione e la verifica dell'account aziendale.
In HTTPS il cookie di sessione deve mantenere `Secure`; il preflight verifica
anche questa impostazione. Con protezione abilitata, configurazioni invalide
devono rifiutare l'accesso senza mostrare segreti.

`SLPS_PROVIDER_REQUESTS_TOTAL` limita da 1 a 10000 i tentativi complessivi
verso il motore AI. Il contatore si prenota atomicamente prima della chiamata,
comprende analisi e chiarimenti e non restituisce credito per errori che possono
essere stati fatturati. Il contatore è separato dalla prova gratuita aziendale:
un errore può non consumare la prova del cliente ma conta comunque come tentativo
del collaudo. La riapertura degli stessi database mantiene il totale.

Il limite è un numero di tentativi, **non un tetto in franchi**. Occorrono comunque
un consumo approvato, verifica dei costi del modello e prova della persistenza
del contatore nell'ambiente di destinazione. Non eliminare o sostituire il
database per rinnovare il limite. Chiarimenti e tentativi falliti possono avere
un costo effettivo diverso dalla risposta riuscita.

Il valore vuoto e la protezione disabilitata preservano solo l'esecuzione dei
test sintetici locali preesistenti: il preflight li considera bloccanti per
uno staging riservato. Questi controlli non attivano alcun servizio, invio,
pagamento o chiamata AI e non rendono durevoli gli adapter locali.
