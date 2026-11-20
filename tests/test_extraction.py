from app.conversation.extraction import coerce_budget_to_inr, safe_parse_extracted_signals
from app.models.schemas import ExtractedSignals


def test_normal_well_formed_payload():
    result = safe_parse_extracted_signals(
        {"asked_price": True, "budget_inr": 70000, "features": ["Razorpay"]}
    )
    assert result.asked_price is True
    assert result.concrete_budget_inr == 70000
    assert result.specific_feature_questions == ["Razorpay"]


def test_not_a_dict_at_all_does_not_crash():
    for bad_input in [None, "just a string", 42, ["a", "list"], True]:
        result = safe_parse_extracted_signals(bad_input)  # type: ignore[arg-type]
        assert isinstance(result, ExtractedSignals)


def test_empty_dict_returns_default_signals():
    result = safe_parse_extracted_signals({})
    assert result == ExtractedSignals()


def test_wrong_type_for_bool_field_is_dropped_not_fatal():
    # asked_price given as a string instead of a bool
    result = safe_parse_extracted_signals({"asked_price": "yes please", "asked_start_timeline": True})
    assert result.asked_start_timeline is True  # the valid sibling field survives
    # the malformed field is dropped rather than raising -- default value wins
    assert result.asked_price is False


def test_wrong_type_for_list_field_is_dropped_not_fatal():
    result = safe_parse_extracted_signals({"features": "Razorpay, inventory"})  # should be a list
    assert result.specific_feature_questions == []


def test_unrecognized_extra_fields_are_ignored_not_fatal():
    result = safe_parse_extracted_signals(
        {"asked_price": True, "some_field_the_llm_invented": {"nested": "garbage"}}
    )
    assert result.asked_price is True


def test_budget_coercion_handles_common_shorthands():
    assert coerce_budget_to_inr(70000) == 70000
    assert coerce_budget_to_inr("70000") == 70000
    assert coerce_budget_to_inr("70,000") == 70000
    assert coerce_budget_to_inr("₹70,000") == 70000
    assert coerce_budget_to_inr("50k") == 50000
    assert coerce_budget_to_inr("1.5 lakh") == 150000
    assert coerce_budget_to_inr("2 lac") == 200000
    assert coerce_budget_to_inr(None) is None
    assert coerce_budget_to_inr("not a number") is None
    assert coerce_budget_to_inr(True) is None  # bool must never masquerade as a budget


def test_budget_given_as_shorthand_string_flows_through_end_to_end():
    result = safe_parse_extracted_signals({"budget_inr": "50k"})
    assert result.concrete_budget_inr == 50000


def test_key_quote_singular_field_does_not_break_validation():
    # 'key_quote' is on the tool schema exposed to the voice platform but
    # is not a field on ExtractedSignals -- it must be silently tolerated
    # here (the orchestrator, not this module, moves it into LeadState).
    result = safe_parse_extracted_signals(
        {"asked_price": True, "key_quote": "budget is around 70 thousand"}
    )
    assert result.asked_price is True


def test_all_tool_schema_discovery_fields_survive_extraction():
    """Regression test: business_type, sells_online_currently, product_count,
    decision_maker, and timeline (tool-schema name for concrete_timeline)
    were previously silently dropped by safe_parse_extracted_signals because
    ExtractedSignals had no matching fields / the rename map missed
    "timeline" specifically -- 4 of the assignment's 8 required discovery
    fields ("what they sell", "sell online already", "product count",
    "decision-making authority") were being thrown away before ever
    reaching LeadState. This exercises the exact property names declared
    in app.decision.signal_schema.UPDATE_LEAD_SIGNALS_TOOL."""
    result = safe_parse_extracted_signals({
        "business_type": "clothing",
        "sells_online_currently": False,
        "product_count": 200,
        "decision_maker": "self",
        "timeline": "3 weeks",  # tool schema's name; ExtractedSignals calls it concrete_timeline
    })
    assert result.business_type == "clothing"
    assert result.sells_online_currently is False  # explicit False must survive, not become None
    assert result.product_count == 200
    assert result.decision_maker == "self"
    assert result.concrete_timeline == "3 weeks"


def test_sells_online_currently_false_is_distinct_from_not_mentioned():
    not_mentioned = safe_parse_extracted_signals({"asked_price": True})
    explicitly_no = safe_parse_extracted_signals({"sells_online_currently": False})
    assert not_mentioned.sells_online_currently is None
    assert explicitly_no.sells_online_currently is False
