'use strict';
// Submission state tests with a small DOM double. These do not replace visual/browser QA.
// Run with: node --test tests/test_ui_feedback.cjs (no npm dependencies).
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const script = fs.readFileSync(path.join(root, 'static/app.js'), 'utf8');
const template = fs.readFileSync(path.join(root, 'templates/index.html'), 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));

async function fixture({ reducedMotion = false, imageAvailable = false, initialCases = [], caseStorage = null, caseListStatus = 200, sessionResponses = [], deferHistory = false, sessionData = {}, initialLocale = null } = {}) {
  const elements = new Map(), requests = [], historyGets = [], scrolls = [], exports = [], prints = [], navigations = [];
  const stored = new Map(initialLocale ? [['slps.locale', initialLocale]] : []), storageWrites = [];
  let currentCases = [...initialCases];
  let doc;
  class Element {
    constructor(tag = 'div', id = '') { this.tagName = tag.toUpperCase(); this.id = id; this.hidden = false; this.disabled = false; this.value = ''; this.textContent = ''; this.className = ''; this.dataset = {}; this.attrs = {}; this.childNodes = []; this.handlers = {}; this.files = []; }
    addEventListener(name, handler) { this.handlers[name] = handler; }
    get textContent() { return this.childNodes.map(child => child instanceof Element ? child.textContent : String(child)).join(''); }
    set textContent(value) { this.childNodes = value === '' ? [] : [String(value)]; }
    setAttribute(name, value) { this.attrs[name] = value; }
    removeAttribute(name) { delete this.attrs[name]; }
    append(...children) { this.childNodes.push(...children); }
    replaceChildren(...children) { this.childNodes = children; }
    focus() { doc.activeElement = this; }
    click() { if (this.handlers.click) return this.handlers.click(); }
    remove() { this.hidden = true; }
    scrollIntoView(options) { scrolls.push({ id: this.id, ...options }); }
    querySelectorAll(selector) { const matches = child => selector.startsWith('.') ? child.className.split(/\s+/).includes(selector.slice(1)) : child.tagName.toLowerCase() === selector; return this.childNodes.flatMap(child => child instanceof Element ? [...(matches(child) ? [child] : []), ...child.querySelectorAll(selector)] : []); }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
    cloneNode() { const copy = new Element(this.tagName, this.id); Object.assign(copy, this); copy.childNodes = this.childNodes.map(child => child instanceof Element ? child.cloneNode(true) : child); copy.handlers = {}; return copy; }
    async decode() { if (!imageAvailable) throw new Error('No bitmap in this DOM fixture'); }
    getContext() { return { drawImage() {} }; }
    reset() { this.value = ''; }
  }
  for (const match of template.matchAll(/<([a-z][\w-]*)\b[^>]*\bid="([^"]+)"[^>]*>/g)) {
    const element = new Element(match[1], match[2]); element.hidden = /\bhidden\b/.test(match[0]); elements.set(element.id, element);
  }
  const $ = id => elements.get(id);
  $('preview').naturalWidth = 640; $('preview').naturalHeight = 480;
  // The report draft isolates all report field writes until renderAnalysis commits them.
  $('report').cloneNode = () => {
    const copies = new Map([...elements].filter(([id]) => id !== 'report').map(([id, element]) => [id, element.cloneNode(true)]));
    return { querySelector: selector => copies.get(selector.slice(1)) };
  };
  doc = { getElementById: $, createElement: tag => new Element(tag), createTextNode: text => text, body: new Element('body'), documentElement: {}, activeElement: null };
  const session = { authenticated: true, configured: true, csrf: 'test-csrf', ...sessionData };
  let sessionReadCount = 0;
  const response = (data, status = 200) => ({ ok: status < 400, status, json: async () => data });
  const context = { document: doc, navigator: { language: 'it-CH' }, window: { matchMedia: () => ({ matches: reducedMotion }), localStorage: { getItem: key => stored.get(key) || null, setItem: (key, value) => { stored.set(key, value); storageWrites.push([key, value]); } }, location: { assign: value => navigations.push(value) }, print() { prints.push(true); } }, URL: class extends URL { static createObjectURL(value) { if (value instanceof Blob) exports.push(value); return 'blob:test-photo'; } static revokeObjectURL() {} }, Blob, AbortController, FormData: class { append() {} }, setTimeout: callback => { callback(); }, console,
    fetch: async (url, options = {}) => {
      if (url === '/api/session') {
        if (sessionReadCount++ === 0) return response(session);
        const next = sessionResponses.shift(); return next ? response(next.data, next.status || 200) : response(session);
      }
      if (url === '/api/cases' && (!options.method || options.method === 'GET')) {
        if (deferHistory) return new Promise(resolve => historyGets.push({ url, options, resolve: () => resolve(response({ cases: currentCases, storage: caseStorage })) }));
        historyGets.push({ url, options }); return caseListStatus < 400 ? response({ cases: currentCases, storage: caseStorage }) : response({ error: { message: 'Archivio temporaneamente non disponibile' } }, caseListStatus);
      }
      return new Promise(resolve => requests.push({ url, options, resolve: (data, status) => resolve(response(data, status)) }));
    } };
  vm.runInNewContext(script, context, { filename: 'static/app.js' }); await tick();
  function photo(name = 'sample.jpg') { $('photo').files = [{ name, type: 'image/jpeg', size: 100 }]; $('photo').handlers.change(); }
  function video(name = 'sample.mp4') { $('photo').files = [{ name, type: 'video/mp4', size: 100 }]; $('photo').handlers.change(); }
  async function submit(origin = 'analysis') { $(origin + '-form').handlers.submit({ preventDefault() {} }); await tick(); }
  async function finishRequest(expectedUrl, data, status = 200) {
    const request = requests.shift(); assert.equal(request.url, expectedUrl);
    if (request.options.method === 'DELETE' && status < 400 && data.deleted) currentCases = currentCases.filter(item => '/api/cases/' + encodeURIComponent(item.id) !== expectedUrl);
    request.resolve(data, status); await tick(); await tick();
  }
  async function finish(data, status = 200) { await finishRequest('/analizza', data, status); }
  return { $, doc, photo, video, submit, finish, finishRequest, requests, historyGets, scrolls, exports, prints, navigations, session, Element, storageWrites, i18n: context.window.SLPS_APP_I18N };
}
const report = (summary = 'Valid report') => ({ findings: [], questions: [], sources: [], summary });

test('app locale dictionaries have parity and the explicit selector persists only the shared locale key', async () => {
  assert.match(template, /id="app-language"/);
  for (const code of ['it', 'de', 'fr', 'en']) assert.match(template, new RegExp('option value="' + code + '"'));
  const f = await fixture();
  const keys = Object.keys(f.i18n.messages.it).sort();
  for (const code of f.i18n.locales) assert.deepEqual(Object.keys(f.i18n.messages[code]).sort(), keys);
  f.$('app-language').value = 'de';
  await f.$('app-language').handlers.change({ target: f.$('app-language') });
  assert.deepEqual(f.storageWrites, [['slps.locale', 'de']]);
  assert.equal(f.doc.documentElement.lang, 'de');
  assert.equal(f.$('workspace-title').textContent, 'Arbeitssituation analysieren.');
  assert.equal(f.requests.length, 0, 'changing language must not issue a provider request');
});

test('all four metadata descriptions distinguish photo AI analysis from technical video and audio verification', async () => {
  const f = await fixture();
  const descriptions = f.i18n.metaDescriptions;
  assert.deepEqual(Object.keys(descriptions).sort(), ['de', 'en', 'fr', 'it']);
  assert.equal(template.includes(`content="${descriptions.it}"`), true);
  for (const code of ['it', 'de', 'fr', 'en']) {
    assert.match(descriptions[code], /AI|IA|KI/);
    assert.match(descriptions[code], /foto|Foto|photos/);
    assert.match(descriptions[code], /tecnic|technisch|technique|technical/i);
    assert.match(descriptions[code], /vid[ée]o/i);
    assert.match(descriptions[code], /audio/i);
  }
});

test('all four locales render dynamic validation and localized dates', async () => {
  const expected = { it: 'Seleziona una foto', de: 'Wählen Sie vor dem Start', fr: 'Sélectionnez une photo', en: 'Select a photo' };
  for (const code of ['it', 'de', 'fr', 'en']) {
    const f = await fixture({ initialLocale: code, initialCases: [{ id: code, created_at: 1792920000, summary: 'Verbatim summary', context: '' }] });
    await f.submit();
    assert.match(f.$('analysis-feedback').textContent, new RegExp(expected[code]));
    const date = f.$('history-list').childNodes[0].querySelector('.history-date').textContent;
    assert.equal(date, new Intl.DateTimeFormat({ it:'it-CH', de:'de-CH', fr:'fr-CH', en:'en-CH' }[code], { dateStyle:'medium', timeStyle:'short' }).format(new Date(1792920000 * 1000)));
  }
});

test('non-Italian locales never echo an Italian backend error message', async () => {
  const f = await fixture({ initialLocale: 'en' });
  f.photo(); await f.submit();
  await f.finish({ error: { code: 'provider_unavailable', message: 'Servizio non disponibile in italiano' } }, 503);
  assert.match(f.$('analysis-feedback').textContent, /temporarily unavailable/i);
  assert.doesNotMatch(f.$('analysis-feedback').textContent, /Servizio|italiano/);
});

