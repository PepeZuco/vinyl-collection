# Search by name — what to check by hand

The suite mocks Claude, MusicBrainz, Cover Art Archive and iTunes. These are
the things only the real ones can tell you. Needs `ANTHROPIC_API_KEY` and
`MUSICBRAINZ_CONTACT` set.

---

## Before you start

Set these on Railway (see README):

| Variable | Needed for |
|---|---|
| `ANTHROPIC_API_KEY` | reading the query, parsing what you typed |
| `MUSICBRAINZ_CONTACT` | the required MusicBrainz `User-Agent` |

---

## The price is what the hint claimed

1. Note the month total under the Analyse button.
2. Search `jorge ben`. The hint said roughly 0.05¢ for a query parse.
3. Reopen the form. The month total should have moved by about that much —
   an order of magnitude under a photo scan, which is the point of using
   Haiku for a query parse.

---

## Thirty covers arrive in a tolerable time

Search an artist with a long discography (`jorge ben`, `rita lee`,
`pink floyd`). Expect the grid within about **30 seconds**: MusicBrainz is 
heavily rate-limited, and it is not unusual for the artist search or artist-country 
lookups to retry once or twice, each hitting the 1-second throttle plus backoff. 
The form's existing *"this can take up to a minute"* copy covers this. Do not 
treat 30 seconds as a fault.

Rows past the 24th showing **"no artwork found"** are expected — that is the 
`COVER_FETCH_LIMIT`, not a bug. A search for `jorge ben` in particular returns 
30 releases, but only 24 of them have artwork in the Cover Art Archive. The cap 
working correctly is the most likely thing to be misread as a defect.

---

## A search of an artist you own badges the right rows

Search `jorge ben` with *Ben é Samba Bom*, *A Tábua de Esmeralda* and
*África Brasil* in the collection. All three should wear the red bar.

If none do, the credited-versus-canonical artist name has regressed:
MusicBrainz canonicalises to "Jorge Ben Jor" and the collection says
"Jorge Ben". The app matches on the **credited** artist name as well as the 
canonical one (see `_search_duplicate` in `app.py`). If a search returns zero 
badged records when it should return three, that function is the cause.

---

## An unreachable MusicBrainz says so

MusicBrainz sheds load with a 503 often enough to hit by trying a few
searches in a row. When it does, the message must be **"couldn't reach
MusicBrainz"**, never **"no artist matched"** — they call for different next
steps from you.

---

## The form is filled with the credited name

After adding a Jorge Ben record from a search, the shelf must show it in the
same crate as the ones already there — not a second "Jorge Ben Jor" crate
beside it.

---

## A queue survives a wrong turn

Pick three releases. On record two, hit **skip this one**: the counter goes to 
"2 of 2" and record three is on screen. Start again, and on record two hit 
**cancel**: it should warn that one more record is waiting and will be dropped.
