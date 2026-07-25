"""Payment collection agent.

Architecture: a deterministic finite-state machine (this file) owns the
conversation flow, all business rules, the verification decision, all API
calls, and all reply text. The only non-deterministic component is
extractor.extract(), which turns one free-form message into structured
slot values (see extractor.py for why that's LLM-driven and everything
else isn't).

Each call to next() is exactly one turn:
  1. Run extraction on the raw message (unless the session is closed).
  2. Merge newly-extracted, still-relevant fields into state.slots.
  3. Handle a global "cancel" request if present.
  4. Dispatch to the handler for the current stage. A handler either
     (a) returns a message and stays on/returns to some stage waiting for
         more user input, or
     (b) makes internal progress (e.g. a lookup succeeded) and signals the
         FSM to immediately re-dispatch into the next stage within the
         same turn - this is what lets out-of-order/early-volunteered
         information collapse multiple stages into a single reply instead
         of forcing redundant questions.
"""
from dataclasses import dataclass
from typing import Optional

import api_client
import responses
import validators
import verification
from extractor import ExtractionUnavailable, extract
from state import (
    MAX_ACCOUNT_LOOKUP_ATTEMPTS,
    MAX_EXTRACTION_FAILURES,
    MAX_PAYMENT_ATTEMPTS,
    MAX_VERIFICATION_ATTEMPTS,
    ConversationState,
    Stage,
)

# Safety cap on how many internal (no-user-input) stage transitions can
# chain together in a single turn. Generously above anything the real FSM
# needs, purely to prevent an accidental infinite loop from hanging.
MAX_INTERNAL_ADVANCES = 10


@dataclass
class _HandlerResult:
    message: Optional[str]
    advance: bool = False


