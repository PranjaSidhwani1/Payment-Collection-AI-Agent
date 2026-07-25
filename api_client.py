"""Thin REST client for the payment verification API.

Every function returns a small, explicit result object rather than raising
on "expected" API error responses (404 / 422) - those are normal business
outcomes the FSM needs to branch on. Only genuinely unexpected failures
(network errors, timeouts, 5xx, malformed responses) raise ApiUnavailable,
which the agent treats as a terminal system failure for that turn.

Card data hygiene: card_number/cvv are only ever held in memory for the
duration of building the request and are never written to any log line in
this module (see the masked repr used in error logging).
"""
import os
from dataclasses import dataclass
from typing import Optional

import requests

BASE_URL = os.environ.get(
    "PAYMENT_API_BASE_URL",
    "https://se-payment-verification-api.service.external.usea2.aws.prodigaltech.com",
)
REQUEST_TIMEOUT_SECONDS = 15

# Append-only log of API calls made, for the eval harness's tool-call
# correctness checks. Deliberately never stores raw card_number/cvv - only
# a masked last-4 - so this is safe to inspect/print in reports.
call_log = []


class ApiUnavailable(Exception):
    """Network error, timeout, 5xx, or unparseable response."""


@dataclass
class LookupResult:
    found: bool
    account: Optional[dict] = None
    error_code: Optional[str] = None


@dataclass
class PaymentResult:
    success: bool
    transaction_id: Optional[str] = None
    error_code: Optional[str] = None


def _mask_card(card_number: str) -> str:
    if not card_number:
        return ""
    return "*" * max(0, len(card_number) - 4) + card_number[-4:]


def lookup_account(account_id: str) -> LookupResult:
    call_log.append({"endpoint": "lookup-account", "payload": {"account_id": account_id}})
    try:
        resp = requests.post(
            f"{BASE_URL}/api/lookup-account",
            json={"account_id": account_id},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise ApiUnavailable(f"lookup-account request failed: {exc}") from exc

    if resp.status_code == 200:
        try:
            return LookupResult(found=True, account=resp.json())
        except ValueError as exc:
            raise ApiUnavailable("lookup-account returned unparseable JSON") from exc

    if resp.status_code == 404:
        try:
            body = resp.json()
        except ValueError:
            body = {}
        return LookupResult(found=False, error_code=body.get("error_code", "account_not_found"))

    raise ApiUnavailable(f"lookup-account returned unexpected status {resp.status_code}")


def process_payment(account_id: str, amount: float, card: dict) -> PaymentResult:
    """card must have: cardholder_name, card_number, cvv, expiry_month, expiry_year."""
    call_log.append(
        {
            "endpoint": "process-payment",
            "payload": {
                "account_id": account_id,
                "amount": amount,
                "card_last4": _mask_card(card.get("card_number", "")),
            },
        }
    )
    payload = {
        "account_id": account_id,
        "amount": amount,
        "payment_method": {
            "type": "card",
            "card": {
                "cardholder_name": card["cardholder_name"],
                "card_number": card["card_number"],
                "cvv": card["cvv"],
                "expiry_month": card["expiry_month"],
                "expiry_year": card["expiry_year"],
            },
        },
    }
    try:
        resp = requests.post(
            f"{BASE_URL}/api/process-payment",
            json=payload,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise ApiUnavailable(
            f"process-payment request failed for card {_mask_card(card['card_number'])}: {exc}"
        ) from exc

    if resp.status_code == 200:
        try:
            body = resp.json()
        except ValueError as exc:
            raise ApiUnavailable("process-payment returned unparseable JSON") from exc
        return PaymentResult(success=True, transaction_id=body.get("transaction_id"))

    if resp.status_code == 422:
        try:
            body = resp.json()
        except ValueError:
            body = {}
        return PaymentResult(success=False, error_code=body.get("error_code", "unknown_error"))

    raise ApiUnavailable(f"process-payment returned unexpected status {resp.status_code}")