test('anonymous and pending company accounts return to the dedicated account page without fetching cases', async () => {
  for (const sessionData of [
    { auth_mode: 'accounts', authenticated: false },
    { auth_mode: 'accounts', verification_required: true, account: { eligible_for_analysis: false } },
    { auth_mode: 'accounts', verification_required: false, account: {} },
  ]) {
    const f = await fixture({ sessionData });
    assert.deepEqual(f.navigations, ['/account']);
    assert.equal(f.historyGets.length, 0);
    assert.equal(f.$('workspace').hidden, true);
    assert.equal(f.$('login-panel').hidden, true);
  }
});

test('verified company accounts can enter the workspace and find the account link', async () => {
  const f = await fixture({ sessionData: { auth_mode: 'accounts', verification_required: false, account: { eligible_for_analysis: true } } });
  assert.deepEqual(f.navigations, []);
  assert.equal(f.$('workspace').hidden, false);
  assert.equal(f.$('account-link').hidden, false);
  assert.equal(f.historyGets.length, 1);
});

test('an expired company session leaves the pilot login hidden and returns to account access', async () => {
  const f = await fixture({
    sessionData: { auth_mode: 'accounts', account: { eligible_for_analysis: true } },
    sessionResponses: [{ data: { auth_mode: 'accounts', authenticated: false, csrf: 'rotated' } }],
  });
  f.photo(); await f.submit();
  await f.finish({ error: { message: 'Session expired' } }, 401);
  assert.deepEqual(f.navigations, ['/account']);
  assert.equal(f.$('login-panel').hidden, true);
});

test('video intake verifies frames and audio without claiming AI analysis', async () => {
  const f = await fixture({ sessionData: { media: { image_max_bytes: 10485760, video_max_bytes: 52428800, video_intake_enabled: true, video_analysis_enabled: false } } });
  f.video();
  assert.equal(f.$('media-note').hidden, false);
  assert.match(f.$('media-note').textContent, /non esegue ancora l’analisi AI/);
  assert.equal(f.$('analyse-button').disabled, false);
  await f.submit();
  assert.equal(f.requests.length, 1);
  await f.finishRequest('/api/media/inspect', { message: 'Video e audio verificati localmente.', media: { duration_seconds: 1.2, frames: [{ timestamp_seconds: 0.4, image_data_url: 'data:image/jpeg;base64,AA==' }], audio: { status: 'ready_for_transcription' } }, archive: { saved: true, case_id: 'video-case' }, trial_consumed: false });
  assert.equal(f.$('video-evidence').hidden, false);
  assert.match(f.$('audio-summary').textContent, /non sono ancora state verificate/);
  assert.match(f.$('media-note').textContent, /non è stata consumata.*salvati nello storico protetto/);
  assert.equal(f.$('empty-state').hidden, true);
});

test('saved technical video reopens with protected evidence and no AI-risk claim', async () => {
  const saved = { id: 'video-case', created_at: 1792920000, summary: 'Verifica tecnica di video e audio', context: 'Area di carico', kind: 'video_technical_verification' };
  const f = await fixture({ initialCases: [saved] }); await tick();
  const card = f.$('history-list').childNodes[0], open = card.querySelectorAll('button')[0];
  assert.equal(open.textContent, 'Apri verifica');
  assert.match(card.textContent, /senza analisi dei rischi AI/);
  open.click(); await tick();
  await f.finishRequest('/api/cases/video-case', { case: {
    ...saved,
    analysis: { summary: saved.summary, findings: [], meta: { case_kind: 'video_technical_verification', analysis_performed: false, video_inspection: { duration_seconds: 1.2, frames: [{ timestamp_seconds: 0.4 }], audio: { status: 'ready_for_transcription' } } } },
    assets: [
      { id: 'video-1', role: 'original', filename: 'scene.mp4', media_type: 'video/mp4', download_url: '/api/cases/video-case/assets/video-1' },
      { id: 'frame-1', role: 'frame', filename: 'frame-01-0.400s.jpg', media_type: 'image/jpeg', download_url: '/api/cases/video-case/assets/frame-1' },
    ],
  } });
  assert.equal(f.$('video-evidence').hidden, false);
  assert.equal(f.$('archived-video').src, '/api/cases/video-case/assets/video-1');
  assert.equal(f.$('video-frames').querySelector('img').src, '/api/cases/video-case/assets/frame-1');
  assert.match(template, /Non è stata eseguita un’analisi dei rischi con l’AI/);
  assert.match(f.$('video-archive-note').textContent, /caso protetto.*traccia audio presente.*mantenuta/);
  assert.equal(f.$('report').hidden, true); assert.equal(f.$('input-panel').hidden, true);
  assert.equal(f.doc.activeElement.id, 'video-evidence-title');
});

test('saved video without audio states that no audio track exists', async () => {
  const saved = { id: 'silent-container', created_at: 1792920000, summary: 'Verifica tecnica di video e audio', context: '', kind: 'video_technical_verification' };
  const f = await fixture({ initialCases: [saved] }); await tick();
  f.$('history-list').querySelectorAll('button')[0].click(); await tick();
  await f.finishRequest('/api/cases/silent-container', { case: {
    ...saved,
    analysis: { summary: saved.summary, findings: [], meta: { case_kind: 'video_technical_verification', analysis_performed: false, video_inspection: { duration_seconds: 1, frames: [], audio: { status: 'absent' } } } },
    assets: [{ id: 'video-1', role: 'original', filename: 'scene.mp4', media_type: 'video/mp4', download_url: '/api/cases/silent-container/assets/video-1' }],
  } });
  assert.match(f.$('video-archive-note').textContent, /non contiene una traccia audio/);
  assert.doesNotMatch(f.$('video-archive-note').textContent, /audio incorporata/);
  assert.match(f.$('audio-summary').textContent, /Nessuna traccia audio/);
});

test('video archive quota failure keeps the completed technical evidence visible', async () => {
  const f = await fixture({ sessionData: { media: { video_max_bytes: 52428800, video_intake_enabled: true } } });
  f.video(); await f.submit();
  await f.finishRequest('/api/media/inspect', {
    message: 'Video e audio verificati localmente.',
    media: { duration_seconds: 2, frames: [{ timestamp_seconds: 1, image_data_url: 'data:image/jpeg;base64,AA==' }], audio: { status: 'absent' } },
    archive: { saved: false, case_id: null, message: 'Spazio archivio esaurito: i casi esistenti restano disponibili.' },
    trial_consumed: false,
  });
  assert.equal(f.$('video-evidence').hidden, false);
  assert.equal(f.$('empty-state').hidden, true);
  assert.match(f.$('media-note').textContent, /prova gratuita non è stata consumata.*Spazio archivio esaurito/);
});

test('trial result remains readable while print and export are unavailable', async () => {
  const trial = { plan: 'trial', analyses_total: 1, analyses_used: 0, analyses_remaining: 1, clarifications_remaining: 1, export_allowed: false };
  const f = await fixture({ sessionData: { entitlement: trial } });
  f.photo(); await f.submit();
  await f.finish({ analysis: report(), archive: { saved: true, case_id: 'case-1' }, entitlement: { ...trial, analyses_used: 1, analyses_remaining: 0 } });
  assert.equal(f.$('report').hidden, false);
  assert.equal(f.$('print-report').hidden, true);
  assert.equal(f.$('export-json').hidden, true);
  assert.equal(f.$('trial-export-note').hidden, false);
});

test('trial archive failure does not suggest an unavailable export', async () => {
  const trial = { plan: 'trial', analyses_total: 1, analyses_used: 0, analyses_remaining: 1, clarifications_remaining: 1, export_allowed: false };
  const f = await fixture({ sessionData: { entitlement: trial } });
  f.photo(); await f.submit();
  await f.finish({
    analysis: report(),
    archive: { saved: false, case_id: null, clarification_available: false, message: 'Risultato non archiviato. Il chiarimento incluso richiede un caso salvato.' },
    entitlement: { ...trial, analyses_used: 1, analyses_remaining: 0 },
  });
  assert.doesNotMatch(f.$('report-notice').textContent, /Esporta/);
  assert.match(f.$('report-notice').textContent, /resta consultabile/);
});

test('loading is focused; completion focuses its title and enables report actions', async () => {
  const f = await fixture(); f.photo(); await f.submit();
  assert.equal(f.doc.activeElement.id, 'busy-title'); assert.equal(f.$('busy-state').hidden, false);
  assert.equal(f.$('analyse-button').disabled, true); assert.equal(f.$('result-region').attrs['aria-busy'], 'true');
  await f.finish({ analysis: report() });
  assert.equal(f.doc.activeElement.id, 'report-title'); assert.equal(f.$('report').hidden, false);
  assert.equal(f.$('report-title').textContent, 'Analisi completata'); assert.equal(f.$('export-json').disabled, false);
  assert.equal(f.$('result-region').attrs['aria-labelledby'], 'report-title');
});

