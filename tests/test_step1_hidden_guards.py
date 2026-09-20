"""Elements whose phone-only `hidden` toggle needs an author-origin [hidden]
guard to beat a UA-origin one.

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
    # Task 6's renderLogCollapse: see the module docstring.
    "#formOverlay .log-plus[hidden]{display:none}",
    # Task 8's edit root: #editRoot toggles hidden through .edit-root's own
    # unconditional author display:flex, and .modal-foot toggles hidden
    # through its own base (unscoped, outside this media query) display:flex.
    # Same trap, same fix.
    "#formOverlay .edit-root[hidden]{display:none}",
    "#formOverlay .modal-foot[hidden]{display:none}",
    # Task 8's rail.hidden = !phone || root made the phone+edit-root
    # combination reachable for the first time; Task 4's rail.hidden = !phone
    # alone never needed a guard because the display:flex rule that matters
    # here is itself scoped inside @media(max-width:760px) and desktop was
    # always out of that rule's scope. See the comment beside these two rules
    # in templates/index.html.
    "#formOverlay .form-rail[hidden]{display:none}",
    "#formOverlay .form-rail-label[hidden]{display:none}",
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
    # All of GUARDS live in the same phone block as the rest of step 1's
    # lookup/identity CSS and step 3's log sections; find that block's own
    # close brace rather than the first @media's, since several
    # @media(max-width:760px) blocks exist.
    mq_end = css.index("/* ── multi-artist editor in form", mq_start)
    block = css[mq_start:mq_end]
    for guard in GUARDS:
        assert guard in block, f"{guard!r} must live inside the phone media query"
