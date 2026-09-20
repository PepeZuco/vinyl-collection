"""Step 1's phone lookup/identity toggle relies on an author-origin
[hidden] guard that beats a UA-origin one.

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

jsdom — what tests/test_phone_dom.js runs against — never evaluates CSS at
all, so a test reading the `.hidden` IDL property there would stay green
whether or not the guard exists; that is exactly what happened here, which is
why this check exists as a separate, static one. It cannot evaluate the
cascade either (no real browser, no computed styles), but it CAN confirm the
guard rules — the exact selectors specificity requires — are present in the
CSS the app actually serves, so a future edit that quietly drops one of them
fails a test instead of silently reintroducing a state four elements can no
longer distinguish between on a phone.
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
GUARDS = [
    "#formOverlay .phone-lookup[hidden]{display:none}",
    "#formOverlay .phone-identity[hidden]{display:none}",
    "#formOverlay .form-layout[hidden]{display:none}",
    "#censorRow[hidden]{display:none}",
]


@pytest.mark.parametrize("guard", GUARDS)
def test_hidden_guard_present(page, guard):
    assert guard in page, (
        f"missing author-origin guard {guard!r} — without it, [hidden]'s "
        "UA-origin display:none loses to this element's own unconditional "
        "author display: declaration, and renderStep1Phone's .hidden "
        "toggle stops doing anything visible on a phone"
    )


def test_hidden_guards_live_inside_the_phone_media_query(page):
    """Each guard only needs to beat the OTHER phone-only display rules —
    scoping it outside @media(max-width:760px) would be needless and, for
    .form-layout/.check-row (also styled on desktop), could interact with
    rules this task does not own. renderStep1Phone's desktop branch always
    clears these elements' hidden flag on the way out, so nothing on desktop
    can ever be left relying on a guard that only exists on phone."""
    style = re.search(r"<style>(.*)</style>", page, re.S)
    assert style, "could not find the page's <style> block"
    css = style.group(1)
    mq_start = css.index("@media(max-width:760px){")
    # The four guards live in the same phone block as the rest of step 1's
    # lookup/identity CSS; find that block's own close brace rather than the
    # first @media's, since several @media(max-width:760px) blocks exist.
    mq_end = css.index("/* ── multi-artist editor in form", mq_start)
    block = css[mq_start:mq_end]
    for guard in GUARDS:
        assert guard in block, f"{guard!r} must live inside the phone media query"