test('a failed update preserves the previous report and places its error beside the question action', async () => {
  const f = await fixture(); f.photo(); f.$('context').value = 'Original context'; await f.submit();
  await f.finish({ analysis: { ...report('Previous report'), questions: [{ text: 'Is the guard fitted?', critical: true }] } });
  const answer = f.$('questions').querySelectorAll('textarea')[0]; answer.value = 'Yes';
  f.$('context').value = 'Changed context';
  await f.submit('questions'); await f.finish({ error: { message: 'Temporary failure' } }, 503);
  assert.equal(f.$('summary').textContent, 'Previous report'); assert.equal(f.$('report-title').textContent, 'Analisi precedente');
  assert.equal(f.$('report-notice').hidden, false); assert.equal(f.$('questions-feedback').hidden, false);
  assert.equal(f.doc.activeElement.id, 'questions-feedback'); assert.equal(f.$('analysis-feedback').hidden, true);
  assert.equal(f.$('export-json').disabled, false); assert.equal(f.$('questions').querySelectorAll('textarea')[0].value, 'Yes');
  f.$('export-json').handlers.click();
  const exported = JSON.parse(await f.exports.at(-1).text());
  assert.equal(exported.analysis.summary, 'Previous report'); assert.equal(exported.context, 'Original context');
  f.photo('different.jpg');
  assert.equal(f.$('report').hidden, true); assert.equal(f.$('empty-state').hidden, false);
  assert.equal(f.$('export-json').disabled, true); assert.equal(f.$('print-report').disabled, true);
  assert.equal(f.$('questions').childNodes.length, 0); assert.equal(f.$('questions-feedback').hidden, true);
  await f.submit(); await f.finish({ error: { message: 'Temporary failure' } }, 503);
  assert.equal(f.$('report').hidden, true); assert.equal(f.doc.activeElement.id, 'analysis-feedback');
  assert.match(f.$('analysis-feedback').textContent, /Nessun risultato/);
});

test('rendering failures cannot replace a valid report with partially rendered data', async () => {
  const f = await fixture(); f.photo(); await f.submit(); await f.finish({ analysis: report('Keep this report') });
  await f.submit(); await f.finish({ analysis: { ...report('Broken report'), findings: [null] } });
  assert.equal(f.$('summary').textContent, 'Keep this report'); assert.equal(f.$('report-title').textContent, 'Analisi precedente');
  assert.equal(f.$('report').hidden, false); assert.equal(f.$('export-json').disabled, false);
  await f.submit(); await f.finish({ analysis: report('Recovered') });
  assert.equal(f.$('summary').textContent, 'Recovered'); assert.equal(f.$('report-title').textContent, 'Analisi completata');
  assert.equal(f.$('report-notice').hidden, true); assert.equal(f.$('analysis-feedback').hidden, true);
});

test('expired sessions focus a visible login notice while keeping the previous report', async () => {
  const f = await fixture(); f.photo(); await f.submit(); await f.finish({ analysis: report() });
  await f.submit(); f.session.authenticated = false; f.session.configured = false;
  await f.finish({ error: { message: 'Session expired' } }, 401);
  assert.equal(f.$('workspace').hidden, true); assert.equal(f.$('login-panel').hidden, false);
  assert.equal(f.doc.activeElement.id, 'status'); assert.equal(f.$('status').hidden, false);
  assert.equal(f.$('summary').textContent, 'Valid report'); assert.equal(f.$('report-title').textContent, 'Analisi precedente');
});

test('reduced motion uses instant scrolling and completion does not steal focus after navigation', async () => {
  const f = await fixture({ reducedMotion: true }); f.photo(); await f.submit();
  assert.equal(f.scrolls.at(-1).behavior, 'instant');
  const anotherField = new f.Element('textarea', 'elsewhere'); anotherField.focus();
  await f.finish({ analysis: report() });
  assert.equal(f.doc.activeElement, anotherField); assert.match(f.$('analysis-announcement').textContent, /Analisi completata/);
});

test('invalid inputs stay near the primary action and never issue an analysis request', async () => {
  const f = await fixture(); await f.submit();
  assert.equal(f.requests.length, 0); assert.equal(f.doc.activeElement.id, 'analysis-feedback');
  f.photo(); f.$('context').value = 'x'.repeat(8001); await f.submit();
  assert.equal(f.requests.length, 0); assert.match(f.$('analysis-feedback').textContent, /8.000/);
});

const finding = id => ({ id, title: 'Proteggere il passaggio', risk: 'high', certainty: 'visible', evidence: 'Apertura visibile', action: 'Installare una protezione stabile', deadline: 'Prima di accedere alla zona', bbox: { x: 0, y: 0, width: 0.5, height: 0.5 } });

test('actions and deadlines precede the numbered crop and evidence, with a fallback when no crop is available', async () => {
  const f = await fixture({ imageAvailable: true }); f.photo(); await f.submit();
  await f.finish({ analysis: { ...report(), findings: [finding('A1'), { ...finding('A2'), bbox: null }] } });
  const [first, second] = f.$('findings').childNodes;
  assert.equal(first.childNodes[2].className, 'measure');
  assert.match(first.childNodes[2].textContent, /Installare una protezione stabile.*Quando: Prima di accedere/);
  assert.equal(first.childNodes[3].className, 'crop');
  assert.match(first.childNodes[3].textContent, /Osservazione A1/);
  assert.match(first.childNodes[0].textContent, /Rischio alto/);
  assert.equal(first.childNodes[4].className, 'evidence-label');
  assert.match(second.childNodes[3].textContent, /Osservazione A2.*Ritaglio non disponibile/);
  assert.equal(second.childNodes[3].querySelector('a').href, f.$('preview').src);
});

test('a long report exposes all decisive questions and only collapses secondary questions', async () => {
  const f = await fixture(); f.photo(); await f.submit();
  const questions = Array.from({ length: 9 }, (_, i) => ({ text: 'Domanda ' + (i + 1), critical: i < 4 }));
  await f.finish({ analysis: { ...report(), findings: Array.from({ length: 12 }, (_, i) => finding('R' + i)), questions } });
  assert.match(f.$('assessment-state').textContent, /Valutazione da completare/);
  assert.match(f.$('question-summary').textContent, /Domande da chiarire: 9.*Informazioni decisive: 4/);
  assert.equal(f.$('question-summary').hidden, false);
  const children = f.$('questions').childNodes;
  assert.equal(children.length, 8); // Four decisive + three secondary + two in details.
  for (let i = 0; i < 4; i++) { assert.equal(children[i].tagName, 'DIV'); assert.match(children[i].textContent, /Informazione decisiva/); }
  const collapsed = children.at(-1); assert.equal(collapsed.tagName, 'DETAILS');
  assert.doesNotMatch(collapsed.textContent, /Informazione decisiva/);
  assert.equal(collapsed.querySelectorAll('textarea').length, 2);
  f.$('question-summary').querySelector('button').handlers.click();
  assert.equal(f.doc.activeElement.id, 'questions-title');
  assert.equal(f.$('print-questions').querySelectorAll('li').length, 9);
  assert.ok(template.indexOf('id="question-summary"') < template.indexOf('id="findings"'));
});

test('printed photo, context and metadata belong to the successful report, including after a failed update', async () => {
  const f = await fixture({ imageAvailable: true }); f.photo(); f.$('context').value = 'Contesto realmente inviato'; await f.submit();
  await f.finish({ analysis: { ...report(), meta: { created_at: '2026-10-01T10:00:00Z', method_version: 'test-method' } } });
  const before = f.$('case-summary').textContent;
  assert.match(before, /Contesto realmente inviato/); assert.match(before, /2026-10-01T10:00:00Z.*test-method/);
  const photo = f.$('case-summary').querySelector('img'); assert.equal(photo.src, f.$('preview').src);
  f.$('context').value = 'Testo modificato e non acquisito'; await f.submit(); await f.finish({ error: { message: 'Errore' } }, 503);
  assert.equal(f.$('case-summary').textContent, before);
  assert.equal(f.$('case-summary').querySelector('img'), photo);
  await f.$('print-report').handlers.click(); assert.equal(f.prints.length, 1);
  photo.decode = async () => { throw new Error('Photo not ready'); };
  await f.$('print-report').handlers.click(); assert.equal(f.prints.length, 1);
  assert.match(f.$('status').textContent, /fotografia non è pronta/);
  f.photo('new.jpg'); assert.equal(f.$('case-summary').childNodes.length, 0);
  assert.equal(f.$('question-summary').hidden, true); assert.equal(f.$('print-report').disabled, true);
});

test('decisive questions attached only to findings are visible, deduplicated and associated with their observations', async () => {
  const f = await fixture(); f.photo(); await f.submit();
  const findings = Array.from({ length: 12 }, (_, i) => ({ ...finding('R' + (i + 1)), critical_unknown: i < 4, question: i < 4 ? 'Verifica ' + (i + 1) + '?' : '' }));
  await f.finish({ analysis: { ...report(), findings, questions: [] } });
  assert.match(f.$('question-summary').textContent, /Domande da chiarire: 4.*Informazioni decisive: 4/);
  assert.equal(f.$('questions').querySelectorAll('textarea').length, 4);
  assert.equal(f.$('questions').querySelectorAll('details').length, 0);
  assert.match(f.$('questions').childNodes[0].textContent, /Osservazioni: R1/);
  assert.match(f.$('print-questions').textContent, /Osservazioni: R4/);
  await f.submit();
  await f.finish({ analysis: { ...report(), findings, questions: [{ text: ' Verifica 1? ', critical: false, why: 'Dettaglio non leggibile' }] } });
  assert.match(f.$('question-summary').textContent, /Domande da chiarire: 4.*Informazioni decisive: 4/);
  assert.equal(f.$('questions').querySelectorAll('textarea').length, 4);
  assert.match(f.$('questions').childNodes[0].textContent, /Informazione decisiva.*Osservazioni: R1.*Dettaglio non leggibile/);
});

