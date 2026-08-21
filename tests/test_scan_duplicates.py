from scan import find_duplicate

EXISTING = [
    {"id": 1, "artist": "Bill Withers", "album_name": "Live at Carnegie Hall"},
    {"id": 2, "artist": "Sérgio Mendes", "album_name": "Brasil '66"},
    {"id": 3, "artist": "The Beatles", "album_name": "Abbey Road"},
    {"id": 4, "artist": "Bill Withers", "album_name": "Bill Withers' Greatest Hits"},
]


def test_exact_match():
    assert find_duplicate("Bill Withers", "Live at Carnegie Hall", EXISTING)["id"] == 1


def test_case_insensitive():
    assert find_duplicate("BILL WITHERS", "live at carnegie hall", EXISTING)["id"] == 1


def test_accents_ignored():
    assert find_duplicate("Sergio Mendes", "Brasil '66", EXISTING)["id"] == 2


def test_leading_article_ignored():
    assert find_duplicate("Beatles", "Abbey Road", EXISTING)["id"] == 3


def test_punctuation_ignored():
    assert find_duplicate(
        "Bill Withers", "Bill Withers Greatest Hits", EXISTING
    )["id"] == 4


def test_no_match_returns_none():
    assert find_duplicate("Adele", "30", EXISTING) is None


def test_album_must_also_match():
    assert find_duplicate("Bill Withers", "Menagerie", EXISTING) is None


def test_empty_inputs_return_none():
    assert find_duplicate("", "", EXISTING) is None
    assert find_duplicate("Adele", "30", []) is None
