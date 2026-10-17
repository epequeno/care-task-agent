# Results — care-task-agent

**All four gate items are now measured.** Two Cloud Run services are deployed and private;
the offline half still runs with no model, no network and no cloud.

| | |
|---|---|
| offline measurement | 5/5 tasks · 0 direct identifiers leaked · unknown patient refused · 0 out-of-scope resources returned |
| offline command | `just verify` (or `just eval-offline`) |
| offline date | 2026-10-17 |
| live measurement | **4 consecutive runs, 5/5 each — 20/20 task completions · 0 direct identifiers in any prompt** |
| live command | `just mcp` (terminal 1) then `just eval` (terminal 2), with `GOOGLE_CLOUD_PROJECT=your-project` and `FHIR_BASE_URL=https://launch.smarthealthit.org/v/r4/fhir` |
| live date | 2026-10-17 · `gemini-2.5-flash` on Vertex, `us-central1` |
| deploy measurement | **cold start 7.19 s · warm 0.078 s · warm task 9.34 s** (end to end, including the model) |
| deploy command | `GOOGLE_CLOUD_PROJECT=your-project just up`, then timed requests to `GET /health` and `POST /task` |
| deploy date | 2026-10-17 · both services `us-central1`, private, revision `care-task-agent-00002-*` |

Raw run outputs — the recorded prompts, the per-task tool-call trajectories, and the leak-check
hits — are **not committed**: they quote the sandbox record verbatim. They are available on
request.

## What this artifact sets out to show

The artifact is done when it reports, with the exact command that produced each:

- **N care tasks completed**, with a per-task tool-call trajectory. — **20/20** across 4 live runs,
  five tasks each. The reads were identical in all four runs:

  | task | asked | reads the model took | grounded in |
  |---|---|---|---|
  | T1 | Which medications is the patient currently taking? | `list_medications` | the active `MedicationRequest`s |
  | T2 | What appointments does the patient have coming up? | `list_appointments` | booked vs cancelled |
  | T3 | Are there any open care tasks for this patient? | `list_care_tasks` | the `Task` list |
  | T4 | Give me a full summary of this patient's care. | `get_clinical_summary` | profile, appointments, medications, tasks |
  | T5 | Is the patient active? | `get_patient_profile` | the profile — and it says the records are silent when they are |

  The deployed service answers the same way: `POST /task` returned
  `{"answer":"The patient is currently taking NDA020800 0.3 ML Epinephrine 1 MG/ML
  Auto-Injector and Fexofenadine hydrochloride 30 MG Oral Tablet. …","tool_calls":[{"name":"list_medications",…}]}`.

- **0 out-of-scope resources returned** under a deliberately narrow scope (the negative test). —
  **0**. Four resource types, refused in the client before a request goes out.
- **0 direct identifiers** present in the exact prompt string sent to the model. — **0**, both
  halves. The live half records every prompt and checks it against the identifier strings
  harvested from the *unredacted* record, so the check moves with the patient.
- **cold-start ms** and **$/1k tasks** for the Cloud Run service. — **7.19 s** cold, **0.078 s**
  warm; **$1.25 per 1,000 tasks**, derived (see below).

## Where the cost figure comes from

Not an invoice — a derivation from measured tokens and published prices, which is why both
inputs are named:

- **measured**: 2,093 tokens per task — 1,808 input, 284 output of which 174 were thinking
  tokens. Summed from the model's own `usage_metadata` across the run's turns, and checked
  against the recorded prompts: `usage_turns == prompts == 2` on every task, so the sum is over
  the turns it claims to be.
- **published**: Gemini 2.5 Flash on Vertex is $0.30 / 1M input tokens and $2.50 / 1M output
  tokens, where "output" is *response and reasoning* — so thinking tokens bill at the output
  rate. (Google's pricing page, read 2026-10-17.)
- **arithmetic**: 1,000 tasks × 1.8084 M input × $0.30 + 0.2842 M output × $2.50 = **$1.25**.
- **Cloud Run compute: $0 at this scale.** 1,000 tasks at ~9.3 s each is ~9,300 vCPU-seconds
  and ~4,650 GiB-seconds, against a free tier of 240,000 vCPU-seconds and 450,000 GiB-seconds
  per month (us-central1). Even counting a cold start per task it stays inside that. Past the
  free tier, or with `--min-instances` set, compute adds on top of the $1.25.

## What these numbers do and do not say

- The eval reads the **first patient the sandbox returns**, so the record under test changes
  between runs (two different patients across the four). It is not a fixed benchmark.
- The model is non-deterministic; **n = 4 runs**. Treat 20/20 as "it worked four times", not a rate.
- **Cold start is a first request to a fresh revision** — a revision with no warm instance. I
  could not observe a *post-idle* scale-from-zero start in the same session: five minutes after
  the last request the instance was still warm (0.097 s).
- It measures whether the agent answers from records it chose to read, and whether anything
  identifying the patient reached the model. It does not measure clinical correctness.

## Offline vs live

- **Offline** — `just verify` / `just eval-offline`: fixture bundle + scripted policy, deterministic,
  no model, no network. 5/5 tasks, 0 direct identifiers, the unknown-patient read refused,
  0 out-of-scope resources. Measures the tool, redaction and projection layers — **not** model quality.
- **Runtime, still offline** — `just test-runtime`: a real FastMCP server on a loopback port driven
  by a real ADK toolset, with a scripted model. This guards the seam between the two frameworks.
- **Live** — `just eval`, measured above: the real agent, a real sandbox, a real model.
- **Deployed** — `just up`, measured above: the same code as two private Cloud Run services, with
  Cloud Run IAM between them.

`just down` deletes both services and prints what it leaves behind.