test('print snapshot includes only answers actually submitted and remains incomplete for returned decisive questions', async () => {
  const f = await fixture(); f.photo(); f.$('context').value = 'Attività'; await f.submit();
  await f.finish({ analysis: { ...report(), questions: [{ text: 'Protezione presente?', critical: true }] } });
  f.$('questions').querySelector('textarea').value = 'Sì'; await f.submit('questions');
  await f.finish({ analysis: { ...report(), questions: [{ text: 'È fissata?', critical: true }] } });
  assert.match(f.$('case-summary').textContent, /Protezione presente\?\nRisposta: Sì/);
  assert.match(f.$('case-summary').textContent, /Fotografia non disponibile per la stampa/);
  assert.match(f.$('assessment-state').textContent, /Valutazione da completare/);
  assert.match(f.$('question-summary').textContent, /Informazioni decisive: 1/);
});

test('changing the case while its printable image is decoding prevents a stale print', async () => {
  const f = await fixture({ imageAvailable: true }); f.photo(); await f.submit(); await f.finish({ analysis: report() });
  let finishDecoding;
  f.$('case-summary').querySelector('img').decode = () => new Promise(resolve => { finishDecoding = resolve; });
  const printing = f.$('print-report').handlers.click();
  f.photo('new-case.jpg'); finishDecoding(); await printing;
  assert.equal(f.prints.length, 0); assert.equal(f.$('case-summary').childNodes.length, 0);
  assert.equal(f.$('print-report').disabled, true);
});

test('authenticated case history exposes loading, empty and readable saved-case cards', async () => {
  const cases = [
    { id: 'case-one', created_at: 1792920000, summary: 'Passaggio da proteggere', context: 'Area logistica durante la movimentazione' },
    { id: 'case-two', created_at: 1792910000, summary: '', context: '' },
  ];
  const f = await fixture({ initialCases: cases }); await tick();
  assert.equal(f.$('history-loading').hidden, true); assert.equal(f.$('history-empty').hidden, true);
  assert.equal(f.$('history-panel').attrs['aria-busy'], 'false');
  assert.equal(f.historyGets[0].options.headers['X-CSRF-Token'], f.session.csrf);
  assert.equal(f.$('history-list').childNodes.length, 2);
  assert.match(f.$('history-list').childNodes[0].textContent, /Passaggio da proteggere.*Area logistica/);
  assert.match(f.$('history-list').childNodes[1].textContent, /Analisi senza sintesi/);
  assert.match(f.$('history-status').textContent, /2 casi salvati/);

  const empty = await fixture(); await tick();
  assert.equal(empty.$('history-empty').hidden, false); assert.match(empty.$('history-status').textContent, /Nessun caso/);
  empty.$('refresh-history').click(); await tick(); assert.equal(empty.doc.activeElement.id, 'history-empty');
});

test('history warns before capacity blocks new uploads without hiding saved cases', async () => {
  const saved = { id: 'capacity-case', created_at: 1792920000, summary: 'Caso conservato', context: '' };
  const f = await fixture({ initialCases: [saved], caseStorage: { warning: true, uploads_blocked: false } }); await tick();
  assert.equal(f.$('history-list').childNodes.length, 1);
  assert.match(f.$('history-status').textContent, /quasi esaurito/);
  const full = await fixture({ initialCases: [saved], caseStorage: { warning: true, uploads_blocked: true } }); await tick();
  assert.match(full.$('history-status').textContent, /nuovi file non possono essere salvati/);
});

test('a pending deletion remains visible only as a retryable cleanup action', async () => {
  const pending = { id: 'pending-delete', created_at: 1792920000, summary: 'Eliminazione da completare', context: '', deletion_pending: true };
  const f = await fixture({ initialCases: [pending] }); await tick();
  const card = f.$('history-list').childNodes[0], buttons = card.querySelectorAll('button');
  assert.equal(buttons.length, 1);
  assert.equal(buttons[0].textContent, 'Riprova eliminazione');
  assert.match(card.textContent, /non è consultabile.*Riprova/s);
});

test('case history failure is explicit and receives focus after a manual retry', async () => {
  const f = await fixture({ caseListStatus: 503 }); await tick();
  assert.equal(f.$('history-loading').hidden, true); assert.equal(f.$('history-error').hidden, false);
  assert.match(f.$('history-error').textContent, /Archivio non disponibile.*temporaneamente/);
  f.$('refresh-history').click(); await tick(); assert.equal(f.doc.activeElement.id, 'history-error');
  assert.match(f.$('history-status').textContent, /Impossibile caricare/);
});

test('an expired session while listing cases returns to login without retrying', async () => {
  const f = await fixture({ caseListStatus: 401 }); await tick();
  assert.equal(f.$('workspace').hidden, true); assert.equal(f.$('login-panel').hidden, false);
  assert.equal(f.doc.activeElement.id, 'status'); assert.match(f.$('status').textContent, /Sessione scaduta.*accedi nuovamente/i);
  assert.equal(f.historyGets.length, 1); assert.equal(f.requests.length, 0);
});

test('an older saved case without media states that the photograph is unavailable', async () => {
  const saved = { id: 'saved-case', created_at: 1792920000, summary: 'Sintesi archivio', context: 'Contesto archiviato' };
  const f = await fixture({ initialCases: [saved] }); await tick();
  const open = f.$('history-list').querySelectorAll('button')[0]; open.click(); await tick();
  assert.equal(open.disabled, true); assert.match(f.$('history-status').textContent, /Apertura/);
  assert.equal(f.requests[0].options.headers['X-CSRF-Token'], f.session.csrf);
  await f.finishRequest('/api/cases/saved-case', { case: { ...saved, analysis: { ...report('Rapporto riaperto'), findings: [finding('S1')] } } });
  assert.equal(f.$('report').hidden, false); assert.equal(f.$('report-title').textContent, 'Analisi salvata');
  assert.equal(f.doc.activeElement.id, 'report-title'); assert.match(f.$('case-summary').textContent, /non contiene una fotografia archiviata.*Contesto archiviato/);
  assert.match(f.$('report-notice').textContent, /caso precedente non contiene/);
  const fallback = f.$('findings').childNodes[0].querySelector('.crop-fallback');
  assert.equal(fallback.querySelector('a'), null); assert.match(fallback.textContent, /foto originale/);
});

test('opening a new saved case renders its protected original photograph', async () => {
  const saved = { id: 'saved-with-photo', created_at: 1792920000, summary: 'Sintesi archivio', context: 'Contesto archiviato' };
  const f = await fixture({ initialCases: [saved], imageAvailable: true }); await tick();
  f.$('history-list').querySelectorAll('button')[0].click(); await tick();
  await f.finishRequest('/api/cases/saved-with-photo', { case: {
    ...saved, analysis: { ...report('Rapporto riaperto'), findings: [finding('S1')] },
    assets: [{ id: 'asset-1', role: 'original', media_type: 'image/jpeg', download_url: '/api/cases/saved-with-photo/assets/asset-1' }],
  } });
  const photo = f.$('case-summary').querySelector('img');
  assert.equal(photo.src, '/api/cases/saved-with-photo/assets/asset-1');
  assert.match(f.$('report-notice').textContent, /file originale è conservato/);
  assert.equal(f.$('questions-photo-note').hidden, false);
});

test('a malformed saved case cannot replace the current report or selected photograph', async () => {
  const saved = { id: 'broken-case', created_at: 1792920000, summary: 'Caso corrotto', context: '' };
  const f = await fixture({ initialCases: [saved], imageAvailable: true }); await tick();
  f.photo(); await f.submit(); await f.finish({ analysis: report('Rapporto corrente') });
  const photo = f.$('case-summary').querySelector('img');
  f.$('history-list').querySelectorAll('button')[0].click(); await tick();
  await f.finishRequest('/api/cases/broken-case', { case: { ...saved, analysis: { ...report('Non valido'), findings: [null] } } });
  assert.equal(f.$('summary').textContent, 'Rapporto corrente'); assert.equal(f.$('case-summary').querySelector('img'), photo);
  assert.equal(f.$('preview-wrap').hidden, false); assert.equal(f.$('history-error').hidden, false);
  assert.equal(f.doc.activeElement.id, 'history-error');
});

test('an expired session while opening a case preserves the local report and does not loop', async () => {
  const saved = { id: 'expired-open', created_at: 1792920000, summary: 'Caso', context: '' };
  const f = await fixture({ initialCases: [saved] }); await tick();
  f.photo(); await f.submit(); await f.finish({ analysis: report('Rapporto locale') });
  f.$('history-list').querySelectorAll('button')[0].click(); await tick();
  await f.finishRequest('/api/cases/expired-open', { error: { message: 'Sessione scaduta' } }, 401);
  assert.equal(f.$('workspace').hidden, true); assert.equal(f.$('login-panel').hidden, false);
  assert.equal(f.$('summary').textContent, 'Rapporto locale'); assert.equal(f.$('report').hidden, false);
  assert.equal(f.doc.activeElement.id, 'status'); assert.equal(f.requests.length, 0);
});

