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

async function fixture({ reducedMotion = false, imageAvailable = false } = {}) {
  const elements = new Map(), requests = [], scrolls = [], exports = [], prints = [];
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
    click() {}
    remove() {}
    scrollIntoView(options) { scrolls.push({ id: this.id, ...options }); }
    querySelectorAll(selector) { return this.childNodes.flatMap(child => child instanceof Element ? [...(child.tagName.toLowerCase() === selector ? [child] : []), ...child.querySelectorAll(selector)] : []); }
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
  doc = { getElementById: $, createElement: tag => new Element(tag), createTextNode: text => text, body: new Element('body'), activeElement: null };
  const session = { authenticated: true, configured: true, csrf: 'test-csrf' };
  const response = (data, status = 200) => ({ ok: status < 400, status, json: async () => data });
  const context = { document: doc, window: { matchMedia: () => ({ matches: reducedMotion }), print() { prints.push(true); } }, URL: class extends URL { static createObjectURL(value) { if (value instanceof Blob) exports.push(value); return 'blob:test-photo'; } static revokeObjectURL() {} }, Blob, AbortController, FormData: class { append() {} }, setTimeout: callback => { callback(); }, console,
    fetch: async url => url === '/api/session' ? response(session) : new Promise(resolve => requests.push({ url, resolve: (data, status) => resolve(response(data, status)) })) };
  vm.runInNewContext(script, context, { filename: 'static/app.js' }); await tick();
  function photo(name = 'sample.jpg') { $('photo').files = [{ name, type: 'image/jpeg', size: 100 }]; $('photo').handlers.change(); }
  async function submit(origin = 'analysis') { $(origin + '-form').handlers.submit({ preventDefault() {} }); await tick(); }
  async function finish(data, status = 200) { const request = requests.shift(); assert.equal(request.url, '/analizza'); request.resolve(data, status); await tick(); await tick(); }
  return { $, doc, photo, submit, finish, requests, scrolls, exports, prints, session, Element };
}
const report = (summary = 'Valid report') => ({ findings: [], questions: [], sources: [], summary });

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
