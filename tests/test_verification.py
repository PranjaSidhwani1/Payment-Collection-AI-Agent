import verification

ACCOUNT = {
    "account_id": "ACC1001",
    "full_name": "Nithin Jain",
    "dob": "1990-05-14",
    "aadhaar_last4": "4321",
    "pincode": "400001",
    "balance": 1250.75,
}


def test_verified_with_dob():
    claimed = {"full_name": "Nithin Jain", "dob": "1990-05-14", "aadhaar_last4": None, "pincode": None}
    assert verification.is_verified(ACCOUNT, claimed) is True


def test_verified_with_aadhaar_only():
    claimed = {"full_name": "Nithin Jain", "dob": None, "aadhaar_last4": "4321", "pincode": None}
    assert verification.is_verified(ACCOUNT, claimed) is True


def test_verified_with_pincode_only():
    claimed = {"full_name": "Nithin Jain", "dob": None, "aadhaar_last4": None, "pincode": "400001"}
    assert verification.is_verified(ACCOUNT, claimed) is True


def test_name_mismatch_fails_even_with_correct_secondary():
    claimed = {"full_name": "Nithin K Jain", "dob": "1990-05-14", "aadhaar_last4": None, "pincode": None}
    assert verification.is_verified(ACCOUNT, claimed) is False


def test_name_case_sensitivity_no_fuzzy_matching():
    claimed = {"full_name": "nithin jain", "dob": "1990-05-14", "aadhaar_last4": None, "pincode": None}
    assert verification.is_verified(ACCOUNT, claimed) is False


def test_correct_name_but_all_secondary_wrong_fails():
    claimed = {
        "full_name": "Nithin Jain",
        "dob": "1991-05-14",
        "aadhaar_last4": "0000",
        "pincode": "000000",
    }
    assert verification.is_verified(ACCOUNT, claimed) is False


def test_leap_day_account_exact_match_verifies():
    account = {
        "account_id": "ACC1004",
        "full_name": "Rahul Mehta",
        "dob": "1988-02-29",
        "aadhaar_last4": "1357",
        "pincode": "400004",
        "balance": 3200.50,
    }
    claimed = {"full_name": "Rahul Mehta", "dob": "1988-02-29", "aadhaar_last4": None, "pincode": None}
    assert verification.is_verified(account, claimed) is True


def test_leap_day_account_off_by_one_day_rejected():
    account = {
        "account_id": "ACC1004",
        "full_name": "Rahul Mehta",
        "dob": "1988-02-29",
        "aadhaar_last4": "1357",
        "pincode": "400004",
        "balance": 3200.50,
    }
    claimed = {"full_name": "Rahul Mehta", "dob": "1988-02-28", "aadhaar_last4": None, "pincode": None}
    assert verification.is_verified(account, claimed) is False


def test_nothing_claimed_fails():
    claimed = {"full_name": "Nithin Jain", "dob": None, "aadhaar_last4": None, "pincode": None}
    assert verification.is_verified(ACCOUNT, claimed) is False
