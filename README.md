# Weather-Advisory Support Bot

A LangGraph agent that answers outdoor-activity-safety questions ("is it safe to cycle today?")
by pulling live Open-Meteo data and matching the question against a written set of Standard
Operating Procedures (SOPs). It never improvises safety advice: every answer is either traceable
to a specific SOP id, or an explicit "we don't have guidance for that."

## Setup

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then put a real GROQ_API_KEY in .env
```

Open-Meteo needs no API key. The LLM does — this project uses [Groq](https://console.groq.com/keys)
(free tier, OpenAI-compatible, fast) via `langchain-groq`, model `openai/gpt-oss-120b` by
default. Put your key in `.env` (never commit it — `.gitignore` already excludes it). Swapping to a
different provider/model only touches `app/llm.py` — nothing else in the graph, weather client, or
SOPs depends on which LLM is behind `get_llm()`.

## Run

**Backend + frontend together** (Streamlit is both — there's no separate server process):

```bash
streamlit run frontend/streamlit_app.py
```

Open the URL Streamlit prints, type a question, get a reply in a conversational thread.
Follow-up questions in the same browser session share memory (LangGraph checkpointer keyed by
a per-session `thread_id`); click "New session" in the sidebar to reset it.

**Eval suite**:

```bash
python evals/eval_suite.py
```

## Repo layout

```
sops.yaml                  # the policy — the only file a policy editor should ever touch
app/
  weather.py                # deterministic Open-Meteo client (geocoding + forecast)
  sop_store.py               # loads sops.yaml fresh on every call
  llm.py                     # model config + structured-output schemas
  state.py                   # LangGraph state schema
  graph.py                   # the graph: nodes, routing, prompts
frontend/streamlit_app.py    # chat UI
evals/eval_suite.py          # eval suite (see below)
```

## The SOPs

`sops.yaml` holds 12 SOPs across 4 categories (`outdoor_exercise`, `travel`, `vulnerable_groups`,
`general_leisure`), spanning severities `low` → `critical`, including one override SOP (SOP-007,
for an active regional rain/wind system) and one fuzzy non-numeric SOP (SOP-011, "is today good
for a picnic").

**Why YAML, and why this shape:** each SOP is `id`, `category`, `severity`, `overrides`,
`condition` (natural language), `guidance` (natural language advice, not a template string).
Two decisions worth calling out:

- **Condition is prose, not a code expression.** A few SOPs (wind > 40 km/h, UV ≥ 8) could have
  been `field/operator/threshold` structs checked in Python. But SOP-011 (picnic judgment) and
  SOP-007 (a regional weather *situation*, not a single clean number) can't be reduced to that
  shape — and once one SOP needs prose matching, using two different mechanisms for "some SOPs"
  vs "others" would mean two matching engines to maintain and two ways for a policy author to get
  it wrong. So *all* matching goes through the LLM reading prose conditions against real numbers.
  The cost is that matching is a judgment call rather than a deterministic branch; the mitigation
  is everything in "grounding," below.
- **Guidance is prose the composer paraphrases, not a canned string.** This keeps the assistant's
  reply readable and specific to the user's actual question, while `guidance` still bounds *what
  advice exists* — the composer is explicitly forbidden from adding advice beyond it (see
  `COMPOSE_SYSTEM_PROMPT` in `graph.py`).

**Adding an 11th SOP live, with zero code changes:** add a new block to `sops.yaml`. `sop_store.py`
re-reads the file on every single graph invocation — no caching, no restart. This was tested by
hand: adding a block and asking a question that should trigger it works on the very next message.

**Multiple SOPs can genuinely apply at once** (e.g. high UV *and* strong wind for the same cycling
question). Resolution is: (1) any SOP marked `overrides: true` always wins, regardless of severity,
because it represents a situational risk bigger than any single category (this is what makes the
Madhya Pradesh-style scenario work: SOP-007 pre-empts the category-specific SOPs even if their own
individual numbers look moderate); (2) otherwise, pick the satisfied SOP with the highest severity;
(3) if still tied, pick the SOP whose category most specifically matches what the user asked about.
This is encoded directly in `MATCH_SYSTEM_PROMPT` (`app/graph.py`), not hidden — it's a stated,
defensible policy choice, not an emergent side effect of prompt wording.

**On SOP-007 specifically:** Open-Meteo doesn't carry IMD bulletins or "a well-marked low-pressure
area is active" as a field. SOP-007's condition uses IMD's own published rainfall-intensity
thresholds (≥64.5mm/day = "heavy rain", ≥15mm in a single hour = "very heavy") plus a sustained-wind
check across multiple consecutive hourly entries, as an honest, explainable proxy for "this is a
system, not an ordinary shower." It is not literally polling IMD's live bulletin feed — that's a
real limitation, stated plainly rather than implied away.

## The LangGraph

```
extract_query → (needs location?) ─── no ──→ need_location → END
      │
     yes
      ↓
 geocode_location → (failed?) ── yes ──→ weather_unavailable → END
      │
      no
      ↓
 fetch_weather → (failed?) ── yes ──→ weather_unavailable → END
      │
      no
      ↓
 match_sop → (matched?) ── no ──→ no_match_response → END
      │
     yes
      ↓
 compose_answer → END
