'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ui = require('../static/account.js');
const html = fs.readFileSync(path.join(__dirname, '../templates/account.html'), 'utf8');

function element(id, i18n = null) {
  return { id, hidden: false, disabled: false, value: '', textContent: '', className: '', dataset: {}, attributes: i18n ? { 'data-i18n': i18n } : {}, listeners: {}, focused: false, children: [],
    setAttribute(key, value) { this.attributes[key] = value; }, getAttribute(key) { return this.attributes[key]; },
    addEventListener(type, fn) { this.listeners[type] = fn; }, focus() { this.focused = true; }, scrollIntoView() {},
    appendChild(child) { this.children.push(child); }, replaceChildren(...children) { this.children = children; if (this.id === 'consultation-case') this.value = children[0] ? children[0].value : ''; } };
}
function harness(responses = [], route = '/account', storedEntries = []) {
  const nodes = Object.fromEntries([...html.matchAll(/id="([^"]+)"/g)].map(match => [match[1], element(match[1])]));
  const translated = [...html.matchAll(/data-i18n="([^"]+)"/g)].map((match, index) => element('translated-' + index, match[1]));
  const saved = new Map(storedEntries), requests = [];
  const document = { title: '', documentElement: { lang: 'it' }, getElementById: id => { assert.ok(nodes[id], 'Known element ' + id); return nodes[id]; }, querySelectorAll: () => translated, querySelector: () => null, createElement: tag => element(tag) };
  const window = { location: { pathname: route }, navigator: { language: 'it-CH' }, localStorage: { getItem: key => saved.get(key) || null, setItem: (key, value) => saved.set(key, value) } };
  async function fetcher(url, options) {
    requests.push({ url, options });
    const response = responses.shift();
    if (response instanceof Error) throw response;
    assert.ok(response, 'A response fixture is required for ' + url);
    if (typeof response === 'function') return response(url, options);
    return { ok: response.status === undefined || response.status < 400, status: response.status || 200, json: async () => response.data };
  }
  const controller = ui.createController(document, window, fetcher);
  return { controller, nodes, document, window, saved, requests, translated, responses };
}
const anonymous = { authenticated: false, auth_mode: 'accounts', registration_open: true, csrf: 'csrf-before' };
const pending = { ...anonymous, authenticated: true, csrf: 'csrf-after', account: { id: 'user-1', email: 'user@example.test', locale: 'it', role: 'owner', email_verified: false, membership_verified: false, company: { id: 'company-1', name: 'Example Company', identifier: 'CHE-example', verified: false }, eligible_for_analysis: false } };
const verified = { ...pending, account: { ...pending.account, email_verified: true, membership_verified: true, company: { ...pending.account.company, verified: true }, eligible_for_analysis: true } };

test('All new screen labels and error messages have the same four language keys', () => {
  assert.deepEqual(ui.locales.sort(), ['de', 'en', 'fr', 'it']);
  const keys = Object.keys(ui.dictionaries.it).sort();
  for (const language of ui.locales) {
    assert.deepEqual(Object.keys(ui.dictionaries[language]).sort(), keys);
    for (const key of keys) assert.ok(ui.dictionaries[language][key].trim(), language + ':' + key);
  }
  for (const match of html.matchAll(/data-i18n="([^"]+)"/g)) assert.ok(keys.includes(match[1]), match[1]);
});

test('Account journey states that verification, recovery and invitations have no email delivery', () => {
  const patterns = {
    it: [/verific/i, /recuper/i, /invit/i],
    de: [/Bestät|Prüf/i, /Wiederher/i, /Einlad/i],
    fr: [/vérific/i, /récup/i, /invit/i],
    en: [/verif/i, /recover/i, /invit/i]
  };
  for (const language of ui.locales) {
    const copy = ui.dictionaries[language].deliveryNote + ' ' + ui.dictionaries[language].recoveryNote;
    for (const pattern of patterns[language]) assert.match(copy, pattern, language + ':' + pattern);
  }
  const source = html + fs.readFileSync(path.join(__dirname, '../static/account.js'), 'utf8');
  assert.doesNotMatch(source, /mailto:|\/api\/accounts\/(?:request-reset|invite)/i);
  assert.doesNotMatch(html, /action=|formaction=/i);
});

test('Registration screen initial state uses server configuration and reveals no app access', async () => {
  const h = harness([{ data: anonymous }], '/register'); await h.controller.start();
  assert.equal(h.nodes['account-register-form'].hidden, false);
  assert.equal(h.nodes['account-login-form'].hidden, true);
  assert.equal(h.nodes['account-status'].hidden, true);
  assert.equal(h.nodes['account-workspace'].hidden, true);
  assert.equal(h.nodes['account-loading'].hidden, true);
});

test('Pilot mode offers the real pilot route without a company registration form', async () => {
  const h = harness([{ data: { authenticated: false, auth_mode: 'pilot', csrf: 'token' } }]); await h.controller.start();
  assert.equal(h.nodes['account-unavailable'].hidden, false);
  assert.equal(h.nodes['account-auth'].hidden, true);
  assert.equal(h.nodes['account-status'].hidden, true);
});

test('Closed registrations cannot be submitted even when invoked directly', async () => {
  const h = harness([{ data: { ...anonymous, registration_open: false } }], '/register'); await h.controller.start();
  assert.equal(h.nodes['registration-closed'].hidden, false);
  assert.equal(h.nodes['account-register-form'].hidden, true);
  assert.equal(h.nodes['show-register'].hidden, true);
  await h.controller.register({ preventDefault() {} });
  assert.equal(h.requests.length, 1);
});

test('A stale registration closes on delivery interlock failure in every language without retry', async () => {
  for (const language of ui.locales) {
    const h = harness([{ data: anonymous }, { status: 503, data: { error: {
      code: 'account_delivery_unavailable', message: 'PRIVATE PROVIDER PATH OR SECRET'
    }, registration_open: false } }], '/register');
    await h.controller.start(); h.controller.setLanguage(language);
    h.nodes['register-password'].value = 'synthetic-password-only';
    await h.controller.register({ preventDefault() {} });
    assert.equal(h.controller.state.registrationOpen, false);
    assert.equal(h.controller.state.view, 'login');
    assert.equal(h.nodes['account-register-form'].hidden, true);
    assert.equal(h.nodes['show-register'].hidden, true);
    assert.equal(h.nodes['account-login-form'].hidden, false);
    assert.equal(h.nodes['register-password'].value, '');
    assert.equal(h.nodes['account-notice'].textContent, ui.dictionaries[language].errorDeliveryUnavailable);
    assert.equal(h.nodes['account-notice'].focused, true);
    assert.equal(h.controller.state.busy, false);
    assert.equal(h.requests.length, 2);
    await h.controller.register({ preventDefault() {} });
    assert.equal(h.requests.length, 2);
  }
});

test('Missing authentication configuration or CSRF disables account mutations', async () => {
  const h = harness([{ data: { ...anonymous, csrf: null, auth_configured: false } }], '/register'); await h.controller.start();
  assert.equal(h.nodes['register-submit'].disabled, true); assert.equal(h.nodes['login-submit'].disabled, true);
  assert.equal(h.nodes['account-notice'].textContent, ui.dictionaries.it.errorConfiguration);
  await h.controller.register({ preventDefault() {} }); await h.controller.login({ preventDefault() {} });
  assert.equal(h.requests.length, 1);
});

test('Pending email/company/member states stay separate and never unlock workspace', async () => {
  const h = harness([{ data: pending }]); await h.controller.start();
  assert.equal(h.nodes['account-status'].hidden, false);
  assert.equal(h.nodes['email-verification'].dataset.state, 'pending');
  assert.equal(h.nodes['company-verification'].dataset.state, 'pending');
  assert.equal(h.nodes['membership-verification'].dataset.state, 'pending');
  assert.equal(h.nodes['email-verification'].textContent, ui.dictionaries.it.emailPending);
  assert.equal(h.nodes['company-verification'].textContent, ui.dictionaries.it.companyPending);
  assert.equal(h.nodes['membership-verification'].textContent, ui.dictionaries.it.membershipPending);
  assert.match(h.nodes['company-verification'].textContent, /operatore/i);
  assert.equal(h.nodes['verification-pending-note'].hidden, false);
  assert.equal(h.nodes['delivery-note'].hidden, false);
  assert.equal(h.nodes['account-workspace'].hidden, true);
  h.controller.applySession({ ...pending, account: { ...pending.account, email_verified: true } });
  assert.equal(h.nodes['email-verification'].dataset.state, 'verified');
  assert.equal(h.nodes['email-verification'].textContent, ui.dictionaries.it.emailVerified);
  assert.equal(h.nodes['company-verification'].dataset.state, 'pending');
  assert.equal(h.nodes['delivery-note'].hidden, true);
  assert.equal(h.nodes['account-workspace'].hidden, true);
});

test('Every language distinguishes email, company and membership review without automatic approval', () => {
  const required = {
    it: /operatore/i,
    de: /zuständige Person/i,
    fr: /personne responsable/i,
    en: /operator/i
  };
  for (const language of ui.locales) {
    const copy = ui.dictionaries[language];
    assert.notEqual(copy.emailPending, copy.companyPending);
    assert.notEqual(copy.companyPending, copy.membershipPending);
    assert.match(copy.companyPending, required[language]);
    assert.match(copy.pendingNote, /non|nicht|pas|not/i);
  }
});

test('Workspace link requires every explicit verification flag and backend eligibility', async () => {
  assert.equal(ui.eligible(verified.account), true);
  for (const patch of [{ eligible_for_analysis: false }, { email_verified: false }, { membership_verified: false }, { company: { verified: false } }, { company: undefined }, { email_verified: 'true' }]) assert.equal(ui.eligible({ ...verified.account, ...patch }), false);
  const h = harness([{ data: verified }]); await h.controller.start();
  assert.equal(h.nodes['account-workspace'].hidden, false);
  assert.equal(h.nodes['verification-pending-note'].hidden, true);
  h.controller.applySession({ ...verified, account: { ...verified.account, eligible_for_analysis: false } });
  assert.equal(h.nodes['account-workspace'].hidden, true);
});

test('Checkout CTA is visible only to a verified account when the sandbox is available', async () => {
  const h = harness([{ data: { ...verified, billing_sandbox_available: true } }]); await h.controller.start();
  assert.equal(h.nodes['billing-checkout-link'].hidden, false);
  h.controller.applySession({ ...verified, billing_sandbox_available: false });
  assert.equal(h.nodes['billing-checkout-link'].hidden, true);
  h.controller.applySession({ ...pending, billing_sandbox_available: true });
  assert.equal(h.nodes['billing-checkout-link'].hidden, true);
});

test('Registration submits one CSRF-protected payload, clears password and makes no analysis request', async () => {
  const h = harness([{ data: anonymous }, { status: 202, data: { registered: true, verification_required: true, delivery_configured: false } }], '/register'); await h.controller.start();
  Object.assign(h.nodes['register-email'], { value: ' person@example.test ' });
  h.nodes['register-password'].value = 'synthetic-password-only'; h.nodes['register-company'].value = ' Example AG ';
  h.nodes['register-identifier'].value = ' CHE-fixture '; h.nodes['register-role'].value = 'owner';
  h.controller.setLanguage('de'); await h.controller.register({ preventDefault() {} });
  const req = h.requests[1]; assert.equal(req.url, '/api/accounts/register');
  assert.equal(req.options.headers['X-CSRF-Token'], 'csrf-before');
  assert.deepEqual(JSON.parse(req.options.body), { email: 'person@example.test', password: 'synthetic-password-only', company_name: 'Example AG', company_identifier: 'CHE-fixture', role: 'owner', locale: 'de' });
  assert.equal(h.nodes['register-password'].value, ''); assert.equal(h.nodes['login-email'].value, 'person@example.test');
  assert.equal(h.nodes['account-notice'].textContent, ui.dictionaries.de.created); assert.equal(h.nodes['account-notice'].focused, true);
  assert.equal(h.nodes['account-login-form'].hidden, false); assert.equal(h.controller.state.authenticated, false);
  assert.deepEqual([...h.saved.entries()], [[ui.storageKey, 'de']]); assert.equal(h.requests.some(r => r.url === '/analizza'), false);
});

test('Login rotates CSRF from server and logout uses the new token', async () => {
  const h = harness([{ data: anonymous }, { data: pending }, { data: { authenticated: false } }, { data: { ...anonymous, csrf: 'csrf-after-logout' } }]); await h.controller.start();
  h.nodes['login-email'].value = 'user@example.test'; h.nodes['login-password'].value = 'synthetic-password-only';
  await h.controller.login({ preventDefault() {} });
  assert.equal(h.nodes['login-password'].value, ''); assert.equal(h.controller.state.csrf, 'csrf-after');
  assert.equal(h.nodes['status-heading'].focused, true); assert.equal(h.nodes['account-workspace'].hidden, true);
  await h.controller.logout();
  assert.equal(h.requests[2].url, '/api/logout'); assert.equal(h.requests[2].options.headers['X-CSRF-Token'], 'csrf-after');
  assert.equal(h.controller.state.authenticated, false); assert.equal(h.controller.state.account, null);
  assert.equal(h.controller.state.csrf, 'csrf-after-logout'); assert.equal(h.nodes['account-company-name'].textContent, '');
});

test('Status refresh hides access immediately if eligibility has been revoked', async () => {
  const h = harness([{ data: verified }, { data: pending }]); await h.controller.start(); assert.equal(h.nodes['account-workspace'].hidden, false);
  await h.controller.refresh(true); assert.equal(h.nodes['account-workspace'].hidden, true); assert.equal(h.nodes['account-notice'].textContent, ui.dictionaries.it.statusUpdated);
});

test('User and company values render as text without innerHTML', async () => {
  const name = '<img src=x onerror=alert(1)>';
  const h = harness([{ data: { ...pending, account: { ...pending.account, company: { ...pending.account.company, name } } } }]); await h.controller.start();
  assert.equal(h.nodes['account-company-name'].textContent, name);
  assert.equal(fs.readFileSync(path.join(__dirname, '../static/account.js'), 'utf8').includes('.innerHTML'), false);
});

test('Errors are localised and focused, not echoed from raw server content', async () => {
  const h = harness([{ data: anonymous }, { status: 401, data: { error: { code: 'invalid_credentials', message: 'RAW SERVER CONTENT' } } }]); await h.controller.start(); h.controller.setLanguage('fr');
  h.nodes['login-email'].value = 'user@example.test'; h.nodes['login-password'].value = 'wrong'; await h.controller.login({ preventDefault() {} });
  assert.equal(h.nodes['account-notice'].textContent, ui.dictionaries.fr.errorCredentials); assert.equal(h.nodes['account-notice'].focused, true);
  assert.equal(h.nodes['login-submit'].disabled, false); assert.equal(h.controller.state.busy, false);
  assert.equal(h.nodes['account-workspace'].hidden, true);
});

test('Network failure clears busy state and shows a useful translated error', async () => {
  const h = harness([new Error('offline')]); await h.controller.start();
  assert.equal(h.nodes['account-loading'].hidden, true); assert.equal(h.nodes['account-notice'].textContent, ui.dictionaries.it.errorNetwork);
  assert.equal(h.controller.state.busy, false);
});

test('A registration conflict stays distinct from closed registration in every language', async () => {
  for (const language of ui.locales) {
    for (const response of [
      { status: 409, code: 'registration_unavailable', key: 'errorDuplicate' },
      { status: 503, code: 'registration_closed', key: 'errorClosed' }
    ]) {
      const h = harness([{ data: anonymous }, { status: response.status, data: { error: { code: response.code, message: 'PRIVATE CONFLICT FIELD' } } }], '/register');
      await h.controller.start(); h.controller.setLanguage(language);
      await h.controller.register({ preventDefault() {} });
      assert.equal(h.nodes['account-notice'].textContent, ui.dictionaries[language][response.key]);
      assert.equal(h.nodes['account-notice'].focused, true);
      assert.equal(h.nodes['account-register-form'].hidden, false);
      assert.equal(h.nodes['register-submit'].disabled, false);
      assert.equal(h.controller.state.authenticated, false);
      assert.equal(h.requests.length, 2);
    }
  }
});

test('Duplicate clicks while a request is pending do not create two registrations', async () => {
  let release;
  const h = harness([{ data: anonymous }, () => new Promise(resolve => { release = () => resolve({ ok: true, status: 202, json: async () => ({ registered: true }) }); })], '/register'); await h.controller.start();
  const first = h.controller.register({ preventDefault() {} });
  assert.equal(h.nodes['register-submit'].disabled, true); assert.equal(h.nodes['account-auth'].attributes['aria-busy'], 'true');
  await h.controller.register({ preventDefault() {} }); assert.equal(h.requests.length, 2);
  release(); await first; assert.equal(h.nodes['register-submit'].disabled, false); assert.equal(h.nodes['account-auth'].attributes['aria-busy'], 'false');
});

test('Language survives a refresh without persisting account credentials', async () => {
  const h = harness([{ data: anonymous }]); await h.controller.start(); h.controller.setLanguage('en');
  assert.equal(h.document.documentElement.lang, 'en'); assert.equal(h.document.title, ui.dictionaries.en.pageTitle);
  assert.equal(h.nodes['account-heading'].textContent, ui.dictionaries.en.loginTitle);
  assert.deepEqual([...h.saved.keys()], [ui.storageKey]);
});

test('Account shares the site and app locale key and reads the previous account key', async () => {
  const h = harness([{ data: anonymous }], '/account', [[ui.legacyStorageKey, 'fr']]);
  await h.controller.start();
  assert.equal(ui.storageKey, 'slps.locale');
  assert.equal(h.controller.state.language, 'fr');
  h.controller.setLanguage('de');
  assert.equal(h.saved.get('slps.locale'), 'de');
  assert.equal(h.saved.get(ui.legacyStorageKey), 'fr');
});

test('New screen includes accessible controls and responsive/reduced-motion rules', () => {
  assert.match(html, /role="status" aria-live="polite" aria-atomic="true" tabindex="-1"/);
  assert.match(html, /autocomplete="new-password" minlength="16" maxlength="256"/);
  assert.match(html, /<label[^>]+for="account-language"/);
  assert.doesNotMatch(html, /onclick=|style=/);
  const css = fs.readFileSync(path.join(__dirname, '../static/account.css'), 'utf8');
  assert.match(css, /@media\(max-width:740px\)/); assert.match(css, /prefers-reduced-motion/);
});

test('Verified user can inspect ledger and record one case-bound phone request without contact side effects', async () => {
  const consultation = { included: 1, reserved: 0, used: 0, cancelled: 0, balance: 1, next_reset: '2027-10-26T10:00:00Z', period_months: 12, requests: [] };
  const recorded = { ...consultation, reserved: 1, balance: 0, request_id: 'request-1', requests: [{ id:'request-1', case_id:'case-1', user_id:'user-1', channel:'phone', status:'reserved' }] };
  const h = harness([{ data: verified }, { data: { consultation, cases: [{ id:'case-1', summary:'Analisi officina' }], hypothesis:true } }, { status:201, data:{ recorded:true, contacted:false, charged:false, consultation:recorded } }]);
  await h.controller.start();
  assert.equal(h.nodes['consultation-panel'].hidden, false);
  await h.controller.loadConsultations();
  assert.equal(h.nodes['consultation-content'].hidden, false);
  assert.equal(h.nodes['consultation-balance'].textContent, '1');
  assert.equal(h.nodes['consultation-availability'].textContent, ui.dictionaries.it.consultationAvailableState);
  assert.equal(h.nodes['consultation-case'].value, 'case-1');
  await h.controller.requestConsultation({ preventDefault() {} });
  const request = h.requests[2];
  assert.equal(request.url, '/api/consultations');
  assert.equal(request.options.headers['X-CSRF-Token'], 'csrf-after');
  assert.ok(request.options.headers['Idempotency-Key'].length >= 12);
  assert.deepEqual(JSON.parse(request.options.body), { case_id:'case-1', channel:'phone' });
  assert.equal(h.nodes['consultation-result'].textContent, ui.dictionaries.it.consultationRecorded);
  assert.equal(h.nodes['consultation-result'].focused, true);
  assert.equal(h.nodes['consultation-balance'].textContent, '0');
  assert.equal(h.nodes['consultation-availability'].textContent, ui.dictionaries.it.consultationExhaustedState);
  assert.equal(h.nodes['consultation-requests'].children[0].textContent.startsWith('Canale: telefono · stato: prenotata · Analisi officina'), true);
  assert.equal(h.nodes['consultation-requests'].children[0].textContent.includes('case-1'), false);
});

test('Consultation conflicts have distinct messages before generic HTTP 409 mapping', () => {
  assert.equal(ui.errorKey('consultation_unavailable', 409), 'consultationUnavailable');
  assert.equal(ui.errorKey('idempotency_mismatch', 409), 'consultationIdempotency');
  assert.equal(ui.errorKey('registration_unavailable', 409), 'errorDuplicate');
  for (const language of ui.locales) {
    assert.notEqual(ui.dictionaries[language].consultationUnavailable, ui.dictionaries[language].errorDuplicate);
    assert.notEqual(ui.dictionaries[language].consultationIdempotency, ui.dictionaries[language].errorDuplicate);
  }
});

test('Consultation interface contains no private contact link, price, duration cap or provider call', () => {
  const source = html + fs.readFileSync(path.join(__dirname, '../static/account.js'), 'utf8');
  assert.doesNotMatch(source, /tel:|wa\.me|phone_number|stripe|paypal/i);
  assert.doesNotMatch(source, /\b(?:15|99|199)\s*(?:CHF|franchi)\b/i);
  assert.match(source, /Nessun messaggio o chiamata è stato inviato/);
  assert.match(source, /non è prevista una durata massima/i);
});
