"""api_client.py tests using a mocked requests.post - no real network calls.

Covers: correct payload construction, status-code branching (200/404/422/
unexpected), and that call_log never contains raw card_number/cvv.
"""
from unittest.mock import patch

import pytest

import api_client


class _FakeResponse:
    def __init__(self, status_code, json_body):
        self.status_code = status_code
        self._json_body = json_body

    def json(self):
        return self._json_body


@pytest.fixture(autouse=True)
def clear_call_log():
    api_client.call_log.clear()
    yield
    api_client.call_log.clear()


def test_lookup_account_success():
    account = {
        "account_id": "ACC1001",
        "full_name": "Nithin Jain",
        "dob": "1990-05-14",
        "aadhaar_last4": "4321",
        "pincode": "400001",
        "balance": 1250.75,
    }
    with patch("api_client.requests.post", return_value=_FakeResponse(200, account)) as mock_post:
        result = api_client.lookup_account("ACC1001")

    assert result.found is True
    assert result.account == account
    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    assert kwargs["json"] == {"account_id": "ACC1001"}
    assert api_client.call_log == [{"endpoint": "lookup-account", "payload": {"account_id": "ACC1001"}}]


def test_lookup_account_not_found():
    body = {"error_code": "account_not_found", "message": "No account found"}
    with patch("api_client.requests.post", return_value=_FakeResponse(404, body)):
        result = api_client.lookup_account("ACC9999")

    assert result.found is False
    assert result.error_code == "account_not_found"


def test_lookup_account_unexpected_status_raises():
    with patch("api_client.requests.post", return_value=_FakeResponse(500, {})):
        with pytest.raises(api_client.ApiUnavailable):
            api_client.lookup_account("ACC1001")


def test_lookup_account_network_error_raises():
    import requests

    with patch("api_client.requests.post", side_effect=requests.Timeout("timed out")):
        with pytest.raises(api_client.ApiUnavailable):
            api_client.lookup_account("ACC1001")


def test_process_payment_success_and_payload_shape():
    card = {
        "cardholder_name": "Nithin Jain",
        "card_number": "4532015112830366",
        "cvv": "123",
        "expiry_month": 12,
        "expiry_year": 2027,
    }
    with patch(
        "api_client.requests.post",
        return_value=_FakeResponse(200, {"success": True, "transaction_id": "txn_abc123"}),
    ) as mock_post:
        result = api_client.process_payment("ACC1001", 500.0, card)

    assert result.success is True
    assert result.transaction_id == "txn_abc123"
    _, kwargs = mock_post.call_args
    payload = kwargs["json"]
    assert payload["account_id"] == "ACC1001"
    assert payload["amount"] == 500.0
    assert payload["payment_method"]["card"]["card_number"] == "4532015112830366"

    # Call log must never contain the raw card number/cvv - only masked last4.
    logged = api_client.call_log[-1]
    assert logged["payload"]["card_last4"] == "************0366"
    assert "4532015112830366" not in str(api_client.call_log)
    assert "123" not in str(logged["payload"])


def test_process_payment_insufficient_balance():
    card = {
        "cardholder_name": "Priya Agarwal",
        "card_number": "4532015112830366",
        "cvv": "123",
        "expiry_month": 12,
        "expiry_year": 2027,
    }
    with patch(
        "api_client.requests.post",
        return_value=_FakeResponse(422, {"success": False, "error_code": "insufficient_balance"}),
    ):
        result = api_client.process_payment("ACC1003", 100.0, card)

    assert result.success is False
    assert result.error_code == "insufficient_balance"


def test_process_payment_unexpected_status_raises():
    card = {
        "cardholder_name": "Nithin Jain",
        "card_number": "4532015112830366",
        "cvv": "123",
        "expiry_month": 12,
        "expiry_year": 2027,
    }
    with patch("api_client.requests.post", return_value=_FakeResponse(500, {})):
        with pytest.raises(api_client.ApiUnavailable):
            api_client.process_payment("ACC1001", 100.0, card)
