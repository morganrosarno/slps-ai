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

async function fixture({ reducedMotion = false } = {}) {
  const elements = new Map(), requests = [], scrolls = [], exports = [];
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
    querySelectorAll(selector) { return this.childNodes.flatMap(child => child instanceof Element ? [...(selector === 'textarea' && child.tagName === 'TEXTAREA' ? [child] : []), ...child.querySelectorAll(selector)] : []); }
    cloneNode() { const copy = new Element(this.tagName, this.id); Object.assign(copy, this); copy.childNodes = this.childNodes.map(child => child instanceof Element ? child.cloneNode(true) : child); copy.handlers = {}; return copy; }
    async decode() { throw new Error('No bitmap in this DOM fixture'); }
    reset() { this.value = ''; }
  }
  for (const match of template.matchAll(/<([a-z][\w-]*)\b[^>]*\bid="([^"]+)"[^>]*>/g)) {
    const element = new Element(match[1], match[2]); element.hidden = /\bhidden\b/.test(match[0]); elements.set(element.id, element);
  }
  const $ = id => elements.get(id);
  // The report draft isolates all report field writes until renderAnalysis commits them.
  $('report').cloneNode = () => {
    const copies = new Map([...elements].filter(([id]) => id !== 'report').map(([id, element]) => [id, element.cloneNode(true)]));
    return { querySelector: selector => copies.get(selector.slice(1)) };
  };
  doc = { getElementById: $, createElement: tag => new Element(tag), createTextNode: text => text, body: new Element('body'), activeElement: null };
  const session = { authenticated: true, configured: true, csrf: 'test-csrf' };
  const response = (data, status = 200) => ({ ok: status < 400, status, json: async () => data });
  const context = { document: doc, window: { matchMedia: () => ({ matches: reducedMotion }), print() {} }, URL: class extends URL { static createObjectURL(value) { if (value instanceof Blob) exports.push(value); return 'blob:test-photo'; } static revokeObjectURL() {} }, Blob, AbortController, FormData: class { append() {} }, setTimeout: callback => { callback(); }, console,
    fetch: async url => url === '/api/session' ? response(session) : new Promise(resolve => requests.push({ url, resolve: (data, status) => resolve(response(data, status)) })) };
  vm.runInNewContext(script, context, { filename: 'static/app.js' }); await tick();
  function photo(name = 'sample.jpg') { $('photo').files = [{ name, type: 'image/jpeg', size: 100 }]; $('photo').handlers.change(); }
  async function submit(origin = 'analysis') { $(origin + '-form').handlers.submit({ preventDefault() {} }); await tick(); }
  async function finish(data, status = 200) { const request = requests.shift(); assert.equal(request.url, '/analizza'); request.resolve(data, status); await tick(); await tick(); }
  return { $, doc, photo, submit, finish, requests, scrolls, exports, session, Element };
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
