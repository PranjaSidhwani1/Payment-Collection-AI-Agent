from datetime import date

import validators


def test_valid_leap_day_1988():
    # 1988 is a leap year - this must be accepted as a real calendar date.
    assert validators.is_valid_calendar_date("1988-02-29") is True


def test_invalid_leap_day_non_leap_year():
    # 1990 is not a leap year.
    assert validators.is_valid_calendar_date("1990-02-29") is False


def test_invalid_date_format():
    assert validators.is_valid_calendar_date("14-05-1990") is False
    assert validators.is_valid_calendar_date("1990-5-14") is False
    assert validators.is_valid_calendar_date(None) is False
    assert validators.is_valid_calendar_date("") is False


def test_is_exact_digit_string():
    assert validators.is_exact_digit_string("4321", 4) is True
    assert validators.is_exact_digit_string("432", 4) is False
    assert validators.is_exact_digit_string("43a1", 4) is False
    assert validators.is_exact_digit_string("400001", 6) is True


def test_luhn_check_valid_card():
    assert validators.luhn_check("4532015112830366") is True


def test_luhn_check_invalid_card():
    assert validators.luhn_check("4532015112830367") is False
    assert validators.luhn_check("not-a-number") is False
    assert validators.luhn_check("123") is False


def test_amex_detection_and_cvv_length():
    assert validators.is_amex("340000000000009") is True
    assert validators.is_amex("4532015112830366") is False
    assert validators.expected_cvv_length("340000000000009") == 4
    assert validators.expected_cvv_length("4532015112830366") == 3


def test_is_valid_cvv():
    assert validators.is_valid_cvv("123", "4532015112830366") is True
    assert validators.is_valid_cvv("1234", "4532015112830366") is False
    assert validators.is_valid_cvv("1234", "340000000000009") is True
    assert validators.is_valid_cvv("12a", "4532015112830366") is False


def test_is_valid_expiry_future_and_current_month():
    today = date(2026, 7, 25)
    assert validators.is_valid_expiry(12, 2027, today=today) is True
    assert validators.is_valid_expiry(7, 2026, today=today) is True  # expires this month, still valid
    assert validators.is_valid_expiry(6, 2026, today=today) is False  # expired last month
    assert validators.is_valid_expiry(13, 2027, today=today) is False  # invalid month
    assert validators.is_valid_expiry(0, 2027, today=today) is False


def test_is_valid_amount_bounds():
    ok, reason = validators.is_valid_amount(500, 1250.75)
    assert ok is True and reason is None

    ok, reason = validators.is_valid_amount(0, 1250.75)
    assert ok is False and reason == "not_positive"

    ok, reason = validators.is_valid_amount(-10, 1250.75)
    assert ok is False and reason == "not_positive"

    ok, reason = validators.is_valid_amount(2000, 1250.75)
    assert ok is False and reason == "exceeds_balance"

    ok, reason = validators.is_valid_amount(500.567, 1250.75)
    assert ok is False and reason == "too_many_decimals"

    ok, reason = validators.is_valid_amount(1250.75, 1250.75)
    assert ok is True and reason is None
