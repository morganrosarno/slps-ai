"""Landing and workspace routing must not trigger the analysis provider."""
from html.parser import HTMLParser

import pytest

import server


class PageLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.ids = set()
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if "id" in attributes:
            self.ids.add(attributes["id"])
        if tag == "a":
            self.links.append(attributes.get("href", ""))
        if tag == "script":
            self.scripts.append(attributes.get("src", ""))


@pytest.fixture
def client(tmp_path, monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("Page navigation must not call the analysis provider")

    monkeypatch.setattr(server, "analizza_immagine", forbidden)
    app = server.create_app({
        "TESTING": True,
        "SECRET_KEY": "site-route-test-session-secret-32-chars",
        "PILOT_PASSWORD": "site-route-test-password",
        "SESSION_COOKIE_SECURE": False,
        "RATE_DB_PATH": str(tmp_path / "limits.sqlite3"),
        "CASE_DB_PATH": str(tmp_path / "cases.sqlite3"),
    })
    return app.test_client()


def test_home_is_a_static_landing_with_working_navigation(client):
    response = client.get("/")
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "Dalla foto," in page
    assert "Progetto in collaudo riservato" in page
    parsed = PageLinks()
    parsed.feed(page)
    assert not parsed.scripts
    assert "analysis-form" not in parsed.ids
    assert parsed.links.count("/app") >= 3
    for href in parsed.links:
        if href.startswith("#"):
            assert href[1:] in parsed.ids
        else:
            assert href in {"/", "/app"}
            assert client.get(href).status_code == 200
    assert client.get("/static/landing.css").status_code == 200


@pytest.mark.parametrize("path", ["/app", "/app/"])
def test_workspace_paths_serve_existing_application_without_redirect(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert not response.location
    parsed = PageLinks()
    parsed.feed(response.get_data(as_text=True))
    assert "analysis-form" in parsed.ids
    assert "login-form" in parsed.ids
    assert parsed.scripts == ["/static/app.js"]


def test_health_and_anonymous_api_protection_are_unchanged(client):
    assert client.get("/healthz").json == {"status": "ok"}
    response = client.post("/analizza")
    assert response.status_code == 401
    assert response.json["error"]["code"] == "authentication_required"
    assert client.get("/api/cases").status_code == 401
