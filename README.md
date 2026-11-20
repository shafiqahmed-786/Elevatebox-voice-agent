# ElevateBox Voice AI Agent

An AI voice sales agent for the ElevateBox SDE Intern assignment: it's meant to call a customer,
sell e-commerce website development in Telugu/Hindi/English, qualify the lead, fire a WhatsApp
mid-call on high intent, book callbacks from natural speech, and follow up with real conversation
content.

<img width="2179" height="1679" alt="image" src="https://github.com/user-attachments/assets/cb9e21e1-c316-4200-8911-3d7f7535cde5" />



**Read this first:** this README distinguishes **VERIFIED LOCALLY** (I ran it, here's the output)
from **REQUIRES EXTERNAL CREDENTIALS** (written correctly, cannot be exercised without an account
I don't have access to). No claim below says a real phone call or a real WhatsApp message was sent,
because neither has happened yet -- see "What Requires External Credentials".

## What I Built

A FastAPI backend that is the "brain" behind an OmniDimension voice agent:

- **Decision engine** -- deterministic HOT/WARM/COLD classification from structured signals, with
  scoring rules traceable directly to the assignment's own definitions and examples.
- **Cumulative signal tracking** -- classification reflects everything said across the whole call,
  not just the latest turn (this was a real bug I found and fixed during development -- see below).
- **Callback parser** -- turns "tomorrow morning" / "Friday at 4" / "kal subah" / "next Tuesday
  evening" into concrete `Asia/Kolkata` datetimes, deterministically, with every assumption logged.
- **WhatsApp message generation** -- mid-call and follow-up messages built from structured lead
  state, so they reference what the customer actually said instead of a generic template.
- **Idempotency** -- duplicate mid-call triggers, duplicate callback requests, and concurrent
  webhook deliveries cannot cause duplicate WhatsApp sends or duplicate callbacks.
- **Malformed-LLM-output safety** -- the extraction layer never crashes on bad tool-call input; it
  salvages whatever fields are valid and logs what it dropped.
- **A real, runnable offline simulation** (`scripts/simulate_call.py`) that drives the entire
  pipeline -- extraction contract, classification, mid-call WhatsApp, callback scheduling,
  follow-up generation -- with no external credentials, so the logic can be demonstrated end to end
  right now.

## Assignment Requirements -> Implementation Mapping

| # | Requirement (from the PDF) | Implementation | File / Module | Status |
|---|---|---|---|---|
| 1 | Place the call, on its own | `OmniDimensionClient.dispatch_call` (real API shape) + mock for local runs | `app/telephony/voice_provider_client.py` | **PARTIAL** -- code complete; live dispatch needs `OMNIDIMENSION_API_KEY` |
| 2 | Speak Telugu, Hindi, or English; stay in it | Agent persona instructs language-matching; OmniDimension provides the multilingual STT/TTS | `app/conversation/persona.py` | **BLOCKED** -- requires a live call to verify |
| 3 | Sell e-commerce website development like a person | Persona instructions (tone, pacing, no menu-style questions) | `app/conversation/persona.py` | **BLOCKED** -- requires a live call to verify |
| 4 | Ask budget, products, timeline, features naturally | Discovery flow encoded in persona; captured via `update_lead_signals` tool | `app/conversation/persona.py`, `app/decision/signal_schema.py` | **PARTIAL** -- schema + prompt done; naturalness only provable live |
| 5 | Understand vague/indirect answers, classify HOT/WARM/COLD | Deterministic scoring engine, tested against the PDF's own example phrases | `app/decision/classifier.py`, `tests/test_classifier.py` | **COMPLETE** -- verified, 62/62 tests passing locally |
| 6 | Fire WhatsApp mid-call on high intent | `apply_turn()` sends on first HOT classification, idempotency-guarded | `app/services/call_orchestrator.py`, `tests/test_orchestrator.py` | **COMPLETE** logic / **BLOCKED** live send (no `WHATSAPP_ACCESS_TOKEN`) |
| 7 | Book a callback from spoken time, any language | Deterministic date/time resolver, EN/HI/TE phrase table | `app/scheduler/time_parser.py`, `tests/test_time_parser.py` | **COMPLETE** -- verified, 13/13 tests passing, incl. a caught-and-fixed real bug |
| 8 | Follow-up references what was actually said | Template pulls business type, budget, timeline, features, barriers, a verbatim quote | `app/whatsapp/payload_builder.py`, `tests/test_whatsapp_payload.py` | **COMPLETE** -- verified via tests asserting real content appears |
| 9 | Send WhatsApp with context + resume + number + architecture image | Follow-up message + `MetaCloudAPIWhatsAppClient.send_template_message` (document/image header support) | `app/whatsapp/client.py`, `app/whatsapp/payload_builder.py` | **PARTIAL** -- message generation complete; resume file was never supplied, no `WHATSAPP_ACCESS_TOKEN` to actually send |
| 10 | It works, end to end, live | -- | -- | **NOT YET** -- see "What Requires External Credentials" |

Scorecard-relevant extras built beyond the minimum:

| Area | What's there |
|---|---|
| Robustness against malformed LLM output | `app/conversation/extraction.py` -- never raises, salvages field-by-field, logs drops |
| Code-switching (Hinglish/Tenglish) | Persona explicitly instructs tolerance; callback parser handles Hindi/Telugu phrases directly |
| Observability | Every business-logic log line is `call_id`-prefixed; see `app/logging_config.py` |
| Failure handling | WhatsApp/telephony provider failures never raise past the caller; see "Failure Handling" below |

## Architecture

```
Evaluator's phone
      |
OmniDimension  (outbound dispatch, STT, conversational LLM, TTS, barge-in)
      |
Custom API actions (tool calls, mid-call): update_lead_signals / schedule_callback / trigger_midcall_whatsapp
      |
FastAPI backend (this repo)
      |  webhooks -> extraction validation -> cumulative signal merge -> deterministic decision engine
      |
   +--+------------------+------------------+
   |                     |                  |
WhatsApp client   Callback scheduler   Claude (Anthropic API)
(Meta Cloud API)  (EN/HI/TE parser,    (extraction fallback +
                   Asia/Kolkata)        follow-up polish, optional)
   |                     |                  |
   +---------------------+------------------+
                          |
        PostgreSQL (SQLite locally) via async SQLAlchemy
        Call / Lead (LeadState as JSONB) / ConversationTurn /
        ScheduledCallback / OutboundAction
```

See `docs/architecture.png` for the rendered version (this is the image sent as part of the
WhatsApp payload, per requirement #9).

**Why this shape:** OmniDimension bundles telephony + STT + the live conversational LLM + TTS +
barge-in into one platform, which directly addresses the assignment's own stated hard part
("if the reply takes three seconds, the conversation is dead") -- there's no hand-rolled
STT-then-LLM-then-TTS relay adding sequential network hops on the live path. Our backend only
gets involved for things that must be deterministic and auditable: classification, callback
parsing, and the WhatsApp payload -- exactly the split the assignment asks for ("do not make the
LLM responsible for everything").

## Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Voice / telephony / STT / TTS | **OmniDimension** | Suggested by the assignment; confirmed (via current docs) to offer outbound dispatch, 90+ languages, SIP trunk import (Twilio/Exotel) for Indian numbers, and "Custom API" mid-call tool calling -- one platform instead of four |
| WhatsApp | **Meta WhatsApp Business Cloud API**, called directly from our backend | Full control over the exact 4-part payload (context, framing, number, image) the assignment requires, rather than relying on a platform's generic delivery |
| Backend | **FastAPI**, async | Assignment's own suggestion; async matters for webhook responsiveness under a live call |
| Persistence | **PostgreSQL** (prod) / **SQLite** (local dev), via **SQLAlchemy 2.0 async** | One JSONB column (`Lead.state_json`) holding the full `LeadState` -- schema stayed fluid during development, a JSON blob meant no migration per new field discovered |
| LLM (extraction fallback / follow-up polish) | **Claude** (`claude-haiku-4-5` for latency-sensitive paths, `claude-sonnet-5` off the hot path) | Not on the live-call latency path -- OmniDimension's own configured LLM handles turn-by-turn conversation |
| Scheduling | Lightweight in-process polling loop, no queue | Assignment's own guidance: "Redis/background jobs only if genuinely useful" -- a callback backlog of dozens of leads doesn't need one |

## Project Structure

```
app/
  api/            FastAPI routes (calls, webhooks, health) + dependency wiring
  conversation/   Persona/system prompt, Claude-based extraction, malformed-output safety
  decision/       Deterministic classifier, signal merge logic, tool schema
  models/         Pydantic schemas (LeadState etc.) + SQLAlchemy models
  scheduler/      Callback time parser + scheduling service
  services/       Orchestrator (ties extraction -> decision -> actions), idempotency, DB repository
  telephony/      OmniDimension client (real + mock)
  whatsapp/       Meta Cloud API client (real + mock) + message generation
  config.py       All settings, one place, startup credential reporting
  db.py           Async SQLAlchemy session/engine
  main.py         FastAPI app + background callback poller
tests/            62 tests: unit + integration, see "Running Tests"
scripts/
  simulate_call.py                 end-to-end offline demo (see below)
  _render_architecture_diagram.py  regenerates docs/architecture.png
docs/
  architecture.png             rendered diagram
  assignment-compliance.md     line-by-line rubric audit
```

## Setup

```bash
git clone <this-repo>
cd elevatebox-voice-agent
pip install -r requirements.txt
cp .env.example .env        # fill in credentials as you get them -- see "Environment Variables"
```

No credentials are required to run the app, the tests, or the simulation -- everything degrades to
mock adapters automatically (see `app/config.py: has_live_*` properties).

## Environment Variables

Full documented list in `.env.example`. Summary:

| Variable | Required for | Where to get it |
|---|---|---|
| `DATABASE_URL` | Persistence | Defaults to local SQLite; set to a Postgres DSN for production |
| `OMNIDIMENSION_API_KEY`, `OMNIDIMENSION_AGENT_ID` | Live outbound calls | omnidim.io dashboard |
| `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID` | Live WhatsApp delivery | developers.facebook.com -> your App -> WhatsApp |
| `ANTHROPIC_API_KEY` | Live extraction/follow-up-polish LLM calls | console.anthropic.com |
| `RESUME_URL` | The resume attachment in the final WhatsApp | Host your resume PDF publicly, put the link here -- **no resume file was provided when this repo was built, so this is empty** |
| `ARCHITECTURE_IMAGE_URL` | The architecture-image attachment | Host `docs/architecture.png` publicly once deployed |
| `EVALUATOR_PHONE_E164` | Which number gets called | Already set to `+918688664337` (from the assignment PDF) |

Startup never crashes on a missing credential -- `/health` reports exactly which integrations are
live vs. mock (see "API Endpoints").

## Local Development

```bash
uvicorn app.main:app --reload
curl localhost:8000/health
```

`/health` returns something like:
```json
{"status": "ok", "credentials": {"omnidimension_live": false, "whatsapp_live": false, "llm_live": false, "database_configured": true}}
```

## Running Tests

```bash
pytest -q
```

**Verified locally: 62 passed, 0 failed** (see the final run at the bottom of this README / the
final report for the exact count as of the last change). Covers the classifier (against the PDF's
own HOT/WARM/COLD examples), the callback parser (English/Hindi/Telugu, including a regression test
for a real bug -- see below), malformed-extraction safety, idempotency (including a genuine
concurrent-request race test), the WhatsApp message generator, and integration tests that exercise
the full webhook -> extraction -> decision -> action pipeline through the real orchestrator.

## Running the Simulation

```bash
python scripts/simulate_call.py                       # all 4 scenarios, offline, no credentials
python scripts/simulate_call.py --scenario hot         # just one
python scripts/simulate_call.py --llm                  # use real Claude extraction (needs ANTHROPIC_API_KEY)
```

This runs realistic multi-turn conversations (HOT, WARM-with-budget-barrier, WARM-with-approval-
barrier, COLD) through the exact same `apply_turn` / `finalize_call` functions the live webhooks
call -- not a separate demo path. It prints the classification after every turn, exactly which
actions fired, the real generated WhatsApp text, and the final structured lead state. The two WARM
scenarios also exercise real callback scheduling in English and Hindi.

Last verified run:
```
hot                      classification=HOT   whatsapp_sent=2 callback=False
warm_budget_barrier      classification=WARM  whatsapp_sent=1 callback=True
warm_approval_barrier    classification=WARM  whatsapp_sent=1 callback=True
cold                     classification=COLD  whatsapp_sent=1 callback=False
```

## External Provider Setup

### OmniDimension Setup
1. Create an account and agent at omnidim.io.
2. Configure the agent's system instructions using `app/conversation/persona.py: SYSTEM_PROMPT`
   as the source of truth.
3. Register three "Custom API" actions pointing at this backend's webhook endpoints (once deployed
   and `PUBLIC_BASE_URL` is set): `update_lead_signals` -> `POST /webhooks/voice/signals`,
   `schedule_callback` -> `POST /webhooks/voice/callback`. Tool schemas are in
   `app/decision/signal_schema.py` -- copy them in verbatim.
4. Register a call-ended webhook -> `POST /webhooks/voice/call-ended`.
5. Provision an outbound number. For India, either use an OmniDimension-provided number or import
   one via SIP trunk (Twilio/Exotel/RingCentral, per their docs) -- not verified against a live
   account in this environment.
6. Put the API key and agent ID in `.env`.

### WhatsApp Setup
1. Create a Meta developer app with the WhatsApp product at developers.facebook.com.
2. Every message this system sends is **business-initiated** (the evaluator calls us; they haven't
   messaged our WhatsApp number first), which means Meta requires a **pre-approved message
   template** -- a free-form text message will be rejected outside a 24-hour customer-service
   window. Create two templates in Meta's Template Manager: one with a text body for the mid-call
   message, one with a document header (for the resume) + image header (for the architecture
   diagram) + text body for the follow-up. Submission for a utility-category template is typically
   reviewed quickly, but this is a real, non-automatable setup step with its own lead time.
3. Put the access token, phone number ID, and your template names in `.env`.
4. `RESUME_URL` and `ARCHITECTURE_IMAGE_URL` must be publicly reachable URLs (Meta fetches media by
   URL) -- host your resume PDF and `docs/architecture.png` somewhere public first.

### Webhook Setup
Deploy this backend somewhere with a public HTTPS URL (Railway/Render/Fly.io all work fine with the
provided `Dockerfile`), set `PUBLIC_BASE_URL`, then point OmniDimension's Custom API actions and
call-ended webhook at `{PUBLIC_BASE_URL}/webhooks/voice/...` as above.

## Example Flow

1. `POST /calls/trigger` (or a scheduled callback firing) dispatches an outbound call.
2. OmniDimension calls the evaluator, has the conversation, and calls our `update_lead_signals`
   Custom API action after each qualifying turn.
3. `POST /webhooks/voice/signals` validates the payload defensively, merges it into
   `lead.cumulative_signals`, re-runs the deterministic classifier, and -- the moment the lead
   reads HOT -- sends the mid-call WhatsApp, all before responding back to the live call.
4. If the customer names a callback time, `POST /webhooks/voice/callback` parses it deterministically
   and schedules it.
5. `POST /webhooks/voice/call-ended` sends the final follow-up (content depends on final
   classification: full recap for HOT/WARM, a soft brochure note for COLD).
6. A background poller (`app/main.py: _due_callback_poller`) checks every 60s for callbacks whose
   time has arrived and re-dispatches a call.

Run `python scripts/simulate_call.py` to see this whole flow, with real generated text, right now.

## API Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness + which integrations are live vs. mock |
| POST | `/calls/trigger` | Dispatch an outbound call (defaults to the assignment's evaluator number) |
| GET | `/calls/{call_id}` | Full current `LeadState` for a call -- the single-call-ID debug view |
| POST | `/webhooks/voice/signals` | OmniDimension Custom API action: new extracted signals |
| POST | `/webhooks/voice/callback` | OmniDimension Custom API action: a callback phrase was said |
| POST | `/webhooks/voice/call-ended` | OmniDimension webhook: call finished, send the follow-up |

## Design Decisions

- **One accumulated signal object, not two.** An earlier version accumulated `LeadState.budget_inr`
  etc. directly, separately from what the classifier saw -- which is exactly the bug described
  below. `LeadState.cumulative_signals` is now the single source of truth; the display fields
  (`budget_inr`, `barriers`, ...) are derived from it every turn, not maintained in parallel.
- **Deterministic message generation, not an LLM call, for anything scored.** The mid-call and
  follow-up WhatsApp text come from a template function, not a Claude call, specifically so an LLM
  outage can never be the reason a scored action doesn't fire (see "Failure Handling"). An optional
  LLM "polish" pass exists but always falls back to the deterministic draft unchanged on any error.
- **A real bug found and fixed during development, worth stating explicitly:** the classifier was
  initially called with only the current turn's signals. A neutral or unrelated later turn (e.g.
  "call me next week") would silently overwrite earlier HOT/WARM evidence, regressing the
  classification mid-call -- caught by running the offline simulation, not by unit tests alone
  (each turn's classifier call was individually correct; the bug was only visible across turns).
  Fixed via `merge_signals()` (`app/decision/classifier.py`) with field-specific semantics: boolean
  signals accumulate (once true, stays true), lists union, scalars take the latest *meaningful*
  value (an explicit `False` counts; `None`/empty does not). Regression tests for six specific
  scenarios are in `tests/test_cumulative_signals_regression.py`.
- **A second, related bug from the same audit:** `business_type`, `sells_online_currently`,
  `product_count`, and `decision_maker` -- 4 of the assignment's 8 required discovery fields --
  were declared in the tool schema exposed to the voice platform but had no matching fields on
  `ExtractedSignals`, so a well-formed tool call naming them would be silently dropped before ever
  reaching `LeadState`. Fixed by adding the fields and the `timeline` -> `concrete_timeline` rename
  that was similarly missing (`budget_inr`/`features` already had equivalent renames; `timeline`
  didn't). Covered by `tests/test_extraction.py::test_all_tool_schema_discovery_fields_survive_extraction`.

## Reliability / Idempotency

- Mid-call WhatsApp, follow-up WhatsApp, and callback creation each go through a compare-and-set
  claim (`app/services/idempotency.py`) checked *before* the send happens, so two near-simultaneous
  triggers (a retried webhook, the LLM calling `trigger_midcall_whatsapp` twice) can't both succeed.
  Tested under real `asyncio.gather` concurrency in `tests/test_idempotency.py`.
- A failed WhatsApp send rolls the claim back to `FAILED` (not `SENT`), so a later turn can retry --
  a transient provider failure doesn't permanently block the message.
- Scope: the guard is in-process (matches the assignment's "modular monolith" guidance and a
  single-worker deployment). A multi-worker production deployment would need a DB-level unique
  constraint doing the same job at the row level -- noted here rather than built, since it's outside
  this assignment's actual scale.

## Failure Handling

| Failure | Behaviour |
|---|---|
| Malformed/wrong-typed LLM tool-call output | Salvaged field-by-field; bad fields dropped and logged, never raises (`app/conversation/extraction.py`) |
| WhatsApp send fails (timeout, 4xx/5xx, transport error) | Caught, logged with the call ID, recorded on the lead as `FAILED`, live conversation is never interrupted |
| Telephony dispatch fails | Returns a structured failure, never raises; caller gets a clean `dispatched: false` |
| LLM (Claude) call fails, for extraction or follow-up polish | Extraction returns empty signals (nothing is guessed); follow-up polish falls back to the deterministic draft, unchanged |
| Callback phrase can't be parsed at all | Never crashes -- falls back to next-day 10:00 IST with `confidence <= 0.4` and an explicit note to confirm with the customer |
| Callback resolves to a past datetime (parser bug / clock drift) | Rejected with `InvalidCallbackError` rather than silently scheduled |
| Duplicate webhook delivery | Idempotency guard rejects the second claim; see above |
| Unknown `call_id` on any webhook | `404`, not a crash |
| Any unhandled exception inside a webhook handler | Caught at the route level, returns `{"ok": false, "detail": ...}` -- a bug here must never surface as a `5xx` to a live call |

## Security Considerations

- No secret has a hardcoded value anywhere in the codebase -- every credential is `None` by default
  in `app/config.py` and loaded from the environment only.
- `.env` is git-ignored; `.env.example` documents every variable with no real values.
- Error logs include the provider's error *message* only, never request headers or the token/key
  itself (see `app/whatsapp/client.py`, `app/telephony/voice_provider_client.py`).
- The evaluator's own personal information (their stated business details, budget, etc.) lives only
  in the database, never in code -- `AGENT_NAME` / `AGENT_PHONE` / `RESUME_URL` are the only
  candidate-identifying values, and those are configuration, not hardcoded business logic.

## What Requires External Credentials

Everything in this list is **implemented and code-reviewed, not exercised against the real
service**, because this build environment has no network path to any of these providers and no
credentials were available:

- An actual outbound phone call (needs `OMNIDIMENSION_API_KEY` + a deployed public webhook URL)
- An actual WhatsApp message delivered to a phone (needs `WHATSAPP_ACCESS_TOKEN` + an approved
  message template)
- Live Claude API calls for extraction/follow-up polish (needs `ANTHROPIC_API_KEY`) -- the
  deterministic paths that don't need this are fully tested and don't depend on it
- Deployment to a public HTTPS endpoint (needs your own hosting account -- Railway/Render/Fly.io
  all work with the provided `Dockerfile`; not attempted here since it would need your credentials)
- The resume attachment specifically -- no resume file was supplied when this repository was built,
  so `RESUME_URL` is empty; the WhatsApp payload code is ready for it the moment a URL is provided

Docker/docker-compose are written but **not build-tested** -- Docker isn't installed in this build
environment.

## What Was Tested Locally

- `pytest -q` -- 62/62 passing as of the last change (see the final report for the exact final
  count), including integration tests that exercise the real webhook -> extraction -> decision ->
  WhatsApp-action pipeline via the actual orchestrator functions
- `scripts/simulate_call.py` -- full offline run across 4 realistic scenarios, output inspected
  manually turn-by-turn (classification, actions fired, generated WhatsApp text, final state)
- `uvicorn`/`TestClient` smoke test -- app boots, `/health` responds, a full
  trigger -> signals -> callback -> call-ended -> get-state cycle runs correctly against the mock
  providers and a real (SQLite) database
- A concurrent-request race test proving the idempotency guard actually blocks a duplicate send
  under real `asyncio` concurrency, not just sequential calls

## Known Limitations / What I'd Build Next

- Naturalness of the live conversation, actual latency, and real STT accuracy on Telugu/Hindi/
  Hinglish can only be judged on a real call -- nothing here substitutes for that.
- The idempotency guard is in-process; a multi-worker deployment needs a DB-level constraint too.
- The barrier-always-caps-at-WARM rule is a simplification of genuinely ambiguous cases (e.g. "let
  me just check with my brother, but yes let's go ahead" has both a barrier and a clear next-step
  request) -- documented as a deliberate choice in `app/decision/classifier.py`, worth revisiting
  against real transcripts.
- `just_browsing` accumulates for the call (once said, it's on record) but no longer dominates the
  displayed reasoning once real engagement shows up later -- see the reasons-scoping logic in
  `classify_lead()`. A cleaner model would let later strong engagement actively retract it.
- Callback due-polling is O(all leads) every 60s -- fine at this scale, would need an indexed query
  or a proper scheduler at real volume.
