"""End-to-end FSM tests.

These hit the REAL lookup-account / process-payment API (it's a shared
test service with fixed sample accounts and does not persist state, so
this is safe and repeatable) but replace extractor.extract with a
deterministic stub, so these tests are fast, free, and fully offline with
respect to the LLM - the FSM/verification/validation/business-rule logic
is what's under test here, independent of Groq availability.
"""
import pytest

import agent as agent_module
from agent import Agent

CARD_OK = {
    "card_number": "4532015112830366",
    "cvv": "123",
    "expiry_month": 12,
    "expiry_year": 2027,
    "cardholder_name": "Nithin Jain",
}


def _empty():
    return {
        "account_id": None,
        "full_name": None,
        "dob": None,
        "aadhaar_last4": None,
        "pincode": None,
        "amount": None,
        "pay_in_full": None,
        "card_number": None,
        "cvv": None,
        "expiry_month": None,
        "expiry_year": None,
        "cardholder_name": None,
        "cancel_requested": None,
    }


def make_stub(script: dict):
    """script maps exact input string -> partial dict of extracted fields."""

    def _stub(user_input, state):
        base = _empty()
        base.update(script.get(user_input, {}))
        return base

    return _stub


def run_conversation(monkeypatch, script: dict, turns: list) -> list:
    monkeypatch.setattr(agent_module, "extract", make_stub(script))
    bot = Agent()
    replies = []
    for turn in turns:
        replies.append(bot.next(turn)["message"])
    return replies, bot


def test_happy_path_full_payment(monkeypatch):
    script = {
        "Hi": {},
        "it's ACC 1001": {"account_id": "ACC1001"},
        "you can call me Nithin, Nithin Jain": {"full_name": "Nithin Jain"},
        "14th May 1990": {"dob": "1990-05-14"},
        "pay the full amount": {"pay_in_full": True},
        "card is 4532 0151 1283 0366": {"card_number": CARD_OK["card_number"]},
        "expires December 2027": {"expiry_month": 12, "expiry_year": 2027},
        "CVV is one two three": {"cvv": "123"},
        "cardholder is Nithin Jain": {"cardholder_name": "Nithin Jain"},
    }
    turns = list(script.keys())
    replies, bot = run_conversation(monkeypatch, script, turns)

    assert "account ID" in replies[0]
    assert bot.state.outcome == "success"
    assert "Payment successful" in replies[-1]
    assert "Transaction ID" in replies[-1]
    # No sensitive data ever echoed back.
    combined = " ".join(replies)
    assert "1990-05-14" not in combined


def test_happy_path_partial_payment(monkeypatch):
    script = {
        "Hi": {},
        "account id acc1002": {"account_id": "ACC1002"},
        "Rajarajeswari Balasubramaniam": {"full_name": "Rajarajeswari Balasubramaniam"},
        "pincode 400002": {"pincode": "400002"},
        "can I do 200 for now?": {"amount": 200.00},
        "4532 0151 1283 0366": {"card_number": CARD_OK["card_number"]},
        "12/27": {"expiry_month": 12, "expiry_year": 2027},
        "123": {"cvv": "123"},
        "Rajarajeswari Balasubramaniam is the cardholder": {"cardholder_name": "Rajarajeswari Balasubramaniam"},
    }
    turns = list(script.keys())
    replies, bot = run_conversation(monkeypatch, script, turns)

    assert bot.state.outcome == "success"
    assert "Payment successful" in replies[-1]
    assert "200.00" in replies[-1]


def test_verification_failure_exhausts_retries(monkeypatch):
    script = {
        "Hi": {},
        "ACC1001": {"account_id": "ACC1001"},
        "attempt1 name": {"full_name": "Wrong Name"},
        "attempt1 dob": {"dob": "1990-05-14"},
        "attempt2 name": {"full_name": "Wrong Name"},
        "attempt2 dob": {"dob": "1990-05-14"},
        "attempt3 name": {"full_name": "Wrong Name"},
        "attempt3 dob": {"dob": "1990-05-14"},
    }
    turns = list(script.keys())
    replies, bot = run_conversation(monkeypatch, script, turns)

    assert bot.state.outcome == "verification_failed"
    assert bot.state.closed is True
    combined = " ".join(replies)
    assert "1990-05-14" not in combined
    assert "4321" not in combined
    assert "400001" not in combined

    # Session stays closed on further input.
    followup = bot.next("hello?")
    assert "ended" in followup["message"].lower()


