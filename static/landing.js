'use strict';
(function (root, factory) {
  const landingUI = factory();
  if (typeof module === 'object' && module.exports) module.exports = landingUI;
  if (root.document) {
    const start = () => landingUI.createController(root.document, root).start();
    if (root.document.readyState === 'loading') root.document.addEventListener('DOMContentLoaded', start, { once: true });
    else start();
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  const storageKey = 'slps.locale';
  const locales = ['it', 'de', 'fr', 'en'];
  const dictionaries = {
    it: {
      pageTitle: 'SLPS AI · Dalla foto, alle azioni.', description: 'SLPS AI affianca la verifica della sicurezza sul lavoro con foto, contesto e azioni. I video brevi sono ancora una verifica tecnica, non un’analisi AI dei rischi.',
      skip: 'Vai al contenuto', homeLabel: 'SLPS AI, pagina iniziale', brandTag: 'Sicurezza sul lavoro · Svizzera', navLabel: 'Navigazione principale', navHow: 'Come funziona', navResults: 'Cosa ricevi', language: 'Lingua', openApp: 'Apri l’app',
      pilotStatus: 'Progetto in collaudo riservato', heroEyebrow: 'Un supporto alla valutazione sul posto', heroLine1: 'Dalla foto,', heroLine2: 'alle', heroAccent: 'azioni.', heroDescription: 'Osserva una situazione di lavoro. Aggiungi ciò che la foto non racconta. Metti a fuoco le azioni da verificare sul posto.', mediaNote: 'Sono accettati anche brevi video con audio per una verifica tecnica di formato, fotogrammi e traccia audio. Non è ancora un’analisi AI dei rischi del video.', discover: 'Scopri il percorso',
      accountAccess: 'Accesso con account personale e azienda verificata.', createAccount: 'Crea il tuo account aziendale →', signInAccount: 'Accedi al tuo account →', pilotAccess: 'Accesso con la password del pilota.',
      visualTop: 'DAL DETTAGLIO ALLA DECISIONE', photoTitle: 'La foto', photoCopy: 'Quello che si vede.', contextTitle: 'Il contesto', contextCopy: 'Quello che sai.', actionsTitle: 'Le azioni', actionsCopy: 'Da verificare sul posto.', visualCaption: 'Schema del percorso', visualFormula: 'Foto + contesto + verifica',
      principle1: 'Una foto è un punto di partenza.', principle2: 'Il contesto fa la differenza.', principleCopy: 'SLPS AI aiuta a organizzare osservazioni, misure proposte e domande aperte. La valutazione va completata rispetto alle condizioni effettive di lavoro.',
      howEyebrow: 'Come funziona', howTitle1: 'Tre passi.', howTitle2: 'Una situazione concreta.', howIntro: 'Parti da ciò che hai davanti e costruisci una base per la verifica, un’informazione alla volta.',
      step1Title: 'Carica una foto', step1Copy: 'Scegli una fotografia della situazione di lavoro da esaminare.', step1Detail: 'JPG, PNG o WebP · massimo 10 MB', step2Title: 'Aggiungi il contesto', step2Copy: 'Descrivi l’attività, le attrezzature e le condizioni che non si vedono nell’inquadratura.', step2Detail: 'Le informazioni che conosci contano.', step3Title: 'Verifica le azioni', step3Copy: 'Esamina le misure proposte e rispondi alle domande utili a completare la valutazione.', step3Detail: 'Conferma le condizioni sul posto.',
      resultsEyebrow: 'Cosa ricevi', resultsTitle1: 'Un punto di partenza', resultsTitle2: 'per agire con criterio.', resultsIntro: 'Il risultato mette in ordine ciò che emerge dalla foto e dal contesto, lasciando visibili i punti da chiarire.', newAnalysis: 'Nuova analisi', outcome1Title: 'Osservazioni da esaminare', outcome1Copy: 'Elementi rilevati, informazioni fornite e limiti della valutazione.', outcome2Title: 'Misure e tempi proposti', outcome2Copy: 'Azioni operative da valutare rispetto all’attività e alle condizioni reali.', outcome3Title: 'Domande per fare chiarezza', outcome3Copy: 'Informazioni mancanti che possono cambiare la valutazione.', outcome4Title: 'Uno storico riservato', outcome4Copy: 'Gli account abilitati possono riaprire i propri casi conservati. Esportazione e condivisione dipendono dalle condizioni di accesso.',
      closingTitle1: 'Parti dalla', closingTitle2: 'situazione reale.', closingCopy: 'Apri l’accesso riservato e prepara la tua prima analisi quando il tuo account o il pilota sono abilitati.', closingNote: 'Le misure proposte richiedono verifica sul posto. Una foto non rappresenta tutte le condizioni di lavoro.', footerClaim: 'Osservare con precisione. Agire con criterio.', footerStatus: 'Collaudo riservato'
    },
    de: {
      pageTitle: 'SLPS AI · Vom Foto zu den Massnahmen.', description: 'SLPS AI unterstützt die Überprüfung der Arbeitssicherheit mit Foto, Kontext und Massnahmen. Kurze Videos werden derzeit nur technisch geprüft, nicht durch eine KI-Gefährdungsanalyse.',
      skip: 'Zum Inhalt', homeLabel: 'SLPS AI, Startseite', brandTag: 'Arbeitssicherheit · Schweiz', navLabel: 'Hauptnavigation', navHow: 'So funktioniert es', navResults: 'Das Ergebnis', language: 'Sprache', openApp: 'App öffnen',
      pilotStatus: 'Geschütztes Testprojekt', heroEyebrow: 'Unterstützung für die Prüfung vor Ort', heroLine1: 'Vom Foto', heroLine2: 'zu den', heroAccent: 'Massnahmen.', heroDescription: 'Betrachten Sie eine Arbeitssituation. Ergänzen Sie, was das Foto nicht zeigt. Klären Sie die Massnahmen, die vor Ort zu prüfen sind.', mediaNote: 'Kurze Videos mit Ton werden für eine technische Prüfung von Format, Einzelbildern und Tonspur angenommen. Eine KI-Gefährdungsanalyse des Videos findet noch nicht statt.', discover: 'Ablauf ansehen',
      accountAccess: 'Zugang mit persönlichem Konto und geprüftem Unternehmen.', createAccount: 'Unternehmenskonto erstellen →', signInAccount: 'Beim Konto anmelden →', pilotAccess: 'Zugang mit dem Pilotpasswort.',
      visualTop: 'VOM DETAIL ZUR ENTSCHEIDUNG', photoTitle: 'Das Foto', photoCopy: 'Was sichtbar ist.', contextTitle: 'Der Kontext', contextCopy: 'Was Sie wissen.', actionsTitle: 'Die Massnahmen', actionsCopy: 'Vor Ort zu prüfen.', visualCaption: 'Ablaufübersicht', visualFormula: 'Foto + Kontext + Prüfung',
      principle1: 'Ein Foto ist ein Ausgangspunkt.', principle2: 'Der Kontext macht den Unterschied.', principleCopy: 'SLPS AI ordnet Beobachtungen, vorgeschlagene Massnahmen und offene Fragen. Die Beurteilung muss anhand der tatsächlichen Arbeitsbedingungen vervollständigt werden.',
      howEyebrow: 'So funktioniert es', howTitle1: 'Drei Schritte.', howTitle2: 'Eine konkrete Situation.', howIntro: 'Beginnen Sie mit dem, was vor Ihnen liegt, und schaffen Sie Information für Information eine Grundlage für die Prüfung.',
      step1Title: 'Foto hochladen', step1Copy: 'Wählen Sie ein Foto der zu untersuchenden Arbeitssituation.', step1Detail: 'JPG, PNG oder WebP · höchstens 10 MB', step2Title: 'Kontext ergänzen', step2Copy: 'Beschreiben Sie Tätigkeit, Arbeitsmittel und Bedingungen, die im Bild nicht sichtbar sind.', step2Detail: 'Ihr Wissen über die Situation zählt.', step3Title: 'Massnahmen prüfen', step3Copy: 'Prüfen Sie die vorgeschlagenen Massnahmen und beantworten Sie die Fragen zur Vervollständigung der Beurteilung.', step3Detail: 'Bestätigen Sie die Bedingungen vor Ort.',
      resultsEyebrow: 'Das Ergebnis', resultsTitle1: 'Ein Ausgangspunkt', resultsTitle2: 'für überlegtes Handeln.', resultsIntro: 'Das Ergebnis ordnet die Angaben aus Foto und Kontext und hält offene Punkte sichtbar.', newAnalysis: 'Neue Analyse', outcome1Title: 'Zu prüfende Beobachtungen', outcome1Copy: 'Erkannte Elemente, bereitgestellte Angaben und Grenzen der Beurteilung.', outcome2Title: 'Vorgeschlagene Massnahmen und Fristen', outcome2Copy: 'Operative Schritte, die anhand von Tätigkeit und tatsächlichen Bedingungen zu prüfen sind.', outcome3Title: 'Fragen zur Klärung', outcome3Copy: 'Fehlende Angaben, die die Beurteilung verändern können.', outcome4Title: 'Geschützter Verlauf', outcome4Copy: 'Freigeschaltete Konten können ihre gespeicherten Fälle erneut öffnen. Export und Freigabe hängen von den Zugangsbedingungen ab.',
      closingTitle1: 'Beginnen Sie mit der', closingTitle2: 'realen Situation.', closingCopy: 'Öffnen Sie den geschützten Zugang und bereiten Sie Ihre erste Analyse vor, sobald Konto oder Pilot freigeschaltet sind.', closingNote: 'Vorgeschlagene Massnahmen müssen vor Ort geprüft werden. Ein Foto bildet nicht alle Arbeitsbedingungen ab.', footerClaim: 'Genau beobachten. Überlegt handeln.', footerStatus: 'Geschützter Test'
    },
    fr: {
      pageTitle: 'SLPS AI · De la photo aux actions.', description: 'SLPS AI accompagne la vérification de la sécurité au travail à partir d’une photo, du contexte et d’actions. Les courtes vidéos font encore l’objet d’un contrôle technique, pas d’une analyse IA des risques.',
      skip: 'Aller au contenu', homeLabel: 'SLPS AI, page d’accueil', brandTag: 'Sécurité au travail · Suisse', navLabel: 'Navigation principale', navHow: 'Fonctionnement', navResults: 'Résultat', language: 'Langue', openApp: 'Ouvrir l’app',
      pilotStatus: 'Projet en test privé', heroEyebrow: 'Un appui à la vérification sur place', heroLine1: 'De la photo', heroLine2: 'aux', heroAccent: 'actions.', heroDescription: 'Observez une situation de travail. Ajoutez ce que la photo ne montre pas. Précisez les actions à vérifier sur place.', mediaNote: 'Les courtes vidéos avec audio sont aussi acceptées pour un contrôle technique du format, des images et de la piste sonore. Il ne s’agit pas encore d’une analyse IA des risques de la vidéo.', discover: 'Découvrir le parcours',
      accountAccess: 'Accès avec un compte personnel et une entreprise vérifiée.', createAccount: 'Créer le compte de l’entreprise →', signInAccount: 'Se connecter au compte →', pilotAccess: 'Accès avec le mot de passe du pilote.',
      visualTop: 'DU DÉTAIL À LA DÉCISION', photoTitle: 'La photo', photoCopy: 'Ce qui est visible.', contextTitle: 'Le contexte', contextCopy: 'Ce que vous savez.', actionsTitle: 'Les actions', actionsCopy: 'À vérifier sur place.', visualCaption: 'Schéma du parcours', visualFormula: 'Photo + contexte + vérification',
      principle1: 'Une photo est un point de départ.', principle2: 'Le contexte fait la différence.', principleCopy: 'SLPS AI aide à organiser les observations, les mesures proposées et les questions ouvertes. L’évaluation doit être complétée selon les conditions de travail réelles.',
      howEyebrow: 'Fonctionnement', howTitle1: 'Trois étapes.', howTitle2: 'Une situation concrète.', howIntro: 'Partez de ce que vous avez devant vous et construisez une base de vérification, information après information.',
      step1Title: 'Charger une photo', step1Copy: 'Choisissez une photo de la situation de travail à examiner.', step1Detail: 'JPG, PNG ou WebP · 10 Mo au maximum', step2Title: 'Ajouter le contexte', step2Copy: 'Décrivez l’activité, les équipements et les conditions qui ne sont pas visibles dans l’image.', step2Detail: 'Les informations que vous connaissez comptent.', step3Title: 'Vérifier les actions', step3Copy: 'Examinez les mesures proposées et répondez aux questions utiles pour compléter l’évaluation.', step3Detail: 'Confirmez les conditions sur place.',
      resultsEyebrow: 'Résultat', resultsTitle1: 'Un point de départ', resultsTitle2: 'pour agir avec discernement.', resultsIntro: 'Le résultat organise ce qui ressort de la photo et du contexte tout en laissant visibles les points à clarifier.', newAnalysis: 'Nouvelle analyse', outcome1Title: 'Observations à examiner', outcome1Copy: 'Éléments relevés, informations fournies et limites de l’évaluation.', outcome2Title: 'Mesures et délais proposés', outcome2Copy: 'Actions opérationnelles à examiner selon l’activité et les conditions réelles.', outcome3Title: 'Questions à clarifier', outcome3Copy: 'Informations manquantes susceptibles de modifier l’évaluation.', outcome4Title: 'Historique privé', outcome4Copy: 'Les comptes autorisés peuvent rouvrir leurs dossiers conservés. L’exportation et le partage dépendent des conditions d’accès.',
      closingTitle1: 'Partez de la', closingTitle2: 'situation réelle.', closingCopy: 'Ouvrez l’accès privé et préparez votre première analyse lorsque votre compte ou le pilote est autorisé.', closingNote: 'Les mesures proposées doivent être vérifiées sur place. Une photo ne représente pas toutes les conditions de travail.', footerClaim: 'Observer avec précision. Agir avec discernement.', footerStatus: 'Test privé'
    },
    en: {
      pageTitle: 'SLPS AI · From photo to action.', description: 'SLPS AI supports workplace-safety checks with a photo, context and actions. Short videos currently receive a technical check, not an AI risk analysis.',
      skip: 'Skip to content', homeLabel: 'SLPS AI, home page', brandTag: 'Workplace safety · Switzerland', navLabel: 'Main navigation', navHow: 'How it works', navResults: 'What you receive', language: 'Language', openApp: 'Open the app',
      pilotStatus: 'Private testing project', heroEyebrow: 'Support for on-site assessment', heroLine1: 'From photo', heroLine2: 'to', heroAccent: 'action.', heroDescription: 'Observe a work situation. Add what the photograph cannot show. Focus on the actions that need checking on site.', mediaNote: 'Short videos with audio are also accepted for a technical check of format, frames and audio track. This is not yet an AI video risk analysis.', discover: 'See the journey',
      accountAccess: 'Access requires a personal account and a verified company.', createAccount: 'Create your company account →', signInAccount: 'Sign in to your account →', pilotAccess: 'Access with the pilot password.',
      visualTop: 'FROM DETAIL TO DECISION', photoTitle: 'The photo', photoCopy: 'What is visible.', contextTitle: 'The context', contextCopy: 'What you know.', actionsTitle: 'The actions', actionsCopy: 'To check on site.', visualCaption: 'Journey overview', visualFormula: 'Photo + context + verification',
      principle1: 'A photo is a starting point.', principle2: 'Context makes the difference.', principleCopy: 'SLPS AI helps organise observations, proposed measures and open questions. The assessment must be completed against the actual working conditions.',
      howEyebrow: 'How it works', howTitle1: 'Three steps.', howTitle2: 'One real situation.', howIntro: 'Start with what is in front of you and build a basis for verification, one piece of information at a time.',
      step1Title: 'Upload a photo', step1Copy: 'Choose a photograph of the work situation you want to examine.', step1Detail: 'JPG, PNG or WebP · up to 10 MB', step2Title: 'Add context', step2Copy: 'Describe the task, equipment and conditions that are not visible in the image.', step2Detail: 'What you know about the situation matters.', step3Title: 'Check the actions', step3Copy: 'Review the proposed measures and answer the questions that help complete the assessment.', step3Detail: 'Confirm the conditions on site.',
      resultsEyebrow: 'What you receive', resultsTitle1: 'A starting point', resultsTitle2: 'for informed action.', resultsIntro: 'The result organises what emerges from the photo and context while keeping points that need clarification visible.', newAnalysis: 'New analysis', outcome1Title: 'Observations to examine', outcome1Copy: 'Detected elements, information supplied and limits of the assessment.', outcome2Title: 'Proposed measures and timing', outcome2Copy: 'Operational actions to check against the task and actual conditions.', outcome3Title: 'Questions for clarity', outcome3Copy: 'Missing information that could change the assessment.', outcome4Title: 'Private history', outcome4Copy: 'Enabled accounts can reopen their stored cases. Export and sharing depend on access conditions.',
      closingTitle1: 'Start with the', closingTitle2: 'real situation.', closingCopy: 'Open private access and prepare your first analysis when your account or pilot access is enabled.', closingNote: 'Proposed measures require on-site verification. A photo does not represent every working condition.', footerClaim: 'Observe precisely. Act with judgement.', footerStatus: 'Private testing'
    }
  };

  function createController(document, window) {
    const stored = (() => { try { return window.localStorage.getItem(storageKey); } catch (_) { return null; } })();
    const browser = String((window.navigator && window.navigator.language) || '').slice(0, 2).toLowerCase();
    let language = locales.includes(stored) ? stored : locales.includes(browser) ? browser : 'it';
    const text = key => dictionaries[language][key] || dictionaries.it[key] || key;

    function apply() {
      document.documentElement.lang = language;
      document.title = text('pageTitle');
      const meta = document.querySelector('meta[name="description"]');
      if (meta) meta.setAttribute('content', text('description'));
      document.querySelectorAll('[data-i18n]').forEach(element => {
        element.textContent = text(element.getAttribute('data-i18n'));
      });
      document.querySelectorAll('[data-i18n-aria]').forEach(element => {
        element.setAttribute('aria-label', text(element.getAttribute('data-i18n-aria')));
      });
      const select = document.getElementById('site-language');
      if (select) select.value = language;
    }

    function change(next) {
      if (!locales.includes(next)) return;
      language = next;
      try { window.localStorage.setItem(storageKey, language); } catch (_) { /* Locale is optional. */ }
      apply();
    }

    function start() {
      const select = document.getElementById('site-language');
      if (select) select.addEventListener('change', event => change(event.target.value));
      apply();
    }
    return { start, change, getLanguage: () => language };
  }

  return { createController, dictionaries, locales, storageKey };
});
