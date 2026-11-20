# Assignment Compliance Audit

Audited directly against `ElevateBox_SDE_Intern_Assignment.pdf`, Sections 02 ("What your system
must do") and 05 ("How we score it"). Every row below was checked against the actual repository
state at audit time, not against what was planned.

**Status definitions used throughout:**
- **COMPLETE** -- implemented AND verified by a passing local test or an executed script, evidence
  cited.
- **PARTIAL** -- implemented, but either not fully exercised locally or depends on something
  (naturalness, live timing) that only a real call can prove.
- **BLOCKED** -- cannot be executed at all in this environment; requires a credential, account, or
  network access this sandbox does not have. Blocked items are implemented in code unless stated
  otherwise.

## Section 02 -- What your system must do

| # | Requirement | Implementation | Evidence | Status |
|---|---|---|---|---|
| 1 | Place the call. "Your system dials 8688664337 by itself. No manual dialling, no you on the line." | `OmniDimensionClient.dispatch_call` implements the documented dispatch request shape; `POST /calls/trigger` defaults to `EVALUATOR_PHONE_E164=+918688664337`. `MockVoiceProviderClient` is used when no API key is configured. | `app/telephony/voice_provider_client.py`; smoke-tested via `POST /calls/trigger` against the mock in the TestClient run | **PARTIAL** -- dispatch call path is implemented and exercised against the mock; a real call requires `OMNIDIMENSION_API_KEY` and has not been placed |
| 2 | Speak the language. "Telugu, Hindi or English. Handle whichever one I answer in, and stay in it." | Persona system prompt explicitly instructs starting in whatever language the customer answers in and staying in it, including code-switching tolerance. OmniDimension is the platform providing the actual multilingual STT/TTS. | `app/conversation/persona.py: SYSTEM_PROMPT` | **BLOCKED** -- prompt is written; actual multilingual behavior can only be verified on a live call |
| 3 | Sell the service. "Pitch e-commerce website development like a person would, not like a recorded message." | Persona instructs short spoken sentences, no monologues, acknowledging answers, avoiding call-center phrasing. | `app/conversation/persona.py` | **BLOCKED** -- same reason as #2 |
| 4 | Ask the right questions. "Budget, what I sell, how many products, timeline, features I need. Ask them naturally, not as a form." | Discovery flow is written into the persona as progressive, non-questionnaire style; the fields themselves are captured via the `update_lead_signals` tool, which the LLM is instructed to call after every qualifying turn, not on a fixed schedule. | `app/conversation/persona.py`, `app/decision/signal_schema.py` | **PARTIAL** -- the mechanism (tool schema + instructions) is complete and unit-tested for correctness of what happens once data arrives; naturalness of the actual question flow is unverifiable without a live call |
| 5 | Understand the answers. "Parse what I actually said, including when I am vague, and classify me as Hot, Warm or Cold." | Deterministic classifier (`classify_lead`) scored directly off the assignment's own HOT/WARM/COLD definitions and example phrases; signals accumulate across the whole call via `merge_signals`, not just the latest turn. | `app/decision/classifier.py`; `tests/test_classifier.py` (5 tests, using the PDF's own examples verbatim); `tests/test_cumulative_signals_regression.py` (11 tests) | **COMPLETE** -- 62/62 total suite passing at last run, this module's tests included |
| 6 | Act during the call. "If I show high buying intent, a WhatsApp message reaches me before the call ends. Mid call, not after." | `apply_turn()` sends the mid-call WhatsApp the instant classification reads HOT, before returning control to the (simulated) live call; idempotency-guarded against duplicate triggers. | `app/services/call_orchestrator.py`; `tests/test_orchestrator.py::test_hot_turn_fires_midcall_whatsapp_exactly_once` | **COMPLETE** logic, verified against the mock WhatsApp client / **BLOCKED** for an actual delivered message (needs `WHATSAPP_ACCESS_TOKEN` + an approved template) |
| 7 | Schedule from speech. "If I say call me back tomorrow morning, your system understands it and books the callback itself." | `parse_callback_phrase` resolves English/Hindi/Telugu phrases deterministically to `Asia/Kolkata` datetimes; `schedule_callback_from_phrase` validates and persists. A real bug (a third-party parser silently reading "4" in "Friday at 4" as April 2027) was caught and fixed with a from-scratch deterministic date/time resolver. | `app/scheduler/time_parser.py`, `app/scheduler/callback_service.py`; `tests/test_time_parser.py` (13 tests); `tests/test_callback_service.py` (6 tests) | **COMPLETE** -- verified, including the two WARM simulation scenarios which schedule real callbacks from "next week" and "kal subah" |
| 8 | Follow up smartly. "The follow up references what I actually said, not a template with my name pasted in." | `build_followup_whatsapp_message` pulls business type, product count, budget, timeline, features, barriers, and a verbatim quote from `LeadState`; tests assert the actual captured values appear in the output and that two different leads produce different messages. | `app/whatsapp/payload_builder.py`; `tests/test_whatsapp_payload.py` (7 tests) | **COMPLETE** -- verified via passing tests and real generated text from `scripts/simulate_call.py` |
| 9 | Send yourself, with context. "A WhatsApp message carrying the full context of what we actually discussed, your resume, your mobile number, and an image showing how you built it." | Follow-up message (context + framing) is complete and tested. `MetaCloudAPIWhatsAppClient.send_template_message` supports a document header (resume) and image header (architecture diagram) in the request shape, per Meta's documented Cloud API. `AGENT_PHONE` is injected via config, never hardcoded. | `app/whatsapp/payload_builder.py`, `app/whatsapp/client.py`, `.env.example: RESUME_URL / ARCHITECTURE_IMAGE_URL` | **PARTIAL** -- message content and client code are complete; no resume file was ever supplied in this conversation, so `RESUME_URL` is empty and nothing has actually been sent (also blocked on `WHATSAPP_ACCESS_TOKEN` + template approval) |
| 10 | Work. "If it works, I call you back. That is the whole selection process." | -- | -- | **NOT YET** -- depends on #1, #2, #3, #6, #9 all happening live, which requires deployment and credentials outside this environment; see README "What Requires External Credentials" |

