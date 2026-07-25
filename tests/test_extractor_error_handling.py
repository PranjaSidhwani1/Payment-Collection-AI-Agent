"""Exercises extractor.py's resilience/retry behavior without any network
access - the Groq client is replaced with a fake that can be told to fail
N times before succeeding, or to always fail.
"""
import json

import pytest

import extractor
from state import ConversationState


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, fail_times: int, error: Exception, success_payload: dict):
        self.fail_times = fail_times
        self.error = error
        self.success_payload = success_payload
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.error
        return _FakeResponse(json.dumps(self.success_payload))


class _FakeChat:
    def __init__(self, completions):
        self.completions = completions


class _FakeGroqClient:
    def __init__(self, completions):
        self.chat = _FakeChat(completions)


EMPTY_PAYLOAD = {
    "account_id": None,
    "full_name": None,
    "dob": None,
    "aadhaar_last4": None,
    "pincode": None,
    "amount": None,
    "pay_in_full": None,
    "card_number": None,
    "cvv": None,
    "expiry_month": None,
    "expiry_year": None,
    "cardholder_name": None,
    "cancel_requested": None,
}


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    monkeypatch.setattr(extractor.time, "sleep", lambda *_args, **_kwargs: None)


def test_succeeds_first_try(monkeypatch):
    payload = dict(EMPTY_PAYLOAD, account_id="ACC1001")
    fake_completions = _FakeCompletions(fail_times=0, error=RuntimeError("n/a"), success_payload=payload)
    monkeypatch.setattr(extractor, "_client", lambda: _FakeGroqClient(fake_completions))

    result = extractor.extract("my account is ACC1001", ConversationState())

    assert result["account_id"] == "ACC1001"
    assert fake_completions.calls == 1


def test_recovers_after_transient_failure(monkeypatch):
    payload = dict(EMPTY_PAYLOAD, full_name="Nithin Jain")
    fake_completions = _FakeCompletions(
        fail_times=2, error=ConnectionError("network blip"), success_payload=payload
    )
    monkeypatch.setattr(extractor, "_client", lambda: _FakeGroqClient(fake_completions))

    result = extractor.extract("my name is Nithin Jain", ConversationState(), max_retries=2)

    assert result["full_name"] == "Nithin Jain"
    assert fake_completions.calls == 3


def test_raises_extraction_unavailable_after_exhausting_retries(monkeypatch):
    fake_completions = _FakeCompletions(
        fail_times=99, error=ConnectionError("still down"), success_payload=EMPTY_PAYLOAD
    )
    monkeypatch.setattr(extractor, "_client", lambda: _FakeGroqClient(fake_completions))

    with pytest.raises(extractor.ExtractionUnavailable):
        extractor.extract("hello", ConversationState(), max_retries=2)

    assert fake_completions.calls == 3  # 1 initial + 2 retries


def test_missing_api_key_raises_extraction_unavailable(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(extractor.ExtractionUnavailable):
        extractor.extract("hello", ConversationState())
