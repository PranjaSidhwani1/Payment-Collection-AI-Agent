"""LLM-based slot extraction.

This is the ONLY place natural-language understanding happens. Everything
downstream (verification, validation, business rules, API calls, replies)
is plain deterministic Python - see agent.py and validators.py. This
module's only job is: given one free-form user message plus what we
already know, return which of our known fields (if any) the user just
stated, normalized into a fixed shape.

Design notes (see the design doc for the full rationale):
  * Uses Groq's Structured Outputs API with `strict: true`. That mode uses
    constrained decoding server-side, so the response is *guaranteed* to
    be valid JSON matching SLOT_SCHEMA exactly (correct keys/types, no
    extras) - there is no "malformed JSON" failure mode to handle.
  * temperature=0 for maximally consistent behavior across runs.
  * No regex/keyword fallback for parsing. If the Groq call itself fails
    (network/timeout/5xx/auth), we retry a couple of times with backoff
    and then raise ExtractionUnavailable - the agent turns that into a
    "please resend that" reply rather than guessing at the content.
"""
import json
import os
import time

from groq import Groq

DEFAULT_MODEL = "openai/gpt-oss-120b"

# Every possible slot the agent can ever need, each nullable. Groq's
# strict mode requires every property to be listed in "required" - a
# field simply being absent from the user's message is represented as
# that property's value being null, not the key being missing.
SLOT_SCHEMA = {
    "type": "object",
    "properties": {
        "account_id": {
            "type": ["string", "null"],
            "description": "Account identifier such as ACC1001, normalized to remove spaces/lowercasing quirks (e.g. 'acc 1001' -> 'ACC1001').",
        },
        "full_name": {
            "type": ["string", "null"],
            "description": "The user's full legal name as they stated it, verbatim (do not shorten to a nickname; if they give both a nickname and a full name, use the full name).",
        },
        "dob": {
            "type": ["string", "null"],
            "description": "Date of birth normalized to YYYY-MM-DD. If the user corrects themselves mid-message (e.g. 'oh sorry, actually...'), use only the corrected value.",
        },
        "aadhaar_last4": {
            "type": ["string", "null"],
            "description": "Last 4 digits of Aadhaar, digits only, no spaces (e.g. '4 3 2 1' -> '4321').",
        },
        "pincode": {
            "type": ["string", "null"],
            "description": "Postal PIN code, digits only, no spaces.",
        },
        "amount": {
            "type": ["number", "null"],
            "description": "Payment amount in rupees as a plain number, resolving spelled-out amounts (e.g. 'a thousand rupees' -> 1000). Do not set this if the user is asking to pay the full/entire balance - use pay_in_full for that instead.",
        },
        "pay_in_full": {
            "type": ["boolean", "null"],
            "description": "true only if the user explicitly asked to pay the full outstanding balance (e.g. 'clear the full amount', 'pay it all off').",
        },
        "card_number": {
            "type": ["string", "null"],
            "description": "Card number, digits only, no spaces or dashes.",
        },
        "cvv": {
            "type": ["string", "null"],
            "description": "CVV/CVC, digits only. Resolve spelled-out or typo'd digit words (e.g. 'two hunder sixty 5' -> '265').",
        },
        "expiry_month": {
            "type": ["integer", "null"],
            "description": "Card expiry month as an integer 1-12.",
        },
        "expiry_year": {
            "type": ["integer", "null"],
            "description": "Card expiry year as a 4-digit integer (e.g. '27' or '2027' -> 2027).",
        },
        "cardholder_name": {
            "type": ["string", "null"],
            "description": "Name printed on the card, if the user is stating it as a card detail (may be the same as full_name).",
        },
        "cancel_requested": {
            "type": ["boolean", "null"],
            "description": "true only if the user explicitly wants to stop/cancel the conversation (e.g. 'cancel', 'stop', 'never mind').",
        },
    },
    "required": [
        "account_id",
        "full_name",
        "dob",
        "aadhaar_last4",
        "pincode",
        "amount",
        "pay_in_full",
        "card_number",
        "cvv",
        "expiry_month",
        "expiry_year",
        "cardholder_name",
        "cancel_requested",
    ],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You are the slot-extraction engine inside a payment-collection chat agent.
You do NOT talk to the user. You read exactly one user message plus a short
summary of what is already known, and return a single JSON object matching
the given schema.

Rules:
- You will be told what the agent just asked the user for. Use that to
  disambiguate: e.g. if the agent asked for the cardholder name and the
  user replies with just a name, put it in cardholder_name - even if an
  identical-looking value is already known under a different field (like
  full_name). A bare short reply almost always answers the question that
  was just asked.
- Only extract information the user actually stated in THIS message. Do not
  carry over or re-state values already listed as "already known" - leave
  those fields null unless the user is explicitly changing/correcting them
  in this message.
- Do not invent, guess, or infer values that were not stated.
- If the user corrects themselves within the message (e.g. "oh sorry",
  "actually", "I mean", "no wait"), extract only the corrected/final value.
- Resolve minor typos and spelled-out or mixed word/digit numbers into
  plain digits (e.g. "two hunder sixty 5" -> "265", "oh-one-two-three" is
  not applicable here but similar patterns should resolve the same way).
- Normalize dates to YYYY-MM-DD. Preserve the date exactly as stated once
  normalized - do not "correct" an unusual-looking but valid date.
- card_number, cvv, aadhaar_last4, pincode are digit strings only: strip
  spaces, dashes, and any other separators.
- Two-digit expiry years mean 20XX (e.g. 27 -> 2027).
- Return null for every field not clearly present in this message.
"""


class ExtractionUnavailable(Exception):
    """Raised when the LLM extraction call could not be completed after
    retries. The agent treats this as a transient system issue, not a
    user input problem."""


def _client() -> Groq:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ExtractionUnavailable("GROQ_API_KEY is not set")
    return Groq(api_key=api_key)


def _known_slots_summary(state) -> str:
    known = {}
    for f in SLOT_SCHEMA["properties"]:
        if f in ("cancel_requested",):
            continue
        value = getattr(state.slots, f, None)
        if value is not None:
            known[f] = value
    if not known:
        return "(nothing yet)"
    return ", ".join(f"{k}={v!r}" for k, v in known.items())


def extract(user_input: str, state, max_retries: int = 2) -> dict:
    """Extract structured slot values from one user message.

    Args:
        user_input: the raw message text.
        state: the current ConversationState (used only to give the LLM
            context about what's already known; never mutated here).
        max_retries: number of retries after the first attempt.

    Returns:
        dict matching SLOT_SCHEMA's properties, with null -> None.

    Raises:
        ExtractionUnavailable: if the call fails after all retries.
    """
    model = os.environ.get("GROQ_MODEL", DEFAULT_MODEL)
    client = _client()

    user_prompt = (
        f"The agent just asked the user for: {state.current_ask_description()}\n\n"
        f"Already known (do not re-extract unless the user is correcting it): "
        f"{_known_slots_summary(state)}\n\n"
        f"Latest user message:\n{user_input}"
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    last_error = None
    for attempt in range(max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "extracted_slots",
                        "strict": True,
                        "schema": SLOT_SCHEMA,
                    },
                },
            )
            raw = response.choices[0].message.content
            data = json.loads(raw)
            return data
        except Exception as exc:  # noqa: BLE001 - broad on purpose, see docstring
            last_error = exc
            if attempt < max_retries:
                time.sleep(0.5 * (attempt + 1))
                continue

    raise ExtractionUnavailable(str(last_error))
