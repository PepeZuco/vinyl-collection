"""The genre vocabulary: the one list every genre choice in the app comes from.

Style-based, not country-based — the old "MPB & Samba" bucket was retired and
its records spread over Samba, Bossa Nova, Singer-Songwriter and the rest.
Alphabetical, so the form's dropdown reads in a predictable order however the
counts shift; the charts sort by count on their own.

The page gets this list from the index route, the scan and search passes hand
it to Claude as the only genres it may answer with, and create/update reject a
genre that is not on it. templates/index.html keeps a colour per entry in
GENRE_PALETTE; tests/test_genres.py fails if the two drift apart.
"""

GENRES = [
    "Alternative & Indie",
    "Blues",
    "Bossa Nova",
    "Classical",
    "Compilations & Soundtracks",
    "Country",
    "Easy Listening",
    "Folk",
    "Hip Hop",
    "Jazz",
    "Pop",
    "R&B & Neo-Soul",
    "Reggae",
    "Rock",
    "Salsa",
    "Samba",
    "Singer-Songwriter",
    "Soft Rock",
    "Soul & Funk",
]


def canonical_genre(value):
    """The GENRES spelling of value, matched case- and whitespace-insensitively.

    Returns "" for a blank value and None for anything not on the list.
    """
    folded = " ".join((value or "").split()).casefold()
    if not folded:
        return ""
    for genre in GENRES:
        if genre.casefold() == folded:
            return genre
    return None
