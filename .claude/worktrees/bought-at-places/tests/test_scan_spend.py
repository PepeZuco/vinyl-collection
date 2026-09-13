"""The scan spend ledger, and the readout the form shows before you spend."""
from unittest.mock import patch

import pytest

import app as app_module
import pricing

SLEEVE = {"artist": "Bill Withers", "album_name": "Menagerie", "genre": "Soul & Funk",
          "label": None, "catalog_number": None}
RESOLVED = {"artist": "Bill Withers", "album_name": "Menagerie",
            "image_url": "https://i.scdn.co/image/big"}


@pytest.fixture
def client():
    """An authed client over an empty ledger.

    The database is session-scoped, so rows left by another test would land in
    this module's month totals.
    """
    app_module.app.config["TESTING"] = True
    with app_module.app.app_context():
        app_module.ScanSpend.query.delete()
        app_module.db.session.commit()
    with app_module.app.test_client() as test_client:
        with test_client.session_transaction() as session:
            session["authed"] = True
        yield test_client


def _spending_extract(tokens_in=1000, tokens_out=200):
    """Stand-in for extract_from_image that bills like the real one."""
    def extract(image, genres, usage_out=None):
        if usage_out is not None:
            usage_out.append({"model": "claude-sonnet-5",
                              "input_tokens": tokens_in, "output_tokens": tokens_out})
        return SLEEVE
    return extract


def _rows():
    with app_module.app.app_context():
        return app_module.ScanSpend.query.all()


def test_a_photo_scan_records_what_it_spent(client):
    with patch.object(app_module.scan, "extract_from_image",
                      side_effect=_spending_extract()), \
         patch.object(app_module.scan, "lookup_musicbrainz", return_value=[]):
        assert client.post("/api/scan",
                           json={"image": "data:image/jpeg;base64,x"}).status_code == 200

    rows = _rows()
    assert len(rows) == 1
    assert rows[0].source == "photo"
    assert rows[0].model == "claude-sonnet-5"
    assert rows[0].input_tokens == 1000
    assert rows[0].output_tokens == 200
    assert rows[0].cost_usd == pricing.cost_usd("claude-sonnet-5", 1000, 200)


def test_a_spotify_scan_records_its_genre_call(client):
    def classify(artist, album, genres, usage_out=None):
        if usage_out is not None:
            usage_out.append({"model": "claude-haiku-4-5",
                              "input_tokens": 90, "output_tokens": 12})
        return "Soul & Funk"

    with patch.object(app_module.scan, "extract_from_spotify", return_value=RESOLVED), \
         patch.object(app_module.scan, "classify_genre", side_effect=classify), \
         patch.object(app_module.scan, "lookup_musicbrainz", return_value=[]):
        client.post("/api/scan", json={"spotify_url": "spotify:album:abc"})

    rows = _rows()
    assert len(rows) == 1
    assert rows[0].source == "spotify"
    assert rows[0].model == "claude-haiku-4-5"


def test_spend_is_recorded_when_the_scan_fails_after_the_api_call(client):
    """MusicBrainz blowing up does not refund the vision call."""
    with patch.object(app_module.scan, "extract_from_image",
                      side_effect=_spending_extract()), \
         patch.object(app_module.scan, "lookup_musicbrainz",
                      side_effect=TypeError("contract violated")):
        assert client.post("/api/scan",
                           json={"image": "data:image/jpeg;base64,x"}).status_code == 502

    assert len(_rows()) == 1


def test_a_scan_that_never_reached_the_api_records_nothing(client):
    with patch.object(app_module.scan, "extract_from_image",
                      side_effect=RuntimeError("ANTHROPIC_API_KEY is not set")):
        client.post("/api/scan", json={"image": "data:image/jpeg;base64,x"})

    assert _rows() == []


def test_usage_readout_requires_auth():
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as anon:
        assert anon.get("/api/scan/usage").status_code == 401


def test_usage_readout_totals_the_ledger(client):
    with patch.object(app_module.scan, "extract_from_image",
                      side_effect=_spending_extract()), \
         patch.object(app_module.scan, "lookup_musicbrainz", return_value=[]):
        client.post("/api/scan", json={"image": "data:image/jpeg;base64,x"})
        client.post("/api/scan", json={"image": "data:image/jpeg;base64,x"})

    body = client.get("/api/scan/usage").get_json()
    one_scan = pricing.cost_usd("claude-sonnet-5", 1000, 200)
    assert body["month_scans"] == 2
    assert body["total_scans"] == 2
    assert body["month_usd"] == pytest.approx(one_scan * 2)
    assert body["total_usd"] == pytest.approx(one_scan * 2)


def test_the_estimate_is_the_average_of_past_scans_of_that_source(client):
    with patch.object(app_module.scan, "lookup_musicbrainz", return_value=[]):
        with patch.object(app_module.scan, "extract_from_image",
                          side_effect=_spending_extract(1000, 200)):
            client.post("/api/scan", json={"image": "data:image/jpeg;base64,x"})
        with patch.object(app_module.scan, "extract_from_image",
                          side_effect=_spending_extract(3000, 600)):
            client.post("/api/scan", json={"image": "data:image/jpeg;base64,x"})

    body = client.get("/api/scan/usage").get_json()
    expected = (pricing.cost_usd("claude-sonnet-5", 1000, 200)
                + pricing.cost_usd("claude-sonnet-5", 3000, 600)) / 2
    assert body["estimate"]["photo"] == pytest.approx(expected)


def test_the_estimate_falls_back_to_a_seed_with_no_history(client):
    body = client.get("/api/scan/usage").get_json()
    assert body["estimate"]["photo"] == app_module.SEED_ESTIMATE_USD["photo"]
    assert body["estimate"]["spotify"] == app_module.SEED_ESTIMATE_USD["spotify"]
    assert body["month_usd"] == 0
    assert body["total_scans"] == 0


def test_the_two_sources_are_estimated_separately(client):
    """A cheap Spotify scan must not drag down the photo estimate."""
    def classify(artist, album, genres, usage_out=None):
        if usage_out is not None:
            usage_out.append({"model": "claude-haiku-4-5",
                              "input_tokens": 90, "output_tokens": 12})
        return "Jazz"

    with patch.object(app_module.scan, "lookup_musicbrainz", return_value=[]), \
         patch.object(app_module.scan, "extract_from_image",
                      side_effect=_spending_extract()):
        client.post("/api/scan", json={"image": "data:image/jpeg;base64,x"})
    with patch.object(app_module.scan, "lookup_musicbrainz", return_value=[]), \
         patch.object(app_module.scan, "extract_from_spotify", return_value=RESOLVED), \
         patch.object(app_module.scan, "classify_genre", side_effect=classify):
        client.post("/api/scan", json={"spotify_url": "spotify:album:abc"})

    estimate = client.get("/api/scan/usage").get_json()["estimate"]
    assert estimate["photo"] == pytest.approx(pricing.cost_usd("claude-sonnet-5", 1000, 200))
    assert estimate["spotify"] == pytest.approx(pricing.cost_usd("claude-haiku-4-5", 90, 12))
