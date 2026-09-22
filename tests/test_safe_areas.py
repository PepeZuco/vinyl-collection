"""The chrome that a home-screen install draws under must buy its space back.

`apple-mobile-web-app-status-bar-style=black-translucent` plus
`viewport-fit=cover` hand the status bar's strip and the home indicator's strip
to the page. That is what makes the app look installed rather than letterboxed
— and it means every piece of fixed or sticky chrome is now responsible for its
own clearance. Several did not have it, and every one was invisible until the
app was opened on a real phone:

  * `header` — the collection title rendered underneath the clock.
  * `.dm-top` — the record sheet's close button sat behind the clock, so a
    record could not be dismissed at all once opened.
  * `.mobile-tabbar` — worse than missing. It had `height:58px` AND
    `padding-bottom:env(safe-area-inset-bottom)`, and `box-sizing:border-box`
    is global in this template, so the inset was spent OUT of the 58px instead
    of added to it. On a notched iPhone that left roughly 24px of usable bar
    and visibly squashed the tab icons and their labels.
  * `#scanOverlay` — found a round later, and the same shape as `.dm-top`: the
    results screen's "back to the form" button rendered under the clock, and it
    is the only way out, so a search became a dead end.

Three overlays drop the centring padding and go edge-to-edge on a phone
(`#formOverlay`, `#detailOverlay`, `#scanOverlay`); those pay their own insets
on their own chrome. Everything else keeps `.overlay`'s padding, which now
carries the insets too so a tall centred dialog cannot slide under a system bar
— a floor, so the next overlay someone adds is covered by default rather than
by remembering.

Like tests/test_step1_hidden_guards.py, this is a static check on the CSS the
app actually serves. It cannot evaluate the cascade, it cannot lay anything
out, and it cannot tell you the result looks right — jsdom evaluates no CSS at
all, so the DOM tests stayed green through every one of these. What it CAN do
is fail when a future edit drops one of these rules, instead of letting the
regression reach a phone silently.
"""

import re

import pytest

import app as app_module


@pytest.fixture()
def page():
    return app_module.app.test_client().get("/").get_data(as_text=True)


def test_the_page_opts_into_the_safe_area():
    """Without viewport-fit=cover the insets all resolve to zero and the rules
    below are inert — so this is the precondition for every other check here."""
    html = app_module.app.test_client().get("/").get_data(as_text=True)
    viewport = next(l for l in html.splitlines() if 'name="viewport"' in l)
    assert "viewport-fit=cover" in viewport


def test_the_status_bar_is_handed_to_the_page():
    """black-translucent is what puts the clock over the header. If this ever
    becomes plain `black`, iOS reserves the strip itself and the top insets
    below stop being load-bearing — worth knowing, not worth failing over
    silently."""
    html = app_module.app.test_client().get("/").get_data(as_text=True)
    assert 'name="apple-mobile-web-app-status-bar-style" content="black-translucent"' in html


def test_the_header_clears_the_status_bar(page):
    assert "padding:calc(28px + env(safe-area-inset-top,0px)) 0 20px" in page, (
        "the collection header lost its top inset — the title renders under the "
        "clock in a home-screen install"
    )


def test_the_record_sheets_top_bar_clears_the_status_bar(page):
    assert "padding:calc(12px + env(safe-area-inset-top,0px)) 14px 8px" in page, (
        "the record sheet's top bar lost its top inset — the close button ends "
        "up behind the clock and the record cannot be dismissed"
    )


def test_the_tab_bar_grows_by_the_inset_rather_than_spending_it(page):
    """The height must ADD the inset. A bare `height:58px` beside a
    padding-bottom of the same inset is the original bug, not a fix."""
    assert "height:calc(58px + env(safe-area-inset-bottom,0px))" in page, (
        "the mobile tab bar is back to a fixed height — with box-sizing:border-box "
        "its bottom inset is subtracted from the bar instead of added to it, "
        "squashing the icons and labels"
    )
    tabbar = re.search(r"\.mobile-tabbar\{[^}]*\}", page, re.S)
    assert tabbar, "could not find the .mobile-tabbar rule at all"
    assert "height:58px;" not in tabbar.group(0), (
        "a fixed 58px height is still present in the .mobile-tabbar rule"
    )


def test_the_scan_results_back_button_clears_the_status_bar(page):
    """#scanOverlay goes edge-to-edge on a phone, so its own head is the only
    thing standing between the back button and the clock. That button is the
    single exit from a search result, which is what made this one costly."""
    assert "border:none;\n    padding-top:env(safe-area-inset-top,0px)" in page, (
        "#scanOverlay's modal lost its top inset — the 'back to the form' "
        "button renders under the clock and a search becomes inescapable"
    )


def test_the_scan_results_footer_clears_the_home_indicator(page):
    assert "padding:12px 14px calc(12px + env(safe-area-inset-bottom,0px))" in page, (
        "the scan results footer lost its bottom inset — 'add N records' sits "
        "on the home indicator"
    )


def test_centred_overlays_have_an_inset_floor(page):
    """The eleven overlays that stay centred keep `.overlay`'s padding. 16px is
    not enough to clear a notch, so the insets belong in that shared rule — it
    means a new overlay is covered by default instead of by remembering."""
    assert (
        "padding:calc(16px + env(safe-area-inset-top,0px)) 16px "
        "calc(16px + env(safe-area-inset-bottom,0px))"
    ) in page, (
        ".overlay lost its safe-area floor — a tall centred dialog can render "
        "its own header under the status bar"
    )