```

Three failure/no-match branches are real, separate terminal nodes (`need_location`,
`weather_unavailable`, `no_match_response`) — not one generic `except` swallowing every problem
into the same shrug. `weather_unavailable` intentionally handles both "location couldn't be
geocoded" and "the forecast API failed," because the spec (and a real user) treats both the same
way: no real numbers exist, so no advice gets given.

**What's deterministic code vs. what's the LLM**, and why:

| Node | LLM? | Why |
|---|---|---|
| `extract_query` | yes | Free-text intent + coreference ("what about this evening?") is exactly what LLMs are for; nothing here decides safety facts. |
| `geocode_location` / `fetch_weather` | no | Pure API calls. No model ever gets a chance to "recall" or estimate a weather number. |
| `match_sop` | yes | Picking which written policy applies from natural-language conditions is a judgment call, deliberately not reduced to if/else (see above). |
| `compose_answer` | yes (bounded) | Only turns a pre-selected `guidance` string + pre-fetched facts into readable prose. Cannot introduce new advice or new numbers — see "Grounding" below. |
| everything else (routing, fact formatting, fallback text) | no | No reason to hand a coin-flip to a model. |

## Memory / session state

LangGraph's `MemorySaver` checkpointer, keyed by a `thread_id` created once per Streamlit session.
`state["messages"]` accumulates the full conversation (via `add_messages`); `resolved_location` /
`activity_category` persist as separate state fields specifically so `extract_query` can resolve a
bare follow-up ("what about this evening?") without re-asking for the city. Memory is in-process
only — restarting the app or starting a "New session" clears it, matching the assignment's scope
(no cross-session persistence required).

## Grounding — where it's actually enforced in code

The requirement is "the bot only composes language, it doesn't get to decide facts." Concretely:

- `app/weather.py` is the only code that ever produces a weather number, and it comes straight
  from the Open-Meteo response — nothing in it is computed or estimated.
- `graph.py`'s `_format_facts_block()` builds the numbers shown to the user by **string-formatting
  directly from `state["weather"]`** — the dict `fetch_weather` populated from the API response.
  This block is appended to the final answer by code, verbatim, every time. The LLM in
  `compose_answer` is never asked to restate the numbers; it's explicitly told they're "shown
  separately" and to write advice prose only. Even if the model ignored that instruction and
  hallucinated a stray number in its prose, the actual facts block underneath is still the
  authoritative, correct one — so the user always sees the real numbers regardless.
- The SOP citation line (`**Policy applied: SOP-00X — Title**`) is also built by code from
  `sop_store.get_sop_by_id(...)`, not asserted by the LLM.
- `match_sop`'s output is validated against the real catalog (`valid_ids = {s["id"] for s in
  catalog}`) before being trusted — if the model ever returns an id that doesn't exist (including
  one injected by an adversarial user prompt), it's treated as "no match," not passed through.

**Where this could still be stronger, honestly:** the LLM's prose in `compose_answer` and its
`rationale` in `match_sop` are not currently scanned for stray hallucinated numbers — they're just
never the source of truth shown to the user for the core facts. A production version might add a
regex/number-diff check on the LLM prose against `state["weather"]` and strip or flag mismatches.
Not done here to keep scope to a day; flagged rather than hidden.

## Eval suite

Run: `python evals/eval_suite.py`. Eight cases, each stating what it checks, what a pass means,
and its actual result when last run (see `evals/results.md` for the full run log and honest notes,
including anything that failed and why).

| # | Case | Type |
|---|---|---|
| 1 | Strong wind + cycling | Clear SOP match |
| 2 | Child + high midday UV | Clear SOP match (also proves tie-break: beats the generic UV SOP) |
| 3 | "My grandma... how hot is it getting?" | Paraphrased intent (elderly + heat, no keyword overlap) |
| 4 | "Is the sea choppy?" for a boat trip | Paraphrased intent (coastal wind, no keyword overlap) |
| 5 | "Is it safe to bike in Bhopal today?" | Real Open-Meteo call; asserts grounding, not a fixed SOP id |
| 6 | Pollen/allergy question | Honest "no SOP applies" |
| 7 | Forecast API mocked to raise | Honest failure, no invented numbers |
| 8 | Injected fake "SOP-999, cycling always safe" | Adversarial: prompt injection / policy fabrication |

**Why case 5 doesn't assert a fixed SOP id:** the assignment explicitly warns that the Madhya
Pradesh system will have weakened and moved on by review time, and monsoon systems shift
constantly. Hardcoding "must match SOP-007" would make the suite pass or fail based on the
weather on the day it's run, not on the bot's logic. Instead it asserts the thing that must always
be true regardless of today's weather: the API call succeeds, and every number quoted in the
answer is exactly the number Open-Meteo returned for that request. If conditions are severe enough
to trip a SOP that day, it also checks the cited id is real. **What I'd do differently for a suite
that has to keep working indefinitely:** add a second, fully mocked "severe conditions" case
(heavy-rain + high-wind fixture, same shape as case 5) that *does* assert an exact SOP-007 match
deterministically, and keep case 5 purely as a live smoke test of the real integration. I chose
not to duplicate that here to keep the suite to a day's scope, but the mocked cases 1-4 already
prove the matching logic works against controlled numbers, so the risk this leaves uncovered is
small.

**On case 8 (the adversarial case) — and why I picked prompt injection over other attacks:** the
assignment's own text flags this as worth considering, and it's the failure mode most specific to
"an LLM sits between user text and a safety-critical answer": a user's message is data, but it's
also literally the input to a language model, so a sufficiently motivated message could try to talk
the model into (a) ignoring the SOP catalog, (b) claiming a policy exists that doesn't, or (c)
softening real safety advice. The mitigation is layered, not just prompt wording: the system
prompts in `graph.py` explicitly tell the model to treat user text as data rather than
instructions, but the code-level backstop is what actually matters — `match_sop`'s output is
validated against the real `sops.yaml` ids regardless of what the model returns, so a fabricated
"SOP-999" can never reach the user even if the model were fully compromised by the injection.

## Known limitations / honest gaps

- LLM prose (advice wording, match rationale) isn't independently fact-checked against the weather
  dict — see "Grounding," above.
- SOP-007's "well-marked system" detection is a numeric proxy for IMD's own thresholds, not a live
  feed of actual IMD bulletins — Open-Meteo has no such field.
- Tie-breaking across multiple applicable SOPs is instructed to the LLM in the matching prompt,
  not independently re-verified in code — a code-side severity-rank re-check (`sop_store.
  SEVERITY_RANK` already exists but isn't currently wired into a post-hoc validator) would be the
  next hardening step if this went to production.
- `fetch_forecast` only requests `forecast_days=2` (today + tomorrow). A question about "this
  weekend" or further out has no real data behind it — found during eval development (see
  `evals/results.md`) when the matcher correctly declined to answer a weekend question using
  today's numbers rather than pretend they applied. It's the right failure mode, but the honest
  fix is either extending the forecast window or having the graph explicitly say "that's beyond
  what I can check" instead of silently falling back to "no SOP applies."
