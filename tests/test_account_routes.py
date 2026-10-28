"""The account journey must not unlock analysis before company verification."""
import pytest

import server
from account_delivery_runtime import synthetic_registration_capability


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'is_analysis_configured', lambda: True)
    monkeypatch.setattr(server, 'analizza_immagine', lambda *_: pytest.fail('Navigation called the provider'))
    return server.create_app({
        'TESTING': True, 'AUTH_MODE': 'accounts', 'ACCOUNT_REGISTRATION_OPEN': True,
        'ACCOUNT_REGISTRATION_TEST_CAPABILITY': synthetic_registration_capability(),
        'SECRET_KEY': 'synthetic-route-session-secret-32-characters',
        'SESSION_COOKIE_SECURE': False, 'PILOT_PASSWORD': None,
        'ACCOUNT_DB_PATH': str(tmp_path / 'accounts.db'),
        'RATE_DB_PATH': str(tmp_path / 'limits.db'),
        'CASE_DB_PATH': str(tmp_path / 'cases.db'),
    })


def signed_in(app, verified=False):
    store = app.extensions['account_store']
    user = store.register(email='route@example.test', password='a-synthetic-route-passphrase',
                          company_name='Route Fixture', role='representative')
    if verified:
        store.consume_token(store.issue_token(user['id'], 'email'), 'email')
        store.verify_company(user['company_id'], user['id'])
    client = app.test_client()
    token = client.get('/api/session').json['csrf']
    result = client.post('/api/login', json={'email': user['email'], 'password': 'a-synthetic-route-passphrase'},
                         headers={'X-CSRF-Token': token})
    assert result.status_code == 200
    return client, user


def test_anonymous_app_navigation_leads_to_account_without_redirect_loop(app):
    client = app.test_client()
    for path in ['/app', '/app/']:
        response = client.get(path)
        assert response.status_code == 302 and response.location == '/account'
        page = client.get(path, follow_redirects=True)
        assert page.status_code == 200
        assert 'account-register-form' in page.get_data(as_text=True)
    assert client.get('/register').status_code == 200


def test_pending_company_cannot_enter_workspace(app):
    client, _ = signed_in(app)
    assert client.get('/app/').location == '/account'
    assert 'account-status' in client.get('/account').get_data(as_text=True)


def test_verified_company_can_enter_workspace_and_revocation_returns_to_account(app):
    client, user = signed_in(app, True)
    assert client.get('/app/').status_code == 200
    assert 'analysis-form' in client.get('/app/').get_data(as_text=True)
    with app.extensions['account_store'].connect() as db:
        db.execute('UPDATE account_companies SET verified=0 WHERE id=?', (user['company_id'],))
    assert client.get('/app/').location == '/account'


def test_landing_registration_link_matches_configuration(app):
    client = app.test_client()
    assert 'href="/register"' in client.get('/').get_data(as_text=True)
    app.config['ACCOUNT_REGISTRATION_OPEN'] = False
    page = client.get('/').get_data(as_text=True)
    assert 'href="/register"' not in page and 'href="/account"' in page


def test_new_account_assets_use_same_origin_security_and_no_cache(app):
    client = app.test_client()
    for path in ['/register', '/account', '/static/account.js', '/static/account.css']:
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers['Cache-Control'] == 'no-store'
        assert "script-src 'self'" in response.headers['Content-Security-Policy']
    page = client.get('/register').get_data(as_text=True)
    for locale in ['it', 'de', 'fr', 'en']:
        assert f'value="{locale}"' in page


def test_missing_secret_does_not_open_registration_or_workspace(app):
    app.config['SECRET_KEY'] = None
    client = app.test_client()
    assert 'href="/register"' not in client.get('/').get_data(as_text=True)
    assert client.get('/api/session').json['auth_configured'] is False
    assert client.get('/app/').location == '/account'
