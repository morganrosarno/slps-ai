# Collaudo browser sintetico

`node tests/acceptance_browser.cjs` prepara otto percorsi completi: italiano,
tedesco, francese e inglese a 1440 e 390 pixel. Usa le schermate, le route Flask,
gli account, gli archivi e le quote applicative reali in un server temporaneo
su `127.0.0.1`. Solo il risultato del fornitore AI è sostituito con una risposta
sintetica esplicita. I dati di prova sono generati e non rappresentano clienti.

Prerequisiti locali: dipendenze Python del progetto, FFmpeg/FFprobe, Node,
Playwright e il suo browser Chromium già disponibili. Il comando non installa
dipendenze e non chiama servizi remoti. `SLPS_BROWSER_EXECUTABLE` può indicare
un eseguibile Chromium locale esplicitamente scelto. Nessuna chiave API o copia
del master è necessaria.

Il percorso previsto comprende sito, accesso aziendale, foto e contesto,
risultato con ritaglio, blocco esportazione gratuita, archivio e riapertura,
verifica tecnica video/audio, richiesta di contatto registrata e checkout
simulato. Controlla lingua, assenza di scorrimento orizzontale ed errori
JavaScript, e rifiuta richieste browser verso host esterni. Il server blocca
le connessioni in uscita e ripulisce i file temporanei alla terminazione normale.

Le otto aziende sono già verificate da una fixture privata all'avvio. Questo
non dimostra la verifica aziendale reale o la consegna email. Il tono audio
generato prova l'estrazione tecnica: non è una trascrizione o comprensione AI.

Risultati e screenshot sintetici vengono scritti in una cartella temporanea
esterna al repository, oppure nella cartella indicata da
`SLPS_BROWSER_EVIDENCE_DIR`. Conservare il commit collaudato insieme alle prove.
Gli screenshot richiedono una revisione visiva: l'assenza di overflow non
certifica da sola leggibilità, qualità grafica o accessibilità.

## Stato dell'esecuzione

Il 26 ottobre 2026 il server sintetico è stato avviato e ha risposto HTTP 200;
la sintassi Python e JavaScript è stata verificata. Il percorso browser è
**preparato, non ancora eseguito**: nel runtime manca Chromium e il tentativo
standard di installazione Playwright ha restituito un archivio vuoto/non valido
(`End of central directory record signature not found`, `Download failure`).
Non ci sono screenshot o approvazioni grafiche da attribuire a questa prova.

Prima di considerare superato questo controllo, eseguire il comando in un
runtime autorizzato con Chromium disponibile, risolvere eventuali errori,
esaminare i risultati desktop/mobile e registrarne il commit. Anche un esito
positivo resta un collaudo software sintetico: il motore AI reale, la valutazione
SLPS e la persistenza nell'ambiente privato di destinazione hanno prove distinte.