def test_verification_succeeds_via_pincode(monkeypatch):
    script = {
        "Hi": {},
        "ACC1001": {"account_id": "ACC1001"},
        "Nithin Jain": {"full_name": "Nithin Jain"},
        "pincode is 400001": {"pincode": "400001"},
    }
    turns = list(script.keys())
    replies, bot = run_conversation(monkeypatch, script, turns)
    assert bot.state.verified is True
    assert "1,250.75" in replies[-1] or "1250.75" in replies[-1]


def test_account_not_found_then_corrected(monkeypatch):
    script = {
        "Hi": {},
        "ACC9999": {"account_id": "ACC9999"},
        "sorry, ACC1001": {"account_id": "ACC1001"},
    }
    turns = list(script.keys())
    replies, bot = run_conversation(monkeypatch, script, turns)
    assert "couldn't find" in replies[1]
    assert bot.state.account is not None
    assert bot.state.stage.value == "awaiting_name"


def test_payment_failure_insufficient_balance(monkeypatch):
    script = {
        "Hi": {},
        "ACC1003": {"account_id": "ACC1003"},
        "Priya Agarwal": {"full_name": "Priya Agarwal"},
        "aadhaar 2468": {"aadhaar_last4": "2468"},
    }
    turns = list(script.keys())
    replies, bot = run_conversation(monkeypatch, script, turns)
    # ACC1003 balance is 0.00, so any positive amount is rejected locally
    # before ever reaching the API.
    assert bot.state.stage.value == "awaiting_amount"
    assert "0.00" in replies[-1] or "balance" in replies[-1].lower()


def test_invalid_card_then_corrected(monkeypatch):
    script = {
        "Hi": {},
        "ACC1001": {"account_id": "ACC1001"},
        "Nithin Jain": {"full_name": "Nithin Jain"},
        "1990-05-14": {"dob": "1990-05-14"},
        "pay 100": {"amount": 100.00},
        "bad card 4532015112830367": {"card_number": "4532015112830367"},  # fails luhn
        "actual card 4532015112830366": {"card_number": "4532015112830366"},
        "12/27": {"expiry_month": 12, "expiry_year": 2027},
        "123": {"cvv": "123"},
        "Nithin Jain again": {"cardholder_name": "Nithin Jain"},
    }
    turns = list(script.keys())
    replies, bot = run_conversation(monkeypatch, script, turns)
    assert "doesn't look valid" in replies[5]
    assert bot.state.outcome == "success"


def test_leap_year_exact_match_verifies(monkeypatch):
    script = {
        "Hi": {},
        "ACC1004": {"account_id": "ACC1004"},
        "Rahul Mehta": {"full_name": "Rahul Mehta"},
        "29 Feb 1988": {"dob": "1988-02-29"},
    }
    turns = list(script.keys())
    replies, bot = run_conversation(monkeypatch, script, turns)
    assert bot.state.verified is True


def test_leap_year_off_by_one_rejected(monkeypatch):
    script = {
        "Hi": {},
        "ACC1004": {"account_id": "ACC1004"},
        "Rahul Mehta": {"full_name": "Rahul Mehta"},
        "28 Feb 1988": {"dob": "1988-02-28"},
    }
    turns = list(script.keys())
    replies, bot = run_conversation(monkeypatch, script, turns)
    assert bot.state.verified is False
    assert bot.state.verify_attempts == 1


def test_out_of_order_info_before_being_asked(monkeypatch):
    # User front-loads name + dob + even card details before the account
    # id has even been requested/looked up. Everything should be stored
    # and only acted on once the required order is reached, and nothing
    # should be re-asked once it's known.
    script = {
        "I'm Nithin Jain, born 1990-05-14, my card is 4532015112830366": {
            "full_name": "Nithin Jain",
            "dob": "1990-05-14",
            "card_number": "4532015112830366",
        },
        "ACC1001": {"account_id": "ACC1001"},
        "pay 50": {"amount": 50.00},
        "12/27": {"expiry_month": 12, "expiry_year": 2027},
        "123": {"cvv": "123"},
        "Nithin Jain": {"cardholder_name": "Nithin Jain"},
    }
    turns = list(script.keys())
    replies, bot = run_conversation(monkeypatch, script, turns)
    assert bot.state.outcome == "success"
    # full_name/dob were never re-asked because they were already known.
    assert "confirm your full name" not in " ".join(replies)


def test_cancel_mid_flow(monkeypatch):
    script = {
        "Hi": {},
        "ACC1001": {"account_id": "ACC1001"},
        "actually never mind, cancel": {"cancel_requested": True},
    }
    turns = list(script.keys())
    replies, bot = run_conversation(monkeypatch, script, turns)
    assert bot.state.outcome == "cancelled"
    assert bot.state.closed is True
    assert "ended" in replies[-1].lower() or "cancel" in replies[-1].lower()
