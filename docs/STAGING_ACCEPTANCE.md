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
| Archivio | Elenco, apertura e cancellazione confermata di rapporto e file; originali visibili nel caso; accessi di altri proprietari/aziende respinti; quota piena senza cancellazione automatica. |
| Accesso gratuito ed esportazione | Una sola analisi riuscita per azienda verificata; errore tecnico senza consumo; seconda analisi bloccata prima del fornitore. Il rapporto gratuito è consultabile online, senza PDF, stampa o JSON offerti dall'app. Il browser non può garantire il blocco degli screenshot. L'eventuale esportazione a pagamento richiede un diritto server verificato e un collaudo separato. |
| Persistenza | Rapporto, originali, derivati e contatori sopravvivono al riavvio e al redeploy; backup e ripristino provati nell'ambiente di destinazione. |
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

## Criteri finiti: cosa rende accettabile una consegna

Il collaudo locale sintetico e il collaudo con fornitore reale sono due passaggi
distinti. Un controllo saltato, un servizio non collegato o una risposta simulata
non possono essere registrati come prova reale superata.

| Passaggio | Chiusura verificabile | Evidenza da conservare privatamente |
| --- | --- | --- |
| A. Percorsi software senza consumo API | Registrazione, verifiche, login, prova aziendale, errore, chiarimento, video tecnico, archivio, isolamento e richiesta specialista attraversano le route e gli archivi effettivi. | Commit, comando, esito e numero delle chiamate al fornitore simulato; zero chiamate esterne. |
| B. Uso nel browser | Sito, account, app e checkout di prova utilizzabili a desktop e 390 px, nelle quattro lingue; niente errori JavaScript o contenuti fuori schermo; controlli gratuiti rispettati. | Commit, versioni browser, dimensioni, azioni effettivamente percorse e difetti corretti. I testi del rapporto simulato non provano traduzione o qualità del modello. |
| C. Ambiente riservato | Intero ambiente protetto; limiti totali di consumo; storage e account conservati dopo riavvio e ridistribuzione; ripristino verificato. | Commit distribuito, controllo accessi, prova backup/ripristino, configurazione depurata. Il filesystem locale sintetico non soddisfa questo passaggio. |
| D. Analisi effettiva | Una foto e un video con audio elaborati dal motore reale, con domande, evidenze corrette e rapporto riapribile. Errori e limiti espliciti. | Identificativi tecnici, modello, consumo e risultati, senza segreti nei log. L'estrazione di fotogrammi e audio non equivale alla loro comprensione. |
| E. Verifica SLPS | Casi approvati e tenuti separati dallo sviluppo valutati da un revisore professionale; nessuna omissione critica aperta o rassicurazione infondata. | Confronto caso per caso tra atteso e ottenuto, decisione del revisore e rilievi risolti. Nessuna autocertificazione del modello. |
| F. Percorso commerciale | Onboarding e recupero accesso effettivi; benefici e contatti dello specialista applicati secondo offerta approvata; pagamento solo di prova; condizioni e trattamento dati verificati. | Prova con account di collaudo, registro dei diritti e checkout sandbox. Una simulazione non attiva un abbonamento. |

Per ogni passaggio registrare `pass`, `fail` o `not_run`, lo stesso commit e un
puntatore all'evidenza. L'accettazione finale richiede tutti i passaggi, revisore
tecnico e supervisore distinti, e l'approvazione del titolare. Una modifica
successiva richiede di ricontrollare i percorsi interessati.

### Registro della verifica professionale

Per ciascun caso approvato annotare: identificativo privato, tipo di media,
contesto disponibile, rilievi attesi, esito ricevuto, omissioni critiche,
falsi positivi, affermazioni non supportate, domande decisive e decisione del
revisore. Separare ciò che è visibile da ciò che è riferito o da verificare.
Non dedurre condizioni personali o fatti non osservabili. I riferimenti normativi
vanno verificati su fonti primarie al momento del collaudo e distinti tra obbligo,
raccomandazione e ipotesi. Questi criteri controllano l'output; non modificano il
metodo approvato e non autorizzano apprendimento automatico dalle correzioni.

Le immagini dei clienti, il master, le risposte reali e le decisioni commerciali
restano fuori dal repository pubblico. Non inventare un insieme di casi
professionali già approvati: finché manca, il passaggio E resta `not_run`.
