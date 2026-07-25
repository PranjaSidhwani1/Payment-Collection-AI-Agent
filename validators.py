"""Deterministic validation helpers.

These functions are the safety net that sits between the LLM extractor and
anything that matters (verification comparisons, API calls). Schema-valid
output from the extractor is not the same as business-valid data - e.g. a
well-formed but non-existent calendar date, or a card number that fails
Luhn - so everything here is plain, dependency-free Python that never
consults the LLM.
"""
from datetime import date


def is_valid_calendar_date(date_str: str) -> bool:
    """True if date_str is a real calendar date in YYYY-MM-DD form.

    This correctly accepts genuine leap-day dates (e.g. 1988-02-29, since
    1988 is a leap year) and correctly rejects fabricated ones (e.g.
    1990-02-29). It does not judge plausibility beyond "is this a date
    that exists" - a wrong-but-valid date is caught later by the exact
    equality check in verification.py, not here.
    """
    if not date_str or not isinstance(date_str, str):
        return False
    parts = date_str.split("-")
    if len(parts) != 3:
        return False
    year_s, month_s, day_s = parts
    if not (len(year_s) == 4 and len(month_s) == 2 and len(day_s) == 2):
        return False
    if not (year_s.isdigit() and month_s.isdigit() and day_s.isdigit()):
        return False
    try:
        date(int(year_s), int(month_s), int(day_s))
    except ValueError:
        return False
    return True


def is_exact_digit_string(value: str, length: int) -> bool:
    """True if value is exactly `length` digit characters (no spaces/signs)."""
    return isinstance(value, str) and value.isdigit() and len(value) == length


def luhn_check(card_number: str) -> bool:
    """Standard Luhn (mod 10) checksum used by all major card networks."""
    if not card_number or not card_number.isdigit():
        return False
    if len(card_number) < 12 or len(card_number) > 19:
        return False
    digits = [int(d) for d in card_number]
    checksum = 0
    parity = len(digits) % 2
    for i, d in enumerate(digits):
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


def is_amex(card_number: str) -> bool:
    return card_number.startswith(("34", "37"))


def expected_cvv_length(card_number: str) -> int:
    return 4 if is_amex(card_number) else 3


def is_valid_cvv(cvv: str, card_number: str) -> bool:
    if not cvv or not cvv.isdigit():
        return False
    return len(cvv) == expected_cvv_length(card_number)


def is_valid_expiry(month, year, today: date = None) -> bool:
    """month/year must form a real, non-expired card expiry.

    A card is considered valid through the end of its expiry month, so a
    card expiring this month is still usable.
    """
    if today is None:
        today = date.today()
    try:
        month = int(month)
        year = int(year)
    except (TypeError, ValueError):
        return False
    if not (1 <= month <= 12):
        return False
    if year < 1000:
        return False
    if year < today.year:
        return False
    if year == today.year and month < today.month:
        return False
    return True


def normalize_amount(amount) -> float:
    """Round to 2 decimal places the same way currency amounts are stored."""
    return round(float(amount), 2)


def is_valid_amount(amount, balance: float) -> tuple:
    """Returns (is_valid, reason) where reason is a short machine key.

    reason in {"not_positive", "too_many_decimals", "exceeds_balance", None}
    """
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return False, "not_a_number"
    if amount <= 0:
        return False, "not_positive"
    if round(amount, 2) != round(amount, 10):
        # more than 2 decimal places of real precision
        return False, "too_many_decimals"
    if round(amount, 2) > round(balance, 2):
        return False, "exceeds_balance"
    return True, None
