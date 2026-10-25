# Collaudo riservato della versione reale

Il collaudo usa lo stesso codice applicativo destinato al rilascio: sito `/`,
app `/app/`, autenticazione e backend di analisi. Una dimostrazione statica o
un test con risposte simulate non soddisfa questo collaudo.

## Prima della prima chiamata AI

- Identificare commit distribuito, ambiente riservato e versione del master.
- Configurare credenziali solo sul server, verificare il master approvato tramite
  hash e confermare il modello scelto e il limite di spesa autorizzato.
- Eseguire il preflight. Il suo esito non prova credito API, disponibilità del
  modello, persistenza, backup o correttezza professionale delle risposte.
- Verificare accesso HTTPS, login, cookie sicuri e rifiuto delle richieste anonime.
- Usare immagini autorizzate. Conservare prove tecniche senza foto o segreti nei
  log e nel repository pubblico.

## Prove di accettazione

| Prova | Evidenza necessaria |
| --- | --- |
| Percorso completo | Dal sito si raggiunge l'app; una foto e il contesto arrivano al fornitore reale, producono un rapporto e un identificativo tecnico tracciabile. |
| Rilievi comprensibili | Ogni rilievo mostra cosa fare, entro quando e l'evidenza; il ritaglio deriva dalla foto effettiva. Nessuna classificazione basata solo sul colore. |
| Incertezza | Le domande decisive restano visibili; le risposte aggiornano il contesto. Un errore conserva e identifica l'eventuale rapporto precedente. |
| Interfaccia | Desktop e telefono a 390 px: navigazione, upload, caricamento, errore, risultato e archivio verificati con tastiera e senza scorrimento orizzontale. |
| Archivio | Elenco, apertura e cancellazione confermata; accessi di altri proprietari/aziende respinti. L'assenza delle foto archiviate viene dichiarata. |
| Stampa ed esportazione | Il rapporto esportato e la stampa riportano il caso corretto, le domande aperte, il contesto e la foto quando disponibile. |
| Persistenza | Un caso e i contatori sopravvivono al riavvio e al redeploy; backup e ripristino provati nell'ambiente di destinazione. |
| Revisione professionale | Valutazione delle risposte reali da parte del responsabile SLPS; omissioni critiche e falsi positivi registrati. Il numero di test software non sostituisce questa verifica. |

Ogni nuova analisi, compreso l'aggiornamento dopo chiarimenti, può consumare API.
La quota oraria non equivale a un tetto di spesa né a un numero massimo totale
di prove. Non effettuare chiamate reali prima dell'approvazione di consumo.

## Promozione al rilascio

Registrare commit, test superati, limiti aperti, consumo reale e approvazione.
Il passaggio al pubblico deve usare lo stesso codice collaudato, salvo le
configurazioni documentate di accesso e dominio. Le funzioni non implementate
non diventano disponibili con il solo cambio di ambiente.

La pubblicazione commerciale, l'apertura degli accessi e gli incassi reali
richiedono l'approvazione finale. Il master approvato resta invariato.
