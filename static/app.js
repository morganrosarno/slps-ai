'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const state = { csrf: '', authenticated: false, configured: false, busy: false, file: null, imageUrl: null, analysis: null, archive: null, controller: null, answers: new Map(), submittedContext: '' };
  const certaintyLabels = { visible: 'Visibile nella foto', reported: 'Riferito dall’utilizzatore', verify: 'Da verificare sul posto' };
  const riskLabels = { high: 'Rischio alto', medium: 'Rischio medio', low: 'Rischio basso', undetermined: 'Rischio da determinare' };
  const make = (tag, text, cls) => { const el = document.createElement(tag); if (text != null) el.textContent = String(text); if (cls) el.className = cls; return el; };
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
    if (!response.ok) { const error = new Error(data.error?.message || 'Operazione non riuscita.'); error.status = response.status; error.code = data.error?.code; throw error; }
    return data;
  }
  function applySession(data) {
    state.authenticated = Boolean(data.authenticated); state.csrf = data.csrf || ''; state.configured = Boolean(data.configured);
    $('login-panel').hidden = state.authenticated; $('workspace').hidden = !state.authenticated; $('logout').hidden = !state.authenticated;
    $('login-button').disabled = data.auth_configured === false;
    if (!state.authenticated && data.auth_configured === false) notice('L’accesso al pilota non è ancora configurato. Completa la configurazione riservata del servizio prima di utilizzarlo.', 'warning');
    if (state.authenticated && !state.configured) notice('Il pilota è accessibile, ma la configurazione per l’analisi non è completa. La fotografia non verrà inviata finché il servizio non sarà configurato.', 'warning');
    updateButton();
  }
  function updateButton() { $('analyse-button').disabled = state.busy || !state.configured; $('reanalyse-button').disabled = state.busy || !state.configured; $('export-json').disabled = state.busy || !state.analysis; $('print-report').disabled = state.busy || !state.analysis; }
  function setBusy(value) {
    state.busy = value; updateButton(); $('photo').disabled = value; $('context').disabled = value; $('logout').disabled = value;
    $('analyse-button').textContent = value ? 'Analisi in corso…' : 'Analizza la situazione';
    $('reanalyse-button').textContent = value ? 'Analisi in corso…' : 'Aggiorna con le risposte';
    $('busy-state').hidden = !value; $('report').hidden = value || !state.analysis; $('empty-state').hidden = value || Boolean(state.analysis);
    $('result-region').setAttribute('aria-busy', String(value));
    $('result-region').setAttribute('aria-labelledby', value ? 'busy-title' : state.analysis ? 'report-title' : 'result-title');
  }
  function clearAnalysis() {
    state.analysis = null; state.archive = null; state.answers.clear(); state.submittedContext = ''; clearFeedback();
    $('report').hidden = true; $('empty-state').hidden = false; $('findings').replaceChildren(); $('questions').replaceChildren();
    $('case-summary').replaceChildren(); $('question-summary').replaceChildren(); $('question-summary').hidden = true;
    $('report-notice').hidden = true; $('report-title').textContent = 'Analisi completata';
    $('analysis-announcement').textContent = '';
    $('result-region').setAttribute('aria-labelledby', 'result-title'); updateButton();
  }
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
      if (state.imageUrl) URL.revokeObjectURL(state.imageUrl); state.imageUrl = null; state.file = null;
      applySession({ authenticated: false, configured: false }); applySession(await api('/api/session')); notice('Sessione chiusa.');
    } catch (err) { notice(err.message, 'error'); }
  });
  $('photo').addEventListener('change', () => {
    clearAnalysis(); notice('');
    if (state.imageUrl) URL.revokeObjectURL(state.imageUrl); state.imageUrl = null; state.file = null; $('preview-wrap').hidden = true;
    const file = $('photo').files[0]; if (!file) return;
    if (file.size > 10 * 1024 * 1024) { focusFeedback(analysisError('La fotografia supera 10 MB. Scegli un file più piccolo.', 'analysis')); $('photo').value = ''; return; }
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) { focusFeedback(analysisError('Scegli una fotografia JPG, PNG o WebP.', 'analysis')); $('photo').value = ''; return; }
    state.file = file; state.imageUrl = URL.createObjectURL(file); $('preview').src = state.imageUrl; $('file-name').textContent = file.name; $('preview-wrap').hidden = false;
  });
  function composedContext() {
    const parts = [$('context').value.trim()];
    if (state.answers.size) parts.push('Chiarimenti forniti dall’utilizzatore:\n' + Array.from(state.answers.entries()).map(([question, answer]) => question + '\nRisposta: ' + answer).join('\n\n'));
    return parts.filter(Boolean).join('\n\n');
  }
  async function analyse(origin = 'analysis') {
    if (state.busy) return;
    clearFeedback();
    if (!state.file) { focusFeedback(analysisError('Seleziona una fotografia prima di avviare l’analisi.', origin)); return; }
    const context = composedContext(); if (context.length > 8000) { focusFeedback(analysisError('Il contesto e le risposte superano 8.000 caratteri. Riduci i dettagli secondari prima di continuare.', origin)); return; }
    if (!state.configured) { focusFeedback(analysisError('Completa la configurazione del servizio prima di avviare un’analisi.', origin)); return; }
    notice(''); setBusy(true); focusFeedback('busy-title'); state.controller = new AbortController();
    $('analysis-announcement').textContent = 'Analisi in corso.';
    let outcomeTarget = 'report-title';
    const form = new FormData(); form.append('file', state.file); form.append('context', context);
    try {
      const data = await api('/analizza', { method: 'POST', headers: { 'X-CSRF-Token': state.csrf }, body: form, signal: state.controller.signal });
      if (!data.analysis || !Array.isArray(data.analysis.findings)) throw new Error('Il risultato è incompleto. Non è stato presentato come analisi valida.');
      await renderAnalysis(data.analysis, context); state.analysis = data.analysis; state.archive = data.archive || null; state.submittedContext = context;
      $('report-title').textContent = 'Analisi completata'; $('report-notice').hidden = true;
      if (data.archive?.saved) notice('Analisi completata e risultato archiviato senza fotografia.');
      else if (data.archive?.message) {
        $('report-notice').textContent = data.archive.message + ' Esporta il rapporto se vuoi conservarlo.';
        $('report-notice').hidden = false;
      }
      $('analysis-announcement').textContent = 'Analisi completata. Il risultato è disponibile e va verificato sul posto.';
    } catch (err) {
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
  $('analysis-form').addEventListener('submit', e => { e.preventDefault(); analyse(); });
  $('questions-form').addEventListener('submit', e => {
    e.preventDefault();
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
  async function renderAnalysis(analysis, submittedContext) {
    // Build off-screen: a rendering failure must not overwrite the previous valid report.
    const draft = document.getElementById('report').cloneNode(true);
    const $ = id => id === 'preview' ? document.getElementById(id) : draft.querySelector('#' + id);
    $('summary').textContent = analysis.summary || '';
    const questionList = collectQuestions(analysis);
    const hasUnknown = Boolean(analysis.needs_clarification) || analysis.findings.some(f => f.critical_unknown || f.risk === 'undetermined') || questionList.some(q => q.critical);
    $('assessment-state').textContent = hasUnknown ? 'Valutazione da completare · restano informazioni decisive da verificare.' : 'Osservazioni e misure proposte · da confermare nelle condizioni effettive.';
    $('assessment-state').className = 'assessment-state' + (hasUnknown ? ' incomplete' : '');
    $('findings').replaceChildren();
    let image = $('preview'); try { await image.decode(); } catch { image = null; }
    // Snapshot only the photo and context used by this successful request.
    const meta = analysis.meta || {};
    $('case-summary').replaceChildren();
    $('case-summary').append(make('h3', 'Situazione analizzata'));
    if (image && state.imageUrl) {
      const photo = make('img'); photo.src = state.imageUrl; photo.alt = 'Fotografia completa utilizzata per questa analisi'; photo.className = 'case-photo';
      $('case-summary').append(photo);
    } else $('case-summary').append(make('p', 'Fotografia non disponibile per la stampa. Verificare il rapporto con la foto originale.', 'notice warning'));
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
        const link = make('a', 'Apri la fotografia completa'); link.href = state.imageUrl; link.target = '_blank'; link.rel = 'noopener'; fallback.append(link, make('span', image ? 'Consulta la fotografia completa all’inizio del rapporto.' : 'Confrontare con la foto originale, non disponibile in questa stampa.', 'print-photo-reference')); card.append(fallback);
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
