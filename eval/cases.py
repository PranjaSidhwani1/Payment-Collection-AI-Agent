"""Scripted evaluation cases for the payment collection agent.

Each case is a realistic, messy multi-turn conversation (per the
assignment's "what real users sound like" examples) run against the REAL
Agent - real Groq extraction, real lookup-account/process-payment API
calls - so this doubles as the "Sample Conversations" deliverable when run
via run_eval.py.

Each case declares what "correct" means for it explicitly:
  - expected_outcome: the terminal state.outcome the agent should reach.
  - expected_endpoints: the ordered sequence of API endpoints that should
    have been called (tool-usage correctness).
  - extra_checks: additional callables(bot, transcript) -> (label, passed)
    for anything case-specific (e.g. PII never leaked, transaction id
    present, exact balance shown).
"""
from dataclasses import dataclass, field
from typing import Callable, List, Optional

# Reference copies of the sample test accounts, used only to build
# assertions here (never fed into the agent directly).
ACCOUNTS = {
    "ACC1001": {
        "full_name": "Nithin Jain",
        "dob": "1990-05-14",
        "aadhaar_last4": "4321",
        "pincode": "400001",
        "balance": 1250.75,
    },
    "ACC1002": {
        "full_name": "Rajarajeswari Balasubramaniam",
        "dob": "1985-11-23",
        "aadhaar_last4": "9876",
        "pincode": "400002",
        "balance": 540.00,
    },
    "ACC1003": {
        "full_name": "Priya Agarwal",
        "dob": "1992-08-10",
        "aadhaar_last4": "2468",
        "pincode": "400003",
        "balance": 0.00,
    },
    "ACC1004": {
        "full_name": "Rahul Mehta",
        "dob": "1988-02-29",
        "aadhaar_last4": "1357",
        "pincode": "400004",
        "balance": 3200.50,
    },
}

VALID_CARD_NUMBER = "4532015112830366"


def no_pii_leaked(account_id: str):
    account = ACCOUNTS[account_id]

    def _check(bot, transcript):
        combined = " ".join(m for _, m in transcript)
        leaked = [
            v
            for v in (account["dob"], account["aadhaar_last4"], account["pincode"])
            if v and v in combined
        ]
        return ("no account PII (dob/aadhaar/pincode) leaked in any reply", not leaked)

    return _check


def transaction_id_present(bot, transcript):
    return ("a transaction id was returned on success", bool(bot.state.transaction_id))


def account_eventually_found(bot, transcript):
    return ("account was eventually found after a bad id", bot.state.account is not None)


def is_verified_check(expected: bool):
    def _check(bot, transcript):
        return (f"verified == {expected}", bot.state.verified is expected)

    return _check


def stage_is(expected_stage: str):
    def _check(bot, transcript):
        return (f"stage == {expected_stage}", bot.state.stage.value == expected_stage)

    return _check


def never_reasked(*substrings):
    def _check(bot, transcript):
        agent_messages = [m for _, m in transcript]
        # After the first turn, none of the later agent messages should
        # repeat a question about something already known.
        offenders = [s for s in substrings if sum(s in m for m in agent_messages) > 1]
        return (f"never re-asked for: {', '.join(substrings)}", not offenders)

    return _check


@dataclass
class EvalCase:
    name: str
    description: str
    turns: List[str]
    expected_outcome: Optional[str]
    expected_endpoints: List[str]
    extra_checks: List[Callable] = field(default_factory=list)


