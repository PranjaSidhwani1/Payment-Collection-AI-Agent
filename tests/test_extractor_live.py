"""Live tests against the real Groq API for the cases that specifically
motivated the LLM-first design: typo'd/mixed-format numbers and
mid-message self-correction. These are skipped automatically if the LLM
is unreachable (e.g. no API key, or network/firewall blocks it, as is the
case in some sandboxed environments) rather than failing the whole suite.
"""
import pytest

import extractor
from state import ConversationState


def _live_or_skip():
    try:
        return extractor.extract("hello", ConversationState())
    except extractor.ExtractionUnavailable as exc:
        pytest.skip(f"Groq API not reachable in this environment: {exc}")


def test_typo_and_mixed_word_digit_cvv():
    _live_or_skip()
    result = extractor.extract("the cvv is two hunder sixty 5", ConversationState())
    assert result["cvv"] == "265"


def test_self_correction_within_message_uses_latest_value():
    _live_or_skip()
    result = extractor.extract(
        "22 september 2003. Oh sorry its 22 September 2002", ConversationState()
    )
    assert result["dob"] == "2002-09-22"


def test_spelled_out_amount():
    _live_or_skip()
    result = extractor.extract("I want to pay a thousand rupees", ConversationState())
    assert result["amount"] == 1000


def test_pay_in_full_intent():
    _live_or_skip()
    result = extractor.extract("just clear the full amount", ConversationState())
    assert result["pay_in_full"] is True


def test_name_with_nickname_prefers_full_name():
    _live_or_skip()
    result = extractor.extract(
        "you can call me Raja but my full name is Rajarajeswari Balasubramaniam",
        ConversationState(),
    )
    assert result["full_name"] == "Rajarajeswari Balasubramaniam"


def test_spaced_out_digits():
    _live_or_skip()
    result = extractor.extract("pincode? it's 4 0 0 0 0 1", ConversationState())
    assert result["pincode"] == "400001"
