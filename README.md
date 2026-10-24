# SLPS AI — pilota privato
Stato del 23 ottobre 2026. Base recuperata: commit 1006d83. Metodo approvato: 1.8.

Questa versione prepara una prova riservata al proprietario. Non è ancora il servizio commerciale multi-azienda.

## Cosa è stato corretto
- La fotografia viene realmente inviata al modello, insieme al contesto.
- Il master 1.8 è caricato da un file privato e verificato tramite SHA-256.
- Il file originale non viene modificato; solo il changelog storico è escluso dalla richiesta al modello.
- Risultato strutturato con evidenze, incertezze, azioni, termini, domande e ritagli della foto.
- Accesso con password, CSRF, quota oraria e una sola analisi simultanea.
- Upload solo in memoria, controllo del contenuto, 10 MB e 25 megapixel, rimozione dei metadati.
- Nessun risultato inventato in caso di errore o quota esaurita; nessuna ripetizione automatica.

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
Foto e risultati non vengono conservati in uno storico sul server. Sono inviati al fornitore AI configurato.
store=false evita la conservazione della risposta per la funzione Responses; non promette
assenza di qualsiasi conservazione da parte del fornitore. Informativa, accordi e flussi
del trattamento vanno completati prima di usare dati dei clienti.
Il browser conserva il caso aperto in memoria fino a chiusura/ricaricamento. Esportazione JSON
senza immagine e stampa sono azioni esplicite.
SQLite conserva contatori e impronte degli indirizzi per i limiti; i record scaduti sono rimossi
alle richieste successive. SLPS_RATE_DB_PATH deve stare su un volume persistente se i limiti
devono sopravvivere ai redeploy. Un solo server applicativo è supportato in questa fase.
Non è ancora implementata una cronologia dei casi, il controllo multi-azienda o la chiusura
documentata delle misure. Non usarlo come archivio aziendale.

## Verifica
Installa requirements-dev.txt ed esegui:
python -m pytest -q
node --check static/app.js

I test software simulano il fornitore e non dimostrano la qualità SLPS del modello.
La prova reale con API, la verifica grafica nel browser e la configurazione dell'hosting
restano necessarie. Non è stata pubblicata una nuova versione online.

## Prima del rilascio commerciale
1. Prova completa con API attiva e modello scelto: foto → analisi → chiarimento → riesame.
2. Fonti normative controllate e tracciabili, con verifica di pertinenza.
3. Casi persistenti, assegnazione delle misure, evidenze e conferma della chiusura.
4. Separazione fra aziende, cancellazione e backup/ripristino verificati.
5. Casi di accettazione definiti da Morgan, inclusi alcuni casi reali non usati per modificare il metodo.
6. Prezzo sulla base di costi misurati, condizioni, informativa e assistenza.
7. Prova con pochi clienti prima di ampliare l'accesso.

Le correzioni dei clienti non cambiano automaticamente il metodo.