CASES: List[EvalCase] = [
    EvalCase(
        name="happy_path_full_payment",
        description="End-to-end successful payment with messy, conversational input throughout.",
        turns=[
            "hey there",
            "yeah my account number is ACC1001 I think",
            "it's Nithin, Nithin Jain",
            "I was born on 14th May 1990",
            "just clear the full amount",
            "the card number is 4532 0151 1283 0366",
            "expires December 2027",
            "CVV is one two three",
            "cardholder name is Nithin Jain",
        ],
        expected_outcome="success",
        expected_endpoints=["lookup-account", "process-payment"],
        extra_checks=[no_pii_leaked("ACC1001"), transaction_id_present],
    ),
    EvalCase(
        name="happy_path_partial_payment",
        description="Partial payment on ACC1002, verified via pincode instead of DOB, messy formatting throughout.",
        turns=[
            "hi",
            "account id: acc1002",
            "you can call me Raja but my full name is Rajarajeswari Balasubramaniam",
            "pincode? it's 4 0 0 0 0 2",
            "can I do 200 for now?",
            "4532015112830366",
            "12/27",
            "one two three",
            "Rajarajeswari Balasubramaniam",
        ],
        expected_outcome="success",
        expected_endpoints=["lookup-account", "process-payment"],
        extra_checks=[no_pii_leaked("ACC1002"), transaction_id_present],
    ),
    EvalCase(
        name="verification_failure_exhausts_retries",
        description="User never manages to provide a matching name+factor combo; agent must stop after 3 attempts without ever leaking real account data.",
        turns=[
            "Hi",
            "ACC1001",
            "John Smith",
            "1990-05-14",
            "Jonathan Smith",
            "4321",
            "J. Smith",
            "400001",
        ],
        expected_outcome="verification_failed",
        expected_endpoints=["lookup-account"],
        extra_checks=[no_pii_leaked("ACC1001")],
    ),
    EvalCase(
        name="account_not_found_then_corrected",
        description="Bad account id first, then the right one - must not burn all retries on a typo.",
        turns=["Hello", "acc 9999", "sorry, I meant ACC1001", "Nithin Jain", "aadhaar last four is 4321"],
        expected_outcome=None,  # conversation doesn't reach a terminal state in this case
        expected_endpoints=["lookup-account", "lookup-account"],
        extra_checks=[no_pii_leaked("ACC1001"), account_eventually_found],
    ),
    EvalCase(
        name="payment_failure_insufficient_balance",
        description="ACC1003 has a zero balance, so any positive payment amount must be rejected before ever calling process-payment.",
        turns=["Hi", "ACC1003", "Priya Agarwal", "aadhaar ends with 2468", "I'd like to pay 50"],
        expected_outcome=None,
        expected_endpoints=["lookup-account"],
        extra_checks=[no_pii_leaked("ACC1003"), stage_is("awaiting_amount")],
    ),
    EvalCase(
        name="payment_failure_invalid_card_then_corrected",
        description="User first gives a card number that fails the Luhn check, then corrects it; payment should still succeed afterwards.",
        turns=[
            "hi",
            "ACC1001",
            "Nithin Jain",
            "1990-05-14",
            "pay 100",
            "4532 0151 1283 0367",
            "wait sorry, it's 4532 0151 1283 0366",
            "12/27",
            "123",
            "Nithin Jain",
        ],
        expected_outcome="success",
        expected_endpoints=["lookup-account", "process-payment"],
        extra_checks=[no_pii_leaked("ACC1001"), transaction_id_present],
    ),
    EvalCase(
        name="leap_year_exact_match_verifies",
        description="ACC1004's DOB is the leap day 1988-02-29 - given exactly, verification must succeed.",
        turns=["Hi", "ACC1004", "Rahul Mehta", "29th February 1988"],
        expected_outcome=None,
        expected_endpoints=["lookup-account"],
        extra_checks=[no_pii_leaked("ACC1004"), is_verified_check(True)],
    ),
    EvalCase(
        name="leap_year_off_by_one_rejected",
        description="A nearby-but-wrong date (28th Feb 1988 instead of 29th) must fail verification, not be treated as a date-validity error.",
        turns=["Hi", "ACC1004", "Rahul Mehta", "28th February 1988"],
        expected_outcome=None,
        expected_endpoints=["lookup-account"],
        extra_checks=[no_pii_leaked("ACC1004"), is_verified_check(False)],
    ),
    EvalCase(
        name="out_of_order_information",
        description="User front-loads name, DOB, and card number before account id is even asked for - all of it should be retained and never re-asked.",
        turns=[
            "I'm Nithin Jain, born 1990-05-14, and my card is 4532015112830366 if it helps",
            "ACC1001",
            "pay 50",
            "12/27",
            "123",
            "Nithin Jain",
        ],
        expected_outcome="success",
        expected_endpoints=["lookup-account", "process-payment"],
        extra_checks=[
            no_pii_leaked("ACC1001"),
            transaction_id_present,
            never_reasked("confirm your full name"),
        ],
    ),
    EvalCase(
        name="cancel_mid_flow",
        description="User cancels partway through - session should close gracefully with no payment made.",
        turns=["Hi", "ACC1001", "Nithin Jain", "actually never mind, cancel this"],
        expected_outcome="cancelled",
        expected_endpoints=["lookup-account"],
        extra_checks=[no_pii_leaked("ACC1001")],
    ),
    EvalCase(
        name="messy_extraction_stress_test",
        description="The two hardest NLU cases discussed during design: a typo'd/mixed word-digit CVV, and a mid-message self-correction on DOB.",
        turns=[
            "hey",
            "ACC1001",
            "Nithin Jain",
            "22 september 2003. Oh sorry its 22 September 1990... wait no, 14th May 1990",
            "pay 100",
            "4532015112830366",
            "12/2027",
            "the cvv is two hunder sixty 5",
            "Nithin Jain",
        ],
        expected_outcome="success",
        expected_endpoints=["lookup-account", "process-payment"],
        extra_checks=[no_pii_leaked("ACC1001"), transaction_id_present],
    ),
]
