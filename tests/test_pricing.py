"""What an API call cost, in dollars."""
import datetime

import pytest

import pricing

# Anywhere inside Sonnet 5's introductory window, and safely past it.
DURING_INTRO = datetime.date(2026, 8, 23)
AFTER_INTRO = datetime.date(2026, 9, 1)


def test_haiku_input_tokens_are_priced_at_a_dollar_a_million():
    assert pricing.cost_usd("claude-haiku-4-5", 1_000_000, 0) == 1.00


def test_haiku_output_tokens_are_priced_at_five_dollars_a_million():
    assert pricing.cost_usd("claude-haiku-4-5", 0, 1_000_000) == 5.00


def test_input_and_output_are_summed():
    # 200k in at $1/M, 40k out at $5/M
    assert pricing.cost_usd("claude-haiku-4-5", 200_000, 40_000) == pytest.approx(0.40)


def test_sonnet_bills_the_intro_rate_inside_the_window():
    assert pricing.cost_usd("claude-sonnet-5", 1_000_000, 0, on=DURING_INTRO) == 2.00


def test_sonnet_bills_the_intro_rate_on_its_final_day():
    """The window closes at the END of 2026-08-31 — that day is still cheap."""
    last_day = datetime.date(2026, 8, 31)
    assert pricing.cost_usd("claude-sonnet-5", 1_000_000, 0, on=last_day) == 2.00


def test_sonnet_bills_the_standard_rate_once_the_window_closes():
    assert pricing.cost_usd("claude-sonnet-5", 1_000_000, 0, on=AFTER_INTRO) == 3.00
    assert pricing.cost_usd("claude-sonnet-5", 0, 1_000_000, on=AFTER_INTRO) == 15.00


def test_an_unpriced_model_costs_nothing_rather_than_guessing():
    """A model swap must not invent a rate — a zero is legible, a guess is not."""
    assert pricing.cost_usd("claude-opus-5", 1_000_000, 1_000_000) == 0.0


def test_an_unpriced_model_is_logged(caplog):
    with caplog.at_level("WARNING"):
        pricing.cost_usd("some-new-model", 100, 100)
    assert "some-new-model" in caplog.text
