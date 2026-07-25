"""Conversation state for the payment collection agent.

All fields here are plain data - no business logic lives in this module.
Keeping state as a single dataclass makes it trivial to reason about what
the agent "knows" at any point in the conversation, and keeps agent.py
focused purely on control flow.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Stage(str, Enum):
    AWAITING_ACCOUNT_ID = "awaiting_account_id"
    AWAITING_NAME = "awaiting_name"
    AWAITING_SECONDARY_FACTOR = "awaiting_secondary_factor"
    AWAITING_AMOUNT = "awaiting_amount"
    AWAITING_CARD_DETAILS = "awaiting_card_details"
    CLOSED_SUCCESS = "closed_success"
    CLOSED_FAILURE = "closed_failure"


# Retry / attempt limits. Centralized so they're easy to tune and to cite
# in the design doc.
MAX_ACCOUNT_LOOKUP_ATTEMPTS = 3
MAX_VERIFICATION_ATTEMPTS = 3
MAX_PAYMENT_ATTEMPTS = 3
MAX_EXTRACTION_FAILURES = 3


@dataclass
class Slots:
    """Structured data collected from the user across turns.

    Every field starts as None and is only ever filled in by validated
    extractor output. Fields are cleared deliberately by the FSM when a
    value turns out to be wrong/invalid, forcing the user to re-supply it.
    """

    account_id: Optional[str] = None
    full_name: Optional[str] = None
    dob: Optional[str] = None
    aadhaar_last4: Optional[str] = None
    pincode: Optional[str] = None
    amount: Optional[float] = None
    pay_in_full: Optional[bool] = None
    card_number: Optional[str] = None
    cvv: Optional[str] = None
    expiry_month: Optional[int] = None
    expiry_year: Optional[int] = None
    cardholder_name: Optional[str] = None


@dataclass
class ConversationState:
    stage: Stage = Stage.AWAITING_ACCOUNT_ID
    turn_count: int = 0
    slots: Slots = field(default_factory=Slots)

    # Account record returned by lookup-account (never shown to the user
    # verbatim - dob/aadhaar/pincode/full_name from here are only ever used
    # for internal comparisons).
    account: Optional[dict] = None

    verified: bool = False
    balance_shared: bool = False
    validated_amount: Optional[float] = None

    account_lookup_attempts: int = 0
    verify_attempts: int = 0
    payment_attempts: int = 0
    extraction_failure_streak: int = 0

    closed: bool = False
    # One of: success, verification_failed, account_not_found,
    # payment_failed, cancelled, system_error. Used for the closing recap
    # and by the eval harness; not required by the interface itself.
    outcome: Optional[str] = None
    transaction_id: Optional[str] = None

    def is_secondary_factor_present(self) -> bool:
        return any(
            [self.slots.dob, self.slots.aadhaar_last4, self.slots.pincode]
        )

    def missing_card_fields(self) -> list:
        missing = []
        if not self.slots.card_number:
            missing.append("card number")
        if not self.slots.expiry_month or not self.slots.expiry_year:
            missing.append("expiry date")
        if not self.slots.cvv:
            missing.append("CVV")
        if not self.slots.cardholder_name:
            missing.append("cardholder name")
        return missing
