'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const localeCodes = ['it', 'de', 'fr', 'en'];
  const localeTags = { it: 'it-CH', de: 'de-CH', fr: 'fr-CH', en: 'en-CH' };
  const metaDescriptions = {
    it: 'SLPS AI: analisi AI delle fotografie e verifica tecnica di video e audio per la sicurezza sul lavoro.',
    de: 'SLPS AI: KI-Analyse von Fotos sowie technische Prüfung von Video und Audio für die Arbeitssicherheit.',
    fr: 'SLPS AI : analyse IA de photos et vérification technique de la vidéo et de l’audio pour la sécurité au travail.',
    en: 'SLPS AI: AI analysis of photos and technical verification of video and audio for occupational safety.'
  };
  const messages = {
    it: {
      language: 'Lingua', analysis: 'Analisi', history: 'Archivio', privatePilot: 'Pilota privato', newAnalysis: 'Nuova analisi', logout: 'Esci', account: 'Account', workspaceNav: 'Spazio di lavoro',
      workspaceDefaultTitle: 'Analizza una situazione di lavoro.', workspaceDefaultDescription: 'Inizia da una foto. Aggiungi il contesto. Individua il prossimo passo.', workspaceHistoryTitle: 'I tuoi casi, in un solo posto.', workspaceHistoryDescription: 'Riapri una verifica tecnica o un rapporto e consulta le evidenze conservate.', workspaceVideoTitle: 'Verifica tecnica video salvata.', workspaceVideoDescription: 'Rivedi il video originale, i fotogrammi e lo stato della traccia audio.', workspaceReportTitle: 'Dalla situazione, alle azioni.', workspaceReportDescription: 'Verifica le misure proposte e completa le informazioni che mancano.',
      upload: 'Carica foto o video', changeFile: 'Vuoi cambiare file?', submitDefault: 'Controlla foto e contesto prima di avviare.', submitExisting: 'Il rapporto corrente cambia solo dopo una nuova analisi riuscita.', actionsClarifications: 'Azioni e chiarimenti', verificationAvailable: 'Verifica disponibile', reportAvailable: 'Rapporto disponibile', processing: 'Elaborazione in corso',
      startAnalysis: 'Avvia analisi AI →', inspectVideo: 'Verifica video e audio →', analysing: 'Analisi in corso…', inspecting: 'Verifica in corso…', addPhotoUpdate: 'Aggiungi la foto per aggiornare', updateAnswers: 'Aggiorna con le risposte',
      highRisk: 'Rischio alto', mediumRisk: 'Rischio medio', lowRisk: 'Rischio basso', unknownRisk: 'Rischio da determinare', visible: 'Visibile nella foto', reported: 'Riferito dall’utilizzatore', verify: 'Da verificare sul posto',
      dateUnavailable: 'Data non disponibile', casesCount: '{count} casi salvati disponibili.', noCases: 'Nessun caso salvato.', historyLoading: 'Caricamento delle analisi salvate.', historyUnavailable: 'Archivio non disponibile.', historyLoadFailed: 'Impossibile caricare l’archivio.', storageFull: ' Spazio esaurito: lo storico resta consultabile, ma i nuovi file non possono essere salvati.', storageWarning: ' Lo spazio dello storico è quasi esaurito.',
      videoTechnical: 'Verifica tecnica video', analysisNoSummary: 'Analisi senza sintesi', videoTechnicalContext: 'Video · verifica tecnica, senza analisi dei rischi AI', caseUnavailable: 'Il caso non è consultabile. Riprova per completare la rimozione dei file dal server.', openCheck: 'Apri verifica', openAnalysis: 'Apri analisi', retryDelete: 'Riprova eliminazione', delete: 'Elimina',
      openingCheck: 'Apertura della verifica tecnica salvata.', openingAnalysis: 'Apertura dell’analisi salvata.', opening: 'Apertura…', savedAnalysis: 'Analisi salvata', savedOpened: 'Analisi salvata aperta.', originalStored: 'Il file originale è conservato nel caso. Il rapporto resta da verificare nelle condizioni effettive.', archivedPhotoMissing: 'Questo caso precedente non contiene una fotografia archiviata. Verifica il rapporto con l’immagine originale prima di usarlo.', openFailed: 'Impossibile aprire l’analisi.', openingFailed: 'Apertura non riuscita.',
      confirmDeleteLabel: 'Conferma eliminazione', confirmDeleteQuestion: 'Eliminare definitivamente questo caso e i file conservati?', cancel: 'Annulla', deleting: 'Eliminazione…', deletingStatus: 'Eliminazione del caso salvato.', deleted: 'Caso eliminato definitivamente.', deleteFailed: 'Impossibile eliminare il caso.', deletionFailed: 'Eliminazione non riuscita.',
      selectedPhoto: 'Foto selezionata', selectedVideo: 'Video selezionato', invalidMedia: 'Scegli una foto JPG, PNG, WebP oppure un video MP4, WebM o MOV.', mediaTooLarge: '{kind} supera il limite di {limit} MB.', photoNoun: 'La fotografia', videoNoun: 'Il video', selectMedia: 'Seleziona una foto o un video prima di avviare l’analisi.', contextTooLong: 'Il contesto e le risposte superano 8.000 caratteri. Riduci i dettagli secondari prima di continuare.', configRequired: 'Completa la configurazione del servizio prima di avviare un’analisi.',
      videoReady: 'Verifica durata, fotogrammi e traccia audio (massimo {seconds} secondi). Questa verifica tecnica non esegue ancora l’analisi AI e non consuma la prova gratuita.', videoDisabled: 'La verifica tecnica dei video non è disponibile in questo ambiente. Il file non verrà inviato e la prova gratuita non verrà consumata.', photoForUpdate: 'Fotografia selezionata per il prossimo aggiornamento. Il rapporto salvato non è ancora cambiato: verifica che sia la fotografia originale.',
      photoContextSent: 'Foto e contesto inviati', videoAudioReceived: 'Video e audio acquisiti', analysisRunning: 'Analisi in corso', videoRunning: 'Verifica tecnica in corso', analysisRunningDescription: 'Sto esaminando la situazione per proporre osservazioni, azioni e chiarimenti.', videoRunningDescription: 'Sto controllando durata, fotogrammi e presenza della traccia audio.',
      attemptNoResult: 'Il tentativo non ha prodotto un nuovo risultato.', previousAnalysis: 'Analisi precedente', previousUnchanged: 'L’ultimo tentativo non ha prodotto un nuovo risultato. Questa analisi non include le modifiche o le risposte appena inviate.', unreadableResponse: 'Il servizio ha restituito una risposta non leggibile. Nessuna analisi è stata acquisita.', operationFailed: 'Operazione non riuscita.', analysisFailed: 'Analisi non completata. {reason}{suffix}', requestAborted: 'Richiesta interrotta. Non è stata avviata automaticamente una nuova analisi.', previousAvailable: ' Resta disponibile il risultato precedente.', noResult: ' Nessun risultato è stato acquisito.',
      completed: 'Analisi completata', completedAnnouncement: 'Analisi completata. Il risultato è disponibile e va verificato sul posto.', completedArchived: 'Analisi completata: file originale e rapporto sono archiviati nel caso.', staysHere: ' Il risultato resta consultabile in questa pagina.', exportHint: ' Esporta il rapporto se vuoi conservarlo.',
      assessmentIncomplete: 'Valutazione da completare · restano informazioni decisive da verificare.', assessmentProposed: 'Osservazioni e misure proposte · da confermare nelle condizioni effettive.', situation: 'Situazione analizzata', fullPhotoAlt: 'Fotografia completa utilizzata per questa analisi', noArchivedPhoto: 'Questo caso non contiene una fotografia archiviata. Verificare il rapporto con la foto originale.', noPrintPhoto: 'Fotografia non disponibile per la stampa. Verificare il rapporto con la foto originale.', sentContext: 'Contesto e chiarimenti inviati', noContext: 'Nessun contesto aggiuntivo fornito.', analysisDate: 'Data analisi: {date} · Metodo: {method}', notAvailable: 'non disponibile', notSpecified: 'non indicato',
      questionsCount: 'Domande da chiarire: {count} · Informazioni decisive: {decisive}', goCritical: 'Vai alle domande decisive', goQuestions: 'Vai alle domande', noStructured: 'Nessuna osservazione strutturata restituita. Questo non dimostra l’assenza di pericoli.', observation: 'Osservazione {id}', whatToDo: 'Cosa fare', when: 'Quando: {deadline}', deadlineUnknown: 'Da definire dopo gli accertamenti', cropAria: 'Dettaglio della fotografia per l’osservazione {id}', cropCaption: 'Osservazione {id} · ritaglio indicato dall’AI', fullPhoto: 'Foto completa', cropUnavailable: 'Osservazione {id} · Ritaglio non disponibile. ', openFullPhoto: 'Apri la fotografia completa', seeFullPhoto: 'Consulta la fotografia completa all’inizio del rapporto.', compareOriginal: 'Confrontare con la foto originale, non disponibile in questa stampa.', exposed: 'Persone esposte: {value}', clarify: 'Da chiarire: {value}', references: 'Riferimenti: ',
      unanswered: 'Domande ancora da chiarire', criticalInfo: 'Informazione decisiva', observations: 'Osservazioni: {ids}', moreQuestions: 'Altre domande di approfondimento ({count})', remaining: 'Cosa resta da accertare', sources: 'Fonti disponibili per questa analisi', noSources: 'Nessuna fonte normativa verificata è associata a questa analisi. Gli obblighi specifici richiedono verifica prima di essere presentati come accertati.', verified: 'verifica: {date}', method: 'Metodo: {value}', model: 'Modello: {value}', analysisMeta: 'Analisi: {value}',
      videoSummary: 'Durata verificata: {seconds} s · {frames} fotogrammi campionati.', frameAlt: 'Fotogramma a {seconds} secondi', audioAbsent: 'Nessuna traccia audio presente.', audioSilent: 'Traccia audio digitale priva di segnale.', audioLow: 'Traccia audio con segnale molto debole: deve ancora essere trascritta e verificata.', audioReady: 'Traccia audio estratta: la trascrizione e la comprensibilità non sono ancora state verificate.', audioError: 'Traccia audio presente, ma estrazione non riuscita: la verifica resta incompleta.', audioUnknown: 'Stato audio non determinato.', videoLocalUnavailable: 'La verifica locale dei video non è disponibile.', videoStarted: 'Verifica tecnica di video e audio in corso.', videoComplete: 'Verifica tecnica del video completata.', videoNotCompleted: 'Verifica video non completata. {reason}', audioIncomplete: ' Attenzione: la parte audio non è stata verificata.', archivedVideo: ' Video ed evidenze sono stati salvati nello storico protetto.', trialNotUsed: ' La prova gratuita non è stata consumata.',
      genericApiError: 'Il servizio non ha completato la richiesta. Riprova.', unauthorized: 'La sessione è scaduta. Accedi nuovamente.', forbidden: 'Non disponi dell’autorizzazione necessaria per questa operazione.', invalidRequest: 'La richiesta non è valida. Controlla i dati e riprova.', tooLarge: 'Il file supera il limite consentito.', rateLimited: 'Troppe richieste ravvicinate. Attendi e riprova.', serverUnavailable: 'Il servizio non è temporaneamente disponibile. Riprova più tardi.'
    },
    de: {}, fr: {}, en: {}
  };
  const languageOverrides = {
    de: {
      language:'Sprache',analysis:'Analyse',history:'Archiv',privatePilot:'Privater Pilot',newAnalysis:'Neue Analyse',logout:'Abmelden',account:'Konto',workspaceNav:'Arbeitsbereich',workspaceDefaultTitle:'Arbeitssituation analysieren.',workspaceDefaultDescription:'Beginnen Sie mit einem Foto oder Video. Ergänzen Sie den Kontext. Ermitteln Sie den nächsten Schritt.',workspaceHistoryTitle:'Alle Ihre Fälle an einem Ort.',workspaceHistoryDescription:'Öffnen Sie eine technische Prüfung oder einen Bericht erneut und sehen Sie die gespeicherten Nachweise ein.',workspaceVideoTitle:'Gespeicherte technische Videoprüfung.',workspaceVideoDescription:'Prüfen Sie Originalvideo, Einzelbilder und Status der Audiospur.',workspaceReportTitle:'Von der Situation zu den Massnahmen.',workspaceReportDescription:'Prüfen Sie die vorgeschlagenen Massnahmen und ergänzen Sie fehlende Angaben.',upload:'Foto oder Video hochladen',changeFile:'Datei wechseln?',submitDefault:'Prüfen Sie Datei und Kontext vor dem Start.',submitExisting:'Der aktuelle Bericht ändert sich erst nach einer erfolgreichen neuen Analyse.',actionsClarifications:'Massnahmen und Abklärungen',verificationAvailable:'Prüfung verfügbar',reportAvailable:'Bericht verfügbar',processing:'Verarbeitung läuft',startAnalysis:'KI-Analyse starten →',inspectVideo:'Video und Audio prüfen →',analysing:'Analyse läuft…',inspecting:'Prüfung läuft…',addPhotoUpdate:'Foto für Aktualisierung hinzufügen',updateAnswers:'Mit Antworten aktualisieren',highRisk:'Hohes Risiko',mediumRisk:'Mittleres Risiko',lowRisk:'Niedriges Risiko',unknownRisk:'Risiko zu bestimmen',visible:'Im Foto sichtbar',reported:'Von der nutzenden Person angegeben',verify:'Vor Ort zu prüfen',dateUnavailable:'Datum nicht verfügbar',casesCount:'{count} gespeicherte Fälle verfügbar.',noCases:'Keine gespeicherten Fälle.',historyLoading:'Gespeicherte Fälle werden geladen.',historyUnavailable:'Archiv nicht verfügbar.',historyLoadFailed:'Archiv konnte nicht geladen werden.',storageFull:' Speicher voll: Das Archiv bleibt einsehbar, neue Dateien können nicht gespeichert werden.',storageWarning:' Der Speicher des Archivs ist fast voll.',videoTechnical:'Technische Videoprüfung',analysisNoSummary:'Analyse ohne Zusammenfassung',videoTechnicalContext:'Video · technische Prüfung ohne KI-Risikoanalyse',caseUnavailable:'Der Fall ist nicht verfügbar. Versuchen Sie erneut, die Dateien vom Server zu entfernen.',openCheck:'Prüfung öffnen',openAnalysis:'Analyse öffnen',retryDelete:'Löschen erneut versuchen',delete:'Löschen',openingCheck:'Gespeicherte technische Prüfung wird geöffnet.',openingAnalysis:'Gespeicherte Analyse wird geöffnet.',opening:'Wird geöffnet…',savedAnalysis:'Gespeicherte Analyse',savedOpened:'Gespeicherte Analyse geöffnet.',originalStored:'Die Originaldatei ist im Fall gespeichert. Der Bericht muss unter realen Bedingungen geprüft werden.',archivedPhotoMissing:'Dieser frühere Fall enthält kein gespeichertes Foto. Prüfen Sie den Bericht mit dem Originalbild.',openFailed:'Analyse konnte nicht geöffnet werden.',openingFailed:'Öffnen fehlgeschlagen.',confirmDeleteLabel:'Löschen bestätigen',confirmDeleteQuestion:'Diesen Fall und die gespeicherten Dateien endgültig löschen?',cancel:'Abbrechen',deleting:'Wird gelöscht…',deletingStatus:'Gespeicherter Fall wird gelöscht.',deleted:'Fall endgültig gelöscht.',deleteFailed:'Fall konnte nicht gelöscht werden.',deletionFailed:'Löschen fehlgeschlagen.',selectedPhoto:'Foto ausgewählt',selectedVideo:'Video ausgewählt',invalidMedia:'Wählen Sie ein JPG-, PNG- oder WebP-Foto oder ein MP4-, WebM- oder MOV-Video.',mediaTooLarge:'{kind} überschreitet die Grenze von {limit} MB.',photoNoun:'Das Foto',videoNoun:'Das Video',selectMedia:'Wählen Sie vor dem Start ein Foto oder Video.',contextTooLong:'Kontext und Antworten überschreiten 8.000 Zeichen. Kürzen Sie nebensächliche Angaben.',configRequired:'Schliessen Sie die Dienstkonfiguration vor einer Analyse ab.',videoReady:'Prüft Dauer, Einzelbilder und Audiospur (maximal {seconds} Sekunden). Diese technische Prüfung führt noch keine KI-Analyse aus und verbraucht den Gratistest nicht.',videoDisabled:'Die technische Videoprüfung ist in dieser Umgebung nicht verfügbar. Die Datei wird nicht gesendet und der Gratistest nicht verbraucht.',photoForUpdate:'Foto für die nächste Aktualisierung ausgewählt. Der gespeicherte Bericht ist noch unverändert; prüfen Sie, ob es das Originalfoto ist.',photoContextSent:'Foto und Kontext gesendet',videoAudioReceived:'Video und Audio erfasst',analysisRunning:'Analyse läuft',videoRunning:'Technische Prüfung läuft',analysisRunningDescription:'Die Situation wird geprüft, um Beobachtungen, Massnahmen und Abklärungen vorzuschlagen.',videoRunningDescription:'Dauer, Einzelbilder und Audiospur werden geprüft.',attemptNoResult:'Der Versuch hat kein neues Ergebnis erzeugt.',previousAnalysis:'Vorherige Analyse',previousUnchanged:'Der letzte Versuch hat kein neues Ergebnis erzeugt. Diese Analyse enthält die soeben gesendeten Änderungen oder Antworten nicht.',unreadableResponse:'Der Dienst hat eine unlesbare Antwort geliefert. Es wurde keine Analyse übernommen.',operationFailed:'Vorgang fehlgeschlagen.',analysisFailed:'Analyse nicht abgeschlossen. {reason}{suffix}',requestAborted:'Anfrage abgebrochen. Es wurde nicht automatisch eine neue Analyse gestartet.',previousAvailable:' Das vorherige Ergebnis bleibt verfügbar.',noResult:' Es wurde kein Ergebnis übernommen.',completed:'Analyse abgeschlossen',completedAnnouncement:'Analyse abgeschlossen. Das Ergebnis ist verfügbar und muss vor Ort geprüft werden.',completedArchived:'Analyse abgeschlossen: Originaldatei und Bericht sind im Fall archiviert.',staysHere:' Das Ergebnis bleibt auf dieser Seite einsehbar.',exportHint:' Exportieren Sie den Bericht, wenn Sie ihn behalten möchten.',assessmentIncomplete:'Bewertung zu vervollständigen · entscheidende Angaben müssen noch geprüft werden.',assessmentProposed:'Beobachtungen und vorgeschlagene Massnahmen · unter realen Bedingungen zu bestätigen.',situation:'Analysierte Situation',fullPhotoAlt:'Für diese Analyse verwendetes vollständiges Foto',noArchivedPhoto:'Dieser Fall enthält kein gespeichertes Foto. Prüfen Sie den Bericht mit dem Originalfoto.',noPrintPhoto:'Foto für den Ausdruck nicht verfügbar. Prüfen Sie den Bericht mit dem Originalfoto.',sentContext:'Übermittelter Kontext und Erläuterungen',noContext:'Kein zusätzlicher Kontext angegeben.',analysisDate:'Analysedatum: {date} · Methode: {method}',notAvailable:'nicht verfügbar',notSpecified:'nicht angegeben',questionsCount:'Zu klärende Fragen: {count} · Entscheidende Angaben: {decisive}',goCritical:'Zu den entscheidenden Fragen',goQuestions:'Zu den Fragen',noStructured:'Keine strukturierten Beobachtungen zurückgegeben. Dies belegt nicht, dass keine Gefahren bestehen.',observation:'Beobachtung {id}',whatToDo:'Was ist zu tun',when:'Wann: {deadline}',deadlineUnknown:'Nach den Abklärungen festzulegen',cropAria:'Fotodetail für Beobachtung {id}',cropCaption:'Beobachtung {id} · von der KI angegebener Ausschnitt',fullPhoto:'Vollständiges Foto',cropUnavailable:'Beobachtung {id} · Ausschnitt nicht verfügbar. ',openFullPhoto:'Vollständiges Foto öffnen',seeFullPhoto:'Siehe vollständiges Foto am Anfang des Berichts.',compareOriginal:'Mit dem Originalfoto vergleichen; es ist in diesem Ausdruck nicht verfügbar.',exposed:'Exponierte Personen: {value}',clarify:'Zu klären: {value}',references:'Referenzen: ',unanswered:'Noch offene Fragen',criticalInfo:'Entscheidende Angabe',observations:'Beobachtungen: {ids}',moreQuestions:'Weitere Vertiefungsfragen ({count})',remaining:'Noch abzuklären',sources:'Für diese Analyse verfügbare Quellen',noSources:'Dieser Analyse ist keine geprüfte Rechtsquelle zugeordnet. Spezifische Pflichten müssen geprüft werden, bevor sie als festgestellt gelten.',verified:'geprüft: {date}',method:'Methode: {value}',model:'Modell: {value}',analysisMeta:'Analyse: {value}',videoSummary:'Geprüfte Dauer: {seconds} s · {frames} Einzelbilder.',frameAlt:'Einzelbild bei {seconds} Sekunden',audioAbsent:'Keine Audiospur vorhanden.',audioSilent:'Digitale Audiospur ohne Signal.',audioLow:'Audiospur mit sehr schwachem Signal; Transkription und Prüfung stehen aus.',audioReady:'Audiospur extrahiert; Transkription und Verständlichkeit wurden noch nicht geprüft.',audioError:'Audiospur vorhanden, Extraktion fehlgeschlagen; die Prüfung bleibt unvollständig.',audioUnknown:'Audiostatus nicht bestimmt.',videoLocalUnavailable:'Lokale Videoprüfung nicht verfügbar.',videoStarted:'Technische Video- und Audioprüfung läuft.',videoComplete:'Technische Videoprüfung abgeschlossen.',videoNotCompleted:'Videoprüfung nicht abgeschlossen. {reason}',audioIncomplete:' Achtung: Der Audioteil wurde nicht geprüft.',archivedVideo:' Video und Nachweise wurden im geschützten Archiv gespeichert.',trialNotUsed:' Der Gratistest wurde nicht verbraucht.',genericApiError:'Der Dienst konnte die Anfrage nicht abschliessen. Versuchen Sie es erneut.',unauthorized:'Die Sitzung ist abgelaufen. Melden Sie sich erneut an.',forbidden:'Sie sind für diesen Vorgang nicht berechtigt.',invalidRequest:'Die Anfrage ist ungültig. Prüfen Sie die Angaben und versuchen Sie es erneut.',tooLarge:'Die Datei überschreitet die erlaubte Grösse.',rateLimited:'Zu viele Anfragen in kurzer Zeit. Warten Sie und versuchen Sie es erneut.',serverUnavailable:'Der Dienst ist vorübergehend nicht verfügbar. Versuchen Sie es später erneut.'
    },
    fr: {
      language:'Langue',analysis:'Analyse',history:'Historique',privatePilot:'Pilote privé',newAnalysis:'Nouvelle analyse',logout:'Déconnexion',account:'Compte',workspaceNav:'Espace de travail',workspaceDefaultTitle:'Analysez une situation de travail.',workspaceDefaultDescription:'Commencez par une photo ou une vidéo. Ajoutez le contexte. Identifiez la prochaine étape.',workspaceHistoryTitle:'Tous vos dossiers au même endroit.',workspaceHistoryDescription:'Rouvrez une vérification technique ou un rapport et consultez les preuves conservées.',workspaceVideoTitle:'Vérification technique vidéo enregistrée.',workspaceVideoDescription:'Consultez la vidéo originale, les images et l’état de la piste audio.',workspaceReportTitle:'De la situation aux actions.',workspaceReportDescription:'Vérifiez les mesures proposées et complétez les informations manquantes.',upload:'Importer une photo ou une vidéo',changeFile:'Changer de fichier ?',submitDefault:'Vérifiez le fichier et le contexte avant de commencer.',submitExisting:'Le rapport actuel ne change qu’après une nouvelle analyse réussie.',actionsClarifications:'Actions et clarifications',verificationAvailable:'Vérification disponible',reportAvailable:'Rapport disponible',processing:'Traitement en cours',startAnalysis:'Lancer l’analyse IA →',inspectVideo:'Vérifier vidéo et audio →',analysing:'Analyse en cours…',inspecting:'Vérification en cours…',addPhotoUpdate:'Ajouter la photo pour actualiser',updateAnswers:'Actualiser avec les réponses',highRisk:'Risque élevé',mediumRisk:'Risque moyen',lowRisk:'Risque faible',unknownRisk:'Risque à déterminer',visible:'Visible sur la photo',reported:'Signalé par l’utilisateur',verify:'À vérifier sur place',dateUnavailable:'Date indisponible',casesCount:'{count} dossiers enregistrés disponibles.',noCases:'Aucun dossier enregistré.',historyLoading:'Chargement des dossiers enregistrés.',historyUnavailable:'Historique indisponible.',historyLoadFailed:'Impossible de charger l’historique.',storageFull:' Espace saturé : l’historique reste consultable, mais aucun nouveau fichier ne peut être enregistré.',storageWarning:' L’espace de l’historique est presque saturé.',videoTechnical:'Vérification technique vidéo',analysisNoSummary:'Analyse sans synthèse',videoTechnicalContext:'Vidéo · vérification technique sans analyse IA des risques',caseUnavailable:'Ce dossier n’est pas consultable. Réessayez pour supprimer les fichiers du serveur.',openCheck:'Ouvrir la vérification',openAnalysis:'Ouvrir l’analyse',retryDelete:'Réessayer la suppression',delete:'Supprimer',openingCheck:'Ouverture de la vérification technique enregistrée.',openingAnalysis:'Ouverture de l’analyse enregistrée.',opening:'Ouverture…',savedAnalysis:'Analyse enregistrée',savedOpened:'Analyse enregistrée ouverte.',originalStored:'Le fichier original est conservé dans le dossier. Le rapport doit être vérifié dans les conditions réelles.',archivedPhotoMissing:'Cet ancien dossier ne contient aucune photo archivée. Vérifiez le rapport avec l’image originale.',openFailed:'Impossible d’ouvrir l’analyse.',openingFailed:'Échec de l’ouverture.',confirmDeleteLabel:'Confirmer la suppression',confirmDeleteQuestion:'Supprimer définitivement ce dossier et les fichiers conservés ?',cancel:'Annuler',deleting:'Suppression…',deletingStatus:'Suppression du dossier enregistré.',deleted:'Dossier définitivement supprimé.',deleteFailed:'Impossible de supprimer le dossier.',deletionFailed:'Échec de la suppression.',selectedPhoto:'Photo sélectionnée',selectedVideo:'Vidéo sélectionnée',invalidMedia:'Choisissez une photo JPG, PNG ou WebP, ou une vidéo MP4, WebM ou MOV.',mediaTooLarge:'{kind} dépasse la limite de {limit} Mo.',photoNoun:'La photo',videoNoun:'La vidéo',selectMedia:'Sélectionnez une photo ou une vidéo avant de lancer l’analyse.',contextTooLong:'Le contexte et les réponses dépassent 8 000 caractères. Réduisez les détails secondaires.',configRequired:'Terminez la configuration du service avant de lancer une analyse.',videoReady:'Vérifie la durée, les images et la piste audio (maximum {seconds} secondes). Cette vérification technique n’effectue pas encore d’analyse IA et ne consomme pas l’essai gratuit.',videoDisabled:'La vérification technique des vidéos n’est pas disponible dans cet environnement. Le fichier ne sera pas envoyé et l’essai gratuit ne sera pas consommé.',photoForUpdate:'Photo sélectionnée pour la prochaine actualisation. Le rapport enregistré n’a pas encore changé ; vérifiez qu’il s’agit de la photo originale.',photoContextSent:'Photo et contexte envoyés',videoAudioReceived:'Vidéo et audio acquis',analysisRunning:'Analyse en cours',videoRunning:'Vérification technique en cours',analysisRunningDescription:'La situation est examinée afin de proposer des observations, des actions et des clarifications.',videoRunningDescription:'Vérification de la durée, des images et de la piste audio.',attemptNoResult:'La tentative n’a produit aucun nouveau résultat.',previousAnalysis:'Analyse précédente',previousUnchanged:'La dernière tentative n’a produit aucun nouveau résultat. Cette analyse n’inclut pas les modifications ou réponses qui viennent d’être envoyées.',unreadableResponse:'Le service a renvoyé une réponse illisible. Aucune analyse n’a été enregistrée.',operationFailed:'Échec de l’opération.',analysisFailed:'Analyse non terminée. {reason}{suffix}',requestAborted:'Requête interrompue. Aucune nouvelle analyse n’a été lancée automatiquement.',previousAvailable:' Le résultat précédent reste disponible.',noResult:' Aucun résultat n’a été enregistré.',completed:'Analyse terminée',completedAnnouncement:'Analyse terminée. Le résultat est disponible et doit être vérifié sur place.',completedArchived:'Analyse terminée : le fichier original et le rapport sont archivés dans le dossier.',staysHere:' Le résultat reste consultable sur cette page.',exportHint:' Exportez le rapport si vous souhaitez le conserver.',assessmentIncomplete:'Évaluation à compléter · des informations décisives restent à vérifier.',assessmentProposed:'Observations et mesures proposées · à confirmer dans les conditions réelles.',situation:'Situation analysée',fullPhotoAlt:'Photo complète utilisée pour cette analyse',noArchivedPhoto:'Ce dossier ne contient aucune photo archivée. Vérifiez le rapport avec la photo originale.',noPrintPhoto:'Photo indisponible pour l’impression. Vérifiez le rapport avec la photo originale.',sentContext:'Contexte et précisions envoyés',noContext:'Aucun contexte supplémentaire fourni.',analysisDate:'Date de l’analyse : {date} · Méthode : {method}',notAvailable:'indisponible',notSpecified:'non indiqué',questionsCount:'Questions à clarifier : {count} · Informations décisives : {decisive}',goCritical:'Aller aux questions décisives',goQuestions:'Aller aux questions',noStructured:'Aucune observation structurée n’a été renvoyée. Cela ne prouve pas l’absence de dangers.',observation:'Observation {id}',whatToDo:'Action à mener',when:'Quand : {deadline}',deadlineUnknown:'À définir après les vérifications',cropAria:'Détail de la photo pour l’observation {id}',cropCaption:'Observation {id} · recadrage indiqué par l’IA',fullPhoto:'Photo complète',cropUnavailable:'Observation {id} · Recadrage indisponible. ',openFullPhoto:'Ouvrir la photo complète',seeFullPhoto:'Consultez la photo complète au début du rapport.',compareOriginal:'Comparer avec la photo originale, indisponible dans cette impression.',exposed:'Personnes exposées : {value}',clarify:'À clarifier : {value}',references:'Références : ',unanswered:'Questions restant à clarifier',criticalInfo:'Information décisive',observations:'Observations : {ids}',moreQuestions:'Autres questions d’approfondissement ({count})',remaining:'Points restant à vérifier',sources:'Sources disponibles pour cette analyse',noSources:'Aucune source normative vérifiée n’est associée à cette analyse. Les obligations spécifiques doivent être vérifiées avant d’être présentées comme établies.',verified:'vérification : {date}',method:'Méthode : {value}',model:'Modèle : {value}',analysisMeta:'Analyse : {value}',videoSummary:'Durée vérifiée : {seconds} s · {frames} images échantillonnées.',frameAlt:'Image à {seconds} secondes',audioAbsent:'Aucune piste audio présente.',audioSilent:'Piste audio numérique sans signal.',audioLow:'Piste audio avec un signal très faible ; elle doit encore être transcrite et vérifiée.',audioReady:'Piste audio extraite ; la transcription et l’intelligibilité n’ont pas encore été vérifiées.',audioError:'Piste audio présente, mais extraction échouée ; la vérification reste incomplète.',audioUnknown:'État audio indéterminé.',videoLocalUnavailable:'La vérification locale des vidéos n’est pas disponible.',videoStarted:'Vérification technique de la vidéo et de l’audio en cours.',videoComplete:'Vérification technique de la vidéo terminée.',videoNotCompleted:'Vérification vidéo non terminée. {reason}',audioIncomplete:' Attention : la partie audio n’a pas été vérifiée.',archivedVideo:' La vidéo et les preuves ont été enregistrées dans l’historique protégé.',trialNotUsed:' L’essai gratuit n’a pas été consommé.',genericApiError:'Le service n’a pas pu terminer la requête. Réessayez.',unauthorized:'La session a expiré. Reconnectez-vous.',forbidden:'Vous n’êtes pas autorisé à effectuer cette opération.',invalidRequest:'La requête n’est pas valide. Vérifiez les données et réessayez.',tooLarge:'Le fichier dépasse la taille autorisée.',rateLimited:'Trop de requêtes rapprochées. Attendez puis réessayez.',serverUnavailable:'Le service est temporairement indisponible. Réessayez plus tard.'
    },
    en: {
      language:'Language',analysis:'Analysis',history:'History',privatePilot:'Private pilot',newAnalysis:'New analysis',logout:'Sign out',account:'Account',workspaceNav:'Workspace',workspaceDefaultTitle:'Analyse a work situation.',workspaceDefaultDescription:'Start with a photo or video. Add context. Identify the next step.',workspaceHistoryTitle:'All your cases in one place.',workspaceHistoryDescription:'Reopen a technical check or report and review the stored evidence.',workspaceVideoTitle:'Saved technical video check.',workspaceVideoDescription:'Review the original video, sampled frames and audio-track status.',workspaceReportTitle:'From the situation to action.',workspaceReportDescription:'Review the proposed measures and complete missing information.',upload:'Upload photo or video',changeFile:'Change file?',submitDefault:'Check the file and context before starting.',submitExisting:'The current report changes only after a successful new analysis.',actionsClarifications:'Actions and clarifications',verificationAvailable:'Check available',reportAvailable:'Report available',processing:'Processing',startAnalysis:'Start AI analysis →',inspectVideo:'Check video and audio →',analysing:'Analysis in progress…',inspecting:'Check in progress…',addPhotoUpdate:'Add the photo to update',updateAnswers:'Update with answers',highRisk:'High risk',mediumRisk:'Medium risk',lowRisk:'Low risk',unknownRisk:'Risk to determine',visible:'Visible in the photo',reported:'Reported by the user',verify:'Verify on site',dateUnavailable:'Date unavailable',casesCount:'{count} saved cases available.',noCases:'No saved cases.',historyLoading:'Loading saved cases.',historyUnavailable:'History unavailable.',historyLoadFailed:'Unable to load history.',storageFull:' Storage is full: history remains available, but new files cannot be saved.',storageWarning:' History storage is nearly full.',videoTechnical:'Technical video check',analysisNoSummary:'Analysis without summary',videoTechnicalContext:'Video · technical check without AI risk analysis',caseUnavailable:'This case cannot be opened. Try again to finish removing its files from the server.',openCheck:'Open check',openAnalysis:'Open analysis',retryDelete:'Retry deletion',delete:'Delete',openingCheck:'Opening saved technical check.',openingAnalysis:'Opening saved analysis.',opening:'Opening…',savedAnalysis:'Saved analysis',savedOpened:'Saved analysis opened.',originalStored:'The original file is stored with the case. The report must be verified under actual conditions.',archivedPhotoMissing:'This earlier case has no archived photo. Verify the report against the original image.',openFailed:'Unable to open the analysis.',openingFailed:'Opening failed.',confirmDeleteLabel:'Confirm deletion',confirmDeleteQuestion:'Permanently delete this case and its stored files?',cancel:'Cancel',deleting:'Deleting…',deletingStatus:'Deleting saved case.',deleted:'Case permanently deleted.',deleteFailed:'Unable to delete the case.',deletionFailed:'Deletion failed.',selectedPhoto:'Photo selected',selectedVideo:'Video selected',invalidMedia:'Choose a JPG, PNG or WebP photo, or an MP4, WebM or MOV video.',mediaTooLarge:'{kind} exceeds the {limit} MB limit.',photoNoun:'The photo',videoNoun:'The video',selectMedia:'Select a photo or video before starting the analysis.',contextTooLong:'Context and answers exceed 8,000 characters. Remove secondary details before continuing.',configRequired:'Complete the service configuration before starting an analysis.',videoReady:'Checks duration, frames and audio track (maximum {seconds} seconds). This technical check does not yet run AI analysis and does not use the free trial.',videoDisabled:'Technical video checking is unavailable in this environment. The file will not be sent and the free trial will not be used.',photoForUpdate:'Photo selected for the next update. The saved report has not changed yet; check that this is the original photo.',photoContextSent:'Photo and context sent',videoAudioReceived:'Video and audio received',analysisRunning:'Analysis in progress',videoRunning:'Technical check in progress',analysisRunningDescription:'The situation is being examined to propose observations, actions and clarifications.',videoRunningDescription:'Checking duration, sampled frames and the audio track.',attemptNoResult:'The attempt did not produce a new result.',previousAnalysis:'Previous analysis',previousUnchanged:'The latest attempt did not produce a new result. This analysis does not include the changes or answers just submitted.',unreadableResponse:'The service returned an unreadable response. No analysis was recorded.',operationFailed:'Operation failed.',analysisFailed:'Analysis not completed. {reason}{suffix}',requestAborted:'Request cancelled. A new analysis was not started automatically.',previousAvailable:' The previous result remains available.',noResult:' No result was recorded.',completed:'Analysis complete',completedAnnouncement:'Analysis complete. The result is available and must be verified on site.',completedArchived:'Analysis complete: the original file and report are archived with the case.',staysHere:' The result remains available on this page.',exportHint:' Export the report if you want to keep it.',assessmentIncomplete:'Assessment to complete · decisive information still needs verification.',assessmentProposed:'Observations and proposed measures · confirm under actual conditions.',situation:'Situation analysed',fullPhotoAlt:'Full photo used for this analysis',noArchivedPhoto:'This case has no archived photo. Verify the report against the original photo.',noPrintPhoto:'Photo unavailable for printing. Verify the report against the original photo.',sentContext:'Submitted context and clarifications',noContext:'No additional context provided.',analysisDate:'Analysis date: {date} · Method: {method}',notAvailable:'unavailable',notSpecified:'not specified',questionsCount:'Questions to clarify: {count} · Decisive information: {decisive}',goCritical:'Go to decisive questions',goQuestions:'Go to questions',noStructured:'No structured observations were returned. This does not demonstrate an absence of hazards.',observation:'Observation {id}',whatToDo:'What to do',when:'When: {deadline}',deadlineUnknown:'Define after verification',cropAria:'Photo detail for observation {id}',cropCaption:'Observation {id} · crop indicated by AI',fullPhoto:'Full photo',cropUnavailable:'Observation {id} · Crop unavailable. ',openFullPhoto:'Open full photo',seeFullPhoto:'See the full photo at the beginning of the report.',compareOriginal:'Compare with the original photo, which is unavailable in this printout.',exposed:'People exposed: {value}',clarify:'To clarify: {value}',references:'References: ',unanswered:'Questions still to clarify',criticalInfo:'Decisive information',observations:'Observations: {ids}',moreQuestions:'More detailed questions ({count})',remaining:'What remains to be checked',sources:'Sources available for this analysis',noSources:'No verified regulatory source is associated with this analysis. Specific obligations must be checked before they are presented as established.',verified:'verified: {date}',method:'Method: {value}',model:'Model: {value}',analysisMeta:'Analysis: {value}',videoSummary:'Verified duration: {seconds} s · {frames} sampled frames.',frameAlt:'Frame at {seconds} seconds',audioAbsent:'No audio track present.',audioSilent:'Digital audio track with no signal.',audioLow:'Audio track with a very weak signal; it still needs transcription and verification.',audioReady:'Audio track extracted; transcription and intelligibility have not yet been verified.',audioError:'Audio track present, but extraction failed; the check remains incomplete.',audioUnknown:'Audio status undetermined.',videoLocalUnavailable:'Local video checking is unavailable.',videoStarted:'Technical video and audio check in progress.',videoComplete:'Technical video check complete.',videoNotCompleted:'Video check not completed. {reason}',audioIncomplete:' Warning: audio was not verified.',archivedVideo:' Video and evidence were saved in protected history.',trialNotUsed:' The free trial was not used.',genericApiError:'The service could not complete the request. Try again.',unauthorized:'Your session has expired. Sign in again.',forbidden:'You are not authorised to perform this operation.',invalidRequest:'The request is invalid. Check the data and try again.',tooLarge:'The file exceeds the allowed size.',rateLimited:'Too many requests in a short period. Wait and try again.',serverUnavailable:'The service is temporarily unavailable. Try again later.'
    }
  };
  Object.assign(messages.it, { trialUsed: 'La prova gratuita è stata utilizzata. Puoi consultare il risultato; una nuova analisi richiede un piano successivo.', notArchived: 'Il risultato non è stato archiviato; resta disponibile in questa pagina.', videoChecked: 'Verifica tecnica completata.', pilotUnconfigured:'L’accesso al pilota non è ancora configurato. Completa la configurazione riservata del servizio prima di utilizzarlo.', analysisUnconfigured:'Il pilota è accessibile, ma la configurazione per l’analisi non è completa. Il file non verrà inviato finché il servizio non sarà configurato.', sessionClosed:'Sessione chiusa.', sessionExpired:'Sessione scaduta. Accedi nuovamente.', videoCaseOpened:'Verifica tecnica video aperta.', savedVideoIncomplete:'La verifica video salvata è incompleta.', savedFramesMismatch:'I fotogrammi conservati non corrispondono alla verifica salvata.', savedCaseIncomplete:'Il caso salvato è incompleto.', incompleteResult:'Il risultato è incompleto. Non è stato presentato come analisi valida.', videoOriginalNoAudio:'Il video originale è conservato in questo caso protetto. Il file non contiene una traccia audio.', videoOriginalAudio:'Il video originale è conservato in questo caso protetto. La traccia audio presente nel contenitore è stata mantenuta; stato e qualità restano indicati qui sotto.', videoOriginalMissing:'Il video originale non è disponibile in questo caso; usa i fotogrammi soltanto come evidenza parziale.', exported:'Analisi esportata in JSON. La fotografia non è inclusa nel file.', printPhotoNotReady:'La fotografia non è pronta per la stampa. Riprova prima di stampare il rapporto.' });
  Object.assign(languageOverrides.de, { trialUsed:'Der Gratistest wurde verwendet. Das Ergebnis bleibt einsehbar; eine neue Analyse erfordert einen weiteren Plan.',notArchived:'Das Ergebnis wurde nicht archiviert und bleibt auf dieser Seite verfügbar.',videoChecked:'Technische Prüfung abgeschlossen.',pilotUnconfigured:'Der Pilotzugang ist noch nicht konfiguriert. Schliessen Sie zuerst die geschützte Dienstkonfiguration ab.',analysisUnconfigured:'Der Pilot ist zugänglich, die Analyse aber noch nicht vollständig konfiguriert. Die Datei wird bis dahin nicht gesendet.',sessionClosed:'Sitzung beendet.',sessionExpired:'Sitzung abgelaufen. Melden Sie sich erneut an.',videoCaseOpened:'Technische Videoprüfung geöffnet.',savedVideoIncomplete:'Die gespeicherte Videoprüfung ist unvollständig.',savedFramesMismatch:'Die gespeicherten Einzelbilder entsprechen nicht der Prüfung.',savedCaseIncomplete:'Der gespeicherte Fall ist unvollständig.',incompleteResult:'Das Ergebnis ist unvollständig und wurde nicht als gültige Analyse dargestellt.',videoOriginalNoAudio:'Das Originalvideo ist in diesem geschützten Fall gespeichert. Die Datei enthält keine Audiospur.',videoOriginalAudio:'Das Originalvideo ist im geschützten Fall gespeichert. Die Audiospur wurde beibehalten; Status und Qualität stehen unten.',videoOriginalMissing:'Das Originalvideo ist in diesem Fall nicht verfügbar; Einzelbilder sind nur Teilnachweise.',exported:'Analyse als JSON exportiert. Das Foto ist nicht enthalten.',printPhotoNotReady:'Das Foto ist noch nicht druckbereit. Versuchen Sie es erneut.' });
  Object.assign(languageOverrides.fr, { trialUsed:'L’essai gratuit a été utilisé. Le résultat reste consultable ; une nouvelle analyse nécessite une formule ultérieure.',notArchived:'Le résultat n’a pas été archivé et reste disponible sur cette page.',videoChecked:'Vérification technique terminée.',pilotUnconfigured:'L’accès au pilote n’est pas encore configuré. Terminez d’abord la configuration réservée du service.',analysisUnconfigured:'Le pilote est accessible, mais l’analyse n’est pas entièrement configurée. Le fichier ne sera pas envoyé avant la fin de la configuration.',sessionClosed:'Session terminée.',sessionExpired:'Session expirée. Reconnectez-vous.',videoCaseOpened:'Vérification technique vidéo ouverte.',savedVideoIncomplete:'La vérification vidéo enregistrée est incomplète.',savedFramesMismatch:'Les images conservées ne correspondent pas à la vérification.',savedCaseIncomplete:'Le dossier enregistré est incomplet.',incompleteResult:'Le résultat est incomplet et n’a pas été présenté comme une analyse valide.',videoOriginalNoAudio:'La vidéo originale est conservée dans ce dossier protégé. Le fichier ne contient aucune piste audio.',videoOriginalAudio:'La vidéo originale est conservée dans ce dossier protégé. La piste audio a été maintenue ; son état et sa qualité figurent ci-dessous.',videoOriginalMissing:'La vidéo originale n’est pas disponible dans ce dossier ; les images ne constituent qu’une preuve partielle.',exported:'Analyse exportée en JSON. La photo n’est pas incluse.',printPhotoNotReady:'La photo n’est pas prête pour l’impression. Réessayez.' });
  Object.assign(languageOverrides.en, { trialUsed:'The free trial has been used. You can still view the result; a new analysis requires a later plan.',notArchived:'The result was not archived and remains available on this page.',videoChecked:'Technical check complete.',pilotUnconfigured:'Pilot access is not configured yet. Complete the restricted service configuration first.',analysisUnconfigured:'The pilot is available, but analysis is not fully configured. The file will not be sent until configuration is complete.',sessionClosed:'Session closed.',sessionExpired:'Session expired. Sign in again.',videoCaseOpened:'Technical video check opened.',savedVideoIncomplete:'The saved video check is incomplete.',savedFramesMismatch:'Stored frames do not match the saved check.',savedCaseIncomplete:'The saved case is incomplete.',incompleteResult:'The result is incomplete and was not presented as a valid analysis.',videoOriginalNoAudio:'The original video is stored in this protected case. The file has no audio track.',videoOriginalAudio:'The original video is stored in this protected case. Its audio track was retained; status and quality are shown below.',videoOriginalMissing:'The original video is unavailable in this case; use sampled frames only as partial evidence.',exported:'Analysis exported as JSON. The photo is not included.',printPhotoNotReady:'The photo is not ready to print. Try again.' });
  Object.assign(messages.it, { archiveFullExisting:'Spazio archivio esaurito: i casi esistenti restano disponibili.', sessionReloadLoss:'Sessione scaduta e nuovo accesso non disponibile. Ricarica la pagina prima di accedere. Il rapporto locale resta nella pagina, ma verrà perso al ricaricamento.' });
  Object.assign(languageOverrides.de, { archiveFullExisting:'Archivspeicher voll: Bestehende Fälle bleiben verfügbar.', sessionReloadLoss:'Sitzung abgelaufen und erneute Anmeldung nicht verfügbar. Laden Sie die Seite neu. Der lokale Bericht bleibt bis dahin sichtbar, geht beim Neuladen aber verloren.' });
  Object.assign(languageOverrides.fr, { archiveFullExisting:'Espace de l’historique saturé : les dossiers existants restent disponibles.', sessionReloadLoss:'Session expirée et nouvelle connexion indisponible. Rechargez la page. Le rapport local reste visible jusque-là, mais sera perdu au rechargement.' });
  Object.assign(languageOverrides.en, { archiveFullExisting:'History storage is full: existing cases remain available.', sessionReloadLoss:'Session expired and a new sign-in is unavailable. Reload the page. The local report remains visible until then but will be lost on reload.' });
  const sourceTranslations = {
  "it": {
    "sourceObligation": "Obbligo nella fonte",
    "sourceRecommendation": "Raccomandazione nella fonte",
    "sourceHypothesis": "Ipotesi da verificare",
    "sourceUnclassified": "Non classificato · da verificare",
    "sourceContext": "La classificazione riguarda il contenuto citato. L’applicabilità alla situazione va verificata: il solo riferimento non dimostra una violazione o la conformità.",
    "sourceLocator": "Riferimento preciso: {value}",
    "sourceScope": "Ambito: {value}",
    "sourceVersion": "Versione del documento: {value}",
    "sourceRegistry": "Registro fonti: {value}",
    "sourceLimits": "Limiti del riferimento"
  },
  "de": {
    "sourceObligation": "Pflicht in der Quelle",
    "sourceRecommendation": "Empfehlung in der Quelle",
    "sourceHypothesis": "Zu prüfende Annahme",
    "sourceUnclassified": "Nicht eingestuft · zu prüfen",
    "sourceContext": "Die Einstufung betrifft den zitierten Inhalt. Die Anwendbarkeit auf die Situation ist zu prüfen: Der Verweis allein belegt weder einen Verstoss noch die Konformität.",
    "sourceLocator": "Genaue Fundstelle: {value}",
    "sourceScope": "Geltungsbereich: {value}",
    "sourceVersion": "Dokumentversion: {value}",
    "sourceRegistry": "Quellenregister: {value}",
    "sourceLimits": "Grenzen des Verweises"
  },
  "fr": {
    "sourceObligation": "Obligation dans la source",
    "sourceRecommendation": "Recommandation dans la source",
    "sourceHypothesis": "Hypothèse à vérifier",
    "sourceUnclassified": "Non classé · à vérifier",
    "sourceContext": "La classification concerne le contenu cité. Son application à la situation doit être vérifiée : la référence seule ne prouve ni une infraction ni la conformité.",
    "sourceLocator": "Passage précis : {value}",
    "sourceScope": "Champ d’application : {value}",
    "sourceVersion": "Version du document : {value}",
    "sourceRegistry": "Registre des sources : {value}",
    "sourceLimits": "Limites de la référence"
  },
  "en": {
    "sourceObligation": "Obligation in the source",
    "sourceRecommendation": "Recommendation in the source",
    "sourceHypothesis": "Hypothesis to verify",
    "sourceUnclassified": "Unclassified · verify before use",
    "sourceContext": "The classification concerns the cited content. Its applicability to the situation must be checked: the reference alone proves neither a breach nor compliance.",
    "sourceLocator": "Exact reference: {value}",
    "sourceScope": "Scope: {value}",
    "sourceVersion": "Document version: {value}",
    "sourceRegistry": "Source registry: {value}",
    "sourceLimits": "Reference limitations"
  }
};
  Object.assign(messages.it, sourceTranslations.it);
  for (const language of ['de', 'fr', 'en']) Object.assign(languageOverrides[language], sourceTranslations[language]);
  const syntheticVideoTranslations = {
    it: {
      syntheticAction:'Avvia collaudo sintetico video e audio',syntheticOnly:'Risultato di collaudo sintetico: non è un’analisi AI reale.',syntheticConsumes:'Questo collaudo privato usa risposte simulate. Se completato, utilizza l’unica prova aziendale; nessun servizio AI reale viene chiamato.',syntheticRunning:'Collaudo sintetico in corso…',syntheticComplete:'Rapporto video sintetico salvato',syntheticCoverage:'Copertura: {count} fotogrammi su {seconds} secondi. Sono campioni temporali, non una visione continua del video.',syntheticSpoken:'Parlato dichiarato, distinto dalle evidenze visive',syntheticTranscriptAvailable:'Trascrizione sintetica disponibile',syntheticTranscriptUnknown:'Il parlato non è comprensibile: restano informazioni da chiarire.',syntheticTranscriptNA:'Trascrizione non applicabile allo stato audio rilevato.',syntheticAudio:'Stato audio: {status}',syntheticNoAmbient:'I rumori ambientali e i livelli acustici non sono stati analizzati.',syntheticFrame:'Fotogramma campionato a {seconds} s',syntheticSourceMissing:'Il caso sorgente o le sue evidenze non sono disponibili. Il rapporto resta consultabile, ma i fotogrammi non possono essere mostrati.',syntheticQuestionNote:'Domande da chiarire sul posto. Questo collaudo video non consente una nuova analisi delle risposte.',syntheticOpenSaved:'Apri il rapporto salvato',syntheticQuotaUnknown:'Il rapporto è stato salvato, ma l’utilizzo della prova non è confermato. Non avviare altre analisi finché il conteggio non è verificato.',syntheticQuotaUsed:'Rapporto salvato e prova aziendale utilizzata. Nessuna nuova prova è disponibile; lo stato dettagliato della quota non è temporaneamente consultabile.',syntheticUnavailable:'Il percorso sintetico non è disponibile o il limite di richieste è stato raggiunto. Nessuna nuova elaborazione è stata confermata.',syntheticFailure:'Il collaudo sintetico non ha prodotto un nuovo rapporto confermato.',syntheticFrameMissing:'Il fotogramma associato a questo rilievo non è disponibile.',syntheticOpenFrame:'Apri il fotogramma',syntheticVisible:'Visibile nel fotogramma campionato',syntheticCropCaption:'Dettaglio del rilievo {id} · {seconds} s',syntheticUnknownNetwork:'L’esito della richiesta non è confermato. Prima di riprovare, verificare l’archivio e il conteggio della prova.',syntheticHistory:'Rapporto video di collaudo sintetico · nessuna analisi AI reale'
    },
    de: {
      syntheticAction:'Synthetischen Video- und Audiotest starten',syntheticOnly:'Synthetisches Testergebnis: keine echte KI-Analyse.',syntheticConsumes:'Dieser private Test verwendet simulierte Antworten. Bei Erfolg wird der einmalige Unternehmenstest genutzt; kein echter KI-Dienst wird aufgerufen.',syntheticRunning:'Synthetischer Test läuft…',syntheticComplete:'Synthetischer Videobericht gespeichert',syntheticCoverage:'Abdeckung: {count} Einzelbilder aus {seconds} Sekunden. Dies sind zeitliche Stichproben, keine kontinuierliche Betrachtung.',syntheticSpoken:'Gesprochene Angaben, getrennt von visuellen Nachweisen',syntheticTranscriptAvailable:'Synthetische Transkription verfügbar',syntheticTranscriptUnknown:'Die Sprache ist unverständlich; Angaben müssen noch geklärt werden.',syntheticTranscriptNA:'Für den festgestellten Audiostatus ist keine Transkription anwendbar.',syntheticAudio:'Audiostatus: {status}',syntheticNoAmbient:'Umgebungsgeräusche und Schallpegel wurden nicht analysiert.',syntheticFrame:'Stichprobenbild bei {seconds} s',syntheticSourceMissing:'Der Quellfall oder seine Nachweise sind nicht verfügbar. Der Bericht bleibt lesbar, Einzelbilder können jedoch nicht angezeigt werden.',syntheticQuestionNote:'Fragen vor Ort klären. Dieser Videotest erlaubt keine erneute Analyse der Antworten.',syntheticOpenSaved:'Gespeicherten Bericht öffnen',syntheticQuotaUnknown:'Bericht gespeichert; die Nutzung des Tests ist jedoch nicht bestätigt. Keine weiteren Analysen starten, bis die Zählung geprüft ist.',syntheticQuotaUsed:'Bericht gespeichert und Unternehmenstest genutzt. Kein neuer Test verfügbar; der genaue Kontingentstatus ist vorübergehend nicht abrufbar.',syntheticUnavailable:'Der synthetische Ablauf ist nicht verfügbar oder die Anfragegrenze wurde erreicht. Keine neue Verarbeitung wurde bestätigt.',syntheticFailure:'Der synthetische Test hat keinen neuen bestätigten Bericht erzeugt.',syntheticFrameMissing:'Das zu dieser Beobachtung gehörende Einzelbild ist nicht verfügbar.',syntheticOpenFrame:'Einzelbild öffnen',syntheticVisible:'Im Stichprobenbild sichtbar',syntheticCropCaption:'Detail zu Beobachtung {id} · {seconds} s',syntheticUnknownNetwork:'Das Ergebnis der Anfrage ist nicht bestätigt. Vor einem neuen Versuch Archiv und Testzählung prüfen.',syntheticHistory:'Synthetischer Videotestbericht · keine echte KI-Analyse'
    },
    fr: {
      syntheticAction:'Lancer le test synthétique vidéo et audio',syntheticOnly:'Résultat de test synthétique : ce n’est pas une analyse IA réelle.',syntheticConsumes:'Ce test privé utilise des réponses simulées. En cas de réussite, il utilise l’unique essai de l’entreprise ; aucun service IA réel n’est appelé.',syntheticRunning:'Test synthétique en cours…',syntheticComplete:'Rapport vidéo synthétique enregistré',syntheticCoverage:'Couverture : {count} images sur {seconds} secondes. Ce sont des échantillons temporels, pas une observation continue.',syntheticSpoken:'Paroles déclarées, distinctes des preuves visuelles',syntheticTranscriptAvailable:'Transcription synthétique disponible',syntheticTranscriptUnknown:'Les paroles sont incompréhensibles : des informations restent à clarifier.',syntheticTranscriptNA:'La transcription ne s’applique pas à l’état audio constaté.',syntheticAudio:'État audio : {status}',syntheticNoAmbient:'Les bruits ambiants et les niveaux sonores n’ont pas été analysés.',syntheticFrame:'Image échantillonnée à {seconds} s',syntheticSourceMissing:'Le dossier source ou ses preuves ne sont pas disponibles. Le rapport reste consultable, mais les images ne peuvent pas être affichées.',syntheticQuestionNote:'Questions à clarifier sur place. Ce test vidéo ne permet pas une nouvelle analyse des réponses.',syntheticOpenSaved:'Ouvrir le rapport enregistré',syntheticQuotaUnknown:'Le rapport est enregistré, mais l’utilisation de l’essai n’est pas confirmée. Ne lancez aucune autre analyse avant vérification du décompte.',syntheticQuotaUsed:'Rapport enregistré et essai de l’entreprise utilisé. Aucun nouvel essai disponible ; le statut détaillé du quota est temporairement inaccessible.',syntheticUnavailable:'Le parcours synthétique est indisponible ou la limite des requêtes est atteinte. Aucun nouveau traitement n’a été confirmé.',syntheticFailure:'Le test synthétique n’a pas produit de nouveau rapport confirmé.',syntheticFrameMissing:'L’image associée à cette observation n’est pas disponible.',syntheticOpenFrame:'Ouvrir l’image',syntheticVisible:'Visible dans l’image échantillonnée',syntheticCropCaption:'Détail de l’observation {id} · {seconds} s',syntheticUnknownNetwork:'Le résultat de la requête n’est pas confirmé. Vérifiez l’historique et le décompte de l’essai avant de réessayer.',syntheticHistory:'Rapport de test vidéo synthétique · aucune analyse IA réelle'
    },
    en: {
      syntheticAction:'Run synthetic video and audio test',syntheticOnly:'Synthetic test result: this is not a real AI analysis.',syntheticConsumes:'This private test uses simulated responses. If successful, it uses the company’s single trial; no real AI service is called.',syntheticRunning:'Synthetic test running…',syntheticComplete:'Synthetic video report saved',syntheticCoverage:'Coverage: {count} frames from {seconds} seconds. These are time samples, not continuous observation.',syntheticSpoken:'Spoken claims, separate from visual evidence',syntheticTranscriptAvailable:'Synthetic transcript available',syntheticTranscriptUnknown:'Speech is unintelligible; information still needs clarification.',syntheticTranscriptNA:'Transcription does not apply to the observed audio status.',syntheticAudio:'Audio status: {status}',syntheticNoAmbient:'Ambient sounds and sound levels were not analysed.',syntheticFrame:'Sampled frame at {seconds} s',syntheticSourceMissing:'The source case or its evidence is unavailable. The report remains readable, but sampled frames cannot be shown.',syntheticQuestionNote:'Questions to clarify on site. This video test does not support a new analysis of the answers.',syntheticOpenSaved:'Open the saved report',syntheticQuotaUnknown:'The report was saved, but trial usage is unconfirmed. Do not start another analysis until accounting has been checked.',syntheticQuotaUsed:'Report saved and company trial used. No new trial is available; detailed quota status is temporarily unavailable.',syntheticUnavailable:'The synthetic path is unavailable or its request limit has been reached. No new processing was confirmed.',syntheticFailure:'The synthetic test did not produce a new confirmed report.',syntheticFrameMissing:'The frame associated with this finding is unavailable.',syntheticOpenFrame:'Open frame',syntheticVisible:'Visible in the sampled frame',syntheticCropCaption:'Finding {id} detail · {seconds} s',syntheticUnknownNetwork:'The request outcome is unconfirmed. Check the archive and trial accounting before trying again.',syntheticHistory:'Synthetic video test report · no real AI analysis'
    }
  };
  const syntheticAudioLabels = {"it": {"syntheticAudioPresent": "Traccia audio presente ed estratta", "syntheticAudioAbsent": "Nessuna traccia audio", "syntheticAudioSilent": "Traccia audio silenziosa", "syntheticAudioLow": "Traccia audio poco udibile", "syntheticAudioError": "Stato della traccia non verificabile"}, "de": {"syntheticAudioPresent": "Audiospur vorhanden und extrahiert", "syntheticAudioAbsent": "Keine Audiospur vorhanden", "syntheticAudioSilent": "Stumme Audiospur", "syntheticAudioLow": "Leise Audiospur", "syntheticAudioError": "Audiostatus nicht überprüfbar"}, "fr": {"syntheticAudioPresent": "Piste audio présente et extraite", "syntheticAudioAbsent": "Aucune piste audio", "syntheticAudioSilent": "Piste audio silencieuse", "syntheticAudioLow": "Piste audio peu audible", "syntheticAudioError": "État audio non vérifiable"}, "en": {"syntheticAudioPresent": "Audio track present and extracted", "syntheticAudioAbsent": "No audio track", "syntheticAudioSilent": "Silent audio track", "syntheticAudioLow": "Low-level audio track", "syntheticAudioError": "Audio track status cannot be verified"}};
  localeCodes.forEach(code => Object.assign(syntheticVideoTranslations[code], syntheticAudioLabels[code]));
  localeCodes.forEach(code => Object.assign(code === 'it' ? messages.it : languageOverrides[code], syntheticVideoTranslations[code]));
  const videoQuestionTranslations = {"it": {"photoQuestionsNote": "Per aggiornare un rapporto salvato, aggiungi prima la fotografia originale. Poi potrai rispondere alle domande senza perdere il contesto.", "photoQuestionsHelp": "Rispondi prima alle domande decisive. Se non conosci una risposta, lasciala vuota. L’aggiornamento avvia una nuova analisi AI.", "syntheticResultUnreadable": "Il rapporto è stato salvato e la prova utilizzata, ma non è stato possibile mostrarlo. Apri il rapporto salvato o consulta l’archivio; non avviare una nuova analisi."}, "de": {"photoQuestionsNote": "Fügen Sie zum Aktualisieren zuerst das Originalfoto hinzu. Danach können Sie Fragen beantworten, ohne den Kontext zu verlieren.", "photoQuestionsHelp": "Beantworten Sie zuerst entscheidende Fragen. Lassen Sie unbekannte Antworten leer. Die Aktualisierung startet eine neue KI-Analyse.", "syntheticResultUnreadable": "Bericht gespeichert und Test genutzt, die Anzeige ist jedoch fehlgeschlagen. Öffnen Sie den gespeicherten Bericht oder das Archiv; keine neue Analyse starten."}, "fr": {"photoQuestionsNote": "Pour actualiser un rapport enregistré, ajoutez d’abord la photo originale. Vous pourrez ensuite répondre aux questions sans perdre le contexte.", "photoQuestionsHelp": "Répondez d’abord aux questions décisives. Laissez une réponse vide si vous ne la connaissez pas. La mise à jour lance une nouvelle analyse IA.", "syntheticResultUnreadable": "Le rapport est enregistré et l’essai utilisé, mais l’affichage a échoué. Ouvrez le rapport enregistré ou consultez l’historique ; ne lancez pas de nouvelle analyse."}, "en": {"photoQuestionsNote": "To update a saved report, add the original photo first. You can then answer questions without losing context.", "photoQuestionsHelp": "Answer decisive questions first. Leave an answer blank if unknown. Updating starts a new AI analysis.", "syntheticResultUnreadable": "The report was saved and the trial used, but it could not be displayed. Open the saved report or check the archive; do not start a new analysis."}};
  localeCodes.forEach(code => Object.assign(code === 'it' ? messages.it : languageOverrides[code], videoQuestionTranslations[code]));

  localeCodes.slice(1).forEach(code => { messages[code] = { ...messages.it, ...languageOverrides[code] }; });
  const messageKeys = Object.keys(messages.it).sort();
  localeCodes.forEach(code => { if (Object.keys(messages[code]).sort().join('\0') !== messageKeys.join('\0')) throw new Error('Incomplete UI locale: ' + code); });
  window.SLPS_APP_I18N = Object.freeze({ locales: Object.freeze([...localeCodes]), messages, metaDescriptions: Object.freeze({ ...metaDescriptions }) });
  const storedLocale = (() => { try { return window.localStorage?.getItem('slps.locale'); } catch { return null; } })();
  const browserLocale = typeof navigator === 'object' && navigator.language ? navigator.language.slice(0, 2).toLowerCase() : 'it';
  const initialLocale = localeCodes.includes(storedLocale) ? storedLocale : localeCodes.includes(browserLocale) ? browserLocale : 'it';
  const state = { language: initialLocale, csrf: '', authenticated: false, configured: false, busy: false, historyBusy: false, caseBusy: false, historyLoaded: false, historyCases: [], openedCaseId: null, file: null, mediaKind: null, imageUrl: null, mediaUrl: null, videoInspection: null, technicalArchiveOpen: false, videoReportSource: null, syntheticVideoBusy: false, quotaUncertain: false, videoTrialConsumed: false, savedVideoResultId: null, analysis: null, archive: null, controller: null, answers: new Map(), submittedContext: '', view: 'analysis', editing: true, entitlement: { plan: 'internal', export_allowed: true }, media: { image_max_bytes: 10 * 1024 * 1024, video_max_bytes: 50 * 1024 * 1024, video_max_seconds: 30, video_intake_enabled: false, video_analysis_enabled: false, video_synthetic_analysis_enabled: false } };
  const t = (key, vars = {}) => String(messages[state.language][key] ?? messages.it[key] ?? key).replace(/\{(\w+)\}/g, (_, name) => vars[name] ?? '');
  const certaintyLabels = { visible: 'visible', reported: 'reported', verify: 'verify' };
  const riskLabels = { high: 'highRisk', medium: 'mediumRisk', low: 'lowRisk', undetermined: 'unknownRisk' };
  const make = (tag, text, cls) => { const el = document.createElement(tag); if (text != null) el.textContent = String(text); if (cls) el.className = cls; return el; };
  function apiErrorMessage(code, status) {
    const byCode = { trial_completion_unknown: 'syntheticQuotaUnknown', video_synthetic_analysis_disabled: 'syntheticUnavailable', provider_request_cap_required: 'syntheticUnavailable', provider_request_cap_reached: 'syntheticUnavailable', video_adapter_unavailable: 'syntheticUnavailable', video_evidence_invalid: 'syntheticFailure', video_adapter_failed: 'syntheticFailure', video_analysis_timeout: 'syntheticFailure', video_result_not_saved: 'syntheticFailure', video_trial_not_confirmed: 'syntheticFailure', video_analysis_failed: 'syntheticFailure', authentication_required: 'unauthorized', invalid_csrf: 'unauthorized', account_verification_required: 'forbidden', analysis_disabled: 'forbidden', trial_exhausted: 'forbidden', invalid_image: 'invalidRequest', invalid_video: 'invalidRequest', invalid_request: 'invalidRequest', file_too_large: 'tooLarge', rate_limited: 'rateLimited', configuration_missing: 'serverUnavailable', provider_unavailable: 'serverUnavailable' };
    return t(byCode[code] || (status === 401 ? 'unauthorized' : status === 403 ? 'forbidden' : status === 413 ? 'tooLarge' : status === 429 ? 'rateLimited' : status >= 500 ? 'serverUnavailable' : 'genericApiError'));
  }
  function localizedError(error) { return error?.name === 'AbortError' ? t('requestAborted') : apiErrorMessage(error?.code, error?.status || 0); }
  const staticPhrases = {
    'Vai al contenuto':['Zum Inhalt springen','Aller au contenu','Skip to content'],'Un progetto ROST International':['Ein Projekt von ROST International','Un projet de ROST International','A ROST International project'],'Analisi':['Analyse','Analyse','Analysis'],'Archivio':['Archiv','Historique','History'],'Pilota privato':['Privater Pilot','Pilote privé','Private pilot'],'Account':['Konto','Compte','Account'],'Nuova analisi':['Neue Analyse','Nouvelle analyse','New analysis'],'Esci':['Abmelden','Déconnexion','Sign out'],'Lingua':['Sprache','Langue','Language'],
    'Sicurezza sul lavoro · Svizzera':['Arbeitssicherheit · Schweiz','Sécurité au travail · Suisse','Occupational safety · Switzerland'],'Una situazione reale.':['Eine reale Situation.','Une situation réelle.','A real situation.'],'Il prossimo passo,':['Der nächste Schritt,','La prochaine étape,','The next step,'],'più chiaro.':['klarer.','plus claire.','made clearer.'],'Una fotografia, il contesto del lavoro e un’analisi da verificare sul posto.':['Ein Foto, der Arbeitskontext und eine Analyse, die vor Ort zu prüfen ist.','Une photo, le contexte de travail et une analyse à vérifier sur place.','A photo, the work context and an analysis to verify on site.'],'Osserva la situazione':['Situation beobachten','Observer la situation','Observe the situation'],'Aggiungi il contesto':['Kontext ergänzen','Ajouter le contexte','Add context'],'Valuta le azioni':['Massnahmen bewerten','Évaluer les actions','Assess the actions'],'SLPS AI / Spazio di lavoro':['SLPS AI / Arbeitsbereich','SLPS AI / Espace de travail','SLPS AI / Workspace'],'Accesso riservato':['Geschützter Zugang','Accès réservé','Restricted access'],'Entra in SLPS AI':['Bei SLPS AI anmelden','Accéder à SLPS AI','Enter SLPS AI'],'Accedi al pilota privato per analizzare una foto e consultare i rapporti salvati.':['Melden Sie sich beim privaten Pilot an, um eine Datei zu analysieren und gespeicherte Berichte einzusehen.','Connectez-vous au pilote privé pour analyser un fichier et consulter les rapports enregistrés.','Sign in to the private pilot to analyse a file and view saved reports.'],'Password del pilota':['Pilot-Passwort','Mot de passe du pilote','Pilot password'],'Inserisci la password':['Passwort eingeben','Saisissez le mot de passe','Enter password'],'Accedi allo spazio di lavoro':['Arbeitsbereich öffnen','Accéder à l’espace de travail','Open workspace'],'L’analisi AI si avvia soltanto quando la richiedi. Il risultato resta da verificare nelle condizioni effettive di lavoro.':['Die KI-Analyse startet nur auf Ihre Anforderung. Das Ergebnis muss unter realen Arbeitsbedingungen geprüft werden.','L’analyse IA ne démarre qu’à votre demande. Le résultat doit être vérifié dans les conditions réelles de travail.','AI analysis starts only when you request it. The result must be verified under actual working conditions.'],
    'Il tuo spazio di lavoro':['Ihr Arbeitsbereich','Votre espace de travail','Your workspace'],'Foto e video':['Foto und Video','Photos et vidéos','Photos and videos'],'Percorso dell’analisi':['Ablauf der Analyse','Parcours de l’analyse','Analysis workflow'],'Fotografia':['Foto','Photo','Photo'],'La situazione da osservare':['Zu beobachtende Situation','La situation à observer','The situation to observe'],'Contesto':['Kontext','Contexte','Context'],'Le informazioni utili':['Nützliche Angaben','Les informations utiles','Useful information'],'Risultato':['Ergebnis','Résultat','Result'],'Azioni e chiarimenti':['Massnahmen und Abklärungen','Actions et clarifications','Actions and clarifications'],'I tuoi casi':['Ihre Fälle','Vos dossiers','Your cases'],'Casi salvati':['Gespeicherte Fälle','Dossiers enregistrés','Saved cases'],'Aggiorna elenco':['Liste aktualisieren','Actualiser la liste','Refresh list'],'Ogni caso conserva il rapporto o la verifica tecnica e i file originali disponibili. Foto e video restano privati nell’account.':['Jeder Fall enthält den Bericht oder die technische Prüfung und verfügbare Originaldateien. Fotos und Videos bleiben im Konto geschützt.','Chaque dossier conserve le rapport ou la vérification technique et les fichiers originaux disponibles. Les photos et vidéos restent privées dans le compte.','Each case stores the report or technical check and available original files. Photos and videos remain private in the account.'],'Caricamento dei casi salvati…':['Gespeicherte Fälle werden geladen…','Chargement des dossiers enregistrés…','Loading saved cases…'],'Il tuo archivio inizia da una foto o un video.':['Ihr Archiv beginnt mit einem Foto oder Video.','Votre historique commence par une photo ou une vidéo.','Your history starts with a photo or video.'],'Non ci sono ancora casi salvati per questo account.':['Für dieses Konto gibt es noch keine gespeicherten Fälle.','Aucun dossier n’est encore enregistré pour ce compte.','There are no saved cases for this account yet.'],'Nuova verifica':['Neue Prüfung','Nouvelle vérification','New check'],'Elenco dei casi salvati':['Liste der gespeicherten Fälle','Liste des dossiers enregistrés','Saved case list'],
    'Parti da foto o video':['Mit Foto oder Video beginnen','Commencez par une photo ou une vidéo','Start with a photo or video'],'Inquadra la situazione che vuoi valutare.':['Erfassen Sie die zu bewertende Situation.','Cadrez la situation à évaluer.','Frame the situation you want to assess.'],'Torna al risultato →':['Zurück zum Ergebnis →','Retour au résultat →','Back to result →'],'Carica foto o video':['Foto oder Video hochladen','Importer une photo ou une vidéo','Upload photo or video'],'Scegli un file dal tuo dispositivo':['Datei auf Ihrem Gerät wählen','Choisissez un fichier sur votre appareil','Choose a file from your device'],'Scegli file':['Datei wählen','Choisir un fichier','Choose file'],'Foto JPG, PNG, WebP · video MP4, WebM, MOV':['Fotos: JPG, PNG, WebP · Videos: MP4, WebM, MOV','Photos JPG, PNG, WebP · vidéos MP4, WebM, MOV','Photos: JPG, PNG, WebP · videos: MP4, WebM, MOV'],'Foto selezionata':['Foto ausgewählt','Photo sélectionnée','Photo selected'],'Aggiungi il contesto':['Kontext ergänzen','Ajouter le contexte','Add context'],'facoltativo':['optional','facultatif','optional'],'Quale attività è in corso? Ci sono macchine in funzione, protezioni o persone fuori dall’inquadratura?':['Welche Tätigkeit läuft? Gibt es aktive Maschinen, Schutzeinrichtungen oder Personen ausserhalb des Bildes?','Quelle activité est en cours ? Des machines, protections ou personnes sont-elles hors champ ?','What activity is under way? Are machines, safeguards or people outside the frame?'],'Scrivi ciò che la foto non mostra. Il contesto sarà distinto dalle osservazioni sull’immagine.':['Beschreiben Sie, was das Bild nicht zeigt. Der Kontext wird von Bildbeobachtungen getrennt.','Décrivez ce que la photo ne montre pas. Le contexte sera distingué des observations visuelles.','Describe what the photo does not show. Context will be kept separate from image observations.'],'Avvia analisi AI':['KI-Analyse starten','Lancer l’analyse IA','Start AI analysis'],'Controlla foto e contesto prima di avviare.':['Prüfen Sie Datei und Kontext vor dem Start.','Vérifiez le fichier et le contexte avant de commencer.','Check the file and context before starting.'],'Come vengono conservati i dati':['Datenspeicherung','Conservation des données','How data is stored'],'Ogni caso conserva il rapporto e, quando disponibili, i file originali. La conservazione dipende dai limiti dello spazio dell’account. Puoi eliminare definitivamente un caso dallo storico; inserisci soltanto i dati necessari alla valutazione.':['Jeder Fall speichert den Bericht und, sofern verfügbar, die Originaldateien. Die Aufbewahrung hängt vom Kontospeicher ab. Fälle können endgültig gelöscht werden; geben Sie nur erforderliche Daten ein.','Chaque dossier conserve le rapport et, si disponibles, les fichiers originaux. La conservation dépend de l’espace du compte. Vous pouvez supprimer définitivement un dossier ; ne fournissez que les données nécessaires.','Each case stores the report and, when available, original files. Retention depends on account storage limits. You can permanently delete a case; provide only the data needed for the assessment.'],
    'Verifica tecnica del video':['Technische Videoprüfung','Vérification technique de la vidéo','Technical video check'],'Video originale conservato nel caso':['Im Fall gespeichertes Originalvideo','Vidéo originale conservée dans le dossier','Original video stored with the case'],'Non è stata eseguita un’analisi dei rischi con l’AI.':['Es wurde keine KI-Risikoanalyse durchgeführt.','Aucune analyse IA des risques n’a été effectuée.','No AI risk analysis was performed.'],'I fotogrammi sono campioni temporali; l’audio non è stato trascritto o interpretato.':['Die Einzelbilder sind zeitliche Stichproben; Audio wurde weder transkribiert noch interpretiert.','Les images sont des échantillons temporels ; l’audio n’a été ni transcrit ni interprété.','Frames are time samples; audio was not transcribed or interpreted.'],'Dalla foto all’azione':['Vom Foto zur Massnahme','De la photo à l’action','From photo to action'],'Un percorso chiaro,':['Ein klarer Ablauf,','Un parcours clair,','A clear path,'],'un passo alla volta.':['Schritt für Schritt.','étape par étape.','one step at a time.'],'Il risultato sarà costruito sulla tua fotografia e sulle informazioni che aggiungi.':['Das Ergebnis basiert auf Ihrem Foto und Ihren Angaben.','Le résultat sera construit à partir de votre photo et de vos informations.','The result will be built from your photo and the information you add.'],'Osservazioni collegate alla foto':['Beobachtungen zum Foto','Observations liées à la photo','Observations linked to the photo'],'Il dettaglio visibile e ciò che resta da verificare.':['Sichtbare Details und offene Prüfungen.','Le détail visible et ce qui reste à vérifier.','Visible detail and what remains to be checked.'],'Azioni e tempi proposti':['Vorgeschlagene Massnahmen und Fristen','Actions et délais proposés','Proposed actions and timing'],'Cosa fare e quando intervenire.':['Was zu tun ist und wann.','Que faire et quand intervenir.','What to do and when.'],'Domande mirate':['Gezielte Fragen','Questions ciblées','Focused questions'],'Le informazioni che possono cambiare la valutazione.':['Angaben, die die Bewertung verändern können.','Les informations susceptibles de modifier l’évaluation.','Information that may change the assessment.'],'La fotografia è un punto di partenza. Le misure vanno confermate sul luogo di lavoro.':['Das Foto ist ein Ausgangspunkt. Massnahmen müssen am Arbeitsplatz bestätigt werden.','La photo est un point de départ. Les mesures doivent être confirmées sur le lieu de travail.','The photo is a starting point. Measures must be confirmed at the workplace.'],'Mantieni aperta questa pagina.':['Diese Seite geöffnet lassen.','Gardez cette page ouverte.','Keep this page open.'],
    'Risultato da verificare sul posto':['Ergebnis vor Ort zu prüfen','Résultat à vérifier sur place','Result to verify on site'],'Modifica foto o contesto':['Foto oder Kontext ändern','Modifier la photo ou le contexte','Edit photo or context'],'Stampa rapporto':['Bericht drucken','Imprimer le rapport','Print report'],'Esporta JSON':['JSON exportieren','Exporter JSON','Export JSON'],'La prova gratuita permette di consultare il risultato nell’app. Stampa, PDF ed esportazione JSON si attivano con un piano successivo.':['Der Gratistest zeigt das Ergebnis in der App. Druck, PDF und JSON-Export sind mit einem späteren Plan verfügbar.','L’essai gratuit permet de consulter le résultat dans l’application. Impression, PDF et export JSON nécessitent une formule ultérieure.','The free trial lets you view the result in the app. Printing, PDF and JSON export require a later plan.'],'Foto e contesto della valutazione':['Foto und Kontext der Bewertung','Photo et contexte de l’évaluation','Assessment photo and context'],'Il prossimo passo':['Nächster Schritt','Prochaine étape','Next step'],'Osservazioni e misure':['Beobachtungen und Massnahmen','Observations et mesures','Observations and measures'],'Leggi l’azione proposta, poi verifica il dettaglio a cui si riferisce.':['Lesen Sie die vorgeschlagene Massnahme und prüfen Sie das zugehörige Detail.','Lisez l’action proposée, puis vérifiez le détail concerné.','Read the proposed action, then verify the detail it refers to.'],'Le informazioni che mancano':['Fehlende Angaben','Les informations manquantes','Missing information'],'Completa la valutazione':['Bewertung vervollständigen','Compléter l’évaluation','Complete the assessment'],'Rispondi prima alle domande decisive. Se non conosci una risposta, lasciala vuota. L’aggiornamento avvia una nuova analisi AI.':['Beantworten Sie zuerst entscheidende Fragen. Lassen Sie unbekannte Antworten leer. Die Aktualisierung startet eine neue KI-Analyse.','Répondez d’abord aux questions décisives. Laissez une réponse vide si vous ne la connaissez pas. La mise à jour lance une nouvelle analyse IA.','Answer decisive questions first. Leave an answer blank if unknown. Updating starts a new AI analysis.'],'Per aggiornare un rapporto salvato, aggiungi prima la fotografia originale. Poi potrai rispondere alle domande senza perdere il contesto.':['Fügen Sie zum Aktualisieren zuerst das Originalfoto hinzu. Danach können Sie Fragen beantworten, ohne den Kontext zu verlieren.','Pour actualiser un rapport enregistré, ajoutez d’abord la photo originale. Vous pourrez ensuite répondre sans perdre le contexte.','To update a saved report, add the original photo first. You can then answer questions without losing context.'],'Aggiorna con le risposte':['Mit Antworten aktualisieren','Actualiser avec les réponses','Update with answers'],'Limiti, fonti e dettagli dell’analisi':['Grenzen, Quellen und Analysedetails','Limites, sources et détails de l’analyse','Limitations, sources and analysis details'],'La foto rappresenta un momento e un’inquadratura. Le misure proposte vanno confermate rispetto alle condizioni effettive.':['Das Foto zeigt einen Moment und Ausschnitt. Vorgeschlagene Massnahmen sind unter realen Bedingungen zu bestätigen.','La photo représente un instant et un cadrage. Les mesures proposées doivent être confirmées selon les conditions réelles.','The photo captures one moment and view. Proposed measures must be confirmed against actual conditions.'],'Sicurezza sul lavoro, dalla situazione all’azione.':['Arbeitssicherheit, von der Situation zur Massnahme.','Sécurité au travail, de la situation à l’action.','Occupational safety, from situation to action.'],'Pilota privato · ROST International':['Privater Pilot · ROST International','Pilote privé · ROST International','Private pilot · ROST International'],'Per utilizzare il pilota SLPS AI è necessario abilitare JavaScript.':['Für SLPS AI muss JavaScript aktiviert sein.','JavaScript doit être activé pour utiliser le pilote SLPS AI.','JavaScript must be enabled to use the SLPS AI pilot.']
  };
  const originalText = new WeakMap();
  const originalAttributes = new WeakMap();
  function localizeStatic(root = document.body) {
    if (!root || typeof document.createTreeWalker !== 'function') return;
    const walker = document.createTreeWalker(root, 4); let node;
    while ((node = walker.nextNode())) {
      const current = node.nodeValue, previous = originalText.get(node);
      const source = previous && current === previous.rendered ? previous.source : current;
      const trimmed = source.trim(), values = staticPhrases[trimmed];
      if (!values) continue;
      const translated = state.language === 'it' ? trimmed : values[{ de: 0, fr: 1, en: 2 }[state.language]];
      const rendered = source.replace(trimmed, translated); originalText.set(node, { source, rendered }); if (node.nodeValue !== rendered) node.nodeValue = rendered;
    }
    const attributes = [['meta[name="description"]','content',[metaDescriptions.de,metaDescriptions.fr,metaDescriptions.en]],['.brand','aria-label',['SLPS AI, Startseite','SLPS AI, page d’accueil','SLPS AI, home page']],['#context','placeholder',[staticPhrases['Quale attività è in corso? Ci sono macchine in funzione, protezioni o persone fuori dall’inquadratura?'][0],staticPhrases['Quale attività è in corso? Ci sono macchine in funzione, protezioni o persone fuori dall’inquadratura?'][1],staticPhrases['Quale attività è in corso? Ci sono macchine in funzione, protezioni o persone fuori dall’inquadratura?'][2]]],['#preview','alt',['Für die Analyse ausgewähltes Foto','Photo sélectionnée pour l’analyse','Photo selected for analysis']],['#video-preview','aria-label',['Vorschau des ausgewählten Videos','Aperçu de la vidéo sélectionnée','Selected video preview']],['#archived-video','aria-label',['Im Fall gespeichertes Originalvideo','Vidéo originale conservée dans le dossier','Original video stored with the case']],['#workflow','aria-label',['Ablauf der Analyse','Parcours de l’analyse','Analysis workflow']],['#history-list','aria-label',['Liste der gespeicherten Fälle','Liste des dossiers enregistrés','Saved case list']],['#case-summary','aria-label',['Foto und Kontext der Bewertung','Photo et contexte de l’évaluation','Assessment photo and context']]];
    attributes.forEach(([selector, name, values]) => {
      const el = document.querySelector(selector); if (!el) return;
      const originals = originalAttributes.get(el) || {}; if (!(name in originals)) originals[name] = el.getAttribute(name); originalAttributes.set(el, originals);
      el.setAttribute(name, state.language === 'it' ? originals[name] : values[{ de:0, fr:1, en:2 }[state.language]]);
    });
  }
  function syncWorkspace() {
    const history = state.view === 'history', hasReport = Boolean(state.analysis), hasTechnicalCase = state.technicalArchiveOpen;
    $('history-panel').hidden = !history; $('work-grid').hidden = history; $('workflow').hidden = history || hasTechnicalCase;
    $('workspace-nav').hidden = !state.authenticated; $('new-analysis').hidden = !state.authenticated;
    $('nav-analysis').className = 'nav-button' + (!history ? ' active' : '');
    $('nav-history').className = 'nav-button' + (history ? ' active' : '');
    ['nav-analysis', 'nav-history'].forEach(id => $(id).removeAttribute('aria-current'));
    $(history ? 'nav-history' : 'nav-analysis').setAttribute('aria-current', 'page');
    $('workspace-title').textContent = history ? t('workspaceHistoryTitle') : hasTechnicalCase ? t('workspaceVideoTitle') : hasReport && !state.editing ? t('workspaceReportTitle') : t('workspaceDefaultTitle');
    $('workspace-description').textContent = history ? t('workspaceHistoryDescription') : hasTechnicalCase ? t('workspaceVideoDescription') : hasReport && !state.editing ? t('workspaceReportDescription') : t('workspaceDefaultDescription');
    $('work-grid').dataset.mode = state.busy ? 'busy' : hasTechnicalCase ? 'report' : hasReport ? state.editing ? 'edit-report' : 'report' : 'input';
    $('input-panel').hidden = state.busy || hasTechnicalCase || (hasReport && !state.editing);
    $('input-panel').className = 'panel input-panel' + (state.file ? ' has-photo' : '');
    $('return-report').hidden = !hasReport || !state.editing;
    $('upload-title').textContent = state.file ? t('changeFile') : t('upload');
    $('submit-note').textContent = hasReport ? t('submitExisting') : t('submitDefault');
    const activeStep = state.busy || hasTechnicalCase || (hasReport && !state.editing) ? 2 : state.file ? 1 : 0;
    ['step-photo', 'step-context', 'step-result'].forEach((id, index) => {
      $(id).className = 'workflow-step' + (index < activeStep ? ' complete' : index === activeStep ? ' current' : '');
      $(id).removeAttribute('aria-current'); if (index === activeStep) $(id).setAttribute('aria-current', 'step');
    });
    $('result-step-note').textContent = state.busy ? t('processing') : hasTechnicalCase ? t('verificationAvailable') : hasReport ? t('reportAvailable') : t('actionsClarifications');
    const needsArchivedPhoto = Boolean(state.analysis && !state.file);
    $('questions-photo-note').hidden = !needsArchivedPhoto;
    if (isSyntheticVideo(state.analysis)) { $('questions-photo-note').textContent = t('syntheticQuestionNote'); $('questions-photo-note').hidden = false; } else $('questions-photo-note').textContent = t('photoQuestionsNote');
    $('questions-help').textContent = t(isSyntheticVideo(state.analysis) ? 'syntheticQuestionNote' : 'photoQuestionsHelp');
    $('questions').querySelectorAll('textarea').forEach(input => { input.disabled = state.busy || needsArchivedPhoto; });
  }
  function showView(view, focus = false) {
    state.view = view; syncWorkspace();
    if (focus) focusFeedback(view === 'history' ? 'history-title' : state.analysis && !state.editing ? 'report-title' : 'input-title');
  }
  function newAnalysis() {
    if (state.busy || state.caseBusy) return;
    if (state.imageUrl) URL.revokeObjectURL(state.imageUrl);
    if (state.mediaUrl) URL.revokeObjectURL(state.mediaUrl);
    state.file = null; state.mediaKind = null; state.imageUrl = null; state.mediaUrl = null; state.videoInspection = null; state.technicalArchiveOpen = false; $('photo').value = ''; $('context').value = '';
    $('preview-wrap').hidden = true; $('preview').removeAttribute('src'); $('file-name').textContent = '';
    $('video-preview').removeAttribute('src'); $('archived-video').removeAttribute('src'); $('archived-video').hidden = true; $('video-archive-note').hidden = true; $('video-evidence').hidden = true; $('video-frames').replaceChildren();
    $('media-note').hidden = true; $('media-note').textContent = '';
    clearAnalysis(); notice(''); showView('analysis', true);
  }
  function notice(text, kind = '') { $('status').textContent = text; $('status').className = 'notice' + (kind ? ' ' + kind : ''); $('status').hidden = !text; }
  function focusFeedback(id) {
    const target = $(id);
    target.focus({ preventScroll: true });
    target.scrollIntoView({ block: 'start', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' });
  }
  function clearFeedback() {
    ['analysis-feedback', 'questions-feedback'].forEach(id => { $(id).hidden = true; $(id).textContent = ''; });
  }
  function analysisError(message, origin) {
    const target = $(origin + '-feedback');
    target.textContent = message; target.className = 'notice action-feedback error'; target.hidden = false;
    $('analysis-announcement').textContent = t('attemptNoResult');
    if (state.analysis) {
      $('report-title').textContent = t('previousAnalysis');
      $('report-notice').textContent = t('previousUnchanged');
      $('report-notice').hidden = false;
    }
    return target.id;
  }
  async function api(url, options = {}) {
    const response = await fetch(url, { credentials: 'same-origin', ...options });
    let data;
    try { data = await response.json(); } catch { throw new Error(t('unreadableResponse')); }
    if (!response.ok) { const error = new Error(apiErrorMessage(data.error?.code, response.status)); error.status = response.status; error.code = data.error?.code; error.data = data; throw error; }
    return data;
  }
  function applySession(data) {
    // Account verification is enforced by the server; keep its pending states
    // on the dedicated account page instead of exposing the pilot login form.
    if (data.auth_mode === 'accounts' && (!data.authenticated || data.verification_required || data.account?.eligible_for_analysis !== true)) {
      state.authenticated = false; state.csrf = data.csrf || ''; state.configured = false;
      $('login-panel').hidden = true; $('workspace').hidden = true; $('logout').hidden = true;
      $('account-link').hidden = true;
      resetHistory(); window.location.assign('/account'); return;
    }
    const wasAuthenticated = state.authenticated;
    state.authenticated = Boolean(data.authenticated); state.csrf = data.csrf || ''; state.configured = Boolean(data.configured);
    if (data.entitlement) state.entitlement = { ...state.entitlement, ...data.entitlement };
    if (data.media) state.media = { ...state.media, ...data.media };
    $('login-panel').hidden = state.authenticated; $('workspace').hidden = !state.authenticated; $('logout').hidden = !state.authenticated;
    $('account-link').hidden = data.auth_mode !== 'accounts' || !state.authenticated;
    $('login-button').disabled = data.auth_configured === false;
    if (!state.authenticated && data.auth_configured === false) notice(t('pilotUnconfigured'), 'warning');
    if (state.authenticated && !state.configured) notice(t('analysisUnconfigured'), 'warning');
    updateButton();
    if (state.authenticated && (!wasAuthenticated || !state.historyLoaded)) loadCases();
    if (!state.authenticated) resetHistory();
  }
  function updateButton() {
    const trialExhausted = state.entitlement.plan === 'trial' && state.entitlement.analyses_remaining === 0;
    const canExport = state.entitlement.export_allowed !== false;
    const videoReady = state.mediaKind === 'video' && state.media.video_intake_enabled;
    $('analyse-button').disabled = state.busy || state.quotaUncertain || state.videoTrialConsumed || (videoReady ? false : !state.configured || state.mediaKind === 'video' || (trialExhausted && !state.openedCaseId)); $('reanalyse-button').disabled = state.busy || state.quotaUncertain || isSyntheticVideo(state.analysis) || !state.configured;
    $('reanalyse-button').hidden = isSyntheticVideo(state.analysis);
    $('edit-analysis').hidden = isSyntheticVideo(state.analysis);
    const videoSyntheticAvailable = state.authenticated && state.media.video_synthetic_analysis_enabled === true && Boolean(state.videoInspection && state.archive?.saved && state.openedCaseId && !state.analysis);
    $('video-synthetic-controls').hidden = !videoSyntheticAvailable || trialExhausted || state.quotaUncertain || state.videoTrialConsumed;
    $('video-analyze-button').disabled = state.busy || trialExhausted || state.quotaUncertain || state.videoTrialConsumed;
    $('video-analyze-button').textContent = t(state.syntheticVideoBusy ? 'syntheticRunning' : 'syntheticAction');
    $('video-synthetic-note').textContent = t('syntheticConsumes');
    $('video-open-saved-result').hidden = !state.savedVideoResultId || Boolean(state.analysis);
    $('video-open-saved-result').disabled = state.busy;
    $('video-open-saved-result').textContent = t('syntheticOpenSaved');
    if (!state.busy) $('analyse-button').textContent = state.mediaKind === 'video' ? t('inspectVideo') : t('startAnalysis');
    $('export-json').disabled = state.busy || !state.analysis || !canExport; $('print-report').disabled = state.busy || !state.analysis || !canExport;
    $('export-json').hidden = !canExport; $('print-report').hidden = !canExport; $('trial-export-note').hidden = canExport || !state.analysis;
    $('trial-entitlement-note').hidden = !trialExhausted || Boolean(state.openedCaseId);
    $('trial-entitlement-note').textContent = trialExhausted ? t('trialUsed') : '';
    ['new-analysis', 'history-new-analysis', 'nav-analysis', 'nav-history', 'edit-analysis', 'return-report'].forEach(id => { $(id).disabled = state.busy || state.caseBusy; });
    if (!state.busy) $('reanalyse-button').textContent = state.analysis && !state.file ? t('addPhotoUpdate') : t('updateAnswers');
    syncWorkspace();
  }
  function setBusy(value) {
    state.busy = value; updateButton(); $('photo').disabled = value; $('context').disabled = value; $('logout').disabled = value;
    const video = state.mediaKind === 'video';
    $('busy-eyebrow').textContent = video ? t('videoAudioReceived') : t('photoContextSent');
    $('busy-title').textContent = state.syntheticVideoBusy ? t('syntheticRunning') : video ? t('videoRunning') : t('analysisRunning');
    $('busy-description').textContent = state.syntheticVideoBusy ? t('syntheticOnly') : video ? t('videoRunningDescription') : t('analysisRunningDescription');
    $('analyse-button').textContent = value ? (state.mediaKind === 'video' ? t('inspecting') : t('analysing')) : (state.mediaKind === 'video' ? t('inspectVideo') : t('startAnalysis'));
    $('reanalyse-button').textContent = value ? t('analysing') : state.analysis && !state.file ? t('addPhotoUpdate') : t('updateAnswers');
    $('busy-state').hidden = !value; $('report').hidden = value || !state.analysis; $('empty-state').hidden = value || Boolean(state.analysis) || Boolean(state.videoInspection);
    $('result-region').setAttribute('aria-busy', String(value));
    $('result-region').setAttribute('aria-labelledby', value ? 'busy-title' : state.analysis ? 'report-title' : 'result-title');
  }
  function clearAnalysis() {
    state.videoReportSource = null; state.savedVideoResultId = state.quotaUncertain ? state.savedVideoResultId : null;
    $('video-analysis-details').replaceChildren(); $('video-analysis-details').hidden = true;
    state.analysis = null; state.archive = null; state.openedCaseId = null; state.videoInspection = null; state.technicalArchiveOpen = false; state.answers.clear(); state.submittedContext = ''; state.editing = true; clearFeedback();
    $('report').hidden = true; $('empty-state').hidden = false; $('findings').replaceChildren(); $('questions').replaceChildren();
    $('video-evidence').hidden = true; $('video-frames').replaceChildren(); $('archived-video').hidden = true; $('archived-video').removeAttribute('src'); $('video-archive-note').hidden = true;
    $('case-summary').replaceChildren(); $('question-summary').replaceChildren(); $('question-summary').hidden = true;
    $('report-notice').hidden = true; $('report-title').textContent = t('completed');
    $('analysis-announcement').textContent = '';
    $('video-synthetic-status').hidden = !state.quotaUncertain;
    if (state.quotaUncertain) $('video-synthetic-status').textContent = t('syntheticQuotaUnknown');
    $('result-region').setAttribute('aria-labelledby', 'result-title'); updateButton();
  }
  function resetHistory() {
    state.historyBusy = false; state.caseBusy = false; state.historyLoaded = false; state.historyCases = []; state.openedCaseId = null;
    $('history-list').replaceChildren(); $('history-loading').hidden = true; $('history-empty').hidden = true; $('history-error').hidden = true;
    $('history-status').textContent = ''; $('refresh-history').disabled = false;
  }
  function setHistoryBusy(value, message = '', changingCase = false) {
    state.caseBusy = value && changingCase;
    state.historyBusy = value; $('refresh-history').disabled = value; $('history-panel').setAttribute('aria-busy', String(value));
    $('history-list').querySelectorAll('button').forEach(button => { button.disabled = value; });
    if (message) $('history-status').textContent = message;
    updateButton();
  }
  async function archiveSessionExpired() {
    applySession({ authenticated: false, configured: false });
    notice(t('sessionExpired'), 'warning');
    try {
      const fresh = await api('/api/session');
      applySession({ ...fresh, authenticated: false, configured: false });
      notice(t('sessionExpired'), 'warning');
    } catch {
      state.csrf = ''; $('login-button').disabled = true;
      notice(t('sessionReloadLoss'), 'error');
    }
    focusFeedback('status');
  }
  function caseDate(value) {
    const date = new Date(Number(value) * 1000);
    return Number.isNaN(date.getTime()) ? t('dateUnavailable') : new Intl.DateTimeFormat(localeTags[state.language], { dateStyle: 'medium', timeStyle: 'short' }).format(date);
  }
  function caseExcerpt(value, fallback) {
    const text = String(value || fallback || '').trim().replace(/\s+/g, ' ');
    return text.length > 180 ? text.slice(0, 177) + '…' : text;
  }
  function renderCaseList(cases) {
    $('history-list').replaceChildren(); $('history-empty').hidden = cases.length !== 0;
    cases.forEach(item => {
      const technicalVideo = item.kind === 'video_technical_verification';
      const syntheticVideo = item.kind === 'video_synthetic_analysis';
      const card = make('article', null, 'history-item'); card.dataset.caseId = item.id;
      const body = make('div', null, 'history-item-body'); body.append(make('h3', caseExcerpt(item.summary, technicalVideo ? t('videoTechnical') : t('analysisNoSummary'))));
      body.append(make('p', caseDate(item.created_at), 'history-date'));
      if (technicalVideo || syntheticVideo) body.append(make('p', t(syntheticVideo ? 'syntheticHistory' : 'videoTechnicalContext'), 'history-context'));
      if (item.deletion_pending) body.append(make('p', t('caseUnavailable'), 'notice warning'));
      if (item.context) body.append(make('p', caseExcerpt(item.context), 'history-context'));
      const actions = make('div', null, 'history-actions');
      if (!item.deletion_pending) {
        const open = make('button', technicalVideo ? t('openCheck') : t('openAnalysis'), 'button subtle'); open.type = 'button';
        open.addEventListener('click', () => openCase(item.id, open, technicalVideo)); actions.append(open);
      }
      const remove = make('button', item.deletion_pending ? t('retryDelete') : t('delete'), 'button danger'); remove.type = 'button';
      remove.addEventListener('click', () => askDeleteCase(item.id, actions, remove));
      actions.append(remove); card.append(body, actions); $('history-list').append(card);
    });
  }
  async function loadCases({ focus = false } = {}) {
    if (!state.authenticated || state.historyBusy) return;
    $('history-error').hidden = true; $('history-loading').hidden = false; $('history-empty').hidden = true;
    setHistoryBusy(true, t('historyLoading'));
    try {
      const data = await api('/api/cases', { headers: { 'X-CSRF-Token': state.csrf } });
      const cases = Array.isArray(data.cases) ? data.cases : [];
      state.historyCases = cases; renderCaseList(cases); state.historyLoaded = true;
      const storageNote = data.storage?.uploads_blocked ? t('storageFull') : data.storage?.warning ? t('storageWarning') : '';
      $('history-status').textContent = (cases.length ? t('casesCount', { count: cases.length }) : t('noCases')) + storageNote;
      if (focus) { showView('history'); focusFeedback(cases.length ? 'history-title' : 'history-empty'); }
    } catch (err) {
      if (err.status === 401) { await archiveSessionExpired(); return; }
      $('history-list').replaceChildren(); $('history-error').textContent = t('historyUnavailable') + ' ' + localizedError(err); $('history-error').hidden = false;
      $('history-status').textContent = t('historyLoadFailed'); if (focus) { showView('history'); focusFeedback('history-error'); }
    } finally { $('history-loading').hidden = true; setHistoryBusy(false); }
  }
  const isSyntheticVideo = analysis => analysis?.meta?.case_kind === 'video_synthetic_analysis';
  function assertSyntheticReport(analysis) {
    const reject = () => { throw new Error(t('incompleteResult')); };
    const meta = analysis?.meta, coverage = meta?.coverage, transcription = meta?.transcription;
    if (!isSyntheticVideo(analysis) || meta.execution_mode !== 'synthetic_adapters' || meta.real_ai_analysis_performed !== false || (!Array.isArray(analysis.findings) || analysis.findings.length > 100)
        || !coverage || !Number.isFinite(coverage.duration_seconds) || coverage.duration_seconds <= 0 || coverage.duration_seconds > 3600.05 || coverage.continuous_video_observed !== false
        || coverage.ambient_sound_analysis_performed !== false || coverage.sampling_method !== 'archived_timestamp_samples'
        || !Array.isArray(coverage.frames) || coverage.frames.length < 1 || coverage.frames.length > 10 || coverage.frame_count !== coverage.frames.length
        || !['absent', 'silent', 'low_level', 'ready_for_transcription'].includes(coverage.audio_status)) reject();
    const assetIds = new Set();
    let previousFrameTime = -1;
    for (const frame of coverage.frames) {
      if (!frame || !Number.isFinite(frame.timestamp_seconds) || frame.timestamp_seconds < 0 || frame.timestamp_seconds > coverage.duration_seconds
          || frame.timestamp_seconds <= previousFrameTime || typeof frame.asset_id !== 'string' || !frame.asset_id.trim() || frame.asset_id.length > 64 || assetIds.has(frame.asset_id)) reject();
      assetIds.add(frame.asset_id); previousFrameTime = frame.timestamp_seconds;
    }
    if (!transcription || transcription.ambient_sound_analysis_performed !== false || transcription.basis !== 'spoken_claim'
        || !['available', 'unintelligible', 'not_applicable'].includes(transcription.status)
        || ![null, 'it', 'de', 'fr', 'en'].includes(transcription.language)
        || !Array.isArray(transcription.segments) || transcription.segments.length > 200) reject();
    const speechExpected = ['low_level', 'ready_for_transcription'].includes(coverage.audio_status);
    if (transcription.status === 'not_applicable') {
      if (speechExpected || transcription.reason !== coverage.audio_status || transcription.language !== null || transcription.text !== null || transcription.segments.length) reject();
    } else if (!speechExpected || (transcription.status === 'unintelligible' && (transcription.text !== null || transcription.segments.length))) reject();
    let previousSegmentStart = -1;
    for (const segment of transcription.segments) {
      if (!segment || segment.basis !== 'spoken_claim' || !Number.isFinite(segment.start_seconds) || !Number.isFinite(segment.end_seconds)
          || segment.start_seconds < 0 || segment.start_seconds > segment.end_seconds || segment.end_seconds > coverage.duration_seconds + .05
          || segment.start_seconds < previousSegmentStart || typeof segment.text !== 'string' || !segment.text.trim() || Array.from(segment.text).length > 4000) reject();
      previousSegmentStart = segment.start_seconds;
    }
    if (transcription.status === 'available') {
      const joined = transcription.segments.map(segment => segment.text).join(' ');
      if (!joined.trim() || transcription.text !== joined || ['[inaudible]', '[unintelligible]', '[non comprensibile]'].includes(joined.toLowerCase())
          || transcription.segments.reduce((bytes, segment) => bytes + new Blob([segment.text]).size, 0) > 32000) reject();
    }
    const basisForCertainty = { visible: 'sampled_frame', reported: 'reported', verify: 'verify' };
    for (const finding of analysis.findings) {
      const evidence = finding?.video_evidence;
      if (!evidence || !Object.hasOwn(basisForCertainty, finding.certainty) || evidence.basis !== basisForCertainty[finding.certainty]) reject();
      const frameIndex = coverage.frames.findIndex(frame => frame.asset_id === evidence.asset_id && frame.timestamp_seconds === evidence.timestamp_seconds);
      if (frameIndex < 0 || typeof finding.id !== 'string' || !finding.id.startsWith('frame-' + (frameIndex + 1) + ':')) reject();
    }
  }
  function privateAssetUrl(source, asset) {
    if (!source || !asset || typeof asset.download_url !== 'string' || typeof asset.id !== 'string') return null;
    const expected = '/api/cases/' + encodeURIComponent(source.id) + '/assets/' + encodeURIComponent(asset.id);
    return asset.download_url === expected ? expected : null;
  }
  function videoFrameAsset(source, evidence) {
    if (!source || !evidence || !Array.isArray(source.assets)) return null;
    const asset = source.assets.find(item => item.id === evidence.asset_id && item.role === 'frame' && String(item.media_type).startsWith('image/'));
    return privateAssetUrl(source, asset) ? asset : null;
  }
  function renderSyntheticDetails(target, analysis, source) {
    const { coverage, transcription } = analysis.meta;
    target.replaceChildren();
    target.append(make('p', t('syntheticOnly'), 'notice warning'));
    target.append(make('h3', t('syntheticComplete')), make('p', t('syntheticCoverage', { count: coverage.frame_count, seconds: coverage.duration_seconds.toFixed(1) }), 'video-coverage'));
    const original = source?.assets?.find(asset => asset.role === 'original' && String(asset.media_type).startsWith('video/') && privateAssetUrl(source, asset));
    if (original) { const video = make('video'); video.src = original.download_url; video.controls = true; video.preload = 'metadata'; video.setAttribute('aria-label', t('syntheticHistory')); target.append(video); }
    if (!source) target.append(make('p', t('syntheticSourceMissing'), 'notice warning'));
    const gallery = make('div', null, 'video-frames');
    for (const evidence of coverage.frames) {
      const asset = videoFrameAsset(source, evidence); if (!asset) continue;
      const figure = make('figure', null, 'video-frame'), image = make('img'); image.src = asset.download_url; image.alt = t('syntheticFrame', { seconds: evidence.timestamp_seconds.toFixed(1) });
      figure.append(image, make('figcaption', t('syntheticFrame', { seconds: evidence.timestamp_seconds.toFixed(1) }))); gallery.append(figure);
    }
    if (gallery.childNodes.length) target.append(gallery);
    const audioLabels = { absent: 'syntheticAudioAbsent', silent: 'syntheticAudioSilent', low_level: 'syntheticAudioLow', ready_for_transcription: 'syntheticAudioPresent', error: 'syntheticAudioError' };
    target.append(make('p', t('syntheticAudio', { status: t(audioLabels[coverage.audio_status] || 'syntheticAudioError') }), 'audio-summary'));
    target.append(make('h3', t('syntheticSpoken')));
    if (transcription?.status === 'available' && Array.isArray(transcription.segments) && transcription.segments.length) {
      target.append(make('p', t('syntheticTranscriptAvailable'), 'field-note'));
      const list = make('ol', null, 'transcript-segments');
      for (const segment of transcription.segments) {
        const item = make('li');
        const time = Number.isFinite(segment.start_seconds) && Number.isFinite(segment.end_seconds) ? segment.start_seconds.toFixed(1) + '–' + segment.end_seconds.toFixed(1) + ' s' : t('notAvailable');
        item.append(make('span', time, 'transcript-time'), make('p', segment.text)); list.append(item);
      }
      target.append(list);
    } else target.append(make('p', t(transcription?.status === 'not_applicable' ? 'syntheticTranscriptNA' : 'syntheticTranscriptUnknown'), 'notice warning'));
    target.append(make('p', t('syntheticNoAmbient'), 'field-note'));
  }
  async function openSyntheticVideoCase(saved, knownSource = null) {
    assertSyntheticReport(saved.analysis);
    let source = knownSource;
    if (!source && typeof saved.analysis.meta.source_case_id === 'string') {
      try { source = (await api('/api/cases/' + encodeURIComponent(saved.analysis.meta.source_case_id), { headers: { 'X-CSRF-Token': state.csrf } })).case; }
      catch (err) { if (err.status === 401) throw err; source = null; }
    }
    const oldSource = state.videoReportSource, oldImage = state.imageUrl;
    state.videoReportSource = source || null; state.imageUrl = null;
    try { await renderAnalysis(saved.analysis, saved.context || '', { archived: true, videoSource: source }); }
    catch (err) { state.videoReportSource = oldSource; state.imageUrl = oldImage; throw err; }
    if (oldImage?.startsWith('blob:')) URL.revokeObjectURL(oldImage);
    state.analysis = saved.analysis; state.file = null; state.mediaKind = 'video'; state.videoInspection = null; state.technicalArchiveOpen = false;
    state.archive = { saved: true, case_id: saved.id, kind: 'video_synthetic_analysis' }; state.openedCaseId = saved.id; state.submittedContext = saved.context || ''; state.editing = false; state.answers.clear();
    $('photo').value = ''; $('preview-wrap').hidden = true; $('video-evidence').hidden = true; $('archived-video').hidden = true;
    $('report-title').textContent = t('syntheticComplete'); $('report-notice').textContent = t('syntheticOnly') + (state.quotaUncertain ? ' ' + t('syntheticQuotaUnknown') : ''); $('report-notice').hidden = false;
    $('empty-state').hidden = true; $('report').hidden = false; showView('analysis'); updateButton(); focusFeedback('report-title');
  }
  async function runSyntheticVideo() {
    if (state.busy || state.quotaUncertain || state.videoTrialConsumed || (state.entitlement.plan === 'trial' && state.entitlement.analyses_remaining === 0) || !state.authenticated || state.media.video_synthetic_analysis_enabled !== true
        || !state.videoInspection || !state.archive?.saved || !state.openedCaseId || state.analysis) return;
    const sourceId = state.openedCaseId, context = state.submittedContext || $('context').value || '';
    state.syntheticVideoBusy = true; $('video-synthetic-status').hidden = true; setBusy(true); focusFeedback('busy-title');
    try {
      const data = await api('/api/media/cases/' + encodeURIComponent(sourceId) + '/analyze', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': state.csrf }, body: JSON.stringify({ context }) });
      if (data.execution_mode !== 'synthetic_adapters' || data.real_ai_analysis !== false || data.trial_consumed !== true || !data.archive?.saved || !data.archive.case_id) throw new Error(t('incompleteResult'));
      state.videoTrialConsumed = true; state.savedVideoResultId = data.archive.case_id;
      assertSyntheticReport(data.analysis);
      if (data.entitlement) state.entitlement = { ...state.entitlement, ...data.entitlement };
      await openSyntheticVideoCase({ id: data.archive.case_id, context, analysis: data.analysis });
      if (data.entitlement_status?.available === false) { $('report-notice').textContent = t('syntheticOnly') + ' ' + t('syntheticQuotaUsed'); $('report-notice').hidden = false; }
      $('analysis-announcement').textContent = t('syntheticComplete'); loadCases();
    } catch (err) {
      if (err.status === 401) { await archiveSessionExpired(); return; }
      if (state.videoTrialConsumed && !err.status) {
        $('video-synthetic-status').textContent = t('syntheticResultUnreadable');
      } else if (err.code === 'trial_completion_unknown' || !err.status) {
        state.quotaUncertain = true;
        state.savedVideoResultId = err.data?.archive?.saved ? err.data.archive.case_id : null;
        $('video-synthetic-status').textContent = t(err.code === 'trial_completion_unknown' ? 'syntheticQuotaUnknown' : 'syntheticUnknownNetwork');
      } else {
        if (err.code === 'trial_exhausted') state.videoTrialConsumed = true;
        $('video-synthetic-status').textContent = err.code === 'trial_exhausted' ? t('trialUsed') : t('syntheticFailure') + ' ' + localizedError(err);
      }
      $('video-synthetic-status').hidden = false; focusFeedback('video-synthetic-status');
    } finally {
      state.syntheticVideoBusy = false; setBusy(false);
      if (state.analysis) focusFeedback('report-title');
    }
  }
  $('video-analyze-button').addEventListener('click', runSyntheticVideo);
  $('video-open-saved-result').addEventListener('click', async () => {
    if (state.busy || !state.savedVideoResultId) return;
    setBusy(true);
    try {
      const saved = (await api('/api/cases/' + encodeURIComponent(state.savedVideoResultId), { headers: { 'X-CSRF-Token': state.csrf } })).case;
      await openSyntheticVideoCase(saved);
    } catch (err) { $('video-synthetic-status').textContent = t(state.quotaUncertain ? 'syntheticQuotaUnknown' : 'syntheticResultUnreadable') + ' ' + localizedError(err); $('video-synthetic-status').hidden = false; focusFeedback('video-synthetic-status'); }
    finally { setBusy(false); }
  });

  function openTechnicalVideoCase(saved) {
    if (!state.quotaUncertain) state.savedVideoResultId = null;
    const inspection = saved?.analysis?.meta?.video_inspection;
    if (!inspection || !Number.isFinite(inspection.duration_seconds) || !Array.isArray(inspection.frames) || !inspection.audio) throw new Error(t('savedVideoIncomplete'));
    const assets = Array.isArray(saved.assets) ? saved.assets : [];
    const original = assets.find(asset => asset?.role === 'original' && String(asset.media_type || '').startsWith('video/') && asset.download_url);
    const frameAssets = assets.filter(asset => asset?.role === 'frame' && String(asset.media_type || '').startsWith('image/') && asset.download_url).sort((a, b) => String(a.filename).localeCompare(String(b.filename)));
    if (frameAssets.length !== inspection.frames.length) throw new Error(t('savedFramesMismatch'));
    const restored = {
      ...inspection,
      frames: inspection.frames.map((frame, index) => ({ timestamp_seconds: frame.timestamp_seconds, image_data_url: frameAssets[index].download_url })),
    };
    if (state.imageUrl && state.imageUrl.startsWith('blob:')) URL.revokeObjectURL(state.imageUrl);
    if (state.mediaUrl && state.mediaUrl.startsWith('blob:')) URL.revokeObjectURL(state.mediaUrl);
    state.imageUrl = null; state.mediaUrl = original ? original.download_url : null; state.file = null; state.mediaKind = 'video'; state.analysis = null; state.videoInspection = restored; state.technicalArchiveOpen = true; state.archive = { saved: true, case_id: saved.id, kind: 'video_technical_verification' }; state.openedCaseId = saved.id; state.editing = false; state.answers.clear(); state.submittedContext = saved.context || '';
    $('photo').value = ''; $('context').value = saved.context || ''; $('preview-wrap').hidden = true; $('report').hidden = true; $('empty-state').hidden = true;
    $('archived-video').hidden = !original; if (original) $('archived-video').src = original.download_url; else $('archived-video').removeAttribute('src');
    $('video-archive-note').textContent = original
      ? restored.audio.status === 'absent'
        ? t('videoOriginalNoAudio')
        : t('videoOriginalAudio')
      : t('videoOriginalMissing');
    $('video-archive-note').hidden = false; renderVideoInspection(restored); showView('analysis');
    $('result-region').setAttribute('aria-labelledby', 'video-evidence-title'); $('history-status').textContent = t('videoCaseOpened'); updateButton(); focusFeedback('video-evidence-title');
  }
  async function openCase(caseId, trigger, technicalHint = false) {
    if (state.historyBusy || state.busy) return;
    $('history-error').hidden = true; setHistoryBusy(true, technicalHint ? t('openingCheck') : t('openingAnalysis'), true); trigger.textContent = t('opening');
    try {
      const data = await api('/api/cases/' + encodeURIComponent(caseId), { headers: { 'X-CSRF-Token': state.csrf } });
      const saved = data.case;
      if (!saved?.analysis || !Array.isArray(saved.analysis.findings)) throw new Error(t('savedCaseIncomplete'));
      if (saved.analysis.meta?.case_kind === 'video_technical_verification') { openTechnicalVideoCase(saved); return; }
      if (isSyntheticVideo(saved.analysis)) { await openSyntheticVideoCase(saved); return; }
      const previousImageUrl = state.imageUrl, previousFile = state.file, previousAnswers = new Map(state.answers);
      const original = Array.isArray(saved.assets) ? saved.assets.find(asset => asset?.role === 'original' && String(asset.media_type || '').startsWith('image/') && asset.download_url) : null;
      state.imageUrl = original ? original.download_url : null; state.file = null; state.answers.clear(); state.videoInspection = null; state.technicalArchiveOpen = false; $('video-evidence').hidden = true; $('archived-video').hidden = true; $('archived-video').removeAttribute('src'); $('video-archive-note').hidden = true;
      if (state.imageUrl) { $('preview').src = state.imageUrl; $('preview').hidden = false; }
      try { await renderAnalysis(saved.analysis, saved.context || '', { archived: true }); }
      catch (err) { state.imageUrl = previousImageUrl; state.file = previousFile; state.answers = previousAnswers; if (previousImageUrl) $('preview').src = previousImageUrl; else $('preview').removeAttribute('src'); throw err; }
      if (previousImageUrl && previousImageUrl.startsWith('blob:')) URL.revokeObjectURL(previousImageUrl);
      $('photo').value = ''; $('preview-wrap').hidden = true;
      state.analysis = saved.analysis; state.submittedContext = saved.context || ''; state.archive = { saved: true, case_id: saved.id }; state.openedCaseId = saved.id; state.editing = false;
      $('context').value = saved.context || ''; showView('analysis');
      $('empty-state').hidden = true; $('report').hidden = false; $('report-title').textContent = t('savedAnalysis');
      $('report-notice').textContent = original ? t('originalStored') : t('archivedPhotoMissing'); $('report-notice').hidden = false;
      $('result-region').setAttribute('aria-labelledby', 'report-title'); $('history-status').textContent = t('savedOpened'); updateButton(); focusFeedback('report-title');
    } catch (err) {
      if (err.status === 401) { await archiveSessionExpired(); return; }
      $('history-error').textContent = t('openFailed') + ' ' + localizedError(err); $('history-error').hidden = false; $('history-status').textContent = t('openingFailed'); showView('history'); focusFeedback('history-error');
    } finally { trigger.textContent = technicalHint ? t('openCheck') : t('openAnalysis'); setHistoryBusy(false); }
  }
  function askDeleteCase(caseId, actions, trigger) {
    if (state.historyBusy || actions.querySelector('.delete-confirm')) return;
    const confirm = make('div', null, 'delete-confirm'); confirm.setAttribute('role', 'group'); confirm.setAttribute('aria-label', t('confirmDeleteLabel'));
    confirm.append(make('p', t('confirmDeleteQuestion')));
    const yes = make('button', t('confirmDeleteLabel'), 'button danger'); yes.type = 'button';
    const no = make('button', t('cancel'), 'button subtle'); no.type = 'button';
    yes.addEventListener('click', () => deleteCase(caseId, yes));
    no.addEventListener('click', () => { confirm.remove(); trigger.hidden = false; trigger.focus(); });
    trigger.hidden = true; confirm.append(yes, no); actions.append(confirm); yes.focus();
  }
  async function deleteCase(caseId, trigger) {
    if (state.historyBusy) return;
    setHistoryBusy(true, t('deletingStatus'), true); trigger.textContent = t('deleting');
    try {
      await api('/api/cases/' + encodeURIComponent(caseId), { method: 'DELETE', headers: { 'X-CSRF-Token': state.csrf } });
      if (state.openedCaseId === caseId) clearAnalysis();
      setHistoryBusy(false); await loadCases(); $('history-status').textContent = t('deleted'); showView('history'); focusFeedback('history-title');
    } catch (err) {
      if (err.status === 401) { await archiveSessionExpired(); return; }
      $('history-error').textContent = t('deleteFailed') + ' ' + localizedError(err); $('history-error').hidden = false; $('history-status').textContent = t('deletionFailed'); showView('history'); focusFeedback('history-error');
    } finally { trigger.textContent = t('confirmDeleteLabel'); setHistoryBusy(false); }
  }
  $('refresh-history').addEventListener('click', () => loadCases({ focus: true }));
  $('nav-analysis').addEventListener('click', () => { if (!state.busy && !state.caseBusy) showView('analysis', true); });
  $('nav-history').addEventListener('click', () => { if (!state.busy && !state.caseBusy) showView('history', true); });
  $('new-analysis').addEventListener('click', newAnalysis);
  $('history-new-analysis').addEventListener('click', newAnalysis);
  $('edit-analysis').addEventListener('click', () => { if (!state.busy) { state.editing = true; showView('analysis', true); } });
  $('return-report').addEventListener('click', () => { if (!state.busy && state.analysis) { state.editing = false; showView('analysis', true); } });
  $('login-form').addEventListener('submit', async e => {
    e.preventDefault(); $('login-button').disabled = true; notice('');
    try { await api('/api/login', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': state.csrf }, body: JSON.stringify({ password: $('password').value }) }); $('password').value = ''; applySession(await api('/api/session')); }
    catch (err) { notice(localizedError(err), 'error'); }
    finally { $('login-button').disabled = false; }
  });
  $('logout').addEventListener('click', async () => {
    if (state.busy) return;
    try {
      await api('/api/logout', { method: 'POST', headers: { 'X-CSRF-Token': state.csrf } });
      clearAnalysis(); $('analysis-form').reset(); $('preview-wrap').hidden = true; $('preview').removeAttribute('src');
      if (state.imageUrl) URL.revokeObjectURL(state.imageUrl); if (state.mediaUrl) URL.revokeObjectURL(state.mediaUrl); state.imageUrl = null; state.mediaUrl = null; state.file = null; state.mediaKind = null; state.view = 'analysis';
      applySession({ authenticated: false, configured: false }); applySession(await api('/api/session')); notice(t('sessionClosed'));
    } catch (err) { notice(localizedError(err), 'error'); }
  });
  $('photo').addEventListener('change', () => {
    const attachingArchivedPhoto = Boolean(state.analysis && !state.file);
    if (attachingArchivedPhoto) { clearFeedback(); state.editing = true; } else clearAnalysis();
    notice('');
    if (state.imageUrl) URL.revokeObjectURL(state.imageUrl); if (state.mediaUrl) URL.revokeObjectURL(state.mediaUrl); state.imageUrl = null; state.mediaUrl = null; state.file = null; state.mediaKind = null; state.videoInspection = null; state.technicalArchiveOpen = false; $('preview-wrap').hidden = true; $('preview').hidden = false; $('video-preview').hidden = true; $('video-preview').removeAttribute('src'); $('archived-video').hidden = true; $('archived-video').removeAttribute('src'); $('video-archive-note').hidden = true; $('video-evidence').hidden = true; $('video-frames').replaceChildren(); $('media-note').hidden = true;
    syncWorkspace();
    const file = $('photo').files[0]; if (!file) return;
    const images = ['image/jpeg', 'image/png', 'image/webp'], videos = ['video/mp4', 'video/webm', 'video/quicktime'];
    if (!images.includes(file.type) && !videos.includes(file.type)) { focusFeedback(analysisError(t('invalidMedia'), 'analysis')); $('photo').value = ''; return; }
    const isVideo = videos.includes(file.type), limit = isVideo ? state.media.video_max_bytes : state.media.image_max_bytes;
    if (file.size > limit) { focusFeedback(analysisError(t('mediaTooLarge', { kind: isVideo ? t('videoNoun') : t('photoNoun'), limit: Math.floor(limit / 1024 / 1024) }), 'analysis')); $('photo').value = ''; return; }
    state.file = file; state.mediaKind = isVideo ? 'video' : 'image'; $('file-name').textContent = file.name; $('preview-wrap').hidden = false;
    $('media-ready').textContent = isVideo ? t('selectedVideo') : t('selectedPhoto');
    if (isVideo) {
      $('preview').hidden = true; $('preview').removeAttribute('src');
      state.mediaUrl = URL.createObjectURL(file); $('video-preview').src = state.mediaUrl; $('video-preview').hidden = false;
      $('media-note').textContent = state.media.video_intake_enabled
        ? t('videoReady', { seconds: state.media.video_max_seconds })
        : t('videoDisabled');
      $('media-note').hidden = false;
    } else {
      $('video-preview').hidden = true; state.imageUrl = URL.createObjectURL(file); $('preview').src = state.imageUrl; $('preview').hidden = false; $('media-note').hidden = true;
    }
    if (attachingArchivedPhoto) {
      $('report-notice').textContent = t('photoForUpdate');
      $('report-notice').hidden = false;
    }
    updateButton();
  });
  function composedContext() {
    const parts = [$('context').value.trim()];
    if (state.answers.size) parts.push('Chiarimenti forniti dall’utilizzatore:\n' + Array.from(state.answers.entries()).map(([question, answer]) => question + '\nRisposta: ' + answer).join('\n\n'));
    return parts.filter(Boolean).join('\n\n');
  }
  async function analyse(origin = 'analysis') {
    if (state.busy) return;
    if (state.quotaUncertain) { notice(t('syntheticQuotaUnknown'), 'warning'); return; }
    clearFeedback();
    if (!state.file) { focusFeedback(analysisError(t('selectMedia'), origin)); return; }
    if (state.mediaKind === 'video') { await inspectVideo(origin); return; }
    const context = composedContext(); if (context.length > 8000) { focusFeedback(analysisError(t('contextTooLong'), origin)); return; }
    if (!state.configured) { focusFeedback(analysisError(t('configRequired'), origin)); return; }
    notice(''); if (origin === 'analysis') state.editing = true; showView('analysis'); setBusy(true); focusFeedback('busy-title'); state.controller = new AbortController();
    $('analysis-announcement').textContent = t('analysisRunning') + '.';
    let outcomeTarget = 'report-title';
    const form = new FormData(); form.append('file', state.file); form.append('context', context);
    form.append('request_kind', state.analysis && state.openedCaseId ? 'clarification' : 'initial');
    if (state.analysis && state.openedCaseId) form.append('case_id', state.openedCaseId);
    try {
      const data = await api('/analizza', { method: 'POST', headers: { 'X-CSRF-Token': state.csrf }, body: form, signal: state.controller.signal });
      if (!data.analysis || !Array.isArray(data.analysis.findings)) throw new Error(t('incompleteResult'));
      await renderAnalysis(data.analysis, context); state.analysis = data.analysis; state.archive = data.archive || null; state.submittedContext = context; state.editing = false; state.openedCaseId = data.archive?.case_id || state.openedCaseId || null;
      if (data.entitlement) state.entitlement = data.entitlement;
      $('report-title').textContent = t('completed'); $('report-notice').hidden = true;
      if (data.archive?.saved) { notice(t('completedArchived') + (data.archive.storage?.warning ? t('storageWarning') : '')); loadCases(); }
      else if (data.archive?.message) {
        const exportHint = state.entitlement.export_allowed === false ? t('staysHere') : t('exportHint');
        $('report-notice').textContent = t('notArchived') + exportHint;
        $('report-notice').hidden = false;
      }
      $('analysis-announcement').textContent = t('completedAnnouncement');
    } catch (err) {
      if (err.data?.entitlement) { state.entitlement = err.data.entitlement; updateButton(); }
      if (err.status === 401) {
        analysisError(t('sessionExpired'), origin);
        applySession({ authenticated: false, configured: false });
        try { applySession(await api('/api/session')); notice(t('sessionExpired'), 'warning'); }
        catch { $('login-button').disabled = true; notice(t('sessionExpired'), 'error'); }
        outcomeTarget = 'status';
      }
      else {
        const message = localizedError(err);
        outcomeTarget = analysisError(t('analysisFailed', { reason: message, suffix: state.analysis ? t('previousAvailable') : t('noResult') }), origin);
      }
    } finally {
      state.controller = null; setBusy(false);
      // Follow the explicit submission, without interrupting someone who moved on to another field.
      const active = document.activeElement;
      if (!active || active === document.body || active === $('busy-title') || active.disabled) focusFeedback(outcomeTarget);
    }
  }
  function renderVideoInspection(media) {
    $('video-summary').textContent = t('videoSummary', { seconds: Number(media.duration_seconds).toFixed(1), frames: media.frames.length });
    $('video-frames').replaceChildren();
    media.frames.forEach(frame => {
      const timestamp = Number(frame.timestamp_seconds);
      const figure = make('figure', null, 'video-frame'); const image = make('img'); image.src = frame.image_data_url; image.alt = t('frameAlt', { seconds: timestamp.toFixed(1) });
      figure.append(image, make('figcaption', timestamp.toFixed(1) + ' s')); $('video-frames').append(figure);
    });
    const labels = { absent: t('audioAbsent'), silent: t('audioSilent'), low_level: t('audioLow'), ready_for_transcription: t('audioReady'), error: t('audioError') };
    $('audio-summary').textContent = labels[media.audio.status] || t('audioUnknown');
    $('video-evidence').hidden = false;
  }
  async function inspectVideo(origin) {
    if (!state.media.video_intake_enabled) { focusFeedback(analysisError(t('videoLocalUnavailable'), origin)); return; }
    setBusy(true); state.controller = new AbortController(); $('analysis-announcement').textContent = t('videoStarted');
    const form = new FormData(); form.append('file', state.file); form.append('context', composedContext());
    try {
      const data = await api('/api/media/inspect', { method: 'POST', headers: { 'X-CSRF-Token': state.csrf }, body: form, signal: state.controller.signal });
      state.videoInspection = data.media; state.technicalArchiveOpen = false; state.archive = data.archive || null; state.openedCaseId = data.archive?.case_id || null; $('archived-video').hidden = true; $('archived-video').removeAttribute('src'); $('video-archive-note').hidden = true; renderVideoInspection(data.media); $('empty-state').hidden = true;
      const incomplete = data.media.audio.status === 'error' ? t('audioIncomplete') : '';
      const archiveFull = data.archive?.storage?.uploads_blocked || /spazio archivio esaurito/i.test(String(data.archive?.message || ''));
      const archived = data.archive?.saved ? t('archivedVideo') : data.archive?.message ? ' ' + t(archiveFull ? 'archiveFullExisting' : 'notArchived') : '';
      $('media-note').textContent = t('videoChecked') + incomplete + t('trialNotUsed') + archived;
      $('media-note').hidden = false;
      $('analysis-announcement').textContent = t('videoComplete');
      if (data.archive?.saved) loadCases();
    } catch (err) {
      if (err.status === 401) {
        analysisError(t('sessionExpired'), origin);
        applySession({ authenticated: false, configured: false });
        try { applySession(await api('/api/session')); notice(t('sessionExpired'), 'warning'); }
        catch { notice(t('sessionExpired'), 'error'); }
      } else focusFeedback(analysisError(t('videoNotCompleted', { reason: localizedError(err) }), origin));
    }
    finally { state.controller = null; setBusy(false); if (!state.videoInspection) focusFeedback('analysis-feedback'); else focusFeedback('video-evidence-title'); }
  }
  $('analysis-form').addEventListener('submit', e => { e.preventDefault(); analyse(); });
  $('questions-form').addEventListener('submit', e => {
    e.preventDefault();
    if (state.analysis?.meta?.case_kind === 'video_synthetic_analysis' || state.quotaUncertain) return;
    if (state.analysis && !state.file) { state.editing = true; showView('analysis', true); return; }
    $('questions').querySelectorAll('textarea').forEach(input => { const answer = input.value.trim(); if (answer) state.answers.set(input.dataset.question, answer); else state.answers.delete(input.dataset.question); });
    analyse('questions');
  });
  function addText(parent, tag, text, cls) { if (text) parent.append(make(tag, text, cls)); }
  async function createCrop(bbox, image, id, sourceUrl = state.imageUrl, timestamp = null) {
    if (!bbox || !image || ![bbox.x, bbox.y, bbox.width, bbox.height].every(Number.isFinite)) return null;
    const { x, y, width, height } = bbox;
    if (x < 0 || y < 0 || width <= 0 || height <= 0 || x + width > 1.001 || y + height > 1.001) return null;
    const figure = make('figure', null, 'crop'), canvas = make('canvas');
    const sw = width * image.naturalWidth, sh = height * image.naturalHeight, scale = Math.min(1, 900 / Math.max(sw, sh));
    canvas.width = Math.max(1, Math.round(sw * scale)); canvas.height = Math.max(1, Math.round(sh * scale));
    canvas.setAttribute('role', 'img'); canvas.setAttribute('aria-label', t('cropAria', { id }));
    const ctx = canvas.getContext('2d'); if (!ctx) return null;
    try { ctx.drawImage(image, x * image.naturalWidth, y * image.naturalHeight, sw, sh, 0, 0, canvas.width, canvas.height); } catch { return null; }
    const caption = make('figcaption'); caption.append(make('span', timestamp === null ? t('cropCaption', { id }) : t('syntheticCropCaption', { id, seconds: timestamp.toFixed(1) })));
    const link = make('a', t(timestamp === null ? 'fullPhoto' : 'syntheticOpenFrame')); link.href = sourceUrl; link.target = '_blank'; link.rel = 'noopener'; caption.append(link); figure.append(canvas, caption); return figure;
  }
  function validUrl(url) { try { const parsed = new URL(url); return parsed.protocol === 'https:' ? parsed.href : null; } catch { return null; } }
  function collectQuestions(analysis) {
    const merged = new Map();
    const add = (text, critical, why, findingId) => {
      if (typeof text !== 'string' || !text.trim()) return;
      const key = text.trim().replace(/\s+/g, ' ');
      const question = merged.get(key) || { text: key, critical: false, why: '', findingIds: [] };
      question.critical = question.critical || Boolean(critical);
      if (!question.why && why) question.why = why;
      if (findingId && !question.findingIds.includes(findingId)) question.findingIds.push(findingId);
      merged.set(key, question);
    };
    (analysis.questions || []).forEach(q => add(q.text, q.critical, q.why));
    analysis.findings.forEach(f => add(f.question, f.critical_unknown, '', f.id));
    return [...merged.values()].sort((a, b) => Number(b.critical) - Number(a.critical));
  }
  async function renderAnalysis(analysis, submittedContext, options = {}) {
    // Build off-screen: a rendering failure must not overwrite the previous valid report.
    const draft = document.getElementById('report').cloneNode(true);
    const $ = id => id === 'preview' ? document.getElementById(id) : draft.querySelector('#' + id);
    $('summary').textContent = analysis.summary || '';
    const synthetic = isSyntheticVideo(analysis), videoSource = options.videoSource === undefined ? state.videoReportSource : options.videoSource;
    if (synthetic) assertSyntheticReport(analysis);
    const questionList = collectQuestions(analysis);
    const hasUnknown = Boolean(analysis.needs_clarification) || analysis.findings.some(f => f.critical_unknown || f.risk === 'undetermined') || questionList.some(q => q.critical);
    $('assessment-state').textContent = hasUnknown ? t('assessmentIncomplete') : t('assessmentProposed');
    $('assessment-state').className = 'assessment-state' + (hasUnknown ? ' incomplete' : '');
    $('findings').replaceChildren();
    let image = synthetic || !state.imageUrl ? null : $('preview');
    if (image) { try { await image.decode(); } catch { image = null; } }
    // Snapshot only the photo and context used by this successful request.
    const meta = analysis.meta || {};
    $('case-summary').replaceChildren();
    $('case-summary').append(make('h3', t('situation')));
    if (image && state.imageUrl) {
      const photo = make('img'); photo.src = state.imageUrl; photo.alt = t('fullPhotoAlt'); photo.className = 'case-photo';
      $('case-summary').append(photo);
    } else if (!synthetic) $('case-summary').append(make('p', options.archived ? t('noArchivedPhoto') : t('noPrintPhoto'), 'notice warning'));
    $('video-analysis-details').hidden = !synthetic;
    $('video-analysis-details').setAttribute('aria-label', t('syntheticHistory'));
    if (synthetic) renderSyntheticDetails($('video-analysis-details'), analysis, videoSource);
    else $('video-analysis-details').replaceChildren();
    $('case-summary').append(make('p', t('sentContext'), 'measure-label'), make('p', submittedContext || t('noContext'), 'case-context'));
    $('case-summary').append(make('p', t('analysisDate', { date: meta.created_at || t('notAvailable'), method: meta.method_version || meta.prompt_version || t('notSpecified') }), 'case-meta'));
    const decisiveCount = questionList.filter(q => q.critical).length;
    $('question-summary').replaceChildren(); $('question-summary').hidden = !questionList.length;
    if (questionList.length) {
      $('question-summary').append(make('p', t('questionsCount', { count: questionList.length, decisive: decisiveCount })));
      const jump = make('button', decisiveCount ? t('goCritical') : t('goQuestions'), 'button subtle'); jump.type = 'button';
      jump.addEventListener('click', () => focusFeedback('questions-title')); $('question-summary').append(jump);
    }
    const priority = f => f.risk === 'high' ? 0 : f.critical_unknown ? 1 : ({ undetermined: 2, medium: 3, low: 4 }[f.risk] ?? 5);
    const ordered = [...analysis.findings].sort((a, b) => priority(a) - priority(b));
    if (!ordered.length) $('findings').append(make('p', t('noStructured'), 'notice warning'));
    for (const finding of ordered) {
      const risk = Object.hasOwn(riskLabels, finding.risk) ? finding.risk : 'undetermined';
      const card = make('section', null, 'finding ' + risk), top = make('div', null, 'finding-topline');
      top.append(make('span', t('observation', { id: finding.id }), 'finding-id'), make('span', t(riskLabels[risk]), 'risk-tag ' + risk)); card.append(top, make('h3', finding.title));
      const measure = make('div', null, 'measure'); measure.append(make('p', t('whatToDo'), 'measure-label'), make('p', finding.action, 'measure-action'), make('p', t('when', { deadline: finding.deadline || t('deadlineUnknown') }), 'deadline')); card.append(measure);
      let findingImage = image, sourceUrl = state.imageUrl, stamp = null;
      if (synthetic) {
        stamp = Number.isFinite(finding.video_evidence?.timestamp_seconds) ? finding.video_evidence.timestamp_seconds : null;
        const frameAsset = videoFrameAsset(videoSource, finding.video_evidence);
        sourceUrl = frameAsset ? frameAsset.download_url : null;
        if (stamp !== null) card.append(make('p', t('syntheticFrame', { seconds: stamp.toFixed(1) }), 'video-frame-reference'));
        if (sourceUrl) { findingImage = make('img'); findingImage.src = sourceUrl; try { await findingImage.decode(); } catch { findingImage = null; } }
      }
      const crop = await createCrop(finding.bbox, findingImage, finding.id, sourceUrl, stamp);
      if (crop) card.append(crop);
      else if (synthetic) {
        if (sourceUrl && stamp !== null) {
          const figure = make('figure', null, 'crop video-finding-frame'), frame = make('img'); frame.src = sourceUrl; frame.alt = t('syntheticFrame', { seconds: stamp.toFixed(1) });
          const caption = make('figcaption', t('syntheticFrame', { seconds: stamp.toFixed(1) })), link = make('a', t('syntheticOpenFrame')); link.href = sourceUrl; link.target = '_blank'; link.rel = 'noopener'; caption.append(link); figure.append(frame, caption); card.append(figure);
        } else card.append(make('p', t('syntheticFrameMissing'), 'crop-fallback'));
      } else {
        const fallback = make('p', t('cropUnavailable', { id: finding.id }), 'crop-fallback');
        if (state.imageUrl) { const link = make('a', t('openFullPhoto')); link.href = state.imageUrl; link.target = '_blank'; link.rel = 'noopener'; fallback.append(link); }
        fallback.append(make('span', image ? t('seeFullPhoto') : t('compareOriginal'), 'print-photo-reference')); card.append(fallback);
      }
      card.append(make('p', t(synthetic && finding.certainty === 'visible' ? 'syntheticVisible' : certaintyLabels[finding.certainty] || 'verify'), 'evidence-label'), make('p', finding.evidence, 'evidence-text'));
      addText(card, 'p', finding.exposed_people ? t('exposed', { value: finding.exposed_people }) : '', 'finding-detail');
      addText(card, 'p', finding.question ? t('clarify', { value: finding.question }) : '', 'finding-question');
      const cited = (finding.references || []).map(ref => (analysis.sources || []).find(s => s.id === ref.source_id)).filter(Boolean);
      if (cited.length) { const p = make('p', t('references'), 'finding-detail'); cited.forEach((source, index) => { if (index) p.append(document.createTextNode(' · ')); const url = validUrl(source.url); const link = make(url ? 'a' : 'span', source.title); if (url) { link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer'; } p.append(link); }); card.append(p); }
      $('findings').append(card);
    }
    $('questions').replaceChildren(); $('questions-panel').hidden = !questionList.length;
    $('print-questions').replaceChildren();
    if (questionList.length) {
      $('print-questions').append(make('h3', t('unanswered')));
      const list = make('ul');
      questionList.forEach(q => list.append(make('li', (q.critical ? t('criticalInfo') + ': ' : '') + q.text + (q.findingIds.length ? ' · ' + t('observations', { ids: q.findingIds.join(', ') }) : '') + (q.why ? ' — ' + q.why : ''))));
      $('print-questions').append(list);
    }
    let furtherQuestions = null;
    const secondaryCount = questionList.length - decisiveCount;
    if (secondaryCount > 3) {
      furtherQuestions = make('details', null, 'further-questions');
      furtherQuestions.append(make('summary', t('moreQuestions', { count: secondaryCount - 3 })));
    }
    questionList.forEach((q, index) => {
      const wrapper = make('div', null, 'question'); if (q.critical) wrapper.append(make('span', t('criticalInfo'), 'critical-label'));
      if (q.findingIds.length) wrapper.append(make('p', t('observations', { ids: q.findingIds.join(', ') }), 'question-related'));
      const id = 'answer-' + index, label = make('label', q.text); label.htmlFor = id; const input = make('textarea'); input.id = id; input.rows = 2; input.maxLength = 1500; input.dataset.question = q.text; input.value = state.answers.get(q.text) || '';
      if (q.why) { const why = make('p', q.why, 'why'); why.id = id + '-why'; input.setAttribute('aria-describedby', why.id); wrapper.append(label, why, input); } else wrapper.append(label, input);
      if (q.critical || index < decisiveCount + 3) $('questions').append(wrapper); else furtherQuestions.append(wrapper);
    });
    if (furtherQuestions) $('questions').append(furtherQuestions);
    $('limitations').replaceChildren();
    if (Array.isArray(analysis.limitations) && analysis.limitations.length) { $('limitations').append(make('h3', t('remaining'))); const list = make('ul'); analysis.limitations.forEach(item => list.append(make('li', item))); $('limitations').append(list); }
    $('sources').replaceChildren(); $('sources').append(make('h3', t('sources')));
    if (analysis.sources?.length) {
      $('sources').append(make('p', t('sourceContext'), 'source-context'));
      const list = make('ul', null, 'source-list');
      const classifications = { obligation: 'sourceObligation', recommendation: 'sourceRecommendation', hypothesis: 'sourceHypothesis' };
      analysis.sources.forEach(source => {
        const li = make('li', null, 'source-item');
        const url = validUrl(source.url), link = make(url ? 'a' : 'span', source.title);
        if (url) { link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer'; }
        li.append(link, make('p', t(Object.hasOwn(classifications, source.classification) ? classifications[source.classification] : 'sourceUnclassified'), 'source-classification'));
        if (typeof source.verified_at === 'string' && source.verified_at) li.append(make('p', t('verified', { date: source.verified_at }), 'source-metadata'));
        [['locator', 'sourceLocator'], ['scope', 'sourceScope'], ['document_version', 'sourceVersion'], ['registry_version', 'sourceRegistry']].forEach(([field, key]) => {
          if (typeof source[field] === 'string' && source[field].trim()) li.append(make('p', t(key, { value: source[field] }), 'source-metadata'));
        });
        const limits = Array.isArray(source.limitations) ? source.limitations.filter(value => typeof value === 'string' && value.trim()) : [];
        if (limits.length) {
          li.append(make('p', t('sourceLimits'), 'source-limits-label'));
          const items = make('ul'); limits.forEach(value => items.append(make('li', value))); li.append(items);
        }
        list.append(li);
      });
      $('sources').append(list);
    } else $('sources').append(make('p', t('noSources')));
    const parts = [];
    if (meta.method_version || meta.prompt_version) parts.push(t('method', { value: meta.method_version || meta.prompt_version })); if (meta.model) parts.push(t('model', { value: meta.model })); if (meta.created_at) parts.push(t('analysisMeta', { value: meta.created_at }));
    $('analysis-meta').textContent = parts.join(' · ');
    ['summary', 'assessment-state', 'case-summary', 'video-analysis-details', 'question-summary', 'findings', 'questions', 'print-questions', 'limitations', 'sources', 'analysis-meta'].forEach(id => {
      const target = document.getElementById(id), content = $(id);
      target.replaceChildren(...content.childNodes); target.className = content.className;
    });
    document.getElementById('video-analysis-details').hidden = $('video-analysis-details').hidden;
    document.getElementById('video-analysis-details').setAttribute('aria-label', t('syntheticHistory'));
    document.getElementById('questions-panel').hidden = $('questions-panel').hidden;
    document.getElementById('question-summary').hidden = $('question-summary').hidden;
  }
  $('export-json').addEventListener('click', () => {
    if (!state.analysis) return;
    const data = { exported_at: new Date().toISOString(), photograph_included: false, context: state.submittedContext, analysis: state.analysis };
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
    const link = make('a'); link.href = url; link.download = 'SLPS_AI_analisi_' + new Date().toISOString().slice(0, 10) + '.json'; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    notice(t('exported'));
  });
  $('print-report').addEventListener('click', async () => {
    const analysis = state.analysis; if (!analysis || state.busy) return;
    const photo = $('case-summary').querySelector('img');
    if (photo) {
      try { await photo.decode(); }
      catch { notice(t('printPhotoNotReady'), 'error'); return; }
    }
    if (state.analysis !== analysis || state.busy) return;
    $('details-panel').open = true; window.print();
  });
  async function applyLocale({ rerender = true } = {}) {
    if (document.documentElement) document.documentElement.lang = state.language;
    document.title = { it: 'SLPS AI · Spazio di lavoro', de: 'SLPS AI · Arbeitsbereich', fr: 'SLPS AI · Espace de travail', en: 'SLPS AI · Workspace' }[state.language];
    $('app-language').value = state.language;
    $('workspace-nav').setAttribute('aria-label', t('workspaceNav'));
    localizeStatic(); syncWorkspace(); updateButton();
    if (rerender) {
      if (state.historyLoaded) renderCaseList(state.historyCases);
      if (state.videoInspection) renderVideoInspection(state.videoInspection);
      if (state.analysis) await renderAnalysis(state.analysis, state.submittedContext, { archived: Boolean(state.openedCaseId) });
    }
  }
  $('app-language').addEventListener('change', async event => {
    const next = event.target.value;
    if (!localeCodes.includes(next) || next === state.language) return;
    if (state.analysis) $('questions').querySelectorAll('textarea').forEach(input => { const answer = input.value.trim(); if (answer) state.answers.set(input.dataset.question, answer); });
    state.language = next;
    try { window.localStorage?.setItem('slps.locale', next); } catch { /* Locale persistence is optional. */ }
    await applyLocale();
  });
  applyLocale({ rerender: false });
  api('/api/session').then(applySession).catch(err => { $('login-panel').hidden = false; notice(localizedError(err), 'error'); });
})();
