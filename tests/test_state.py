from state import ConversationState, Stage


def test_current_ask_description_per_stage():
    s = ConversationState()

    s.stage = Stage.AWAITING_ACCOUNT_ID
    assert "account ID" in s.current_ask_description()

    s.stage = Stage.AWAITING_NAME
    assert "full_name" in s.current_ask_description()

    s.stage = Stage.AWAITING_SECONDARY_FACTOR
    desc = s.current_ask_description()
    assert "date of birth" in desc and "Aadhaar" in desc and "pincode" in desc

    s.stage = Stage.AWAITING_AMOUNT
    assert "pay" in s.current_ask_description()


def test_current_ask_description_lists_missing_card_fields_only():
    s = ConversationState()
    s.stage = Stage.AWAITING_CARD_DETAILS
    s.slots.card_number = "4532015112830366"
    s.slots.expiry_month = 12
    s.slots.expiry_year = 2027
    desc = s.current_ask_description()
    assert "CVV" in desc
    assert "cardholder name" in desc
    assert "card number" not in desc
    assert "expiry date" not in desc


def test_missing_card_fields_all_present_returns_empty():
    s = ConversationState()
    s.slots.card_number = "4532015112830366"
    s.slots.expiry_month = 12
    s.slots.expiry_year = 2027
    s.slots.cvv = "123"
    s.slots.cardholder_name = "Nithin Jain"
    assert s.missing_card_fields() == []


def test_is_secondary_factor_present():
    s = ConversationState()
    assert s.is_secondary_factor_present() is False
    s.slots.pincode = "400001"
    assert s.is_secondary_factor_present() is True