test('case 401 refreshes session CSRF and the next login uses the new token without losing the report', async () => {
  const saved = { id: 'refresh-login', created_at: 1792920000, summary: 'Caso', context: '' };
  const f = await fixture({
    initialCases: [saved],
    sessionResponses: [
      { data: { authenticated: false, configured: false, csrf: 'fresh-csrf', auth_configured: true } },
      { data: { authenticated: true, configured: true, csrf: 'logged-in-csrf', auth_configured: true } },
    ],
  }); await tick();
  f.photo(); await f.submit(); await f.finish({ analysis: report('Rapporto da conservare') });
  f.$('history-list').querySelectorAll('button')[0].click(); await tick();
  await f.finishRequest('/api/cases/refresh-login', { error: { message: 'Sessione scaduta' } }, 401);
  assert.equal(f.$('login-panel').hidden, false); assert.equal(f.$('login-button').disabled, false);
  assert.match(f.$('status').textContent, /Accedi nuovamente/); assert.equal(f.$('summary').textContent, 'Rapporto da conservare');

  f.$('password').value = 'password'; f.$('login-form').handlers.submit({ preventDefault() {} }); await tick();
  assert.equal(f.requests[0].url, '/api/login'); assert.equal(f.requests[0].options.headers['X-CSRF-Token'], 'fresh-csrf');
  await f.finishRequest('/api/login', { authenticated: true, csrf: 'ignored-post-token' });
  assert.equal(f.$('workspace').hidden, false); assert.equal(f.$('login-panel').hidden, true);
  assert.equal(f.$('summary').textContent, 'Rapporto da conservare'); assert.equal(f.$('report').hidden, false);
});

test('failed session refresh disables login and explains that a reload is required', async () => {
  const saved = { id: 'refresh-fails', created_at: 1792920000, summary: 'Caso', context: '' };
  const f = await fixture({ initialCases: [saved], sessionResponses: [{ data: { error: { message: 'Servizio non disponibile' } }, status: 503 }] }); await tick();
  f.photo(); await f.submit(); await f.finish({ analysis: report('Rapporto locale') });
  f.$('history-list').querySelectorAll('button')[0].click(); await tick();
  await f.finishRequest('/api/cases/refresh-fails', { error: { message: 'Sessione scaduta' } }, 401);
  assert.equal(f.$('login-panel').hidden, false); assert.equal(f.$('login-button').disabled, true);
  assert.equal(f.$('summary').textContent, 'Rapporto locale'); assert.equal(f.$('report').hidden, false);
  assert.equal(f.doc.activeElement.id, 'status'); assert.match(f.$('status').textContent, /Ricarica la pagina.*verrà perso/i);
  assert.equal(f.requests.length, 0);
});

test('deleting a saved case requires inline confirmation and clears an opened report', async () => {
  const saved = { id: 'delete-me', created_at: 1792920000, summary: 'Caso da eliminare', context: '' };
  const f = await fixture({ initialCases: [saved] }); await tick();
  const card = f.$('history-list').childNodes[0], buttons = card.querySelectorAll('button');
  buttons[0].click(); await tick();
  await f.finishRequest('/api/cases/delete-me', { case: { ...saved, analysis: report('Aperto') } });
  assert.equal(f.$('report').hidden, false);

  const remove = card.querySelectorAll('button')[1]; remove.click();
  assert.equal(f.requests.length, 0); assert.equal(remove.hidden, true);
  const confirm = card.querySelector('.delete-confirm'), yes = confirm.querySelectorAll('button')[0];
  assert.equal(f.doc.activeElement, yes); yes.click(); await tick();
  assert.equal(f.requests[0].options.method, 'DELETE');
  await f.finishRequest('/api/cases/delete-me', { deleted: true });
  assert.equal(f.$('history-empty').hidden, false); assert.match(f.$('history-status').textContent, /eliminato definitivamente/);
  assert.equal(f.$('report').hidden, true); assert.equal(f.$('empty-state').hidden, false); assert.equal(f.doc.activeElement.id, 'history-title');
});

test('a failed delete restores its confirmation command', async () => {
  const saved = { id: 'delete-fails', created_at: 1792920000, summary: 'Caso', context: '' };
  const f = await fixture({ initialCases: [saved] }); await tick();
  const card = f.$('history-list').childNodes[0], remove = card.querySelectorAll('button')[1]; remove.click();
  const yes = card.querySelector('.delete-confirm').querySelectorAll('button')[0]; yes.click(); await tick();
  assert.equal(yes.textContent, 'Eliminazione…');
  await f.finishRequest('/api/cases/delete-fails', { error: { message: 'Errore archivio' } }, 503);
  assert.equal(yes.textContent, 'Conferma eliminazione'); assert.equal(yes.disabled, false);
  assert.equal(f.$('history-error').hidden, false); assert.equal(f.doc.activeElement.id, 'history-error');
});

test('an expired session while deleting returns to login and preserves the local report', async () => {
  const saved = { id: 'expired-delete', created_at: 1792920000, summary: 'Caso', context: '' };
  const f = await fixture({ initialCases: [saved] }); await tick();
  f.photo(); await f.submit(); await f.finish({ analysis: report('Rapporto locale') });
  const card = f.$('history-list').childNodes[0], remove = card.querySelectorAll('button')[1]; remove.click();
  const yes = card.querySelector('.delete-confirm').querySelectorAll('button')[0]; yes.click(); await tick();
  await f.finishRequest('/api/cases/expired-delete', { error: { message: 'Sessione scaduta' } }, 401);
  assert.equal(f.$('workspace').hidden, true); assert.equal(f.$('login-panel').hidden, false);
  assert.equal(f.$('summary').textContent, 'Rapporto locale'); assert.equal(f.$('report').hidden, false);
  assert.equal(yes.textContent, 'Conferma eliminazione'); assert.equal(f.doc.activeElement.id, 'status'); assert.equal(f.requests.length, 0);
});

test('workspace navigation preserves a photo and context without issuing an analysis request', async () => {
  const f = await fixture();
  assert.equal(f.$('history-panel').hidden, true); assert.equal(f.$('work-grid').hidden, false);
  assert.equal(f.$('workspace-nav').hidden, false); assert.equal(f.$('step-photo').attrs['aria-current'], 'step');
  f.photo(); f.$('context').value = 'Contesto ancora da inviare';
  assert.equal(f.$('step-context').attrs['aria-current'], 'step');
  f.$('nav-history').click();
  assert.equal(f.$('history-panel').hidden, false); assert.equal(f.$('work-grid').hidden, true);
  assert.equal(f.doc.activeElement.id, 'history-title'); assert.equal(f.$('workflow').hidden, true);
  f.$('nav-analysis').click();
  assert.equal(f.doc.activeElement.id, 'input-title'); assert.equal(f.$('preview-wrap').hidden, false);
  assert.equal(f.$('context').value, 'Contesto ancora da inviare'); assert.equal(f.requests.length, 0);
});

test('the completed report has a focused view and editing preserves it after a failed request', async () => {
  const f = await fixture(); f.photo(); f.$('context').value = 'Prima versione'; await f.submit();
  await f.finish({ analysis: report('Rapporto valido') });
  assert.equal(f.$('input-panel').hidden, true); assert.equal(f.$('work-grid').dataset.mode, 'report');
  assert.equal(f.$('step-result').attrs['aria-current'], 'step');
  f.$('edit-analysis').click();
  assert.equal(f.$('input-panel').hidden, false); assert.equal(f.doc.activeElement.id, 'input-title');
  assert.equal(f.$('return-report').hidden, false); assert.equal(f.$('context').value, 'Prima versione');
  f.$('context').value = 'Seconda versione'; await f.submit();
  await f.finish({ error: { message: 'Servizio temporaneamente non disponibile' } }, 503);
  assert.equal(f.$('input-panel').hidden, false); assert.equal(f.$('analysis-feedback').hidden, false);
  assert.equal(f.doc.activeElement.id, 'analysis-feedback'); assert.equal(f.$('summary').textContent, 'Rapporto valido');
  f.$('return-report').click();
  assert.equal(f.$('input-panel').hidden, true); assert.equal(f.doc.activeElement.id, 'report-title');
  f.$('edit-analysis').click(); assert.equal(f.$('context').value, 'Seconda versione');
});

test('new analysis clears the current draft and answers without deleting any saved report', async () => {
  const saved = { id: 'keep-saved', created_at: 1792920000, summary: 'Rapporto da conservare', context: '' };
  const f = await fixture({ initialCases: [saved] }); f.photo(); f.$('context').value = 'Contesto'; await f.submit();
  await f.finish({ analysis: { ...report(), questions: [{ text: 'Il riparo è presente?', critical: true }] } });
  f.$('questions').querySelector('textarea').value = 'Sì';
  f.$('nav-history').click(); f.$('new-analysis').click();
  assert.equal(f.requests.length, 0); assert.equal(f.$('history-list').childNodes.length, 1);
  assert.equal(f.$('history-panel').hidden, true); assert.equal(f.$('input-panel').hidden, false);
  assert.equal(f.$('context').value, ''); assert.equal(f.$('photo').value, '');
  assert.equal(f.$('preview-wrap').hidden, true); assert.equal(f.$('report').hidden, true);
  assert.equal(f.$('questions').childNodes.length, 0); assert.equal(f.$('export-json').disabled, true);
  assert.equal(f.$('step-photo').attrs['aria-current'], 'step'); assert.equal(f.doc.activeElement.id, 'input-title');
  await f.submit(); assert.equal(f.requests.length, 0); assert.match(f.$('analysis-feedback').textContent, /Seleziona una foto o un video/);
});

