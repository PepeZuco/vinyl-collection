"""Reading the owner's playlists and a playlist's songs, for the wishlist tool.

The Client is replaced by a stub whose pages() answers from a dict: these
functions only shape Spotify's paging objects, so the HTTP layer (already
covered by test_spotify_playlists.py) is not what is under test here.
"""

import spotify_sync


class StubClient:
    def __init__(self, pages):
        self._pages = pages
        self.asked = []

    def pages(self, path):
        self.asked.append(path)
        for prefix, items in self._pages.items():
            if path.startswith(prefix):
                yield from items
                return


def _track(title, artist, album, date="1969-09-26", image="https://i/x.jpg"):
    return {"type": "track", "name": title, "is_local": False,
            "artists": [{"name": artist}],
            "album": {"name": album, "release_date": date,
                      "images": [{"url": image}]}}


def test_user_playlists_shapes_each_playlist():
    c = StubClient({"/me/playlists": [
        {"id": "P1", "name": "Road trip", "owner": {"display_name": "Me"},
         "images": [{"url": "https://i/p1.jpg"}], "items": {"total": 42}},
        # Pre-2026 shape: the count is under "tracks", there are no images.
        {"id": "P2", "name": "Old", "owner": {"id": "someone"},
         "images": None, "tracks": {"total": 7}},
    ]})
    assert spotify_sync.user_playlists(c) == [
        {"id": "P1", "name": "Road trip", "image_url": "https://i/p1.jpg",
         "track_count": 42, "owner": "Me"},
        {"id": "P2", "name": "Old", "image_url": "", "track_count": 7,
         "owner": "someone"},
    ]


def test_user_playlists_skips_null_entries():
    c = StubClient({"/me/playlists": [None, {"id": "P1", "name": "A"}]})
    assert [p["id"] for p in spotify_sync.user_playlists(c)] == ["P1"]


def test_playlist_tracks_reads_the_items_path_and_both_entry_shapes():
    c = StubClient({"/playlists/PL/items": [
        {"item": _track("Come Together", "The Beatles", "Abbey Road")},
        {"track": _track("Something", "The Beatles", "Abbey Road")},
    ]})
    tracks, truncated = spotify_sync.playlist_tracks(c, "PL", cap=500)
    assert c.asked[0].startswith("/playlists/PL/items")
    assert "additional_types=track" in c.asked[0]
    assert truncated is False
    assert tracks == [
        {"title": "Come Together", "artists": ["The Beatles"], "album": "Abbey Road",
         "release_year": "1969", "image_url": "https://i/x.jpg"},
        {"title": "Something", "artists": ["The Beatles"], "album": "Abbey Road",
         "release_year": "1969", "image_url": "https://i/x.jpg"},
    ]


def test_playlist_tracks_skips_episodes_local_files_and_removed_tracks():
    local = _track("Demo", "Me", "Tape")
    local["is_local"] = True
    c = StubClient({"/playlists/PL/items": [
        {"item": {"type": "episode", "name": "A podcast"}},
        {"item": local},
        {"item": None},
        None,
        {"item": _track("Lovely Day", "Bill Withers", "Menagerie", date="1977")},
    ]})
    tracks, _ = spotify_sync.playlist_tracks(c, "PL", cap=500)
    assert [t["title"] for t in tracks] == ["Lovely Day"]
    assert tracks[0]["release_year"] == "1977"


def test_playlist_tracks_stops_at_the_cap_and_says_so():
    c = StubClient({"/playlists/PL/items": [
        {"item": _track(f"Song {i}", "A", "B")} for i in range(5)]})
    tracks, truncated = spotify_sync.playlist_tracks(c, "PL", cap=3)
    assert [t["title"] for t in tracks] == ["Song 0", "Song 1", "Song 2"]
    assert truncated is True


def test_playlist_tracks_exactly_at_the_cap_is_not_truncated():
    c = StubClient({"/playlists/PL/items": [
        {"item": _track(f"Song {i}", "A", "B")} for i in range(3)]})
    _, truncated = spotify_sync.playlist_tracks(c, "PL", cap=3)
    assert truncated is False
