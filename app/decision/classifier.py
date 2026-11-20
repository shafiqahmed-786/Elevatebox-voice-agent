"""
Deterministic lead classification.

Design rule (from the assignment): "Do not rely on the caller literally
saying 'I am a hot lead.' Infer intent from indirect statements... Use
structured extraction and deterministic decision logic wherever appropriate."

So the split is:
  - The conversation LLM's ONLY job is to extract `ExtractedSignals` from
    what the caller actually said (see app/conversation/extraction.py).
  - This module turns those signals into a classification using fixed,
    inspectable rules. No LLM call happens here. Given the same signals,
    this always returns the same answer -- which is what makes it testable
    and defensible in an interview.

Rule of thumb encoded below, straight from the assignment's own definitions:
  HOT  = clear purchase intent, with no real barrier in the way.
  WARM = genuine interest, but a stated barrier (budget/approval/timing).
         A barrier present ALWAYS caps the result at WARM, even if the
         caller also showed strong buying signals -- because the action
         that matters (send WhatsApp now vs. schedule a callback) differs,
         and a real barrier means "not yet", not "yes, now".
  COLD = no business context, no engagement, explicitly just browsing.
"""

from __future__ import annotations

from app.models.schemas import ExtractedSignals, IntentClassification, IntentResult

# Fields where a LATER turn's meaningful value should replace an earlier one
# (the customer revised a figure, or answered something not asked before);
# everything else accumulates (booleans OR together, lists union). See
# merge_signals() and _is_meaningful() below.
_LATEST_WINS_FIELDS = (
    "business_type", "sells_online_currently", "product_count", "decision_maker",
    "concrete_budget_inr", "concrete_timeline", "approval_barrier", "timing_barrier",
)
_LIST_FIELDS = ("specific_feature_questions",)


def _is_meaningful(value: object) -> bool:
    """True if `value` represents an actual answer rather than 'not
    mentioned this turn'. Deliberately NOT a plain truthiness check:
    `sells_online_currently=False` is a real, meaningful answer ("no, not
    online yet") and must not be treated the same as it simply not having
    come up -- only `None` and empty string mean "not mentioned"."""
    if value is None:
        return False
    if isinstance(value, str) and value == "":
        return False
    return True


def merge_signals(accumulated: ExtractedSignals, latest_turn: ExtractedSignals) -> ExtractedSignals:
    """
    Folds one turn's freshly-extracted signals into the call's running
    total. This matters because classification must reflect EVERYTHING
    said so far, not just the most recent turn -- without this, a neutral
    or unrelated later turn (e.g. "call me next week") would silently
    overwrite an earlier HOT/WARM signal (e.g. a stated budget barrier)
    with nothing, regressing the classification mid-call. Boolean SIGNAL
    flags accumulate with OR (once true, stays true for the call); list
    signals union; the scalar/informational fields in _LATEST_WINS_FIELDS
    take the newest MEANINGFUL value (see _is_meaningful) -- a revised
    budget, or an answer to a question that hadn't been asked yet, replaces
    what came before instead of being ignored.
    """
    merged = accumulated.model_copy(deep=True)
    latest_dict = latest_turn.model_dump()

    for field_name, value in latest_dict.items():
        current = getattr(merged, field_name)
        if field_name in _LATEST_WINS_FIELDS:
            if _is_meaningful(value):
                setattr(merged, field_name, value)
        elif field_name in _LIST_FIELDS:
            combined = list(current)
            for item in value:
                if item not in combined:
                    combined.append(item)
            setattr(merged, field_name, combined)
        elif isinstance(current, bool):
            setattr(merged, field_name, current or bool(value))
        else:
            # Fallback for any future field: prefer whichever is truthy.
            setattr(merged, field_name, value if value else current)

    return merged

# Any ONE of these, on its own, is enough to look HOT (each maps to an
# explicit example in the assignment's own "HOT" bucket: asks price, asks
# how soon you can start, asks a specific implementation question, or asks
# to be sent details / move forward).
_STRONG_HOT_WEIGHT = 3
_MODERATE_HOT_WEIGHT = 2
_BARRIER_WEIGHT = 3
_HOT_THRESHOLD = 3  # a single strong signal is already enough


def classify_lead(signals: ExtractedSignals) -> IntentResult:
    hot_reasons: list[str] = []
    warm_reasons: list[str] = []
    cold_reasons: list[str] = []
    hot_score = 0
    warm_score = 0
    cold_score = 0

    if signals.asked_price:
        hot_score += _STRONG_HOT_WEIGHT
        hot_reasons.append("asked pricing")
    if signals.asked_start_timeline:
        hot_score += _STRONG_HOT_WEIGHT
        hot_reasons.append("asked how soon we can start")
    if signals.explicit_next_step_request:
        hot_score += _STRONG_HOT_WEIGHT
        hot_reasons.append("asked for details / next steps to be sent")
    if signals.specific_feature_questions:
        hot_score += _STRONG_HOT_WEIGHT
        hot_reasons.append(
            "asked about specific implementation: " + ", ".join(signals.specific_feature_questions)
        )
    if signals.concrete_budget_inr is not None:
        hot_score += _MODERATE_HOT_WEIGHT
        hot_reasons.append(f"gave a concrete budget (~Rs {signals.concrete_budget_inr:,})")
    if signals.concrete_timeline:
        hot_score += _MODERATE_HOT_WEIGHT
        hot_reasons.append(f"gave a concrete timeline ({signals.concrete_timeline})")

    has_barrier = False
    if signals.budget_barrier:
        warm_score += _BARRIER_WEIGHT
        has_barrier = True
        warm_reasons.append("mentioned a budget constraint")
    if signals.approval_barrier:
        warm_score += _BARRIER_WEIGHT
        has_barrier = True
        warm_reasons.append(f"needs sign-off from someone else ({signals.approval_barrier})")
    if signals.timing_barrier:
        warm_score += 2
        has_barrier = True
        warm_reasons.append(f"not ready yet ({signals.timing_barrier})")
    if signals.general_interest:
        warm_reasons.append("expressed general interest")

    if signals.just_browsing:
        cold_score += 3
        cold_reasons.append("described themselves as just looking / comparing options")
    if not signals.has_business_context:
        cold_score += 1
        cold_reasons.append("no clear business context established")

    has_engagement = hot_score > 0 or signals.general_interest

    # Reasons shown are scoped to whichever category actually decided the
    # outcome -- a lead that opened with "just checking options" (turn 1)
    # and later gave a concrete budget (turn 2) should explain itself with
    # "gave a concrete budget", not a self-contradictory mix of that AND
    # "just looking", even though `just_browsing` is still True in the
    # accumulated signals. See merge_signals() in this module for why
    # boolean signals accumulate rather than reset.
    if has_barrier:
        classification = IntentClassification.WARM
        reasons = warm_reasons + [r for r in hot_reasons]  # HOT-leaning context is still relevant alongside the barrier
    elif hot_score >= _HOT_THRESHOLD:
        classification = IntentClassification.HOT
        reasons = hot_reasons
    elif has_engagement:
        classification = IntentClassification.WARM
        reasons = hot_reasons + warm_reasons
    else:
        classification = IntentClassification.COLD
        reasons = cold_reasons

    if not reasons:
        reasons = ["no strong buying or disqualifying signals detected yet"]

    dominant_score = max(hot_score, warm_score, cold_score, 1)
    confidence = min(0.5 + 0.08 * dominant_score, 0.97)

    return IntentResult(
        classification=classification,
        confidence=round(confidence, 2),
        signals=reasons,
        hot_score=hot_score,
        warm_score=warm_score,
        cold_score=cold_score,
    )