test('navigation and new analysis cannot discard an in-flight analysis', async () => {
  const f = await fixture(); f.photo(); f.$('context').value = 'Attività in corso'; await f.submit();
  for (const id of ['new-analysis', 'history-new-analysis', 'nav-history', 'nav-analysis', 'edit-analysis']) assert.equal(f.$(id).disabled, true);
  f.$('new-analysis').click(); f.$('nav-history').click();
  assert.equal(f.$('history-panel').hidden, true); assert.equal(f.$('context').value, 'Attività in corso');
  assert.equal(f.$('input-panel').hidden, true); assert.equal(f.$('busy-state').hidden, false);
  await f.finish({ analysis: report('Risultato ricevuto') });
  assert.equal(f.$('new-analysis').disabled, false); assert.equal(f.$('nav-history').disabled, false);
  assert.equal(f.$('summary').textContent, 'Risultato ricevuto'); assert.equal(f.$('report').hidden, false);
});

test('opening an archived report restores its context for editing and requires a new photo', async () => {
  const saved = { id: 'archived-edit', created_at: 1792920000, summary: 'Rapporto salvato', context: 'Contesto del rapporto salvato' };
  const f = await fixture({ initialCases: [saved] }); f.photo(); f.$('context').value = 'Un altro contesto';
  f.$('nav-history').click(); f.$('history-list').querySelectorAll('button')[0].click(); await tick();
  await f.finishRequest('/api/cases/archived-edit', { case: { ...saved, analysis: report('Analisi archiviata') } });
  assert.equal(f.$('history-panel').hidden, true); assert.equal(f.$('input-panel').hidden, true);
  f.$('edit-analysis').click();
  assert.equal(f.$('context').value, saved.context); assert.equal(f.$('preview-wrap').hidden, true);
  await f.submit(); assert.equal(f.requests.length, 0); assert.match(f.$('analysis-feedback').textContent, /Seleziona una foto o un video/);
  assert.equal(f.$('summary').textContent, 'Analisi archiviata');
});

test('an archived finding never crops the photograph from the previously opened local report', async () => {
  const saved = { id: 'different-photo', created_at: 1792920000, summary: 'Altra situazione', context: '' };
  const f = await fixture({ imageAvailable: true, initialCases: [saved] }); f.photo(); await f.submit();
  await f.finish({ analysis: { ...report('Rapporto locale'), findings: [finding('L1')] } });
  assert.equal(f.$('findings').querySelectorAll('canvas').length, 1);
  f.$('nav-history').click(); f.$('history-list').querySelectorAll('button')[0].click(); await tick();
  await f.finishRequest('/api/cases/different-photo', { case: { ...saved, analysis: { ...report('Rapporto archiviato'), findings: [finding('A1')] } } });
  assert.equal(f.$('findings').querySelectorAll('canvas').length, 0);
  assert.equal(f.$('case-summary').querySelector('img'), null);
  assert.match(f.$('findings').querySelector('.crop-fallback').textContent, /Ritaglio non disponibile.*foto originale/);
});

test('a slow archive list does not block navigation or starting a new analysis', async () => {
  const f = await fixture({ deferHistory: true });
  assert.equal(f.$('history-loading').hidden, false);
  assert.equal(f.$('new-analysis').disabled, false); assert.equal(f.$('nav-history').disabled, false);
  f.$('nav-history').click(); assert.equal(f.$('history-panel').hidden, false);
  f.$('new-analysis').click(); assert.equal(f.$('input-panel').hidden, false);
  f.photo(); f.$('context').value = 'Nuova situazione'; await f.submit();
  await f.finish({ analysis: report('Analisi disponibile') });
  assert.equal(f.$('edit-analysis').disabled, false); assert.equal(f.$('summary').textContent, 'Analisi disponibile');
  f.historyGets[0].resolve(); await tick();
  assert.equal(f.$('summary').textContent, 'Analisi disponibile'); assert.equal(f.$('report').hidden, false);
});

test('an archived report asks for its photo before answers and preserves questions when it is attached', async () => {
  const saved = { id: 'photo-first', created_at: 1792920000, summary: 'Caso archiviato', context: 'Contesto originale' };
  const f = await fixture({ initialCases: [saved] }); f.$('nav-history').click();
  f.$('history-list').querySelectorAll('button')[0].click(); await tick();
  await f.finishRequest('/api/cases/photo-first', { case: { ...saved, analysis: { ...report('Rapporto originale'), questions: [{ text: 'Il riparo è fisso?', critical: true }] } } });
  const answer = f.$('questions').querySelector('textarea');
  assert.equal(answer.disabled, true); assert.equal(f.$('questions-photo-note').hidden, false);
  assert.equal(f.$('reanalyse-button').textContent, 'Aggiungi la foto per aggiornare');
  await f.submit('questions');
  assert.equal(f.requests.length, 0); assert.equal(f.doc.activeElement.id, 'input-title');
  f.photo('original.jpg');
  assert.equal(f.$('summary').textContent, 'Rapporto originale'); assert.equal(f.$('questions').querySelector('textarea'), answer);
  assert.equal(answer.disabled, false); assert.equal(f.$('questions-photo-note').hidden, true);
  assert.equal(f.$('context').value, saved.context); assert.match(f.$('report-notice').textContent, /non è ancora cambiato/);
  answer.value = 'Sì, fissato'; await f.submit('questions');
  await f.finish({ analysis: report('Rapporto aggiornato') });
  assert.match(f.$('case-summary').textContent, /Contesto originale.*Chiarimenti/s);
  assert.match(f.$('case-summary').textContent, /Il riparo è fisso\?\nRisposta: Sì, fissato/);
});


const videoSourceFixture = () => ({ id: 'video-source', context: 'Synthetic context', analysis: { findings: [], meta: { case_kind: 'video_technical_verification', video_inspection: { validated: true, duration_seconds: 4, frames: [{ timestamp_seconds: 1 }, { timestamp_seconds: 3 }], audio: { status: 'ready_for_transcription' } } } }, assets: [
  { id: 'original', role: 'original', filename: 'scene.mp4', media_type: 'video/mp4', download_url: '/api/cases/video-source/assets/original' },
  { id: 'frame-a', role: 'frame', filename: 'frame-01-1.000s.jpg', media_type: 'image/jpeg', download_url: '/api/cases/video-source/assets/frame-a' },
  { id: 'frame-b', role: 'frame', filename: 'frame-02-3.000s.jpg', media_type: 'image/jpeg', download_url: '/api/cases/video-source/assets/frame-b' },
] });
const syntheticVideoFixture = () => ({ summary: 'Synthetic findings only', findings: [{ id: 'frame-1:f1', title: 'Synthetic frame hazard', evidence: 'Seen in this sampled image', action: 'Synthetic action', deadline: 'Before continuing', risk: 'medium', certainty: 'visible', critical_unknown: false, bbox: null, references: [], video_evidence: { timestamp_seconds: 1, asset_id: 'frame-a', basis: 'sampled_frame' } }], questions: [], sources: [], limitations: ['Temporal samples only'], meta: { case_kind: 'video_synthetic_analysis', source_case_id: 'video-source', execution_mode: 'synthetic_adapters', real_ai_analysis_performed: false, coverage: { duration_seconds: 4, frame_count: 2, sampling_method: 'archived_timestamp_samples', frames: [{ timestamp_seconds: 1, asset_id: 'frame-a' }, { timestamp_seconds: 3, asset_id: 'frame-b' }], continuous_video_observed: false, audio_status: 'ready_for_transcription', ambient_sound_analysis_performed: false }, transcription: { status: 'available', basis: 'spoken_claim', text: '<spoken statement>', language: 'it', segments: [{ start_seconds: .2, end_seconds: .8, text: '<spoken statement>', basis: 'spoken_claim' }], ambient_sound_analysis_performed: false } } });
async function openSyntheticSource(f) {
  f.$('history-list').querySelectorAll('button')[0].click(); await tick();
  await f.finishRequest('/api/cases/video-source', { case: videoSourceFixture() });
}
const sourceListItem = () => ({ id: 'video-source', created_at: 1792920000, kind: 'video_technical_verification', summary: 'Technical video' });

test('synthetic video action is disabled by default and never inferred from real-AI capability', async () => {
  const f = await fixture({ initialCases: [sourceListItem()], sessionData: { media: { video_analysis_enabled: true } } });
  await openSyntheticSource(f);
  assert.equal(f.$('video-synthetic-controls').hidden, true);
  f.$('video-analyze-button').click(); await tick(); assert.equal(f.requests.length, 0);
});

