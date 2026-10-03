"""Umami analytics is opt-in through UMAMI_WEBSITE_ID.

Without the variable the page must not load the tracker at all, so local runs
and this suite never report visits. With it, the head carries the script tag
pointed at the configured website.
"""

import pytest

import app as app_module


@pytest.fixture()
def client():
    return app_module.app.test_client()


def test_no_tracker_without_website_id(client, monkeypatch):
    monkeypatch.delenv("UMAMI_WEBSITE_ID", raising=False)
    html = client.get("/").get_data(as_text=True)
    assert "data-website-id" not in html
    assert "umami" not in html.lower()


def test_tracker_in_head_with_website_id(client, monkeypatch):
    monkeypatch.setenv("UMAMI_WEBSITE_ID", "abc-123")
    monkeypatch.delenv("UMAMI_SCRIPT_URL", raising=False)
    html = client.get("/").get_data(as_text=True)
    head = html.split("</head>", 1)[0]
    assert 'src="https://cloud.umami.is/script.js"' in head
    assert 'data-website-id="abc-123"' in head
    assert "defer" in head.split('data-website-id="abc-123"')[0].rsplit("<script", 1)[1]


def test_script_url_override_for_self_hosting(client, monkeypatch):
    monkeypatch.setenv("UMAMI_WEBSITE_ID", "abc-123")
    monkeypatch.setenv("UMAMI_SCRIPT_URL", "https://stats.example.com/script.js")
    html = client.get("/").get_data(as_text=True)
    assert 'src="https://stats.example.com/script.js"' in html
    assert "cloud.umami.is" not in html