## Section 05 -- Scorecard self-assessment

This section maps to the published scorecard categories. Points are ElevateBox's to award, not
mine to claim -- this is an honest accounting of what's demonstrable **today, in this repository,
without a live call** versus what genuinely needs one.

| Category | Points | Demonstrable today (offline) | Requires a live call |
|---|---|---|---|
| It calls and holds a conversation | 25 | Call dispatch code path runs against the mock and is unit-tested; conversation content itself cannot be demonstrated offline | Yes -- this entire category is fundamentally about a real, live exchange |
| Language handling | 10 | Persona instructions written and reviewed | Yes -- multilingual behavior is unverifiable without OmniDimension actually running STT/TTS |
| Discovery quality | 10 | Tool schema + persona instructions written; the "what happens with captured data" half is fully tested | Partially -- naturalness of the actual question sequence needs a live call |
| Intent classification | 15 | Fully deterministic, tested against every HOT/WARM/COLD example in the PDF plus 6 cumulative-signal regression scenarios | No -- this logic runs identically whether the signals came from a live call or a test fixture |
| Mid-call action | 15 | Trigger logic, idempotency, and message content are fully tested against a mock WhatsApp client | Yes, for the literal "message reaches me before the call ends" part -- needs a real send |
| Callback scheduling | 10 | Fully deterministic, tested including two real EN/HI simulation runs | No -- same reasoning as intent classification |
| Follow-up and WhatsApp quality | 10 | Message generation fully tested; the 4-required-parts payload structure is implemented | Partially -- actual delivery, and the resume attachment specifically, are blocked (see below) |
| Engineering judgement | 5 | Architecture documented and justified; two real bugs found via testing/simulation and fixed with regression tests, not papered over; failure handling, idempotency, and observability all in place | No -- this category is judged from the artifact itself |

**Honest read:** the two purely-logic categories (Intent classification, Callback scheduling -- 25
of 100 points) plus Engineering judgement (5 points) are the ones this repository can actually make
a strong, evidenced claim on right now. The remaining 70 points are either fully or partially gated
on a live call happening, which this environment cannot do (see below).

## Why a live call could not be executed here

This system was built inside a sandboxed container whose network access is limited to package
registries (PyPI, npm, GitHub, crates.io, etc.) -- it has no route to `api.omnidim.io`,
`graph.facebook.com`, or any telephony/WhatsApp provider. Separately, no API credentials for any of
these providers were provided. Both conditions would need to be true to place a real call, and
neither is: this is a hard infrastructure limitation, not a decision to skip it. The repository is
structured so that supplying credentials and deploying (see README "External Provider Setup") is
the only remaining step -- no code changes should be needed to go live.

## What was NOT implemented at all (not even blocked -- genuinely absent)

- No resume file was ever supplied in this conversation, so there is no resume content to attach.
  `RESUME_URL` in `.env.example` is a placeholder for wherever a real resume gets hosted.
- No actual deployment was attempted (would require the user's own hosting account).
- Docker build was not executed (Docker is not installed in this sandbox) -- the Dockerfile and
  docker-compose.yml are written against standard, unremarkable patterns but are unverified.
- A production-grade multi-worker idempotency mechanism (DB-level unique constraint) was not built
  -- the current in-process guard is correct for the single-worker scope this assignment implies,
  and the gap is documented, not silently absent.