test('synthetic video action explicitly uses one company trial and posts only archived source and context', async () => {
  const trial = { plan: 'trial', analyses_total: 1, analyses_remaining: 1, export_allowed: false };
  const f = await fixture({ initialCases: [sourceListItem()], sessionData: { configured: false, entitlement: trial, media: { video_synthetic_analysis_enabled: true, video_analysis_enabled: false } } });
  await openSyntheticSource(f);
  assert.equal(f.$('video-synthetic-controls').hidden, false); assert.match(f.$('video-synthetic-note').textContent, /unica prova aziendale/);
  f.$('video-analyze-button').click(); await tick();
  assert.equal(f.$('video-analyze-button').disabled, true); assert.equal(f.requests.length, 1);
  assert.equal(f.requests[0].url, '/api/media/cases/video-source/analyze');
  assert.equal(f.requests[0].options.headers['X-CSRF-Token'], 'test-csrf');
  assert.deepEqual(JSON.parse(f.requests[0].options.body), { context: 'Synthetic context' });
  await f.finishRequest('/api/media/cases/video-source/analyze', { analysis: syntheticVideoFixture(), execution_mode: 'synthetic_adapters', real_ai_analysis: false, trial_consumed: true, entitlement: { ...trial, analyses_remaining: 0 }, archive: { saved: true, case_id: 'video-result' } });
  await f.finishRequest('/api/cases/video-source', { case: videoSourceFixture() });
  assert.equal(f.$('report').hidden, false); assert.match(f.$('report-notice').textContent, /non è un’analisi AI reale/);
  assert.match(f.$('video-analysis-details').textContent, /2 fotogrammi su 4.0 secondi/);
  assert.match(f.$('video-analysis-details').textContent, /Parlato dichiarato/); assert.match(f.$('video-analysis-details').textContent, /0.2–0.8 s/);
  assert.match(f.$('video-analysis-details').textContent, /<spoken statement>/);
  assert.equal(f.$('findings').querySelector('img').src, '/api/cases/video-source/assets/frame-a');
  assert.match(f.$('findings').textContent, /campionato a 1.0 s/); assert.doesNotMatch(f.$('findings').textContent, /foto completa/);
  assert.equal(f.$('reanalyse-button').hidden, true); assert.equal(f.$('edit-analysis').hidden, true); assert.equal(f.$('print-report').hidden, true);
  assert.equal(f.$('analyse-button').disabled, true); assert.equal(f.doc.activeElement.id, 'report-title');
});

test('saved synthetic report opens without a mutation and states missing original evidence truthfully', async () => {
  const saved = { id: 'video-result', kind: 'video_synthetic_analysis', created_at: 1792920000, summary: 'Synthetic report' };
  const f = await fixture({ initialCases: [saved] });
  assert.match(f.$('history-list').textContent, /nessuna analisi AI reale/);
  f.$('history-list').querySelectorAll('button')[0].click(); await tick();
  await f.finishRequest('/api/cases/video-result', { case: { ...saved, analysis: syntheticVideoFixture(), context: 'Synthetic context', assets: [] } });
  await f.finishRequest('/api/cases/video-source', { error: { code: 'case_not_found', message: 'Missing' } }, 404);
  assert.equal(f.$('report').hidden, false); assert.match(f.$('video-analysis-details').textContent, /caso sorgente.*non sono disponibili/);
  assert.match(f.$('findings').textContent, /fotogramma associato.*non è disponibile/);
  assert.equal(f.$('findings').querySelector('img'), null); assert.equal(f.requests.length, 0);
});

test('quota completion unknown preserves recoverable report and blocks further mutation without retry encouragement', async () => {
  const f = await fixture({ initialCases: [sourceListItem()], sessionData: { media: { video_synthetic_analysis_enabled: true } } });
  await openSyntheticSource(f); f.$('video-analyze-button').click(); await tick();
  await f.finishRequest('/api/media/cases/video-source/analyze', { error: { code: 'trial_completion_unknown', message: 'Do not trust raw text' }, trial_consumed: null, archive: { saved: true, case_id: 'uncertain-result' } }, 503);
  assert.match(f.$('video-synthetic-status').textContent, /non avviare altre analisi/i); assert.doesNotMatch(f.$('video-synthetic-status').textContent, /riprova/i);
  assert.equal(f.$('video-synthetic-controls').hidden, true); assert.equal(f.$('video-open-saved-result').hidden, false);
  f.$('video-analyze-button').click(); await tick(); f.photo(); await f.submit(); assert.equal(f.requests.length, 0);
  assert.equal(f.$('analyse-button').disabled, true); assert.match(f.$('status').textContent, /conteggio/);
});

test('known consumed trial remains consumed when entitlement refresh is unavailable', async () => {
  const f = await fixture({ initialCases: [sourceListItem()], sessionData: { media: { video_synthetic_analysis_enabled: true } } });
  await openSyntheticSource(f); f.$('video-analyze-button').click(); await tick();
  await f.finishRequest('/api/media/cases/video-source/analyze', { analysis: syntheticVideoFixture(), execution_mode: 'synthetic_adapters', real_ai_analysis: false, trial_consumed: true, entitlement: null, entitlement_status: { available: false }, archive: { saved: true, case_id: 'video-result' } });
  await f.finishRequest('/api/cases/video-source', { case: videoSourceFixture() });
  assert.match(f.$('report-notice').textContent, /prova aziendale utilizzata/); assert.equal(f.$('analyse-button').disabled, true);
  f.$('video-analyze-button').click(); await tick(); assert.equal(f.requests.length, 0);
});

test('all four locales disclose synthetic output, partial video coverage and spoken claims', async () => {
  for (const locale of ['it', 'de', 'fr', 'en']) {
    const f = await fixture({ initialLocale: locale, initialCases: [{ id: 'result', kind: 'video_synthetic_analysis', summary: 'Synthetic' }] });
    f.$('history-list').querySelectorAll('button')[0].click(); await tick();
    const analysis = syntheticVideoFixture(); analysis.meta.transcription = { status: 'unintelligible', basis: 'spoken_claim', language: null, text: null, ambient_sound_analysis_performed: false, segments: [] };
    await f.finishRequest('/api/cases/result', { case: { id: 'result', analysis } });
    await f.finishRequest('/api/cases/video-source', { error: { code: 'case_not_found' } }, 404);
    assert.match(f.$('report-notice').textContent, /sintetico|synthetisch|synthétique|synthetic/i);
    assert.ok(f.$('video-analysis-details').textContent.includes(f.i18n.messages[locale].syntheticTranscriptUnknown));
    assert.ok(f.$('video-analysis-details').textContent.includes(f.i18n.messages[locale].syntheticNoAmbient));
    assert.equal(f.requests.length, 0);
  }
});


test('uncertain quota recovery opens the saved report using GET only and keeps mutation locked', async () => {
  const f = await fixture({ initialCases: [sourceListItem()], sessionData: { media: { video_synthetic_analysis_enabled: true } } });
  await openSyntheticSource(f); f.$('video-analyze-button').click(); await tick();
  await f.finishRequest('/api/media/cases/video-source/analyze', { error: { code: 'trial_completion_unknown' }, trial_consumed: null, archive: { saved: true, case_id: 'uncertain-result' } }, 503);
  f.$('video-open-saved-result').click(); await tick();
  assert.equal(f.requests[0].options.method, undefined);
  await f.finishRequest('/api/cases/uncertain-result', { case: { id: 'uncertain-result', analysis: syntheticVideoFixture() } });
  await f.finishRequest('/api/cases/video-source', { case: videoSourceFixture() });
  assert.equal(f.$('report').hidden, false); assert.match(f.$('report-notice').textContent, /non avviare altre analisi/i);
  assert.equal(f.$('analyse-button').disabled, true); assert.equal(f.requests.length, 0);
});

test('sampled finding cannot borrow an asset or timestamp outside its coverage contract', async () => {
  const f = await fixture({ initialCases: [{ id: 'bad-result', kind: 'video_synthetic_analysis', summary: 'Synthetic' }] });
  f.$('history-list').querySelectorAll('button')[0].click(); await tick();
  const analysis = syntheticVideoFixture(); analysis.findings[0].video_evidence.timestamp_seconds = 2;
  await f.finishRequest('/api/cases/bad-result', { case: { id: 'bad-result', analysis } });
  assert.equal(f.$('report').hidden, true); assert.equal(f.$('history-error').hidden, false); assert.equal(f.requests.length, 0);
});

test('saved frame references never load cross-origin or unrelated asset URLs', async () => {
  const f = await fixture({ initialCases: [{ id: 'result', kind: 'video_synthetic_analysis', summary: 'Synthetic' }] });
  f.$('history-list').querySelectorAll('button')[0].click(); await tick();
  await f.finishRequest('/api/cases/result', { case: { id: 'result', analysis: syntheticVideoFixture() } });
  const source = videoSourceFixture(); source.assets[1].download_url = 'https://unexpected.example/frame.jpg';
  await f.finishRequest('/api/cases/video-source', { case: source });
  assert.equal(f.$('findings').querySelector('img'), null); assert.match(f.$('findings').textContent, /non è disponibile/);
  assert.equal(f.$('video-analysis-details').querySelectorAll('img').length, 1);
});


test('exhausted company trial cannot run the synthetic action despite an available capability', async () => {
  const f = await fixture({ initialCases: [sourceListItem()], sessionData: { entitlement: { plan: 'trial', analyses_remaining: 0, export_allowed: false }, media: { video_synthetic_analysis_enabled: true } } });
  await openSyntheticSource(f); assert.equal(f.$('video-synthetic-controls').hidden, true);
  f.$('video-analyze-button').click(); await tick(); assert.equal(f.requests.length, 0);
});


