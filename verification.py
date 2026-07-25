"""Identity verification logic.

Per the spec this must be strict - no fuzzy matching, no case-insensitive
workarounds - and must be implemented in code, not delegated to the LLM.
The LLM (via extractor.py) only ever *proposes* what the user said; this
module makes the actual accept/reject decision with plain equality checks.
"""


def is_verified(account: dict, claimed: dict) -> bool:
    """A user is verified if full_name matches exactly AND at least one of
    dob / aadhaar_last4 / pincode also matches exactly.
    """
    if claimed.get("full_name") != account.get("full_name"):
        return False
    return any(
        [
            claimed.get("dob") is not None and claimed.get("dob") == account.get("dob"),
            claimed.get("aadhaar_last4") is not None
            and claimed.get("aadhaar_last4") == account.get("aadhaar_last4"),
            claimed.get("pincode") is not None and claimed.get("pincode") == account.get("pincode"),
        ]
    )
