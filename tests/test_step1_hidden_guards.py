"""Elements whose `hidden` toggle needs an author-origin [hidden] guard to
beat a UA-origin one.

renderStep1Phone (templates/index.html) switches its three phone-only states
by setting the `hidden` IDL property on four elements: #phoneLookup,
#phoneIdentity, .form-layout and #censorRow. The browser's own [hidden]{
display:none} rule lives in the UA stylesheet, and author-origin CSS always
wins over UA-origin CSS regardless of specificity — so any of these four
elements also carrying an unconditional author `display:` declaration (all
four do, for the phone layout itself) makes `el.hidden = true` a no-op unless
an author-origin [hidden] rule is added to win the fight back. This bit the
project once already for .analysing.wide and .kpi-rot-item, both fixed the
same way.

Task 6's renderLogCollapse hits the identical trap for a fifth element:
.log-plus also carries an unconditional author `display:flex` (in the same
phone media query), and its `plus.hidden = !phone || !collapsed` goes true
exactly when a log section is already open on a phone — squarely inside that
rule's own active width, not only across the breakpoint.

jsdom — what tests/test_phone_dom.js runs against — never evaluates CSS at
all, so a test reading the `.hidden` IDL property there would stay green
whether or not the guard exists; that is exactly what happened here, which is
why this check exists as a separate, static one. It cannot evaluate the
cascade either (no real browser, no computed styles), but it CAN confirm the
guard rules — the exact selectors specificity requires — are present in the
CSS the app actually serves, so a future edit that quietly drops one of them
fails a test instead of silently reintroducing a state these elements can no
longer distinguish between on a phone.

Two flavors of guard, checked differently below:

- PHONE_GUARDS beat OTHER phone-only display rules, so they only need to
  live inside @media(max-width:760px) — the element they cover carries no
  competing author `display:` at all outside that width.
- GLOBAL_GUARDS cover elements whose OWN base `display:` rule is itself
  unconditional and global (.form-spine, .draft-flag) or used on both phone
  and desktop (.modal-foot) — a guard scoped only to the phone query would
  not reach every width that rule's own display: declaration does, so these
  guards must live OUTSIDE the phone media query instead.
"""

import re

import pytest

import app as app_module


@pytest.fixture()
def page():
    return app_module.app.test_client().get("/").get_data(as_text=True)


# Each guard must outrank every OTHER author-origin `display:` declaration
# that selector's own class/id can otherwise match, not just be present
# anywhere. See the comments beside each rule in templates/index.html for the
# specificity arithmetic; this only checks the rule text survives.
PHONE_GUARDS = [
    "#formOverlay .phone-lookup[hidden]{display:none}",
    "#formOverlay .phone-identity[hidden]{display:none}",
    "#formOverlay .form-layout[hidden]{display:none}",
    "#censorRow[hidden]{display:none}",
    # Task 6's renderLogCollapse: see the module docstring.
    "#formOverlay .log-plus[hidden]{display:none}",
    # Task 8's edit root: #editRoot toggles hidden through .edit-root's own
    # unconditional author display:flex.
    "#formOverlay .edit-root[hidden]{display:none}",
    # Task 8's rail.hidden = !phone || root made the phone+edit-root
    # combination reachable for the first time; Task 4's rail.hidden = !phone
    # alone never needed a guard because the display:flex rule that matters
    # here is itself scoped inside @media(max-width:760px) and desktop was
    # always out of that rule's scope. See the comment beside these two rules
    # in templates/index.html.
    "#formOverlay .form-rail[hidden]{display:none}",
    "#formOverlay .form-rail-label[hidden]{display:none}",
]

