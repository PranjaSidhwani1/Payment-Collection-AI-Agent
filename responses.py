"""All user-facing message templates.

Centralizing every reply here (as plain, deterministic string templates -
never LLM-generated) makes it easy to audit the entire surface area for
two hard requirements: (1) never leak dob/aadhaar/pincode values, and
(2) never reveal *which* verification factor was wrong.
"""
def format_currency(amount: float) -> str:
    return f"\u20b9{amount:,.2f}"


GREETING_PREFIX = "Hello!"


def greeting() -> str:
    return "Hello! Please share your account ID to get started."


def ask_account_id() -> str:
    return "Could you share your account ID?"


def account_not_found(attempts_left: int) -> str:
    return (
        "I couldn't find an account with that ID. Could you double-check and "
        f"re-enter it? ({attempts_left} attempt(s) left.)"
    )


def account_lookup_exhausted() -> str:
    return (
        "I still can't find an account matching the ID(s) provided, so I'm "
        "unable to continue. Please double-check your account ID and contact "
        "support if the issue persists."
    )


def ask_name() -> str:
    return "Got it. Could you please confirm your full name?"


def ask_secondary_factor() -> str:
    return (
        "Thanks. Could you verify your date of birth, the last 4 digits of "
        "your Aadhaar, or your pincode?"
    )


def clarify_bad_dob() -> str:
    return (
        "That date doesn't look valid - could you double-check and re-enter "
        "your date of birth (or provide your Aadhaar last 4 / pincode instead)?"
    )


def clarify_bad_aadhaar() -> str:
    return (
        "Aadhaar last 4 digits should be exactly 4 digits - could you re-enter "
        "that (or provide your date of birth / pincode instead)?"
    )


def clarify_bad_pincode() -> str:
    return (
        "That pincode doesn't look right - could you re-enter it (or provide "
        "your date of birth / Aadhaar last 4 instead)?"
    )


def verification_failed(attempts_left: int) -> str:
    return (
        "I wasn't able to verify your identity with those details. Could you "
        "re-enter your full name along with your date of birth, Aadhaar last "
        f"4, or pincode? ({attempts_left} attempt(s) left.)"
    )


def verification_exhausted() -> str:
    return (
        "I'm unable to verify your identity after multiple attempts, so I "
        "can't proceed with this request. Please contact support for "
        "assistance."
    )


def verified_balance_message(balance: float) -> str:
    return f"Identity verified. Your outstanding balance is {format_currency(balance)}."


def ask_amount() -> str:
    return (
        "How much would you like to pay today? You can pay in full or make "
        "a partial payment."
    )


def invalid_amount(reason: str, balance: float, attempts_left: int) -> str:
    if reason == "exceeds_balance":
        base = (
            f"That amount is more than your outstanding balance of "
            f"{format_currency(balance)}. How much would you like to pay?"
        )
    elif reason == "too_many_decimals":
        base = "Amounts can have at most 2 decimal places. How much would you like to pay?"
    elif reason == "not_positive":
        base = "The payment amount needs to be greater than zero. How much would you like to pay?"
    else:
        base = "I couldn't quite understand that amount. How much would you like to pay?"
    return f"{base} ({attempts_left} attempt(s) left.)"


def amount_exhausted() -> str:
    return (
        "I'm unable to get a valid payment amount after multiple attempts, so "
        "I can't proceed with this request. Please contact support for "
        "assistance."
    )


def ask_card_details(missing_fields: list) -> str:
    if not missing_fields:
        return "Could you share your card details?"
    return "Great. Could you share your " + ", ".join(missing_fields) + "?"


def invalid_card_number() -> str:
    return "That card number doesn't look valid. Could you re-enter it?"


def invalid_cvv() -> str:
    return "That CVV doesn't look right. Could you re-enter it?"


def invalid_expiry() -> str:
    return "That expiry date looks invalid or already expired. Could you re-enter it?"


def payment_success(transaction_id: str, amount: float, remaining_balance: float) -> str:
    return (
        f"Payment successful! You paid {format_currency(amount)}. "
        f"Transaction ID: {transaction_id}. "
        f"Remaining balance: {format_currency(remaining_balance)}. "
        "Thank you - is there anything else I can help with? This session is now closed."
    )


def payment_failed_terminal_api_error(attempts_left: int, error_code: str) -> str:
    friendly = {
        "invalid_card": "There's an issue with the card number.",
        "invalid_cvv": "There's an issue with the CVV.",
        "invalid_expiry": "There's an issue with the expiry date.",
    }.get(error_code, "There was an issue with the card details.")
    return f"{friendly} Could you re-enter it? ({attempts_left} attempt(s) left.)"


def payment_insufficient_balance(balance: float) -> str:
    return (
        f"That amount exceeds your outstanding balance of {format_currency(balance)}. "
        "How much would you like to pay instead?"
    )


def payment_exhausted() -> str:
    return (
        "We were unable to process your payment after multiple attempts. "
        "Please double check your card details and try again later, or "
        "contact support."
    )


def extraction_unavailable() -> str:
    return (
        "Sorry, I'm having trouble processing that message right now. Could "
        "you please resend it?"
    )


def extraction_exhausted() -> str:
    return (
        "I'm having ongoing technical trouble understanding messages right "
        "now, so I have to end this session here. Please try again shortly."
    )


def cancelled() -> str:
    return "No problem, I've ended this session. No payment was made. Have a great day!"


def system_error() -> str:
    return (
        "Something went wrong on our end while processing that. I have to "
        "end this session here - please try again shortly or contact "
        "support."
    )


def session_ended(outcome: str) -> str:
    summaries = {
        "success": "Your payment was already completed",
        "verification_failed": "This session ended because identity verification failed",
        "account_not_found": "This session ended because the account could not be found",
        "amount_failed": "This session ended because a valid payment amount could not be provided",
        "payment_failed": "This session ended because the payment could not be completed",
        "cancelled": "This session was cancelled",
        "system_error": "This session ended due to a technical issue",
    }
    summary = summaries.get(outcome, "This session has ended")
    return f"{summary}. Please start a new conversation if you'd like to try again."
