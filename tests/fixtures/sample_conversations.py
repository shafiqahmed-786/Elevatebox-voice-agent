"""
Deterministic evaluation harness fixtures.

Every case here is taken directly from the assignment PDF's own examples
(Sections 03 and the "HOT / WARM / COLD" boxes), so that passing these tests
is a direct, checkable claim: "the classifier reads these examples the way
the assignment says they should be read."
"""

from __future__ import annotations

from app.models.schemas import ExtractedSignals

# --- HOT: "Typical signals: clear purchase intent, asking price, asking
# when work can start, concrete timeline, concrete feature requirements,
# ready to discuss next steps." -------------------------------------------

HOT_CASES: list[tuple[str, ExtractedSignals]] = [
    (
        "asks price",
        ExtractedSignals(asked_price=True, has_business_context=True),
    ),
    (
        "asks how soon you can start",
        ExtractedSignals(asked_start_timeline=True, has_business_context=True),
    ),
    (
        "gives budget + timeline",
        ExtractedSignals(
            concrete_budget_inr=70000,
            concrete_timeline="3 weeks",
            has_business_context=True,
        ),
    ),
    (
        "asks specific implementation question (Razorpay)",
        ExtractedSignals(
            specific_feature_questions=["Razorpay integration"],
            has_business_context=True,
        ),
    ),
    (
        "'Send me the details.' plus concrete budget",
        ExtractedSignals(
            explicit_next_step_request=True,
            concrete_budget_inr=50000,
            has_business_context=True,
        ),
    ),
]

# --- WARM: "genuine need, interested, but has a barrier: budget issue,
# timing issue, needs approval from another person, not ready yet." -------

WARM_CASES: list[tuple[str, ExtractedSignals]] = [
    (
        "'Budget abhi thoda tight hai.' (budget issue, still interested)",
        ExtractedSignals(
            budget_barrier=True,
            general_interest=True,
            has_business_context=True,
        ),
    ),
    (
        "'My brother handles this.' (approval barrier)",
        ExtractedSignals(
            approval_barrier="brother",
            general_interest=True,
            has_business_context=True,
        ),
    ),
    (
        "'Maybe next month.' (timing barrier)",
        ExtractedSignals(
            timing_barrier="maybe next month",
            general_interest=True,
            has_business_context=True,
        ),
    ),
    (
        "Interested, wants it, but timeline is later",
        ExtractedSignals(
            timing_barrier="not right now, later this year",
            general_interest=True,
            has_business_context=True,
        ),
    ),
    (
        "Strong HOT signals but ALSO a real barrier -> still WARM",
        ExtractedSignals(
            asked_price=True,
            concrete_budget_inr=100000,
            approval_barrier="business partner",
            has_business_context=True,
        ),
    ),
]

# --- COLD: "casually browsing, unclear requirement, no meaningful
# timeline, no meaningful budget, low buying intent." ----------------------

COLD_CASES: list[tuple[str, ExtractedSignals]] = [
    (
        "'Just checking options.'",
        ExtractedSignals(just_browsing=True, has_business_context=False),
    ),
    (
        "No clear need, no budget, no timeline",
        ExtractedSignals(has_business_context=False),
    ),
    (
        "Vague browsing with a business mentioned but nothing concrete",
        ExtractedSignals(just_browsing=True, has_business_context=True),
    ),
]


# --- Callback phrases, from the assignment's own testing checklist --------

CALLBACK_PHRASES = [
    "tomorrow morning",
    "Friday at 4",
    "next Tuesday evening",
    "kal subah call karna",
    "repu udayam call cheyandi",  # Telugu: "call [me] tomorrow morning"
    "call me next week",
]