const invalidSyntheticContracts = [
  ['coverage ambient audio inference', a => { a.meta.coverage.ambient_sound_analysis_performed = true; }],
  ['missing coverage ambient audio declaration', a => { delete a.meta.coverage.ambient_sound_analysis_performed; }],
  ['transcription ambient audio inference', a => { a.meta.transcription.ambient_sound_analysis_performed = true; }],
  ['missing transcription ambient audio declaration', a => { delete a.meta.transcription.ambient_sound_analysis_performed; }],
  ['unrecognised transcription status', a => { a.meta.transcription.status = 'not_performed'; }],
  ['transcription basis promoted to visual proof', a => { a.meta.transcription.basis = 'sampled_frame'; }],
  ['segment basis promoted to visual proof', a => { a.meta.transcription.segments[0].basis = 'visual_evidence'; }],
  ['negative segment start', a => { a.meta.transcription.segments[0].start_seconds = -.1; }],
  ['segment end beyond video duration', a => { a.meta.transcription.segments[0].end_seconds = 4.1; }],
  ['segment end before its start', a => { a.meta.transcription.segments[0].end_seconds = .1; }],
  ['segment text inconsistent with combined transcript', a => { a.meta.transcription.text = 'another statement'; }],
  ['segment times out of order', a => { a.meta.transcription.segments.push({ start_seconds: .1, end_seconds: .15, text: 'earlier', basis: 'spoken_claim' }); a.meta.transcription.text += ' earlier'; }],
  ['speech transcript despite absent audio', a => { a.meta.coverage.audio_status = 'absent'; }],
  ['not applicable transcript despite present speech', a => { a.meta.transcription = { status: 'not_applicable', reason: 'silent', language: null, text: null, segments: [], basis: 'spoken_claim', ambient_sound_analysis_performed: false }; }],
  ['unintelligible status retaining alleged speech', a => { a.meta.transcription.status = 'unintelligible'; }],
  ['unknown audio status', a => { a.meta.coverage.audio_status = 'error'; }],
  ['visible finding with reported evidence basis', a => { a.findings[0].video_evidence.basis = 'reported'; }],
  ['reported finding promoted to sampled visual basis', a => { a.findings[0].certainty = 'reported'; }],
  ['duplicate frame asset IDs', a => { a.meta.coverage.frames[1].asset_id = 'frame-a'; }],
  ['duplicate frame timestamps', a => { a.meta.coverage.frames[1].timestamp_seconds = 1; }],
  ['out of order coverage', a => { a.meta.coverage.frames.reverse(); }],
  ['frame beyond video duration', a => { a.meta.coverage.frames[1].timestamp_seconds = 4.1; }],
  ['negative frame timestamp', a => { a.meta.coverage.frames[0].timestamp_seconds = -1; }],
  ['non-finite frame timestamp', a => { a.meta.coverage.frames[1].timestamp_seconds = Infinity; }],
  ['unrecognised sampling method', a => { a.meta.coverage.sampling_method = 'continuous'; }],
  ['frame count inconsistent with samples', a => { a.meta.coverage.frame_count = 3; }],
  ['duration beyond the backend maximum', a => { a.meta.coverage.duration_seconds = 3601; }],
  ['finding identifier inconsistent with sampled frame', a => { a.findings[0].id = 'frame-2:f1'; }],
];
for (const [name, corrupt] of invalidSyntheticContracts) {
  test('synthetic contract rejects ' + name + ' before rendering or source fetch', async () => {
    const f = await fixture({ initialCases: [{ id: 'invalid-result', kind: 'video_synthetic_analysis', summary: 'Synthetic' }] });
    f.$('history-list').querySelectorAll('button')[0].click(); await tick();
    const analysis = syntheticVideoFixture(); corrupt(analysis);
    await f.finishRequest('/api/cases/invalid-result', { case: { id: 'invalid-result', analysis } });
    assert.equal(f.$('report').hidden, true); assert.equal(f.$('video-analysis-details').hidden, true);
    assert.equal(f.$('history-error').hidden, false); assert.equal(f.$('history-error').textContent.length > 0, true);
    assert.equal(f.requests.length, 0, 'invalid provenance must not fetch or display a source');
  });
}

for (const certainty of ['visible', 'reported', 'verify']) {
  test('synthetic finding accepts only the matching backend provenance for ' + certainty, async () => {
    const f = await fixture({ initialCases: [{ id: 'valid-result', kind: 'video_synthetic_analysis', summary: 'Synthetic' }] });
    f.$('history-list').querySelectorAll('button')[0].click(); await tick();
    const analysis = syntheticVideoFixture(); analysis.findings[0].certainty = certainty;
    analysis.findings[0].video_evidence.basis = certainty === 'visible' ? 'sampled_frame' : certainty;
    await f.finishRequest('/api/cases/valid-result', { case: { id: 'valid-result', analysis } });
    await f.finishRequest('/api/cases/video-source', { error: { code: 'case_not_found' } }, 404);
    assert.equal(f.$('report').hidden, false); assert.equal(f.$('findings').querySelectorAll('section').length, 1);
  });
}

for (const audioStatus of ['absent', 'silent']) {
  test('synthetic transcript not-applicable is accepted only with matching ' + audioStatus + ' audio', async () => {
    const f = await fixture({ initialCases: [{ id: 'valid-result', kind: 'video_synthetic_analysis', summary: 'Synthetic' }] });
    f.$('history-list').querySelectorAll('button')[0].click(); await tick();
    const analysis = syntheticVideoFixture(); analysis.meta.coverage.audio_status = audioStatus;
    analysis.meta.transcription = { status: 'not_applicable', reason: audioStatus, language: null, text: null, segments: [], basis: 'spoken_claim', ambient_sound_analysis_performed: false };
    await f.finishRequest('/api/cases/valid-result', { case: { id: 'valid-result', analysis } });
    await f.finishRequest('/api/cases/video-source', { error: { code: 'case_not_found' } }, 404);
    assert.equal(f.$('report').hidden, false); assert.match(f.$('video-analysis-details').textContent, /Trascrizione non applicabile/);
  });
}

test('invalid synthetic response after committed trial does not render or suggest a fresh trial', async () => {
  const f = await fixture({ initialCases: [sourceListItem()], sessionData: { media: { video_synthetic_analysis_enabled: true } } });
  await openSyntheticSource(f); f.$('video-analyze-button').click(); await tick();
  const analysis = syntheticVideoFixture(); analysis.meta.coverage.ambient_sound_analysis_performed = true;
  await f.finishRequest('/api/media/cases/video-source/analyze', { analysis, execution_mode: 'synthetic_adapters', real_ai_analysis: false, trial_consumed: true, archive: { saved: true, case_id: 'stored-invalid-result' } });
  assert.equal(f.$('report').hidden, true); assert.equal(f.$('analyse-button').disabled, true);
  assert.match(f.$('video-synthetic-status').textContent, /rapporto è stato salvato e la prova utilizzata/i);
  assert.equal(f.requests.length, 0, 'invalid result must not fetch its source');
  f.$('video-open-saved-result').click(); await tick();
  await f.finishRequest('/api/cases/stored-invalid-result', { case: { id: 'stored-invalid-result', analysis } });
  assert.equal(f.$('report').hidden, true); assert.equal(f.$('analyse-button').disabled, true);
  assert.match(f.$('video-synthetic-status').textContent, /rapporto è stato salvato e la prova utilizzata/i);
  assert.doesNotMatch(f.$('video-synthetic-status').textContent, /utilizzo della prova non è confermato/i);
  assert.equal(f.requests.length, 0);
});

test('classified source details remain visible, contextual and safe in every report language', async () => {
  const labels = {it:['Obbligo nella fonte','Raccomandazione nella fonte','Ipotesi da verificare','Non classificato'],de:['Pflicht in der Quelle','Empfehlung in der Quelle','Zu prüfende Annahme','Nicht eingestuft'],fr:['Obligation dans la source','Recommandation dans la source','Hypothèse à vérifier','Non classé'],en:['Obligation in the source','Recommendation in the source','Hypothesis to verify','Unclassified']};
  for (const locale of ['it','de','fr','en']) {
    const f = await fixture({initialLocale:locale}); f.photo(); await f.submit();
    await f.finish({analysis:{...report(),sources:[
      {id:'law',title:'General duty',url:'https://www.fedlex.admin.ch/eli/cc/1983/1968_1968_1968/it',verified_at:'2026-10-26',classification:'obligation',locator:'Art. 3',scope:'Check applicability to the actual case',document_version:'2026-01-01',registry_version:'1.0',limitations:['<script>not executable</script>']},
      {id:'guide',title:'Guide',url:'https://www.suva.ch/guide',classification:'recommendation'},
      {id:'idea',title:'Assumption',url:'https://www.seco.admin.ch/',classification:'hypothesis'},
      {id:'old',title:'Old saved reference',url:'javascript:alert(1)',classification:'constructor',scope:{untrusted:'object'},limitations:'not an array'}
    ]}});
    const text = f.$('sources').textContent;
    for(const label of labels[locale]) assert.ok(text.includes(label),locale+': '+label);
    for(const expected of ['Art. 3','2026-10-26','2026-01-01','1.0','Check applicability','<script>not executable</script>']) assert.ok(text.includes(expected));
    assert.equal(f.$('sources').querySelectorAll('script').length,0);
    assert.equal(f.$('sources').querySelectorAll('a').length,3);
    assert.equal(text.includes('[object Object]'),false);
    assert.equal(text.includes('constructor'),false);
    assert.ok(text.includes(f.i18n.messages[locale].sourceContext));
  }
});