class Agent:
    def __init__(self):
        self.state = ConversationState()

    def next(self, user_input: str) -> dict:
        """Process one turn of the conversation."""
        self.state.turn_count += 1
        is_first_turn = self.state.turn_count == 1
        self._prefix_parts = []

        if self.state.closed:
            return {"message": responses.session_ended(self.state.outcome)}

        extraction_ok = self._run_extraction(user_input)
        message = self._process() if extraction_ok else self._pending_message

        if is_first_turn:
            nothing_to_report = (
                extraction_ok
                and not self._any_extracted
                and self.state.stage == Stage.AWAITING_ACCOUNT_ID
                and self.state.account_lookup_attempts == 0
            )
            if nothing_to_report:
                message = responses.greeting()
            else:
                message = f"{responses.GREETING_PREFIX} {message}"

        return {"message": message}

    # -- extraction -----------------------------------------------------

    def _run_extraction(self, user_input: str) -> bool:
        self._pending_message = None
        self._any_extracted = False
        try:
            extracted = extract(user_input, self.state)
        except ExtractionUnavailable:
            self.state.extraction_failure_streak += 1
            if self.state.extraction_failure_streak >= MAX_EXTRACTION_FAILURES:
                self._close(responses.extraction_exhausted(), outcome="system_error")
                self._pending_message = responses.extraction_exhausted()
            else:
                self._pending_message = responses.extraction_unavailable()
            return False

        self.state.extraction_failure_streak = 0
        self._any_extracted = self._merge_slots(extracted)
        return True

    def _merge_slots(self, extracted: dict) -> bool:
        slots = self.state.slots
        any_extracted = any(v is not None for v in extracted.values())

        self._cancel_requested = bool(extracted.get("cancel_requested"))

        # Identity fields are locked once verified - a verified user's
        # name/dob/aadhaar/pincode should never change mid-session.
        if not self.state.verified:
            for field in ("full_name", "dob", "aadhaar_last4", "pincode"):
                value = extracted.get(field)
                if value:
                    setattr(slots, field, value)

        # Account id is locked once a lookup has succeeded.
        if self.state.account is None and extracted.get("account_id"):
            slots.account_id = extracted["account_id"].strip().upper().replace(" ", "")

        if extracted.get("amount") is not None:
            slots.amount = extracted["amount"]
            slots.pay_in_full = False
        if extracted.get("pay_in_full"):
            slots.pay_in_full = True
            slots.amount = None

        for field in ("card_number", "cvv"):
            value = extracted.get(field)
            if value:
                setattr(slots, field, value)
        # cardholder_name is deliberately only ever captured post-verification
        # as a deterministic safety net: pre-verification, "Nithin Jain" must
        # always be interpreted as full_name, never speculatively locked in
        # as a card detail, even if the LLM's ask-context disambiguation
        # (see extractor.py) were ever to get this wrong.
        if self.state.verified and extracted.get("cardholder_name"):
            slots.cardholder_name = extracted["cardholder_name"]
        if extracted.get("expiry_month") is not None:
            slots.expiry_month = extracted["expiry_month"]
        if extracted.get("expiry_year") is not None:
            slots.expiry_year = extracted["expiry_year"]

        return any_extracted

    # -- FSM dispatch -----------------------------------------------------

    def _process(self) -> str:
        if getattr(self, "_cancel_requested", False) and not self.state.closed:
            self._close(responses.cancelled(), outcome="cancelled")
            return self._with_prefix(responses.cancelled())

        result = _HandlerResult(message=None, advance=True)
        for _ in range(MAX_INTERNAL_ADVANCES):
            if self.state.closed:
                return self._with_prefix(result.message)
            result = self._dispatch()
            if not result.advance:
                return self._with_prefix(result.message)
        return self._with_prefix(result.message)

    def _with_prefix(self, message: str) -> str:
        if self._prefix_parts:
            return " ".join(self._prefix_parts + [message])
        return message

    def _dispatch(self) -> _HandlerResult:
        handler = {
            Stage.AWAITING_ACCOUNT_ID: self._handle_account_id,
            Stage.AWAITING_NAME: self._handle_name,
            Stage.AWAITING_SECONDARY_FACTOR: self._handle_secondary_factor,
            Stage.AWAITING_AMOUNT: self._handle_amount,
            Stage.AWAITING_CARD_DETAILS: self._handle_card_details,
        }[self.state.stage]
        return handler()

    def _close(self, message: str, outcome: str, success: bool = False) -> None:
        self.state.closed = True
        self.state.outcome = outcome
        self.state.stage = Stage.CLOSED_SUCCESS if success else Stage.CLOSED_FAILURE

    # -- stage handlers -----------------------------------------------------

    def _handle_account_id(self) -> _HandlerResult:
        slots = self.state.slots
        if not slots.account_id:
            return _HandlerResult(responses.ask_account_id())

        try:
            result = api_client.lookup_account(slots.account_id)
        except api_client.ApiUnavailable:
            self._close(responses.system_error(), outcome="system_error")
            return _HandlerResult(responses.system_error())

        if not result.found:
            self.state.account_lookup_attempts += 1
            slots.account_id = None
            if self.state.account_lookup_attempts >= MAX_ACCOUNT_LOOKUP_ATTEMPTS:
                self._close(responses.account_lookup_exhausted(), outcome="account_not_found")
                return _HandlerResult(responses.account_lookup_exhausted())
            attempts_left = MAX_ACCOUNT_LOOKUP_ATTEMPTS - self.state.account_lookup_attempts
            return _HandlerResult(responses.account_not_found(attempts_left))

        self.state.account = result.account
        self.state.stage = Stage.AWAITING_NAME
        return _HandlerResult(None, advance=True)

    def _handle_name(self) -> _HandlerResult:
        if not self.state.slots.full_name:
            return _HandlerResult(responses.ask_name())
        self.state.stage = Stage.AWAITING_SECONDARY_FACTOR
        return _HandlerResult(None, advance=True)

    def _handle_secondary_factor(self) -> _HandlerResult:
        slots = self.state.slots

        # Filter out malformed secondary-factor values before treating
        # them as "provided" - a mistyped 5-digit pincode shouldn't burn a
        # verification attempt, it should just prompt for a fix.
        if slots.dob and not validators.is_valid_calendar_date(slots.dob):
            slots.dob = None
            return _HandlerResult(responses.clarify_bad_dob())
        if slots.aadhaar_last4 and not validators.is_exact_digit_string(slots.aadhaar_last4, 4):
            slots.aadhaar_last4 = None
            return _HandlerResult(responses.clarify_bad_aadhaar())
        if slots.pincode and not validators.is_exact_digit_string(slots.pincode, 6):
            slots.pincode = None
            return _HandlerResult(responses.clarify_bad_pincode())

        if not self.state.is_secondary_factor_present():
            return _HandlerResult(responses.ask_secondary_factor())

        claimed = {
            "full_name": slots.full_name,
            "dob": slots.dob,
            "aadhaar_last4": slots.aadhaar_last4,
            "pincode": slots.pincode,
        }
        if verification.is_verified(self.state.account, claimed):
            self.state.verified = True
            self.state.stage = Stage.AWAITING_AMOUNT
            return _HandlerResult(None, advance=True)

        self.state.verify_attempts += 1
        # Clear everything and force a full re-entry - never hint at which
        # specific field was wrong.
        slots.full_name = None
        slots.dob = None
        slots.aadhaar_last4 = None
        slots.pincode = None
        self.state.stage = Stage.AWAITING_NAME
        if self.state.verify_attempts >= MAX_VERIFICATION_ATTEMPTS:
            self._close(responses.verification_exhausted(), outcome="verification_failed")
            return _HandlerResult(responses.verification_exhausted())
        attempts_left = MAX_VERIFICATION_ATTEMPTS - self.state.verify_attempts
        return _HandlerResult(responses.verification_failed(attempts_left))

    def _handle_amount(self) -> _HandlerResult:
        slots = self.state.slots
        balance = self.state.account["balance"]

        if not self.state.balance_shared:
            self.state.balance_shared = True
            self._prefix_parts.append(responses.verified_balance_message(balance))

        if slots.pay_in_full:
            candidate = balance
        elif slots.amount is not None:
            candidate = slots.amount
        else:
            return _HandlerResult(responses.ask_amount())

        ok, reason = validators.is_valid_amount(candidate, balance)
        slots.amount = None
        slots.pay_in_full = False
        if not ok:
            return _HandlerResult(responses.invalid_amount(reason, balance))

        self.state.validated_amount = validators.normalize_amount(candidate)
        self.state.stage = Stage.AWAITING_CARD_DETAILS
        return _HandlerResult(None, advance=True)

    def _handle_card_details(self) -> _HandlerResult:
        slots = self.state.slots

        # Validate each field as soon as it's available rather than
        # waiting for every field to be collected, so obviously-bad input
        # is caught (and re-prompted for) immediately.
        if slots.card_number and not validators.luhn_check(slots.card_number):
            slots.card_number = None
            return _HandlerResult(responses.invalid_card_number())
        if slots.cvv and slots.card_number and not validators.is_valid_cvv(slots.cvv, slots.card_number):
            slots.cvv = None
            return _HandlerResult(responses.invalid_cvv())
        if (
            slots.expiry_month
            and slots.expiry_year
            and not validators.is_valid_expiry(slots.expiry_month, slots.expiry_year)
        ):
            slots.expiry_month = None
            slots.expiry_year = None
            return _HandlerResult(responses.invalid_expiry())

        missing = self.state.missing_card_fields()
        if missing:
            return _HandlerResult(responses.ask_card_details(missing))

        card = {
            "cardholder_name": slots.cardholder_name,
            "card_number": slots.card_number,
            "cvv": slots.cvv,
            "expiry_month": slots.expiry_month,
            "expiry_year": slots.expiry_year,
        }
        try:
            result = api_client.process_payment(
                self.state.slots.account_id, self.state.validated_amount, card
            )
        except api_client.ApiUnavailable:
            self._close(responses.system_error(), outcome="system_error")
            return _HandlerResult(responses.system_error())

        if result.success:
            remaining = self.state.account["balance"] - self.state.validated_amount
            self.state.transaction_id = result.transaction_id
            success_message = responses.payment_success(
                result.transaction_id, self.state.validated_amount, remaining
            )
            self._close(success_message, outcome="success", success=True)
            return _HandlerResult(success_message)

        if result.error_code == "insufficient_balance":
            self.state.payment_attempts += 1
            self.state.stage = Stage.AWAITING_AMOUNT
            if self.state.payment_attempts >= MAX_PAYMENT_ATTEMPTS:
                self._close(responses.payment_exhausted(), outcome="payment_failed")
                return _HandlerResult(responses.payment_exhausted())
            return _HandlerResult(
                responses.payment_insufficient_balance(self.state.account["balance"])
            )

        # invalid_card / invalid_cvv / invalid_expiry / anything else the
        # API rejects: user-fixable, clear the implicated field(s).
        self.state.payment_attempts += 1
        if result.error_code == "invalid_card":
            slots.card_number = None
        elif result.error_code == "invalid_cvv":
            slots.cvv = None
        elif result.error_code == "invalid_expiry":
            slots.expiry_month = None
            slots.expiry_year = None
        else:
            slots.card_number = None
            slots.cvv = None
            slots.expiry_month = None
            slots.expiry_year = None

        if self.state.payment_attempts >= MAX_PAYMENT_ATTEMPTS:
            self._close(responses.payment_exhausted(), outcome="payment_failed")
            return _HandlerResult(responses.payment_exhausted())

        attempts_left = MAX_PAYMENT_ATTEMPTS - self.state.payment_attempts
        return _HandlerResult(
            responses.payment_failed_terminal_api_error(attempts_left, result.error_code)
        )
