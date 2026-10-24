'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const state = { csrf: '', authenticated: false, configured: false, busy: false, file: null, imageUrl: null, analysis: null, controller: null, answers: new Map(), submittedContext: '' };
  const certaintyLabels = { visible: 'Visibile nella foto', reported: 'Riferito dall’utilizzatore', verify: 'Da verificare sul posto' };
  const riskLabels = { high: 'Rischio alto', medium: 'Rischio medio', low: 'Rischio basso', undetermined: 'Rischio da determinare' };
  const make = (tag, text, cls) => { const el = document.createElement(tag); if (text != null) el.textContent = String(text); if (cls) el.className = cls; return el; };
  function notice(text, kind = '') { $('status').textContent = text; $('status').className = 'notice' + (kind ? ' ' + kind : ''); $('status').hidden = !text; }
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
    $('busy-state').hidden = !value; $('report').hidden = value || !state.analysis; $('empty-state').hidden = value || Boolean(state.analysis);
    $('result-region').setAttribute('aria-busy', String(value));
  }
  function clearAnalysis() { state.analysis = null; state.answers.clear(); state.submittedContext = ''; $('report').hidden = true; $('empty-state').hidden = false; $('findings').replaceChildren(); $('questions').replaceChildren(); }
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
    if (file.size > 10 * 1024 * 1024) { notice('La fotografia supera 10 MB. Scegli un file più piccolo.', 'error'); $('photo').value = ''; return; }
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) { notice('Scegli una fotografia JPG, PNG o WebP.', 'error'); $('photo').value = ''; return; }
    state.file = file; state.imageUrl = URL.createObjectURL(file); $('preview').src = state.imageUrl; $('file-name').textContent = file.name; $('preview-wrap').hidden = false;
  });
  function composedContext() {
    const parts = [$('context').value.trim()];
    if (state.answers.size) parts.push('Chiarimenti forniti dall’utilizzatore:\n' + Array.from(state.answers.entries()).map(([question, answer]) => question + '\nRisposta: ' + answer).join('\n\n'));
    return parts.filter(Boolean).join('\n\n');
  }
  async function analyse() {
    if (state.busy) return;
    if (!state.file) { notice('Seleziona una fotografia prima di avviare l’analisi.', 'error'); return; }
    const context = composedContext(); if (context.length > 8000) { notice('Il contesto e le risposte superano 8.000 caratteri. Riduci i dettagli secondari prima di continuare.', 'error'); return; }
    if (!state.configured) { notice('Completa la configurazione del servizio prima di avviare un’analisi.', 'warning'); return; }
    notice(''); setBusy(true); state.controller = new AbortController();
    const form = new FormData(); form.append('file', state.file); form.append('context', context);
    try {
      const data = await api('/analizza', { method: 'POST', headers: { 'X-CSRF-Token': state.csrf }, body: form, signal: state.controller.signal });
      if (!data.analysis || !Array.isArray(data.analysis.findings)) throw new Error('Il risultato è incompleto. Non è stato presentato come analisi valida.');
      state.analysis = data.analysis; state.submittedContext = context; await renderAnalysis(data.analysis);
      $('report').hidden = false;
    } catch (err) {
      if (err.status === 401) {
        applySession({ authenticated: false, configured: false });
        try { applySession(await api('/api/session')); notice('Sessione scaduta. Accedi nuovamente per continuare. Foto, contesto e risultato precedente restano in questa pagina.', 'warning'); }
        catch { $('login-button').disabled = true; notice('Sessione scaduta. Ricarica la pagina per ottenere un nuovo accesso. I dati non esportati andranno persi.', 'error'); }
      }
      else {
        const message = err.name === 'AbortError' ? 'Richiesta interrotta. Non è stata avviata automaticamente una nuova analisi.' : err.message;
        notice(message + (state.analysis ? ' L’aggiornamento non è riuscito: resta visibile il risultato dell’analisi precedente.' : ''), 'error');
      }
    } finally { state.controller = null; setBusy(false); }
  }
  $('analysis-form').addEventListener('submit', e => { e.preventDefault(); analyse(); });
  $('questions-form').addEventListener('submit', e => {
    e.preventDefault();
    $('questions').querySelectorAll('textarea').forEach(input => { const answer = input.value.trim(); if (answer) state.answers.set(input.dataset.question, answer); else state.answers.delete(input.dataset.question); });
    analyse();
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
    ctx.drawImage(image, x * image.naturalWidth, y * image.naturalHeight, sw, sh, 0, 0, canvas.width, canvas.height);
    const caption = make('figcaption'); caption.append(make('span', 'Dettaglio indicato dall’AI'));
    const link = make('a', 'Foto completa'); link.href = state.imageUrl; link.target = '_blank'; link.rel = 'noopener'; caption.append(link); figure.append(canvas, caption); return figure;
  }
  function validUrl(url) { try { const parsed = new URL(url); return parsed.protocol === 'https:' ? parsed.href : null; } catch { return null; } }
  async function renderAnalysis(analysis) {
    $('summary').textContent = analysis.summary || '';
    const hasUnknown = Boolean(analysis.needs_clarification) || analysis.findings.some(f => f.critical_unknown || f.risk === 'undetermined') || (analysis.questions || []).some(q => q.critical);
    $('assessment-state').textContent = hasUnknown ? 'Valutazione da completare · restano informazioni decisive da verificare.' : 'Osservazioni e misure proposte · da confermare nelle condizioni effettive.';
    $('assessment-state').className = 'assessment-state' + (hasUnknown ? ' incomplete' : '');
    $('findings').replaceChildren();
    let image = $('preview'); try { await image.decode(); } catch { image = null; }
    const priority = f => f.risk === 'high' ? 0 : f.critical_unknown ? 1 : ({ undetermined: 2, medium: 3, low: 4 }[f.risk] ?? 5);
    const ordered = [...analysis.findings].sort((a, b) => priority(a) - priority(b));
    if (!ordered.length) $('findings').append(make('p', 'Nessuna osservazione strutturata restituita. Questo non dimostra l’assenza di pericoli.', 'notice warning'));
    for (const finding of ordered) {
      const risk = Object.hasOwn(riskLabels, finding.risk) ? finding.risk : 'undetermined';
      const card = make('section', null, 'finding ' + risk), top = make('div', null, 'finding-topline');
      top.append(make('span', 'Osservazione ' + finding.id, 'finding-id'), make('span', riskLabels[risk], 'risk-tag ' + risk)); card.append(top, make('h3', finding.title));
      const crop = await createCrop(finding.bbox, image, finding.id); if (crop) card.append(crop);
      card.append(make('p', certaintyLabels[finding.certainty] || 'Da verificare sul posto', 'evidence-label'), make('p', finding.evidence, 'evidence-text'));
      const measure = make('div', null, 'measure'); measure.append(make('p', 'Cosa fare', 'measure-label'), make('p', finding.action, 'measure-action'), make('p', 'Quando: ' + (finding.deadline || 'Da definire dopo gli accertamenti'), 'deadline')); card.append(measure);
      addText(card, 'p', finding.exposed_people ? 'Persone esposte: ' + finding.exposed_people : '', 'finding-detail');
      addText(card, 'p', finding.question ? 'Da chiarire: ' + finding.question : '', 'finding-question');
      const cited = (finding.references || []).map(ref => (analysis.sources || []).find(s => s.id === ref.source_id)).filter(Boolean);
      if (cited.length) { const p = make('p', 'Riferimenti: ', 'finding-detail'); cited.forEach((source, index) => { if (index) p.append(document.createTextNode(' · ')); const url = validUrl(source.url); const link = make(url ? 'a' : 'span', source.title); if (url) { link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer'; } p.append(link); }); card.append(p); }
      $('findings').append(card);
    }
    const questionList = [...(analysis.questions || [])].sort((a, b) => Number(b.critical) - Number(a.critical));
    $('questions').replaceChildren(); $('questions-panel').hidden = !questionList.length;
    $('print-questions').replaceChildren();
    if (questionList.length) {
      $('print-questions').append(make('h3', 'Domande ancora da chiarire'));
      const list = make('ul');
      questionList.forEach(q => list.append(make('li', (q.critical ? 'Informazione decisiva: ' : '') + q.text + (q.why ? ' — ' + q.why : ''))));
      $('print-questions').append(list);
    }
    let furtherQuestions = null;
    if (questionList.length > 3) {
      furtherQuestions = make('details', null, 'further-questions');
      const extraCritical = questionList.slice(3).some(q => q.critical);
      furtherQuestions.append(make('summary', 'Altre domande' + (extraCritical ? ' decisive' : '') + ' (' + (questionList.length - 3) + ')'));
    }
    questionList.forEach((q, index) => {
      const wrapper = make('div', null, 'question'); if (q.critical) wrapper.append(make('span', 'Informazione decisiva', 'critical-label'));
      const id = 'answer-' + index, label = make('label', q.text); label.htmlFor = id; const input = make('textarea'); input.id = id; input.rows = 2; input.maxLength = 1500; input.dataset.question = q.text; input.value = state.answers.get(q.text) || '';
      if (q.why) { const why = make('p', q.why, 'why'); why.id = id + '-why'; input.setAttribute('aria-describedby', why.id); wrapper.append(label, why, input); } else wrapper.append(label, input);
      if (index < 3) $('questions').append(wrapper); else furtherQuestions.append(wrapper);
    });
    if (furtherQuestions) $('questions').append(furtherQuestions);
    $('limitations').replaceChildren();
    if (Array.isArray(analysis.limitations) && analysis.limitations.length) { $('limitations').append(make('h3', 'Cosa resta da accertare')); const list = make('ul'); analysis.limitations.forEach(item => list.append(make('li', item))); $('limitations').append(list); }
    $('sources').replaceChildren(); $('sources').append(make('h3', 'Fonti disponibili per questa analisi'));
    if (analysis.sources?.length) {
      const list = make('ul'); analysis.sources.forEach(source => { const li = make('li'); const url = validUrl(source.url), link = make(url ? 'a' : 'span', source.title); if (url) { link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer'; } li.append(link); if (source.verified_at) li.append(document.createTextNode(' · verifica: ' + source.verified_at)); list.append(li); }); $('sources').append(list);
    } else $('sources').append(make('p', 'Nessuna fonte normativa verificata è associata a questa analisi. Gli obblighi specifici richiedono verifica prima di essere presentati come accertati.'));
    const meta = analysis.meta || {}, parts = [];
    if (meta.method_version || meta.prompt_version) parts.push('Metodo: ' + (meta.method_version || meta.prompt_version)); if (meta.model) parts.push('Modello: ' + meta.model); if (meta.created_at) parts.push('Analisi: ' + meta.created_at);
    $('analysis-meta').textContent = parts.join(' · ');
  }
  $('export-json').addEventListener('click', () => {
    if (!state.analysis) return;
    const data = { exported_at: new Date().toISOString(), photograph_included: false, context: state.submittedContext, analysis: state.analysis };
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
    const link = make('a'); link.href = url; link.download = 'SLPS_AI_analisi_' + new Date().toISOString().slice(0, 10) + '.json'; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    notice('Analisi esportata in JSON. La fotografia non è inclusa nel file.');
  });
  $('print-report').addEventListener('click', () => { if (state.analysis) { $('details-panel').open = true; window.print(); } });
  api('/api/session').then(applySession).catch(err => { $('login-panel').hidden = false; notice(err.message, 'error'); });
})();