GLOBAL_GUARDS = [
    # .modal-foot's base rule is unscoped (used by every modal, not only the
    # phone form's), so its guard was hoisted out of the 760px query — it
    # used to live in PHONE_GUARDS, where it only covered the state by
    # accident (rebuildFormChrome's `root` currently implies `phone`, but
    # nothing about .modal-foot's own CSS guarantees that stays true).
    "#formOverlay .modal-foot[hidden]{display:none}",
    # .form-spine is the seventh cascade bug: rebuildFormChrome sets
    # spine.hidden = phone on EVERY render (desktop included), and
    # .form-spine{display:flex} is global, not phone-scoped — so this guard
    # has to live outside @media(max-width:760px) to ever apply on a phone.
    ".form-spine[hidden]{display:none}",
    # .draft-flag predates this plan but was never guarded: rememberDraft()/
    # setFormStep()/closeForm() toggle its hidden flag on desktop and phone
    # alike, against a global, unconditional display:inline-flex.
    ".draft-flag[hidden]{display:none}",
]

GUARDS = PHONE_GUARDS + GLOBAL_GUARDS


@pytest.mark.parametrize("guard", GUARDS)
def test_hidden_guard_present(page, guard):
    assert guard in page, (
        f"missing author-origin guard {guard!r} — without it, [hidden]'s "
        "UA-origin display:none loses to this element's own unconditional "
        "author display: declaration, and its own .hidden toggle stops "
        "doing anything visible"
    )


def _media_at_760_blocks(css):
    """Yield the (start, end) content bounds of every TOP-LEVEL
    @media(max-width:760px){...} block in css, found by brace-matching
    rather than by a landmark comment — the file has well over a dozen of
    these blocks (a one-off `test_global_guards_...` run turned up a stray
    early one on the .detail-layout grid, line 602, that a landmark-based
    span used to silently swallow whole). Brace-matching is what makes "is
    this guard inside A phone media query" and "is it inside NONE of them"
    both trustworthy checks instead of assuming there is exactly one block
    that matters."""
    search_from = 0
    needle = "@media(max-width:760px){"
    while True:
        idx = css.find(needle, search_from)
        if idx == -1:
            return
        brace_start = idx + len(needle) - 1  # the '{' itself
        depth = 0
        i = brace_start
        while i < len(css):
            if css[i] == "{":
                depth += 1
            elif css[i] == "}":
                depth -= 1
                if depth == 0:
                    yield brace_start + 1, i
                    search_from = i + 1
                    break
            i += 1
        else:
            raise ValueError("unterminated @media(max-width:760px) block")


def _phone_blocks(css):
    return [css[s:e] for s, e in _media_at_760_blocks(css)]


def test_phone_guards_live_inside_a_phone_media_query(page):
    """Each PHONE_GUARDS entry only needs to beat the OTHER phone-only
    display rules — scoping it outside @media(max-width:760px) would be
    needless and, for .form-layout/.check-row (also styled on desktop),
    could interact with rules this task does not own. renderStep1Phone's
    desktop branch always clears these elements' hidden flag on the way out,
    so nothing on desktop can ever be left relying on a guard that only
    exists on phone."""
    style = re.search(r"<style>(.*)</style>", page, re.S)
    assert style, "could not find the page's <style> block"
    blocks = _phone_blocks(style.group(1))
    for guard in PHONE_GUARDS:
        assert any(guard in b for b in blocks), (
            f"{guard!r} must live inside a @media(max-width:760px) block"
        )


def test_global_guards_live_outside_every_phone_media_query(page):
    """GLOBAL_GUARDS cover elements whose base `display:` rule is itself
    global — scoping the guard inside ANY @media(max-width:760px) block
    would leave the desktop-reachable (or width-independent) hidden state
    uncovered, the exact shape of the .form-spine bug. Checked against every
    such block in the file, not just the one the phone form's own chrome
    lives in, since a global guard placed near the wrong rule could easily
    land inside a different, unrelated 760px block by accident."""
    style = re.search(r"<style>(.*)</style>", page, re.S)
    assert style, "could not find the page's <style> block"
    blocks = _phone_blocks(style.group(1))
    for guard in GLOBAL_GUARDS:
        assert not any(guard in b for b in blocks), (
            f"{guard!r} must live OUTSIDE every @media(max-width:760px) "
            "block — its base display: rule is not phone-scoped, so a "
            "guard scoped to phone would not cover every width that rule "
            "reaches"
        )
