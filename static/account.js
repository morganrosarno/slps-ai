'use strict';
(function (root, factory) {
  const accountUI = factory();
  if (typeof module === 'object' && module.exports) module.exports = accountUI;
  if (root.document) root.document.addEventListener('DOMContentLoaded', () => {
    accountUI.createController(root.document, root, root.fetch.bind(root)).start();
  });
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  const dictionaries = {
    it: {
      pageTitle: 'SLPS AI · Account aziendale', skip: 'Vai al contenuto', language: 'Lingua', pilot: 'Pilota riservato · Svizzera',
      introTitle: 'Il tuo account.\nLa tua azienda.', introCopy: 'Uno spazio riservato per collegare persone, azienda e analisi.',
      stepAccount: 'Crea il tuo account', stepAccountCopy: 'Credenziali personali, accesso riservato.', stepCompany: "Verifica l'azienda", stepCompanyCopy: 'Email e autorizzazione aziendale sono controlli distinti.', stepWorkspace: 'Apri lo spazio di lavoro', stepWorkspaceCopy: 'La prova si abilita soltanto dopo le verifiche.', privateNote: "La registrazione non avvia un'analisi e non invia fotografie.",
      loading: "Caricamento dell'accesso…", privateAccess: 'Accesso riservato', unavailableTitle: 'Account non ancora disponibili', unavailableCopy: "Questa installazione utilizza ancora l'accesso del pilota. La registrazione aziendale non è attiva.", pilotAccess: "Apri l'accesso al pilota", registerTab: 'Crea account', loginTab: 'Accedi',
      registerTitle: 'Inizia dalla tua azienda.', registerCopy: "Inserisci i tuoi dati. L'accesso alle analisi rimane in attesa delle verifiche.", loginTitle: 'Bentornato nel tuo account.', loginCopy: "Accedi con le tue credenziali personali. L'azienda e la tua autorizzazione vengono controllate separatamente.", registrationClosed: 'Le nuove registrazioni sono chiuse in questa installazione. Puoi accedere con un account già creato.',
      companyName: 'Ragione sociale', companyIdentifier: 'Identificativo aziendale, se disponibile', identifierNote: "Ad esempio il numero IDE/CHE. Il solo inserimento non verifica l'azienda.", role: 'Il tuo ruolo', roleOwner: 'Titolare o rappresentante', roleEmployee: 'Collaboratore', roleConsultant: 'Consulente esterno', roleNote: "Il ruolo dichiarato non sostituisce la verifica dell'autorizzazione.", email: 'Email personale di lavoro', newPassword: 'Crea una password', password: 'Password', passwordNote: 'Almeno 16 caratteri. Non condividerla con altri.', registerSubmit: "Crea l'account aziendale", loginSubmit: 'Accedi al tuo account', recoveryNote: 'Il recupero via email non è ancora disponibile in questo pilota. Non inviare la password a nessuno.',
      yourAccount: 'Il tuo account aziendale', logout: 'Esci', pendingTitle: 'Completiamo le verifiche.', readyTitle: 'Il tuo accesso è abilitato.', emailCheck: 'Email personale', companyCheck: "Identità dell'azienda", membershipCheck: "Autorizzazione all'azienda", pendingNote: "Le analisi e l'archivio rimangono bloccati fino al completamento di tutti i controlli.", deliveryNote: "Pilota locale: l'invio delle email di conferma non è configurato. Nessuna email è stata inviata da questa schermata; la conferma email e la verifica aziendale devono essere completate tramite una procedura abilitata.", openWorkspace: 'Apri lo spazio di lavoro', refresh: 'Aggiorna stato', backHome: '← Torna al sito', footer: 'Sicurezza sul lavoro · Svizzera',
      verified: 'Verificata', pending: 'In attesa di verifica', membershipVerified: 'Autorizzazione verificata', membershipPending: "Autorizzazione da verificare; il ruolo dichiarato non basta.", registering: "Creazione dell'account…", loggingIn: 'Accesso in corso…', refreshing: 'Aggiornamento…', loggingOut: 'Uscita in corso…', created: "Account creato, verifiche in attesa. Nessuna email di conferma è stata inviata: l'invio non è configurato nel pilota. Ora puoi accedere per consultare lo stato.", statusUpdated: 'Stato aggiornato.', loggedOut: 'Hai effettuato la disconnessione.',
      errorGeneric: "Operazione non riuscita. Riprova; nessuna analisi è stata avviata.", errorNetwork: 'Impossibile raggiungere il servizio. Controlla la connessione e riprova.', errorCredentials: 'Email o password non valide.', errorCsrf: 'Sessione scaduta. Ricarica la pagina e riprova.', errorRate: 'Troppi tentativi. Attendi prima di riprovare.', errorDuplicate: "Non è possibile creare un account con questi dati. Se hai già un account, accedi.", errorInvalid: 'Controlla i dati inseriti e i requisiti della password.', errorClosed: 'Le nuove registrazioni sono chiuse.', errorSession: 'La sessione non è più valida. Accedi di nuovo.', errorConfiguration: "L'accesso non è ancora configurato in questa installazione."
    },
    de: {
      pageTitle: 'SLPS AI · Unternehmenskonto', skip: 'Zum Inhalt', language: 'Sprache', pilot: 'Geschützter Pilot · Schweiz',
      introTitle: 'Ihr Konto.\nIhr Unternehmen.', introCopy: 'Ein geschützter Bereich für Personen, Unternehmen und Analysen.',
      stepAccount: 'Konto erstellen', stepAccountCopy: 'Persönliche Zugangsdaten, geschützter Zugriff.', stepCompany: 'Unternehmen prüfen', stepCompanyCopy: 'E-Mail und Unternehmensberechtigung werden getrennt geprüft.', stepWorkspace: 'Arbeitsbereich öffnen', stepWorkspaceCopy: 'Der Test wird erst nach den Prüfungen freigeschaltet.', privateNote: 'Die Registrierung startet keine Analyse und sendet keine Fotos.',
      loading: 'Zugang wird geladen…', privateAccess: 'Geschützter Zugang', unavailableTitle: 'Konten noch nicht verfügbar', unavailableCopy: 'Diese Installation verwendet noch den Pilotzugang. Die Unternehmensregistrierung ist nicht aktiv.', pilotAccess: 'Pilotzugang öffnen', registerTab: 'Konto erstellen', loginTab: 'Anmelden',
      registerTitle: 'Beginnen Sie mit Ihrem Unternehmen.', registerCopy: 'Geben Sie Ihre Daten ein. Analysen bleiben bis zum Abschluss der Prüfungen gesperrt.', loginTitle: 'Willkommen zurück.', loginCopy: 'Melden Sie sich mit Ihren persönlichen Zugangsdaten an. Unternehmen und Berechtigung werden getrennt geprüft.', registrationClosed: 'Neue Registrierungen sind in dieser Installation geschlossen. Bestehende Konten können sich anmelden.',
      companyName: 'Unternehmensname', companyIdentifier: 'Unternehmenskennung, falls vorhanden', identifierNote: 'Zum Beispiel die UID/CHE-Nummer. Die Angabe allein bestätigt das Unternehmen nicht.', role: 'Ihre Rolle', roleOwner: 'Inhaber oder Vertretung', roleEmployee: 'Mitarbeitende Person', roleConsultant: 'Externe Beratung', roleNote: 'Die angegebene Rolle ersetzt keine Berechtigungsprüfung.', email: 'Persönliche geschäftliche E-Mail', newPassword: 'Passwort erstellen', password: 'Passwort', passwordNote: 'Mindestens 16 Zeichen. Geben Sie es nicht weiter.', registerSubmit: 'Unternehmenskonto erstellen', loginSubmit: 'Beim Konto anmelden', recoveryNote: 'Die Wiederherstellung per E-Mail ist in diesem Piloten noch nicht verfügbar. Senden Sie Ihr Passwort an niemanden.',
      yourAccount: 'Ihr Unternehmenskonto', logout: 'Abmelden', pendingTitle: 'Prüfungen noch offen.', readyTitle: 'Ihr Zugang ist freigeschaltet.', emailCheck: 'Persönliche E-Mail', companyCheck: 'Identität des Unternehmens', membershipCheck: 'Unternehmensberechtigung', pendingNote: 'Analysen und Archiv bleiben gesperrt, bis alle Prüfungen abgeschlossen sind.', deliveryNote: 'Lokaler Pilot: Der Versand von Bestätigungs-E-Mails ist nicht eingerichtet. Über diese Seite wurde keine E-Mail gesendet. E-Mail und Unternehmen müssen über ein freigeschaltetes Verfahren geprüft werden.', openWorkspace: 'Arbeitsbereich öffnen', refresh: 'Status aktualisieren', backHome: '← Zur Website', footer: 'Arbeitssicherheit · Schweiz',
      verified: 'Geprüft', pending: 'Prüfung ausstehend', membershipVerified: 'Berechtigung geprüft', membershipPending: 'Berechtigung noch zu prüfen; die angegebene Rolle allein genügt nicht.', registering: 'Konto wird erstellt…', loggingIn: 'Anmeldung läuft…', refreshing: 'Wird aktualisiert…', loggingOut: 'Abmeldung läuft…', created: 'Konto erstellt, Prüfungen ausstehend. Es wurde keine Bestätigungs-E-Mail gesendet: Der Versand ist im Piloten nicht eingerichtet. Melden Sie sich an, um den Status zu sehen.', statusUpdated: 'Status aktualisiert.', loggedOut: 'Sie wurden abgemeldet.',
      errorGeneric: 'Vorgang fehlgeschlagen. Versuchen Sie es erneut; keine Analyse wurde gestartet.', errorNetwork: 'Der Dienst ist nicht erreichbar. Prüfen Sie die Verbindung und versuchen Sie es erneut.', errorCredentials: 'E-Mail oder Passwort ungültig.', errorCsrf: 'Sitzung abgelaufen. Laden Sie die Seite neu und versuchen Sie es erneut.', errorRate: 'Zu viele Versuche. Warten Sie, bevor Sie es erneut versuchen.', errorDuplicate: 'Mit diesen Angaben kann kein Konto erstellt werden. Wenn Sie bereits ein Konto haben, melden Sie sich an.', errorInvalid: 'Prüfen Sie die Angaben und die Passwortanforderungen.', errorClosed: 'Neue Registrierungen sind geschlossen.', errorSession: 'Die Sitzung ist nicht mehr gültig. Melden Sie sich erneut an.', errorConfiguration: 'Der Zugang ist in dieser Installation noch nicht eingerichtet.'
    },
    fr: {
      pageTitle: 'SLPS AI · Compte entreprise', skip: 'Aller au contenu', language: 'Langue', pilot: 'Pilote privé · Suisse',
      introTitle: 'Votre compte.\nVotre entreprise.', introCopy: 'Un espace privé reliant personnes, entreprise et analyses.',
      stepAccount: 'Créer votre compte', stepAccountCopy: 'Identifiants personnels, accès privé.', stepCompany: "Vérifier l'entreprise", stepCompanyCopy: "L'email et l'autorisation dans l'entreprise sont vérifiés séparément.", stepWorkspace: "Ouvrir l'espace de travail", stepWorkspaceCopy: "L'essai est activé après les vérifications.", privateNote: "L'inscription ne lance aucune analyse et n'envoie aucune photo.",
      loading: "Chargement de l'accès…", privateAccess: 'Accès privé', unavailableTitle: 'Comptes pas encore disponibles', unavailableCopy: "Cette installation utilise encore l'accès pilote. L'inscription des entreprises n'est pas active.", pilotAccess: "Ouvrir l'accès pilote", registerTab: 'Créer un compte', loginTab: 'Se connecter',
      registerTitle: 'Commencez par votre entreprise.', registerCopy: "Saisissez vos informations. L'accès aux analyses reste en attente des vérifications.", loginTitle: 'Bienvenue dans votre compte.', loginCopy: "Connectez-vous avec vos identifiants personnels. L'entreprise et votre autorisation sont vérifiées séparément.", registrationClosed: 'Les nouvelles inscriptions sont fermées sur cette installation. Vous pouvez utiliser un compte existant.',
      companyName: 'Raison sociale', companyIdentifier: "Identifiant de l'entreprise, si disponible", identifierNote: "Par exemple le numéro IDE/CHE. Le saisir ne vérifie pas l'entreprise.", role: 'Votre rôle', roleOwner: 'Propriétaire ou représentant', roleEmployee: 'Collaborateur', roleConsultant: 'Consultant externe', roleNote: "Le rôle déclaré ne remplace pas la vérification de l'autorisation.", email: 'Email professionnel personnel', newPassword: 'Créer un mot de passe', password: 'Mot de passe', passwordNote: 'Au moins 16 caractères. Ne le partagez pas.', registerSubmit: 'Créer le compte entreprise', loginSubmit: 'Se connecter au compte', recoveryNote: "La récupération par email n'est pas encore disponible dans ce pilote. N'envoyez votre mot de passe à personne.",
      yourAccount: 'Votre compte entreprise', logout: 'Se déconnecter', pendingTitle: 'Vérifications à compléter.', readyTitle: 'Votre accès est activé.', emailCheck: 'Email personnel', companyCheck: "Identité de l'entreprise", membershipCheck: "Autorisation dans l'entreprise", pendingNote: "Les analyses et l'archive restent bloquées jusqu'à la fin de tous les contrôles.", deliveryNote: "Pilote local : l'envoi des emails de confirmation n'est pas configuré. Aucun email n'a été envoyé depuis cette page. L'email et l'entreprise doivent être vérifiés au moyen d'une procédure activée.", openWorkspace: "Ouvrir l'espace de travail", refresh: 'Actualiser le statut', backHome: '← Retour au site', footer: 'Sécurité au travail · Suisse',
      verified: 'Vérifié', pending: 'Vérification en attente', membershipVerified: 'Autorisation vérifiée', membershipPending: "Autorisation à vérifier ; le rôle déclaré ne suffit pas.", registering: 'Création du compte…', loggingIn: 'Connexion en cours…', refreshing: 'Actualisation…', loggingOut: 'Déconnexion…', created: "Compte créé, vérifications en attente. Aucun email de confirmation n'a été envoyé : l'envoi n'est pas configuré dans le pilote. Connectez-vous pour consulter le statut.", statusUpdated: 'Statut actualisé.', loggedOut: 'Vous êtes déconnecté.',
      errorGeneric: "Échec de l'opération. Réessayez ; aucune analyse n'a été lancée.", errorNetwork: 'Service inaccessible. Vérifiez la connexion et réessayez.', errorCredentials: 'Email ou mot de passe incorrect.', errorCsrf: 'Session expirée. Rechargez la page et réessayez.', errorRate: 'Trop de tentatives. Attendez avant de réessayer.', errorDuplicate: "Impossible de créer un compte avec ces informations. Si vous avez déjà un compte, connectez-vous.", errorInvalid: 'Vérifiez les informations et les exigences du mot de passe.', errorClosed: 'Les nouvelles inscriptions sont fermées.', errorSession: "La session n'est plus valide. Connectez-vous à nouveau.", errorConfiguration: "L'accès n'est pas encore configuré sur cette installation."
    },
    en: {
      pageTitle: 'SLPS AI · Company account', skip: 'Skip to content', language: 'Language', pilot: 'Private pilot · Switzerland',
      introTitle: 'Your account.\nYour company.', introCopy: 'A private workspace connecting people, your company and analyses.',
      stepAccount: 'Create your account', stepAccountCopy: 'Personal credentials, private access.', stepCompany: 'Verify the company', stepCompanyCopy: 'Email and company authorisation are separate checks.', stepWorkspace: 'Open the workspace', stepWorkspaceCopy: 'The trial becomes available only after verification.', privateNote: 'Registration does not start an analysis or send photographs.',
      loading: 'Loading account access…', privateAccess: 'Private access', unavailableTitle: 'Accounts are not available yet', unavailableCopy: 'This installation still uses pilot access. Company registration is not active.', pilotAccess: 'Open pilot access', registerTab: 'Create account', loginTab: 'Sign in',
      registerTitle: 'Start with your company.', registerCopy: 'Enter your details. Analysis access remains pending until verification is complete.', loginTitle: 'Welcome back to your account.', loginCopy: 'Sign in with your personal credentials. The company and your authorisation are checked separately.', registrationClosed: 'New registrations are closed on this installation. You can sign in with an existing account.',
      companyName: 'Company name', companyIdentifier: 'Company identifier, if available', identifierNote: 'For example the UID/CHE number. Entering it does not verify the company.', role: 'Your role', roleOwner: 'Owner or representative', roleEmployee: 'Employee', roleConsultant: 'External consultant', roleNote: 'The declared role does not replace an authorisation check.', email: 'Personal work email', newPassword: 'Create a password', password: 'Password', passwordNote: 'At least 16 characters. Do not share it.', registerSubmit: 'Create company account', loginSubmit: 'Sign in to your account', recoveryNote: 'Email recovery is not available in this pilot yet. Never send your password to anyone.',
      yourAccount: 'Your company account', logout: 'Sign out', pendingTitle: 'Verification is still pending.', readyTitle: 'Your access is enabled.', emailCheck: 'Personal email', companyCheck: 'Company identity', membershipCheck: 'Company authorisation', pendingNote: 'Analyses and the archive stay locked until all checks are complete.', deliveryNote: 'Local pilot: confirmation email delivery is not configured. No email has been sent from this page. Email and company verification must be completed through an enabled process.', openWorkspace: 'Open the workspace', refresh: 'Refresh status', backHome: '← Back to the website', footer: 'Workplace safety · Switzerland',
      verified: 'Verified', pending: 'Verification pending', membershipVerified: 'Authorisation verified', membershipPending: 'Authorisation needs checking; a declared role is not enough.', registering: 'Creating account…', loggingIn: 'Signing in…', refreshing: 'Refreshing…', loggingOut: 'Signing out…', created: 'Account created, verification pending. No confirmation email was sent: delivery is not configured in this pilot. You can now sign in to check the status.', statusUpdated: 'Status updated.', loggedOut: 'You have signed out.',
      errorGeneric: 'The operation failed. Try again; no analysis has been started.', errorNetwork: 'The service could not be reached. Check your connection and try again.', errorCredentials: 'Invalid email or password.', errorCsrf: 'Your session has expired. Reload the page and try again.', errorRate: 'Too many attempts. Wait before trying again.', errorDuplicate: 'An account cannot be created with these details. If you already have an account, sign in.', errorInvalid: 'Check the details and password requirements.', errorClosed: 'New registrations are closed.', errorSession: 'Your session is no longer valid. Sign in again.', errorConfiguration: 'Access is not configured on this installation yet.'
    }
  };
  const consultationTranslations = {
    it: { consultationTitle:'Contatto con uno specialista', consultationDraft:'Disponibilità sperimentale separata dalla fatturazione. Nomi, prezzi e regole commerciali non sono definitivi.', consultationLoad:'Mostra disponibilità', consultationIncluded:'Incluse', consultationReserved:'Prenotate', consultationUsed:'Utilizzate', consultationBalance:'Disponibili', consultationRenewal:'Prossimo rinnovo:', consultationCase:'Caso autorizzato', consultationChannel:'Come preferisci essere ricontattato?', consultationPhone:'Telefono', consultationWhatsapp:'WhatsApp', consultationSubmit:'Registra richiesta', consultationSafety:'La richiesta sarà gestita successivamente. Non mostra numeri privati, non effettua chiamate, non invia messaggi e non genera addebiti. Non è prevista una durata massima della chiamata.', consultationRecorded:'Richiesta registrata. Nessun messaggio o chiamata è stato inviato.', consultationNoCases:'Prima salva un’analisi nel tuo archivio.', consultationUnavailable:'Nessuna richiesta inclusa disponibile in questo periodo.', consultationCancel:'Annulla richiesta', consultationCancelled:'Richiesta annullata. La disponibilità non cambia.' },
    de: { consultationTitle:'Kontakt mit einer Fachperson', consultationDraft:'Experimentelle Verfügbarkeit, getrennt von der Abrechnung. Namen, Preise und Geschäftsregeln sind nicht endgültig.', consultationLoad:'Verfügbarkeit anzeigen', consultationIncluded:'Enthalten', consultationReserved:'Reserviert', consultationUsed:'Genutzt', consultationBalance:'Verfügbar', consultationRenewal:'Nächste Erneuerung:', consultationCase:'Berechtigter Fall', consultationChannel:'Wie möchten Sie kontaktiert werden?', consultationPhone:'Telefon', consultationWhatsapp:'WhatsApp', consultationSubmit:'Anfrage erfassen', consultationSafety:'Die Anfrage wird später bearbeitet. Sie zeigt keine private Nummer, tätigt keinen Anruf, sendet keine Nachricht und verursacht keine Belastung. Es gibt keine maximale Gesprächsdauer.', consultationRecorded:'Anfrage erfasst. Es wurde keine Nachricht gesendet und kein Anruf getätigt.', consultationNoCases:'Speichern Sie zuerst eine Analyse in Ihrem Archiv.', consultationUnavailable:'In diesem Zeitraum ist keine enthaltene Anfrage verfügbar.', consultationCancel:'Anfrage stornieren', consultationCancelled:'Anfrage storniert. Die Verfügbarkeit ändert sich nicht.' },
    fr: { consultationTitle:'Contact avec un spécialiste', consultationDraft:'Disponibilité expérimentale distincte de la facturation. Les noms, prix et règles commerciales ne sont pas définitifs.', consultationLoad:'Afficher la disponibilité', consultationIncluded:'Incluses', consultationReserved:'Réservées', consultationUsed:'Utilisées', consultationBalance:'Disponibles', consultationRenewal:'Prochain renouvellement :', consultationCase:'Cas autorisé', consultationChannel:'Comment souhaitez-vous être recontacté ?', consultationPhone:'Téléphone', consultationWhatsapp:'WhatsApp', consultationSubmit:'Enregistrer la demande', consultationSafety:'La demande sera traitée ultérieurement. Elle n’affiche aucun numéro privé, ne passe aucun appel, n’envoie aucun message et ne génère aucun débit. Aucune durée maximale d’appel n’est prévue.', consultationRecorded:'Demande enregistrée. Aucun message ni appel n’a été envoyé.', consultationNoCases:'Enregistrez d’abord une analyse dans vos archives.', consultationUnavailable:'Aucune demande incluse n’est disponible pour cette période.', consultationCancel:'Annuler la demande', consultationCancelled:'Demande annulée. La disponibilité ne change pas.' },
    en: { consultationTitle:'Contact a specialist', consultationDraft:'Experimental availability, separate from billing. Names, prices and commercial rules are not final.', consultationLoad:'Show availability', consultationIncluded:'Included', consultationReserved:'Reserved', consultationUsed:'Used', consultationBalance:'Available', consultationRenewal:'Next renewal:', consultationCase:'Authorised case', consultationChannel:'How would you like to be contacted?', consultationPhone:'Phone', consultationWhatsapp:'WhatsApp', consultationSubmit:'Record request', consultationSafety:'The request will be handled later. It reveals no private number, makes no call, sends no message and creates no charge. There is no maximum call duration.', consultationRecorded:'Request recorded. No message or call was sent.', consultationNoCases:'First save an analysis in your archive.', consultationUnavailable:'No included request is available in this period.', consultationCancel:'Cancel request', consultationCancelled:'Request cancelled. Availability does not change.' }
  };
  Object.keys(dictionaries).forEach(language => Object.assign(dictionaries[language], consultationTranslations[language]));
  const consultationDetailTranslations = {
    it:{consultationAvailableState:'Richiesta disponibile in questo periodo.',consultationExhaustedState:'Disponibilità esaurita per questo periodo.',consultationIdempotency:'La richiesta ripetuta non corrisponde a quella già registrata. Ricarica la disponibilità.',consultationChannelPhone:'Canale: telefono',consultationChannelWhatsapp:'Canale: WhatsApp',consultationStatusReserved:'stato: prenotata',consultationStatusUsed:'stato: utilizzata',consultationStatusCancelled:'stato: annullata',consultationAuthorizedCase:'Caso autorizzato'},
    de:{consultationAvailableState:'In diesem Zeitraum ist eine Anfrage verfügbar.',consultationExhaustedState:'Die Verfügbarkeit für diesen Zeitraum ist ausgeschöpft.',consultationIdempotency:'Die wiederholte Anfrage stimmt nicht mit der bereits erfassten überein. Laden Sie die Verfügbarkeit neu.',consultationChannelPhone:'Kanal: Telefon',consultationChannelWhatsapp:'Kanal: WhatsApp',consultationStatusReserved:'Status: reserviert',consultationStatusUsed:'Status: genutzt',consultationStatusCancelled:'Status: storniert',consultationAuthorizedCase:'Berechtigter Fall'},
    fr:{consultationAvailableState:'Une demande est disponible pour cette période.',consultationExhaustedState:'La disponibilité est épuisée pour cette période.',consultationIdempotency:'La demande répétée ne correspond pas à celle déjà enregistrée. Rechargez la disponibilité.',consultationChannelPhone:'Canal : téléphone',consultationChannelWhatsapp:'Canal : WhatsApp',consultationStatusReserved:'statut : réservée',consultationStatusUsed:'statut : utilisée',consultationStatusCancelled:'statut : annulée',consultationAuthorizedCase:'Cas autorisé'},
    en:{consultationAvailableState:'A request is available in this period.',consultationExhaustedState:'Availability is exhausted for this period.',consultationIdempotency:'The repeated request does not match the one already recorded. Reload availability.',consultationChannelPhone:'Channel: phone',consultationChannelWhatsapp:'Channel: WhatsApp',consultationStatusReserved:'status: reserved',consultationStatusUsed:'status: used',consultationStatusCancelled:'status: cancelled',consultationAuthorizedCase:'Authorised case'}
  };
  Object.keys(dictionaries).forEach(language => Object.assign(dictionaries[language], consultationDetailTranslations[language]));
  const locales = Object.keys(dictionaries);
  const storageKey = 'slps.locale';
  const legacyStorageKey = 'slps.account.locale';
  function eligible(account) {
    return Boolean(account && account.eligible_for_analysis === true && account.email_verified === true && account.membership_verified === true && account.company && account.company.verified === true);
  }
  function errorKey(code, status) {
    if (code === 'invalid_csrf') return 'errorCsrf';
    if (['invalid_credentials', 'invalid_login'].includes(code)) return 'errorCredentials';
    if (code === 'authentication_required' || status === 401) return 'errorSession';
    if (status === 429) return 'errorRate';
    if (code === 'consultation_unavailable') return 'consultationUnavailable';
    if (code === 'idempotency_mismatch') return 'consultationIdempotency';
    if (['invalid_consultation', 'case_not_found'].includes(code)) return 'errorInvalid';
    if (['registration_closed', 'registration_disabled', 'accounts_disabled'].includes(code)) return 'errorClosed';
    if (['registration_unavailable', 'account_exists', 'company_exists', 'duplicate_email', 'duplicate_company', 'registration_conflict'].includes(code) || status === 409) return 'errorDuplicate';
    if (code === 'invalid_registration' || status === 400 || status === 422) return 'errorInvalid';
    if (code === 'configuration_missing') return 'errorConfiguration';
    return 'errorGeneric';
  }
  function createController(document, window, fetcher) {
    const $ = id => document.getElementById(id);
    let saved = null;
    try { saved = window.localStorage.getItem(storageKey) || window.localStorage.getItem(legacyStorageKey); } catch (_) { /* Storage is optional. */ }
    const browser = String(window.navigator && window.navigator.language || '').slice(0, 2);
    const state = { language: locales.includes(saved) ? saved : locales.includes(browser) ? browser : 'it', explicitLanguage: locales.includes(saved), view: window.location.pathname.replace(/\/$/, '') === '/register' ? 'register' : 'login', csrf: '', authenticated: false, authConfigured: false, account: null, authMode: null, registrationOpen: false, busy: false, loading: true, notice: null, consultation: null, consultationCases: [], consultationKey: null };
    const t = key => dictionaries[state.language][key] || dictionaries.it[key] || key;
    function setNotice(key, kind = '', focus = false) {
      state.notice = key ? { key, kind } : null;
      const el = $('account-notice');
      el.textContent = key ? t(key) : ''; el.className = 'notice' + (kind ? ' ' + kind : ''); el.hidden = !key;
      if (focus && key) { el.focus(); if (el.scrollIntoView) el.scrollIntoView({ block: 'nearest' }); }
    }
    function translate() {
      document.documentElement.lang = state.language;
      document.title = t('pageTitle');
      document.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = t(el.getAttribute('data-i18n')); });
      $('account-language').value = state.language;
      if (state.notice) setNotice(state.notice.key, state.notice.kind);
      render();
    }
    function setLanguage(language, explicit = true) {
      if (!locales.includes(language)) return;
      state.language = language;
      if (explicit) {
        state.explicitLanguage = true;
        try { window.localStorage.setItem(storageKey, language); } catch (_) { /* No credential data is stored. */ }
      }
      translate();
    }
    function verification(id, verified, member = false) {
      $(id).textContent = t(member ? verified ? 'membershipVerified' : 'membershipPending' : verified ? 'verified' : 'pending');
      $(id).dataset.state = verified ? 'verified' : 'pending';
    }
    function render() {
      const supported = state.authMode === 'accounts';
      $('account-loading').hidden = !state.loading;
      $('account-unavailable').hidden = state.loading || state.authMode === null || supported;
      $('account-auth').hidden = state.loading || !supported || state.authenticated;
      $('account-status').hidden = state.loading || !supported || !state.authenticated;
      $('registration-closed').hidden = state.registrationOpen;
      $('show-register').hidden = !state.registrationOpen;
      $('show-register').disabled = !state.registrationOpen || state.busy;
      $('show-login').disabled = state.busy;
      if (!state.registrationOpen && state.authMode === 'accounts') state.view = 'login';
      const registering = state.view === 'register';
      $('show-register').setAttribute('aria-current', registering ? 'page' : 'false');
      $('show-login').setAttribute('aria-current', registering ? 'false' : 'page');
      $('account-heading').textContent = t(registering ? 'registerTitle' : 'loginTitle');
      $('auth-description').textContent = t(registering ? 'registerCopy' : 'loginCopy');
      $('account-register-form').hidden = !registering || !state.registrationOpen;
      $('account-login-form').hidden = registering;
      $('account-auth').setAttribute('aria-busy', String(state.busy));
      $('account-status').setAttribute('aria-busy', String(state.busy));
      ['register-submit', 'login-submit', 'account-refresh', 'account-logout'].forEach(id => { $(id).disabled = state.busy || state.loading || !state.authConfigured; });
      $('account-refresh').disabled = state.busy || state.loading;
      $('consultation-panel').setAttribute('aria-busy', String(state.busy));
      $('consultation-load').disabled = state.busy || state.loading || !state.authenticated;
      $('consultation-submit').disabled = state.busy || !state.consultation || state.consultation.balance < 1 || state.consultationCases.length === 0;
      $('register-submit').textContent = t(state.busy && registering ? 'registering' : 'registerSubmit');
      $('login-submit').textContent = t(state.busy && !registering && !state.authenticated ? 'loggingIn' : 'loginSubmit');
      $('account-refresh').textContent = t(state.busy && state.authenticated ? 'refreshing' : 'refresh');
      if (state.authenticated) {
        const account = state.account || {}, company = account.company || {}, ready = eligible(account);
        $('account-company-name').textContent = company.name || '';
        $('account-email').textContent = account.email || '';
        $('status-heading').textContent = t(ready ? 'readyTitle' : 'pendingTitle');
        verification('email-verification', account.email_verified === true);
        verification('company-verification', company.verified === true);
        verification('membership-verification', account.membership_verified === true, true);
        $('verification-pending-note').hidden = ready;
        $('delivery-note').hidden = account.email_verified === true;
        $('account-workspace').hidden = !ready;
        $('consultation-panel').hidden = !ready;
      } else {
        $('account-company-name').textContent = ''; $('account-email').textContent = '';
        $('account-workspace').hidden = true;
        $('consultation-panel').hidden = true;
      }
    }
    function applySession(data) {
      state.csrf = typeof data.csrf === 'string' ? data.csrf : '';
      state.authConfigured = data.auth_configured !== false && Boolean(state.csrf);
      state.authMode = data.auth_mode || 'pilot';
      state.registrationOpen = data.registration_open === true;
      state.authenticated = data.authenticated === true;
      state.account = state.authenticated && data.account && typeof data.account === 'object' ? data.account : null;
      if (state.account && !state.explicitLanguage && locales.includes(state.account.locale)) state.language = state.account.locale;
      translate();
      if (state.authMode === 'accounts' && !state.authConfigured) setNotice('errorConfiguration', 'error');
    }
    async function api(url, options = {}) {
      let response;
      try { response = await fetcher(url, { credentials: 'same-origin', ...options }); }
      catch (_) { const error = new Error('network'); error.key = 'errorNetwork'; throw error; }
      let data;
      try { data = await response.json(); }
      catch (_) { const error = new Error('invalid-response'); error.key = 'errorGeneric'; throw error; }
      if (!response.ok) {
        const error = new Error('request-failed'); error.key = errorKey(data && data.error && data.error.code, response.status); error.status = response.status; throw error;
      }
      return data;
    }
    const post = (url, payload, extraHeaders = {}) => api(url, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': state.csrf, ...extraHeaders }, body: JSON.stringify(payload) });
    function consultationKey(caseId, channel) {
      if (state.consultationKey && state.consultationKey.caseId === caseId && state.consultationKey.channel === channel) return state.consultationKey.value;
      const random = window.crypto && window.crypto.getRandomValues ? Array.from(window.crypto.getRandomValues(new Uint32Array(2))).join('-') : String(Date.now()) + '-' + String(Math.random()).slice(2);
      state.consultationKey = { caseId, channel, value: 'consult-' + random };
      return state.consultationKey.value;
    }
    function renderConsultation(data) {
      const ledger = data.consultation || data;
      state.consultation = ledger; state.consultationCases = Array.isArray(data.cases) ? data.cases : state.consultationCases;
      $('consultation-content').hidden = false;
      ['included','reserved','used','balance'].forEach(key => { $('consultation-' + key).textContent = String(Number.isInteger(ledger[key]) ? ledger[key] : 0); });
      $('consultation-availability').textContent = t(ledger.balance > 0 ? 'consultationAvailableState' : 'consultationExhaustedState');
      const date = new Date(ledger.next_reset); $('consultation-next-reset').textContent = Number.isNaN(date.getTime()) ? '' : new Intl.DateTimeFormat(state.language, { dateStyle:'medium' }).format(date);
      const select = $('consultation-case');
      if (document.createElement && select.replaceChildren) {
        const options = state.consultationCases.map(item => { const option = document.createElement('option'); option.value = item.id; option.textContent = item.summary || item.id; return option; });
        select.replaceChildren(...options);
      }
      select.disabled = state.consultationCases.length === 0;
      $('consultation-submit').disabled = state.busy || ledger.balance < 1 || state.consultationCases.length === 0;
      if (state.consultationCases.length === 0) { $('consultation-result').textContent = t('consultationNoCases'); $('consultation-result').hidden = false; }
      const list = $('consultation-requests');
      if (document.createElement && list.replaceChildren) {
        const items = (ledger.requests || []).map(item => {
          const li = document.createElement('li');
          const found = state.consultationCases.find(candidate => candidate.id === item.case_id);
          const caseLabel = found && found.summary ? found.summary : t('consultationAuthorizedCase');
          const channelLabel = t(item.channel === 'whatsapp' ? 'consultationChannelWhatsapp' : 'consultationChannelPhone');
          const statusKey = item.status === 'used' ? 'consultationStatusUsed' : item.status === 'cancelled' ? 'consultationStatusCancelled' : 'consultationStatusReserved';
          li.textContent = channelLabel + ' · ' + t(statusKey) + ' · ' + caseLabel;
          if (item.status === 'reserved') { const button = document.createElement('button'); button.type='button'; button.className='text-button'; button.textContent=t('consultationCancel'); button.addEventListener('click', () => cancelConsultation(item.id)); li.appendChild(button); }
          return li;
        });
        list.replaceChildren(...items);
      }
    }
    async function loadConsultations() {
      return run(async () => { const data = await api('/api/consultations'); renderConsultation(data); });
    }
    async function requestConsultation(event) {
      if (event) event.preventDefault();
      const caseId = $('consultation-case').value;
      const selected = document.querySelector ? document.querySelector('input[name="consultation-channel"]:checked') : null;
      const channel = selected ? selected.value : 'phone';
      return run(async () => {
        const data = await post('/api/consultations', { case_id: caseId, channel }, { 'Idempotency-Key': consultationKey(caseId, channel) });
        state.consultationKey = null; renderConsultation(data.consultation);
        $('consultation-result').textContent = t('consultationRecorded'); $('consultation-result').hidden = false; $('consultation-result').focus();
      });
    }
    async function cancelConsultation(requestId) {
      return run(async () => { const data = await post('/api/consultations/' + encodeURIComponent(requestId) + '/cancel', {}); renderConsultation(data.consultation); $('consultation-result').textContent=t('consultationCancelled'); $('consultation-result').hidden=false; });
    }
    function showView(view, focus = true) {
      if (state.busy) return;
      state.view = view === 'register' && state.registrationOpen ? 'register' : 'login';
      setNotice(null); render();
      if (focus) $('account-heading').focus();
    }
    async function run(operation) {
      if (state.busy) return;
      state.busy = true; setNotice(null); render();
      try { await operation(); }
      catch (error) {
        if (error.status === 401) { state.authenticated = false; state.account = null; render(); }
        setNotice(error.key || 'errorGeneric', 'error', true);
      } finally { state.busy = false; state.loading = false; render(); }
    }
    async function refresh(announce = false) {
      return run(async () => { applySession(await api('/api/session')); if (announce) setNotice('statusUpdated', 'success', true); });
    }
    async function register(event) {
      if (event) event.preventDefault();
      if (!state.registrationOpen || state.authMode !== 'accounts' || !state.authConfigured) return;
      return run(async () => {
        const email = $('register-email').value.trim();
        await post('/api/accounts/register', { email, password: $('register-password').value, company_name: $('register-company').value.trim(), company_identifier: $('register-identifier').value.trim(), role: $('register-role').value, locale: state.language });
        $('register-password').value = ''; $('login-email').value = email; state.view = 'login';
        setNotice('created', 'success', true);
      });
    }
    async function login(event) {
      if (event) event.preventDefault();
      if (!state.authConfigured || state.authMode !== 'accounts') return;
      return run(async () => {
        const data = await post('/api/login', { email: $('login-email').value.trim(), password: $('login-password').value });
        $('login-password').value = '';
        applySession(data); render();
        if (state.authenticated) $('status-heading').focus();
      });
    }
    async function logout() {
      return run(async () => {
        await post('/api/logout', {});
        state.authenticated = false; state.account = null; $('login-password').value = ''; $('register-password').value = '';
        applySession(await api('/api/session')); state.view = 'login'; setNotice('loggedOut', 'success', true);
      });
    }
    function bind() {
      $('account-language').addEventListener('change', event => setLanguage(event.target.value));
      $('show-register').addEventListener('click', () => showView('register'));
      $('show-login').addEventListener('click', () => showView('login'));
      $('account-register-form').addEventListener('submit', register);
      $('account-login-form').addEventListener('submit', login);
      $('account-refresh').addEventListener('click', () => refresh(true));
      $('account-logout').addEventListener('click', logout);
      $('consultation-load').addEventListener('click', loadConsultations);
      $('consultation-form').addEventListener('submit', requestConsultation);
    }
    async function start() { bind(); translate(); await refresh(); }
    return { start, refresh, register, login, logout, loadConsultations, requestConsultation, cancelConsultation, applySession, setLanguage, showView, state };
  }
  return { dictionaries, locales, storageKey, legacyStorageKey, eligible, errorKey, createController };
});
