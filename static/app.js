'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const state = { csrf: '', authenticated: false, configured: false, busy: false, historyBusy: false, caseBusy: false, historyLoaded: false, openedCaseId: null, file: null, mediaKind: null, imageUrl: null, mediaUrl: null, videoInspection: null, analysis: null, archive: null, controller: null, answers: new Map(), submittedContext: '', view: 'analysis', editing: true, entitlement: { plan: 'internal', export_allowed: true }, media: { image_max_bytes: 10 * 1024 * 1024, video_max_bytes: 50 * 1024 * 1024, video_max_seconds: 30, video_intake_enabled: false, video_analysis_enabled: false } };
  const certaintyLabels = { visible: 'Visibile nella foto', reported: 'Riferito dall’utilizzatore', verify: 'Da verificare sul posto' };
  const riskLabels = { high: 'Rischio alto', medium: 'Rischio medio', low: 'Rischio basso', undetermined: 'Rischio da determinare' };
  const make = (tag, text, cls) => { const el = document.createElement(tag); if (text != null) el.textContent = String(text); if (cls) el.className = cls; return el; };
  function syncWorkspace() {
    const history = state.view === 'history', hasReport = Boolean(state.analysis);
    $('history-panel').hidden = !history; $('work-grid').hidden = history; $('workflow').hidden = history;
    $('workspace-nav').hidden = !state.authenticated; $('new-analysis').hidden = !state.authenticated;
    $('nav-analysis').className = 'nav-button' + (!history ? ' active' : '');
    $('nav-history').className = 'nav-button' + (history ? ' active' : '');
    ['nav-analysis', 'nav-history'].forEach(id => $(id).removeAttribute('aria-current'));
    $(history ? 'nav-history' : 'nav-analysis').setAttribute('aria-current', 'page');
    $('workspace-title').textContent = history ? 'Le tue analisi, in un solo posto.' : hasReport && !state.editing ? 'Dalla situazione, alle azioni.' : 'Analizza una situazione di lavoro.';
    $('workspace-description').textContent = history ? 'Riapri un rapporto, consulta il contesto ed esporta ciò che vuoi conservare.' : hasReport && !state.editing ? 'Verifica le misure proposte e completa le informazioni che mancano.' : 'Inizia da una foto. Aggiungi il contesto. Individua il prossimo passo.';
    $('work-grid').dataset.mode = state.busy ? 'busy' : hasReport ? state.editing ? 'edit-report' : 'report' : 'input';
    $('input-panel').hidden = state.busy || (hasReport && !state.editing);
    $('input-panel').className = 'panel input-panel' + (state.file ? ' has-photo' : '');
    $('return-report').hidden = !hasReport || !state.editing;
    $('upload-title').textContent = state.file ? 'Vuoi cambiare file?' : 'Carica foto o video';
    $('submit-note').textContent = hasReport ? 'Il rapporto corrente cambia solo dopo una nuova analisi riuscita.' : 'Controlla foto e contesto prima di avviare.';
    const activeStep = state.busy || (hasReport && !state.editing) ? 2 : state.file ? 1 : 0;
    ['step-photo', 'step-context', 'step-result'].forEach((id, index) => {
      $(id).className = 'workflow-step' + (index < activeStep ? ' complete' : index === activeStep ? ' current' : '');
      $(id).removeAttribute('aria-current'); if (index === activeStep) $(id).setAttribute('aria-current', 'step');
    });
    $('result-step-note').textContent = state.busy ? 'Analisi in corso' : hasReport ? 'Rapporto disponibile' : 'Azioni e chiarimenti';
    const needsArchivedPhoto = Boolean(state.analysis && !state.file);
    $('questions-photo-note').hidden = !needsArchivedPhoto;
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
    state.file = null; state.mediaKind = null; state.imageUrl = null; state.mediaUrl = null; state.videoInspection = null; $('photo').value = ''; $('context').value = '';
    $('preview-wrap').hidden = true; $('preview').removeAttribute('src'); $('file-name').textContent = '';
    $('video-preview').removeAttribute('src'); $('video-evidence').hidden = true; $('video-frames').replaceChildren();
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
    $('analysis-announcement').textContent = 'Il tentativo non ha prodotto un nuovo risultato.';
    if (state.analysis) {
      $('report-title').textContent = 'Analisi precedente';
      $('report-notice').textContent = 'L’ultimo tentativo non ha prodotto un nuovo risultato. Questa analisi non include le modifiche o le risposte appena inviate.';
      $('report-notice').hidden = false;
    }
    return target.id;
  }
  async function api(url, options = {}) {
    const response = await fetch(url, { credentials: 'same-origin', ...options });
    let data;
    try { data = await response.json(); } catch { throw new Error('Il servizio ha restituito una risposta non leggibile. Nessuna analisi è stata acquisita.'); }
    if (!response.ok) { const error = new Error(data.error?.message || 'Operazione non riuscita.'); error.status = response.status; error.code = data.error?.code; error.data = data; throw error; }
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
    if (!state.authenticated && data.auth_configured === false) notice('L’accesso al pilota non è ancora configurato. Completa la configurazione riservata del servizio prima di utilizzarlo.', 'warning');
    if (state.authenticated && !state.configured) notice('Il pilota è accessibile, ma la configurazione per l’analisi non è completa. La fotografia non verrà inviata finché il servizio non sarà configurato.', 'warning');
    updateButton();
    if (state.authenticated && (!wasAuthenticated || !state.historyLoaded)) loadCases();
    if (!state.authenticated) resetHistory();
  }
  function updateButton() {
    const trialExhausted = state.entitlement.plan === 'trial' && state.entitlement.analyses_remaining === 0;
    const canExport = state.entitlement.export_allowed !== false;
    const videoReady = state.mediaKind === 'video' && state.media.video_intake_enabled;
    $('analyse-button').disabled = state.busy || (videoReady ? false : !state.configured || state.mediaKind === 'video' || (trialExhausted && !state.openedCaseId)); $('reanalyse-button').disabled = state.busy || !state.configured;
    if (!state.busy) $('analyse-button').textContent = state.mediaKind === 'video' ? 'Verifica video e audio →' : 'Avvia analisi AI →';
    $('export-json').disabled = state.busy || !state.analysis || !canExport; $('print-report').disabled = state.busy || !state.analysis || !canExport;
    $('export-json').hidden = !canExport; $('print-report').hidden = !canExport; $('trial-export-note').hidden = canExport || !state.analysis;
    $('trial-entitlement-note').hidden = !trialExhausted || Boolean(state.openedCaseId);
    $('trial-entitlement-note').textContent = trialExhausted ? 'La prova gratuita è stata utilizzata. Puoi consultare il risultato; una nuova analisi richiede un piano successivo.' : '';
    ['new-analysis', 'history-new-analysis', 'nav-analysis', 'nav-history', 'edit-analysis', 'return-report'].forEach(id => { $(id).disabled = state.busy || state.caseBusy; });
    if (!state.busy) $('reanalyse-button').textContent = state.analysis && !state.file ? 'Aggiungi la foto per aggiornare' : 'Aggiorna con le risposte';
    syncWorkspace();
  }
  function setBusy(value) {
    state.busy = value; updateButton(); $('photo').disabled = value; $('context').disabled = value; $('logout').disabled = value;
    const video = state.mediaKind === 'video';
    $('busy-eyebrow').textContent = video ? 'Video e audio acquisiti' : 'Foto e contesto inviati';
    $('busy-title').textContent = video ? 'Verifica tecnica in corso' : 'Analisi in corso';
    $('busy-description').textContent = video ? 'Sto controllando durata, fotogrammi e presenza della traccia audio.' : 'Sto esaminando la situazione per proporre osservazioni, azioni e chiarimenti.';
    $('analyse-button').textContent = value ? (state.mediaKind === 'video' ? 'Verifica in corso…' : 'Analisi in corso…') : (state.mediaKind === 'video' ? 'Verifica video e audio →' : 'Avvia analisi AI →');
    $('reanalyse-button').textContent = value ? 'Analisi in corso…' : state.analysis && !state.file ? 'Aggiungi la foto per aggiornare' : 'Aggiorna con le risposte';
    $('busy-state').hidden = !value; $('report').hidden = value || !state.analysis; $('empty-state').hidden = value || Boolean(state.analysis);
    $('result-region').setAttribute('aria-busy', String(value));
    $('result-region').setAttribute('aria-labelledby', value ? 'busy-title' : state.analysis ? 'report-title' : 'result-title');
  }
  function clearAnalysis() {
    state.analysis = null; state.archive = null; state.openedCaseId = null; state.answers.clear(); state.submittedContext = ''; state.editing = true; clearFeedback();
    $('report').hidden = true; $('empty-state').hidden = false; $('findings').replaceChildren(); $('questions').replaceChildren();
    $('case-summary').replaceChildren(); $('question-summary').replaceChildren(); $('question-summary').hidden = true;
    $('report-notice').hidden = true; $('report-title').textContent = 'Analisi completata';
    $('analysis-announcement').textContent = '';
    $('result-region').setAttribute('aria-labelledby', 'result-title'); updateButton();
  }
  function resetHistory() {
    state.historyBusy = false; state.caseBusy = false; state.historyLoaded = false; state.openedCaseId = null;
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
    notice('Sessione scaduta. Sto preparando un nuovo accesso. L’eventuale rapporto già aperto resta in questa pagina.', 'warning');
    try {
      const fresh = await api('/api/session');
      applySession({ ...fresh, authenticated: false, configured: false });
      notice('Sessione scaduta. Accedi nuovamente per usare l’archivio. L’eventuale rapporto già aperto resta in questa pagina.', 'warning');
    } catch {
      state.csrf = ''; $('login-button').disabled = true;
      notice('Sessione scaduta e nuovo accesso non disponibile. Ricarica la pagina prima di accedere. Il rapporto locale resta nella pagina, ma verrà perso al ricaricamento.', 'error');
    }
    focusFeedback('status');
  }
  function caseDate(value) {
    const date = new Date(Number(value) * 1000);
    return Number.isNaN(date.getTime()) ? 'Data non disponibile' : new Intl.DateTimeFormat('it-CH', { dateStyle: 'medium', timeStyle: 'short' }).format(date);
  }
  function caseExcerpt(value, fallback) {
    const text = String(value || fallback || '').trim().replace(/\s+/g, ' ');
    return text.length > 180 ? text.slice(0, 177) + '…' : text;
  }
  function renderCaseList(cases) {
    $('history-list').replaceChildren(); $('history-empty').hidden = cases.length !== 0;
    cases.forEach(item => {
      const card = make('article', null, 'history-item'); card.dataset.caseId = item.id;
      const body = make('div', null, 'history-item-body'); body.append(make('h3', caseExcerpt(item.summary, 'Analisi senza sintesi')));
      body.append(make('p', caseDate(item.created_at), 'history-date'));
      if (item.deletion_pending) body.append(make('p', 'Il caso non è consultabile. Riprova per completare la rimozione dei file dal server.', 'notice warning'));
      if (item.context) body.append(make('p', caseExcerpt(item.context), 'history-context'));
      const actions = make('div', null, 'history-actions');
      if (!item.deletion_pending) {
        const open = make('button', 'Apri analisi', 'button subtle'); open.type = 'button';
        open.addEventListener('click', () => openCase(item.id, open)); actions.append(open);
      }
      const remove = make('button', item.deletion_pending ? 'Riprova eliminazione' : 'Elimina', 'button danger'); remove.type = 'button';
      remove.addEventListener('click', () => askDeleteCase(item.id, actions, remove));
      actions.append(remove); card.append(body, actions); $('history-list').append(card);
    });
  }
  async function loadCases({ focus = false } = {}) {
    if (!state.authenticated || state.historyBusy) return;
    $('history-error').hidden = true; $('history-loading').hidden = false; $('history-empty').hidden = true;
    setHistoryBusy(true, 'Caricamento delle analisi salvate.');
    try {
      const data = await api('/api/cases', { headers: { 'X-CSRF-Token': state.csrf } });
      const cases = Array.isArray(data.cases) ? data.cases : [];
      renderCaseList(cases); state.historyLoaded = true;
      const storageNote = data.storage?.uploads_blocked ? ' Spazio esaurito: lo storico resta consultabile, ma i nuovi file non possono essere salvati.' : data.storage?.warning ? ' Lo spazio dello storico è quasi esaurito.' : '';
      $('history-status').textContent = (cases.length ? cases.length + ' analisi salvate disponibili.' : 'Nessuna analisi salvata.') + storageNote;
      if (focus) { showView('history'); focusFeedback(cases.length ? 'history-title' : 'history-empty'); }
    } catch (err) {
      if (err.status === 401) { await archiveSessionExpired(); return; }
      $('history-list').replaceChildren(); $('history-error').textContent = 'Archivio non disponibile. ' + err.message; $('history-error').hidden = false;
      $('history-status').textContent = 'Impossibile caricare l’archivio.'; if (focus) { showView('history'); focusFeedback('history-error'); }
    } finally { $('history-loading').hidden = true; setHistoryBusy(false); }
  }
  async function openCase(caseId, trigger) {
    if (state.historyBusy || state.busy) return;
    $('history-error').hidden = true; setHistoryBusy(true, 'Apertura dell’analisi salvata.', true); trigger.textContent = 'Apertura…';
    try {
      const data = await api('/api/cases/' + encodeURIComponent(caseId), { headers: { 'X-CSRF-Token': state.csrf } });
      const saved = data.case;
      if (!saved?.analysis || !Array.isArray(saved.analysis.findings)) throw new Error('Il caso salvato è incompleto.');
      const previousImageUrl = state.imageUrl, previousFile = state.file, previousAnswers = new Map(state.answers);
      const original = Array.isArray(saved.assets) ? saved.assets.find(asset => asset?.role === 'original' && String(asset.media_type || '').startsWith('image/') && asset.download_url) : null;
      state.imageUrl = original ? original.download_url : null; state.file = null; state.answers.clear();
      if (state.imageUrl) { $('preview').src = state.imageUrl; $('preview').hidden = false; }
      try { await renderAnalysis(saved.analysis, saved.context || '', { archived: true }); }
      catch (err) { state.imageUrl = previousImageUrl; state.file = previousFile; state.answers = previousAnswers; if (previousImageUrl) $('preview').src = previousImageUrl; else $('preview').removeAttribute('src'); throw err; }
      if (previousImageUrl && previousImageUrl.startsWith('blob:')) URL.revokeObjectURL(previousImageUrl);
      $('photo').value = ''; $('preview-wrap').hidden = true;
      state.analysis = saved.analysis; state.submittedContext = saved.context || ''; state.archive = { saved: true, case_id: saved.id }; state.openedCaseId = saved.id; state.editing = false;
      $('context').value = saved.context || ''; showView('analysis');
      $('empty-state').hidden = true; $('report').hidden = false; $('report-title').textContent = 'Analisi salvata';
      $('report-notice').textContent = original ? 'Il file originale è conservato nel caso. Il rapporto resta da verificare nelle condizioni effettive.' : 'Questo caso precedente non contiene una fotografia archiviata. Verifica il rapporto con l’immagine originale prima di usarlo.'; $('report-notice').hidden = false;
      $('result-region').setAttribute('aria-labelledby', 'report-title'); $('history-status').textContent = 'Analisi salvata aperta.'; updateButton(); focusFeedback('report-title');
    } catch (err) {
      if (err.status === 401) { await archiveSessionExpired(); return; }
      $('history-error').textContent = 'Impossibile aprire l’analisi. ' + err.message; $('history-error').hidden = false; $('history-status').textContent = 'Apertura non riuscita.'; showView('history'); focusFeedback('history-error');
    } finally { trigger.textContent = 'Apri analisi'; setHistoryBusy(false); }
  }
  function askDeleteCase(caseId, actions, trigger) {
    if (state.historyBusy || actions.querySelector('.delete-confirm')) return;
    const confirm = make('div', null, 'delete-confirm'); confirm.setAttribute('role', 'group'); confirm.setAttribute('aria-label', 'Conferma eliminazione');
    confirm.append(make('p', 'Eliminare definitivamente questa analisi?'));
    const yes = make('button', 'Conferma eliminazione', 'button danger'); yes.type = 'button';
    const no = make('button', 'Annulla', 'button subtle'); no.type = 'button';
    yes.addEventListener('click', () => deleteCase(caseId, yes));
    no.addEventListener('click', () => { confirm.remove(); trigger.hidden = false; trigger.focus(); });
    trigger.hidden = true; confirm.append(yes, no); actions.append(confirm); yes.focus();
  }
  async function deleteCase(caseId, trigger) {
    if (state.historyBusy) return;
    setHistoryBusy(true, 'Eliminazione dell’analisi salvata.', true); trigger.textContent = 'Eliminazione…';
    try {
      await api('/api/cases/' + encodeURIComponent(caseId), { method: 'DELETE', headers: { 'X-CSRF-Token': state.csrf } });
      if (state.openedCaseId === caseId) clearAnalysis();
      setHistoryBusy(false); await loadCases(); $('history-status').textContent = 'Analisi eliminata definitivamente.'; showView('history'); focusFeedback('history-title');
    } catch (err) {
      if (err.status === 401) { await archiveSessionExpired(); return; }
      $('history-error').textContent = 'Impossibile eliminare l’analisi. ' + err.message; $('history-error').hidden = false; $('history-status').textContent = 'Eliminazione non riuscita.'; showView('history'); focusFeedback('history-error');
    } finally { trigger.textContent = 'Conferma eliminazione'; setHistoryBusy(false); }
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
    catch (err) { notice(err.message, 'error'); }
    finally { $('login-button').disabled = false; }
  });
  $('logout').addEventListener('click', async () => {
    if (state.busy) return;
    try {
      await api('/api/logout', { method: 'POST', headers: { 'X-CSRF-Token': state.csrf } });
      clearAnalysis(); $('analysis-form').reset(); $('preview-wrap').hidden = true; $('preview').removeAttribute('src');
      if (state.imageUrl) URL.revokeObjectURL(state.imageUrl); if (state.mediaUrl) URL.revokeObjectURL(state.mediaUrl); state.imageUrl = null; state.mediaUrl = null; state.file = null; state.mediaKind = null; state.view = 'analysis';
      applySession({ authenticated: false, configured: false }); applySession(await api('/api/session')); notice('Sessione chiusa.');
    } catch (err) { notice(err.message, 'error'); }
  });
  $('photo').addEventListener('change', () => {
    const attachingArchivedPhoto = Boolean(state.analysis && !state.file);
    if (attachingArchivedPhoto) { clearFeedback(); state.editing = true; } else clearAnalysis();
    notice('');
    if (state.imageUrl) URL.revokeObjectURL(state.imageUrl); if (state.mediaUrl) URL.revokeObjectURL(state.mediaUrl); state.imageUrl = null; state.mediaUrl = null; state.file = null; state.mediaKind = null; state.videoInspection = null; $('preview-wrap').hidden = true; $('preview').hidden = false; $('video-preview').hidden = true; $('video-preview').removeAttribute('src'); $('video-evidence').hidden = true; $('video-frames').replaceChildren(); $('media-note').hidden = true;
    syncWorkspace();
    const file = $('photo').files[0]; if (!file) return;
    const images = ['image/jpeg', 'image/png', 'image/webp'], videos = ['video/mp4', 'video/webm', 'video/quicktime'];
    if (!images.includes(file.type) && !videos.includes(file.type)) { focusFeedback(analysisError('Scegli una foto JPG, PNG, WebP oppure un video MP4, WebM o MOV.', 'analysis')); $('photo').value = ''; return; }
    const isVideo = videos.includes(file.type), limit = isVideo ? state.media.video_max_bytes : state.media.image_max_bytes;
    if (file.size > limit) { focusFeedback(analysisError((isVideo ? 'Il video' : 'La fotografia') + ' supera il limite di ' + Math.floor(limit / 1024 / 1024) + ' MB.', 'analysis')); $('photo').value = ''; return; }
    state.file = file; state.mediaKind = isVideo ? 'video' : 'image'; $('file-name').textContent = file.name; $('preview-wrap').hidden = false;
    $('media-ready').textContent = isVideo ? 'Video selezionato' : 'Foto selezionata';
    if (isVideo) {
      $('preview').hidden = true; $('preview').removeAttribute('src');
      state.mediaUrl = URL.createObjectURL(file); $('video-preview').src = state.mediaUrl; $('video-preview').hidden = false;
      $('media-note').textContent = state.media.video_intake_enabled
        ? 'Verifica durata, fotogrammi e traccia audio (massimo ' + state.media.video_max_seconds + ' secondi). Questa verifica locale non esegue ancora l’analisi AI e non consuma la prova gratuita.'
        : 'La verifica tecnica dei video non è disponibile in questo ambiente. Il file non verrà inviato e la prova gratuita non verrà consumata.';
      $('media-note').hidden = false;
    } else {
      $('video-preview').hidden = true; state.imageUrl = URL.createObjectURL(file); $('preview').src = state.imageUrl; $('preview').hidden = false; $('media-note').hidden = true;
    }
    if (attachingArchivedPhoto) {
      $('report-notice').textContent = 'Fotografia selezionata per il prossimo aggiornamento. Il rapporto salvato non è ancora cambiato: verifica che sia la fotografia originale.';
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
    clearFeedback();
    if (!state.file) { focusFeedback(analysisError('Seleziona una foto o un video prima di avviare l’analisi.', origin)); return; }
    if (state.mediaKind === 'video') { await inspectVideo(origin); return; }
    const context = composedContext(); if (context.length > 8000) { focusFeedback(analysisError('Il contesto e le risposte superano 8.000 caratteri. Riduci i dettagli secondari prima di continuare.', origin)); return; }
    if (!state.configured) { focusFeedback(analysisError('Completa la configurazione del servizio prima di avviare un’analisi.', origin)); return; }
    notice(''); if (origin === 'analysis') state.editing = true; showView('analysis'); setBusy(true); focusFeedback('busy-title'); state.controller = new AbortController();
    $('analysis-announcement').textContent = 'Analisi in corso.';
    let outcomeTarget = 'report-title';
    const form = new FormData(); form.append('file', state.file); form.append('context', context);
    form.append('request_kind', state.analysis && state.openedCaseId ? 'clarification' : 'initial');
    if (state.analysis && state.openedCaseId) form.append('case_id', state.openedCaseId);
    try {
      const data = await api('/analizza', { method: 'POST', headers: { 'X-CSRF-Token': state.csrf }, body: form, signal: state.controller.signal });
      if (!data.analysis || !Array.isArray(data.analysis.findings)) throw new Error('Il risultato è incompleto. Non è stato presentato come analisi valida.');
      await renderAnalysis(data.analysis, context); state.analysis = data.analysis; state.archive = data.archive || null; state.submittedContext = context; state.editing = false; state.openedCaseId = data.archive?.case_id || state.openedCaseId || null;
      if (data.entitlement) state.entitlement = data.entitlement;
      $('report-title').textContent = 'Analisi completata'; $('report-notice').hidden = true;
      if (data.archive?.saved) { notice('Analisi completata: file originale e rapporto sono archiviati nel caso.' + (data.archive.storage?.warning ? ' Lo spazio dello storico è quasi esaurito.' : '')); loadCases(); }
      else if (data.archive?.message) {
        const exportHint = state.entitlement.export_allowed === false ? ' Il risultato resta consultabile in questa pagina.' : ' Esporta il rapporto se vuoi conservarlo.';
        $('report-notice').textContent = data.archive.message + exportHint;
        $('report-notice').hidden = false;
      }
      $('analysis-announcement').textContent = 'Analisi completata. Il risultato è disponibile e va verificato sul posto.';
    } catch (err) {
      if (err.data?.entitlement) { state.entitlement = err.data.entitlement; updateButton(); }
      if (err.status === 401) {
        analysisError('Sessione scaduta. Il tentativo non ha prodotto un nuovo risultato.', origin);
        applySession({ authenticated: false, configured: false });
        try { applySession(await api('/api/session')); notice('Sessione scaduta. Accedi nuovamente per continuare. Foto, contesto e risultato precedente restano in questa pagina.', 'warning'); }
        catch { $('login-button').disabled = true; notice('Sessione scaduta. Ricarica la pagina per ottenere un nuovo accesso. I dati non esportati andranno persi.', 'error'); }
        outcomeTarget = 'status';
      }
      else {
        const message = err.name === 'AbortError' ? 'Richiesta interrotta. Non è stata avviata automaticamente una nuova analisi.' : err.message;
        outcomeTarget = analysisError('Analisi non completata. ' + message + (state.analysis ? ' Resta disponibile il risultato precedente.' : ' Nessun risultato è stato acquisito.'), origin);
      }
    } finally {
      state.controller = null; setBusy(false);
      // Follow the explicit submission, without interrupting someone who moved on to another field.
      const active = document.activeElement;
      if (!active || active === document.body || active === $('busy-title') || active.disabled) focusFeedback(outcomeTarget);
    }
  }
  function renderVideoInspection(media) {
    $('video-summary').textContent = 'Durata verificata: ' + media.duration_seconds.toFixed(1) + ' s · ' + media.frames.length + ' fotogrammi campionati.';
    $('video-frames').replaceChildren();
    media.frames.forEach(frame => {
      const figure = make('figure', null, 'video-frame'); const image = make('img'); image.src = frame.image_data_url; image.alt = 'Fotogramma a ' + frame.timestamp_seconds.toFixed(1) + ' secondi';
      figure.append(image, make('figcaption', frame.timestamp_seconds.toFixed(1) + ' s')); $('video-frames').append(figure);
    });
    const labels = { absent: 'Nessuna traccia audio presente.', silent: 'Traccia audio digitale priva di segnale.', low_level: 'Traccia audio con segnale molto debole: deve ancora essere trascritta e verificata.', ready_for_transcription: 'Traccia audio estratta: la trascrizione e la comprensibilità non sono ancora state verificate.', error: 'Traccia audio presente, ma estrazione non riuscita: la verifica resta incompleta.' };
    $('audio-summary').textContent = labels[media.audio.status] || 'Stato audio non determinato.';
    $('video-evidence').hidden = false;
  }
  async function inspectVideo(origin) {
    if (!state.media.video_intake_enabled) { focusFeedback(analysisError('La verifica locale dei video non è disponibile.', origin)); return; }
    setBusy(true); state.controller = new AbortController(); $('analysis-announcement').textContent = 'Verifica tecnica di video e audio in corso.';
    const form = new FormData(); form.append('file', state.file);
    try {
      const data = await api('/api/media/inspect', { method: 'POST', headers: { 'X-CSRF-Token': state.csrf }, body: form, signal: state.controller.signal });
      state.videoInspection = data.media; renderVideoInspection(data.media);
      const incomplete = data.media.audio.status === 'error' ? ' Attenzione: la parte audio non è stata verificata.' : '';
      $('media-note').textContent = data.message + incomplete + ' La prova gratuita non è stata consumata.';
      $('analysis-announcement').textContent = 'Verifica tecnica del video completata.';
    } catch (err) {
      if (err.status === 401) {
        analysisError('Sessione scaduta. Il video non è stato verificato.', origin);
        applySession({ authenticated: false, configured: false });
        try { applySession(await api('/api/session')); notice('Sessione scaduta. Accedi nuovamente per verificare il video.', 'warning'); }
        catch { notice('Sessione scaduta. Ricarica la pagina prima di riprovare.', 'error'); }
      } else focusFeedback(analysisError('Verifica video non completata. ' + err.message, origin));
    }
    finally { state.controller = null; setBusy(false); if (!state.videoInspection) focusFeedback('analysis-feedback'); else focusFeedback('video-evidence-title'); }
  }
  $('analysis-form').addEventListener('submit', e => { e.preventDefault(); analyse(); });
  $('questions-form').addEventListener('submit', e => {
    e.preventDefault();
    if (state.analysis && !state.file) { state.editing = true; showView('analysis', true); return; }
    $('questions').querySelectorAll('textarea').forEach(input => { const answer = input.value.trim(); if (answer) state.answers.set(input.dataset.question, answer); else state.answers.delete(input.dataset.question); });
    analyse('questions');
  });
  function addText(parent, tag, text, cls) { if (text) parent.append(make(tag, text, cls)); }
  async function createCrop(bbox, image, id) {
    if (!bbox || !image || ![bbox.x, bbox.y, bbox.width, bbox.height].every(Number.isFinite)) return null;
    const { x, y, width, height } = bbox;
    if (x < 0 || y < 0 || width <= 0 || height <= 0 || x + width > 1.001 || y + height > 1.001) return null;
    const figure = make('figure', null, 'crop'), canvas = make('canvas');
    const sw = width * image.naturalWidth, sh = height * image.naturalHeight, scale = Math.min(1, 900 / Math.max(sw, sh));
    canvas.width = Math.max(1, Math.round(sw * scale)); canvas.height = Math.max(1, Math.round(sh * scale));
    canvas.setAttribute('role', 'img'); canvas.setAttribute('aria-label', 'Dettaglio della fotografia per l’osservazione ' + id);
    const ctx = canvas.getContext('2d'); if (!ctx) return null;
    try { ctx.drawImage(image, x * image.naturalWidth, y * image.naturalHeight, sw, sh, 0, 0, canvas.width, canvas.height); } catch { return null; }
    const caption = make('figcaption'); caption.append(make('span', 'Osservazione ' + id + ' · ritaglio indicato dall’AI'));
    const link = make('a', 'Foto completa'); link.href = state.imageUrl; link.target = '_blank'; link.rel = 'noopener'; caption.append(link); figure.append(canvas, caption); return figure;
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
    const questionList = collectQuestions(analysis);
    const hasUnknown = Boolean(analysis.needs_clarification) || analysis.findings.some(f => f.critical_unknown || f.risk === 'undetermined') || questionList.some(q => q.critical);
    $('assessment-state').textContent = hasUnknown ? 'Valutazione da completare · restano informazioni decisive da verificare.' : 'Osservazioni e misure proposte · da confermare nelle condizioni effettive.';
    $('assessment-state').className = 'assessment-state' + (hasUnknown ? ' incomplete' : '');
    $('findings').replaceChildren();
    let image = !state.imageUrl ? null : $('preview');
    if (image) { try { await image.decode(); } catch { image = null; } }
    // Snapshot only the photo and context used by this successful request.
    const meta = analysis.meta || {};
    $('case-summary').replaceChildren();
    $('case-summary').append(make('h3', 'Situazione analizzata'));
    if (image && state.imageUrl) {
      const photo = make('img'); photo.src = state.imageUrl; photo.alt = 'Fotografia completa utilizzata per questa analisi'; photo.className = 'case-photo';
      $('case-summary').append(photo);
    } else $('case-summary').append(make('p', options.archived ? 'Questo caso non contiene una fotografia archiviata. Verificare il rapporto con la foto originale.' : 'Fotografia non disponibile per la stampa. Verificare il rapporto con la foto originale.', 'notice warning'));
    $('case-summary').append(make('p', 'Contesto e chiarimenti inviati', 'measure-label'), make('p', submittedContext || 'Nessun contesto aggiuntivo fornito.', 'case-context'));
    $('case-summary').append(make('p', 'Data analisi: ' + (meta.created_at || 'non disponibile') + ' · Metodo: ' + (meta.method_version || meta.prompt_version || 'non indicato'), 'case-meta'));
    const decisiveCount = questionList.filter(q => q.critical).length;
    $('question-summary').replaceChildren(); $('question-summary').hidden = !questionList.length;
    if (questionList.length) {
      $('question-summary').append(make('p', 'Domande da chiarire: ' + questionList.length + ' · Informazioni decisive: ' + decisiveCount));
      const jump = make('button', decisiveCount ? 'Vai alle domande decisive' : 'Vai alle domande', 'button subtle'); jump.type = 'button';
      jump.addEventListener('click', () => focusFeedback('questions-title')); $('question-summary').append(jump);
    }
    const priority = f => f.risk === 'high' ? 0 : f.critical_unknown ? 1 : ({ undetermined: 2, medium: 3, low: 4 }[f.risk] ?? 5);
    const ordered = [...analysis.findings].sort((a, b) => priority(a) - priority(b));
    if (!ordered.length) $('findings').append(make('p', 'Nessuna osservazione strutturata restituita. Questo non dimostra l’assenza di pericoli.', 'notice warning'));
    for (const finding of ordered) {
      const risk = Object.hasOwn(riskLabels, finding.risk) ? finding.risk : 'undetermined';
      const card = make('section', null, 'finding ' + risk), top = make('div', null, 'finding-topline');
      top.append(make('span', 'Osservazione ' + finding.id, 'finding-id'), make('span', riskLabels[risk], 'risk-tag ' + risk)); card.append(top, make('h3', finding.title));
      const measure = make('div', null, 'measure'); measure.append(make('p', 'Cosa fare', 'measure-label'), make('p', finding.action, 'measure-action'), make('p', 'Quando: ' + (finding.deadline || 'Da definire dopo gli accertamenti'), 'deadline')); card.append(measure);
      const crop = await createCrop(finding.bbox, image, finding.id);
      if (crop) card.append(crop);
      else {
        const fallback = make('p', 'Osservazione ' + finding.id + ' · Ritaglio non disponibile. ', 'crop-fallback');
        if (state.imageUrl) { const link = make('a', 'Apri la fotografia completa'); link.href = state.imageUrl; link.target = '_blank'; link.rel = 'noopener'; fallback.append(link); }
        fallback.append(make('span', image ? 'Consulta la fotografia completa all’inizio del rapporto.' : 'Confrontare con la foto originale, non disponibile in questa stampa.', 'print-photo-reference')); card.append(fallback);
      }
      card.append(make('p', certaintyLabels[finding.certainty] || 'Da verificare sul posto', 'evidence-label'), make('p', finding.evidence, 'evidence-text'));
      addText(card, 'p', finding.exposed_people ? 'Persone esposte: ' + finding.exposed_people : '', 'finding-detail');
      addText(card, 'p', finding.question ? 'Da chiarire: ' + finding.question : '', 'finding-question');
      const cited = (finding.references || []).map(ref => (analysis.sources || []).find(s => s.id === ref.source_id)).filter(Boolean);
      if (cited.length) { const p = make('p', 'Riferimenti: ', 'finding-detail'); cited.forEach((source, index) => { if (index) p.append(document.createTextNode(' · ')); const url = validUrl(source.url); const link = make(url ? 'a' : 'span', source.title); if (url) { link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer'; } p.append(link); }); card.append(p); }
      $('findings').append(card);
    }
    $('questions').replaceChildren(); $('questions-panel').hidden = !questionList.length;
    $('print-questions').replaceChildren();
    if (questionList.length) {
      $('print-questions').append(make('h3', 'Domande ancora da chiarire'));
      const list = make('ul');
      questionList.forEach(q => list.append(make('li', (q.critical ? 'Informazione decisiva: ' : '') + q.text + (q.findingIds.length ? ' · Osservazioni: ' + q.findingIds.join(', ') : '') + (q.why ? ' — ' + q.why : ''))));
      $('print-questions').append(list);
    }
    let furtherQuestions = null;
    const secondaryCount = questionList.length - decisiveCount;
    if (secondaryCount > 3) {
      furtherQuestions = make('details', null, 'further-questions');
      furtherQuestions.append(make('summary', 'Altre domande di approfondimento (' + (secondaryCount - 3) + ')'));
    }
    questionList.forEach((q, index) => {
      const wrapper = make('div', null, 'question'); if (q.critical) wrapper.append(make('span', 'Informazione decisiva', 'critical-label'));
      if (q.findingIds.length) wrapper.append(make('p', 'Osservazioni: ' + q.findingIds.join(', '), 'question-related'));
      const id = 'answer-' + index, label = make('label', q.text); label.htmlFor = id; const input = make('textarea'); input.id = id; input.rows = 2; input.maxLength = 1500; input.dataset.question = q.text; input.value = state.answers.get(q.text) || '';
      if (q.why) { const why = make('p', q.why, 'why'); why.id = id + '-why'; input.setAttribute('aria-describedby', why.id); wrapper.append(label, why, input); } else wrapper.append(label, input);
      if (q.critical || index < decisiveCount + 3) $('questions').append(wrapper); else furtherQuestions.append(wrapper);
    });
    if (furtherQuestions) $('questions').append(furtherQuestions);
    $('limitations').replaceChildren();
    if (Array.isArray(analysis.limitations) && analysis.limitations.length) { $('limitations').append(make('h3', 'Cosa resta da accertare')); const list = make('ul'); analysis.limitations.forEach(item => list.append(make('li', item))); $('limitations').append(list); }
    $('sources').replaceChildren(); $('sources').append(make('h3', 'Fonti disponibili per questa analisi'));
    if (analysis.sources?.length) {
      const list = make('ul'); analysis.sources.forEach(source => { const li = make('li'); const url = validUrl(source.url), link = make(url ? 'a' : 'span', source.title); if (url) { link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer'; } li.append(link); if (source.verified_at) li.append(document.createTextNode(' · verifica: ' + source.verified_at)); list.append(li); }); $('sources').append(list);
    } else $('sources').append(make('p', 'Nessuna fonte normativa verificata è associata a questa analisi. Gli obblighi specifici richiedono verifica prima di essere presentati come accertati.'));
    const parts = [];
    if (meta.method_version || meta.prompt_version) parts.push('Metodo: ' + (meta.method_version || meta.prompt_version)); if (meta.model) parts.push('Modello: ' + meta.model); if (meta.created_at) parts.push('Analisi: ' + meta.created_at);
    $('analysis-meta').textContent = parts.join(' · ');
    ['summary', 'assessment-state', 'case-summary', 'question-summary', 'findings', 'questions', 'print-questions', 'limitations', 'sources', 'analysis-meta'].forEach(id => {
      const target = document.getElementById(id), content = $(id);
      target.replaceChildren(...content.childNodes); target.className = content.className;
    });
    document.getElementById('questions-panel').hidden = $('questions-panel').hidden;
    document.getElementById('question-summary').hidden = $('question-summary').hidden;
  }
  $('export-json').addEventListener('click', () => {
    if (!state.analysis) return;
    const data = { exported_at: new Date().toISOString(), photograph_included: false, context: state.submittedContext, analysis: state.analysis };
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
    const link = make('a'); link.href = url; link.download = 'SLPS_AI_analisi_' + new Date().toISOString().slice(0, 10) + '.json'; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    notice('Analisi esportata in JSON. La fotografia non è inclusa nel file.');
  });
  $('print-report').addEventListener('click', async () => {
    const analysis = state.analysis; if (!analysis || state.busy) return;
    const photo = $('case-summary').querySelector('img');
    if (photo) {
      try { await photo.decode(); }
      catch { notice('La fotografia non è pronta per la stampa. Riprova prima di stampare il rapporto.', 'error'); return; }
    }
    if (state.analysis !== analysis || state.busy) return;
    $('details-panel').open = true; window.print();
  });
  api('/api/session').then(applySession).catch(err => { $('login-panel').hidden = false; notice(err.message, 'error'); });
})();
