"""What a Claude API call cost, in dollars.

The rates live here rather than in scan.py so there is exactly one place to
edit when Anthropic's pricing moves or the scan switches models.
"""
import datetime
import logging

logger = logging.getLogger(__name__)

TOKENS_PER_RATE = 1_000_000

# (input, output) USD per million tokens — Anthropic's standard published rates.
_STANDARD = {
    "claude-sonnet-5": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
}

# Introductory rates and the last day they apply, as (input, output), end_date.
# Encoded with the end date rather than folded into _STANDARD either way: a
# hardcoded intro rate silently under-reports every scan once the window shuts,
# and the standard rate over-reports every scan until it does.
_INTRODUCTORY = {
    "claude-sonnet-5": ((2.00, 10.00), datetime.date(2026, 8, 31)),
}


def rates_for(model, on=None):
    """(input, output) USD per million tokens for `model`, or None if unpriced.

    `on` is the date the call was billed, defaulting to today — an explicit
    date is what makes the introductory window testable from both sides.
    """
    introductory = _INTRODUCTORY.get(model)
    if introductory:
        rates, last_day = introductory
        if (on or datetime.date.today()) <= last_day:
            return rates
    return _STANDARD.get(model)


def cost_usd(model, input_tokens, output_tokens, on=None):
    """USD for one API call.

    An unpriced model costs nothing rather than being charged at some other
    model's rate: a zero in the ledger reads as "not counted", where a guess
    would read as fact. It is logged, so swapping the scan to a model nobody
    added a rate for does not quietly zero the running total.
    """
    rates = rates_for(model, on)
    if not rates:
        logger.warning("No published rate for model %r — counted as $0", model)
        return 0.0
    input_rate, output_rate = rates
    return ((input_tokens or 0) * input_rate
            + (output_tokens or 0) * output_rate) / TOKENS_PER_RATE
