# Stato operativo dello storage a istanza singola

Questo documento definisce come comunicare e collaudare lo storage locale
durevole a istanza singola senza esporre percorsi, credenziali o dettagli del
volume. Non autorizza un deploy, dati cliente o l'apertura commerciale.

## Tre stati distinti

| Stato mostrato | Significato verificabile | Cosa non dimostra |
| --- | --- | --- |
| `synthetic` | L'app usa soltanto dati sintetici e il preflight riconosce il profilo locale. | Persistenza di dati reali, backup del provider o ripristino. |
| `single-instance configured` | Il profilo durevole è esplicito e il preflight ha superato profilo, layout, capacità e guardia dei dati reali. | Sopravvivenza a riavvio o ridistribuzione; integrità di snapshot e restore. |
| `blocked` | La configurazione è incompleta, incoerente o non riconosciuta. | Qualsiasi autorizzazione a usare dati reali. |

Lo stato `storage_provider_verified` resta `false` nel controllo offline. Diventa
un'evidenza operativa separata soltanto dopo una prova nell'ambiente di
destinazione che includa riavvio e ripristino. Non va derivato dalla presenza di
una cartella, dal nome del piano o dal solo esito del deploy.

## Stato depurato per proprietario e amministratore

Conservare il report completo del preflight in un'area privata. Per ottenere la
sola proiezione sicura, senza messaggi, percorsi o valori di ambiente:

```bash
python scripts/preflight.py --json > private/preflight-storage.json
python scripts/storage_status.py --input private/preflight-storage.json
```

La proiezione contiene soltanto versione dello schema, uno dei tre stati sopra,
`storage_provider_verified: false` e l'ambito
`offline_configuration_only`. Non deve includere root del volume, nomi dei
database, spazio disponibile, segreti, identificativi di backup o messaggi
liberi. Il report completo rimane necessario per correggere un blocco.

## Prova di persistenza nell'ambiente di destinazione

Eseguire la prova con un insieme esclusivamente sintetico e identificabile,
sullo stesso commit e sulla stessa configurazione destinati al collaudo.

1. Registrare privatamente commit, ambiente, ora UTC e stato depurato.
2. Creare un account sintetico verificato, un caso con originale e derivato e
   consumare un contatore di prova, senza chiamare il fornitore AI.
3. Sospendere nuove scritture e confermare esplicitamente la quiescenza prima
   di avviare il backup coordinato. Un backup avviato senza questa conferma non
   è prova valida.
4. Conservare privatamente il manifesto e le impronte prodotte dal backup;
   nessun media o valore di configurazione entra nel repository o nel riepilogo
   pubblico.
5. Riavviare il servizio e verificare login, caso, file e contatore. Ripetere
   dopo una ridistribuzione controllata soltanto quando autorizzata.
6. Ripristinare il backup in una destinazione vuota e isolata. Verificare
   manifesto e impronte, aprire il caso con il proprietario corretto e
   confermare il rifiuto da un'altra azienda o proprietario.
7. Eliminare l'ambiente di ripristino secondo la procedura approvata e
   registrare `pass`, `fail` o `not_run` per riavvio, ridistribuzione e restore.

La prova fallisce se un file o record manca, se le impronte non coincidono, se
il ripristino richiede modifiche manuali non registrate o se l'isolamento tra
aziende non regge. In tal caso lo stato operativo resta `blocked` per dati reali,
anche se la configurazione offline continua a risultare completa.

## Evidenza minima privata

| Campo | Regola |
| --- | --- |
| Commit | SHA esatto distribuito e poi provato. |
| Profilo | `single-instance configured`; nessun percorso. |
| Riavvio | Ora UTC, `pass`/`fail`/`not_run`, puntatore all'evidenza privata. |
| Ridistribuzione | Ora UTC, esito e stesso commit o modifica dichiarata. |
| Ripristino | Ora UTC, esito del manifesto e destinazione isolata, senza nominarla nel riepilogo. |
| Isolamento | Esito accesso proprietario e rifiuto incrociato. |
| Revisori | Operatore e verificatore distinti quando il passaggio chiude un rilievo di rilascio. |

La verifica riguarda una sola istanza applicativa. Non prova alta disponibilità,
scritture concorrenti da più istanze, failover automatico, replica geografica o
backup gestiti. Queste capacità richiedono un'architettura e un collaudo
separati.
