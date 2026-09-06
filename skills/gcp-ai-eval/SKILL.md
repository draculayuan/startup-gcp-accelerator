---
name: gcp-ai-eval
description: Sets up evaluation for an AI agent that has already been built — recommends metrics, optionally generates a synthetic evaluation dataset, and runs them against the agent. Use when the user wants to measure, evaluate, test or score an agent's quality. Do not use to design an agent that does not exist yet, or to review infrastructure.
---

# AI Agent Evaluation

For an agent that exists. It runs against a local ADK agent — no deployment, no
endpoint, no Cloud Run — so it belongs after the agent is built and before it
ships.

This capability produces two artifacts, runs them, and stops. It does not tune
the agent, and it does not loop.

## The eval skill owns the method

Everything about *how* to evaluate — dataset schema, SDK call shapes, failure
taxonomy, the improvement loop — lives in **`agent-platform-eval-flywheel`**.
Load it and follow it.

Do not restate its content here or from memory. SDK snippets recalled rather
than read are the failure this harness exists to prevent. Read the shipped text,
and check any call shape against the `agentplatform` version installed here —
the SDK moves faster than the examples that describe it.

**If the skill is absent, say so and name it.** Do not recommend metrics from
your own knowledge — an ungrounded eval framework looks exactly like a grounded
one, and it will be trusted. Re-running `bootstrap.sh` reinstalls it.

**Two exceptions, where this skill overrides it.** The flywheel's
`references/metric_registry.md` is prose, and this capability's dataset shape
narrows which of the metrics it lists can actually score — `scripts/_metrics.py`
is that narrowed set, verified against the running service, so use it instead.
And the `generate_conversation_scenarios` examples in
`references/sdk_patterns.md` and `references/dataset_schema.md` predate the call
signature in the pinned SDK; `bootstrap.sh` aligns and marks them, but use the
shipped generator rather than either example.

### Everything in this skill

**The complete contents of `skills/gcp-ai-eval/scripts/`. A file not listed here
does not exist in this skill** — read a name off this table rather than
reconstructing one from the topic you want, because a plausible filename is not
evidence of a file.

| File | Is |
|---|---|
| `scripts/generate_eval_dataset.py` | Billed entry point — synthesises the dataset from the agent itself. |
| `scripts/local_agent_evaluation.py` | Billed entry point — scores it. |
| `scripts/verify_metrics.py` | Confirms `VERIFIED` against the running service. Re-run after an `agentplatform` upgrade. |
| `scripts/_metrics.py` | The `VERIFIED` table and each metric's input contract. Imported, not run. |
| `scripts/_agent_loader.py` | Loads the founder's ADK agent. Imported, not run. |
| `scripts/requirements.txt` | What `bootstrap.sh` installs. Not executable. |

**The result-reading scripts are not here.** `inspect_results.py`,
`compare_results.py`, `validate_dataset.py`, `parse_adk_traces.py` and
`render_html_report.py` live in `skills/agent-platform-eval-flywheel/scripts/`
and exist in exactly one place; `local_agent_evaluation.py` already imports them
from there. Reach into the flywheel directory by its full path rather than
looking for a copy alongside these six.

| Need | Use | Not |
|---|---|---|
| Synthesise cases when there are no traces | this skill's `scripts/generate_eval_dataset.py` | Writing the SDK call yourself |
| Convert ADK session dumps to a dataset | the flywheel's `scripts/parse_adk_traces.py` | A hand-written JSON walk |
| Check a parsed trace dataset | the flywheel's `scripts/validate_dataset.py` | Eyeballing it, or discovering the problem mid-eval |
| Run the eval | this skill's `scripts/local_agent_evaluation.py` | A freshly written `run_eval.py` |
| Read the scores | the flywheel's `scripts/inspect_results.py` (`--save-html` for a report) | Printing the dataframe |

`validate_dataset.py` reads the `{"eval_cases": [...]}` shape that
`parse_adk_traces.py` emits, not a flat prompt/reference JSONL. Pointing it at a
generated dataset fails on the format, not on the content — so use it on the
trace path only.

`endpoint_evaluation.py` and `maas_evaluation.py` are **not** usable here. Both
target something already deployed — one needs an endpoint ID, the other a model
ID. That gap is why this skill ships the third runner.

## What this capability adds

The flywheel is a continuous improvement loop that expects many iterations and
will keep going. Four constraints turn it into a hand-off:

1. **Read context before asking for it.** Take the project and region from
   `~/.startup-gcp-accelerator/profile.json` rather than asking — the flywheel
   asks for `GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_LOCATION` when it cannot
   find them. Read the agent's code to ground the metric choice: its tools,
   whether it is multi-turn, whether it retrieves. If an
   `architecture-design-*.md` is in the workspace, use it as background.
   The code is the authority where they disagree.

   **Name the project in the conversation before anything bills**, even when
   the profile supplied it. An eval that bills against the wrong project is
   only catchable before the run.

   **If a previous run left artifacts, resume from them rather than starting
   over.** An `ai-eval-*.md` or `eval-dataset-*.jsonl` in the workspace means
   the metrics were already chosen and the dataset already paid for. Say what
   you found, then offer the command recorded at the end of the recommendation.
   Regenerating a dataset bills for one they already have, and scores only
   compare across runs when the dataset is held fixed — which is the whole
   point of re-running after changing the agent. Start fresh only if they ask,
   or if the agent has gained a tool or a retrieval step the recorded metrics
   do not cover; say which it is.

2. **Produce exactly two artifacts, dated.** A second run must not silently
   overwrite the first.

   | Artifact | Path |
   |---|---|
   | Evaluation framework recommendation | `ai-eval-<date>.md` |
   | Evaluation dataset, if requested | `eval-dataset-<date>.jsonl` |

   The recommendation names the metrics chosen for *this* agent and why each
   one, what data it needs, and a starting threshold. It is for a founder
   deciding whether the measurement is the right one, so lead with the choice
   and the reason, not with the API. End it with the exact
   `local_agent_evaluation.py` command, so the run is reproducible without
   this conversation.

   **Do not write a third file.** Generating bespoke tooling is the failure
   this skill exists to prevent; both moving parts are shipped, and they are
   the same ones every time.

3. **Ask before generating a dataset, and ask how many.** Two questions, both
   explicit, neither assumed — and both skipped when resuming from an existing
   dataset (see 1):

   - *Generate a dataset?* If they decline, write the recommendation and say
     the runner needs a dataset before it will run.
   - *How many samples?* Offer a small default — ten is enough to see whether
     the metrics behave — and say it can be raised once the loop works.

   Get agreement **before** the first billed call. The safety gate will also
   put each script in front of them as a permission prompt; do not treat that
   as the conversation. A founder who first learns an eval bills when a dialog
   appears has been asked the wrong question at the wrong time.

   Prefer real traces over synthetic ones when the agent has been run — real
   traces beat generated scenarios. In order: `parse_adk_traces.py` on existing
   session dumps, then `generate_eval_dataset.py`, then hand-written cases as a
   last resort. On the trace path, run `validate_dataset.py` before scoring; a
   malformed dataset otherwise surfaces as a confusing failure after the billed
   calls have started.

4. **Stop after the run.** Report the scores, do not analyse failures, propose
   agent changes, or start the next iteration. Let the founder decide.

## Choosing metrics

**Only ten of the SDK's twenty-five metrics score an agent dataset**, and both
scripts refuse the rest, naming a substitute. Google's reference page lists the
required inputs for every managed rubric metric and is the authority:

  https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/rubric-metric-details

`VERIFIED` in `scripts/_metrics.py` is that page reduced to the metrics this
capability's dataset satisfies, with each contract quoted and a `WHY_NOT` entry
naming a substitute for every exclusion. `scripts/verify_metrics.py` confirms it
against the running service, which catches what a document cannot: metrics that
do not run in the installed release, and the spec version the service actually
serves. **Re-run it after an `agentplatform` upgrade** — one judged row per
metric, and `bootstrap.sh --update` reminds you.

Both scripts **pin every metric to its v1 spec**. Unpinned, the SDK requests v2
or v3 for nine of the ten and the service answers v1 — so unpinned scores depend
on a resolution that is not visible in the request and need not hold across
releases. v1 is what the reference page documents and what the sweep measured;
pinning makes the version explicit and the scores reproducible.

Several exclusions are not intuitive. `multi_turn_general_quality` and
`multi_turn_text_quality` evaluate a chat transcript rather than an agent trace,
despite the prefix they share with the three that work; `verbosity`,
`coherence`, `fluency`, `question_answering_quality` and `summarization_quality`
are legacy metric prompt templates and fail. **A metric being the sensible
choice for the founder's agent is not evidence it will run.**

There is also a turn-mode mismatch the scripts check for you: a single-turn
metric on multi-turn data is rejected per case with a 400, *after* billing.
`tool_use_quality` on a conversation plan is the pairing to watch, because the
generator emits plans by default.

If a metric in the recommendation is refused, **say so and put the substitute to
the founder — never quietly swap it in.** The recommendation is where they
agreed what is being measured, and the report is what they will trust.

## Running the evaluation

Two shipped scripts, in order. Nothing in either varies per founder except its
arguments, so **do not copy, adapt or regenerate them.** The only thing to work
out is the `module:attribute` spec — read their code for where the ADK `Agent`
object is defined. It must be the agent itself, not a service class wrapping it.

Generate the dataset:

```bash
python3 <skill>/scripts/generate_eval_dataset.py \
    --agent app.agent.agent:root_agent \
    --metrics multi_turn_task_success,multi_turn_tool_use_quality \
    --count 10 \
    --output eval-dataset-<date>.jsonl
```

Then score it:

```bash
python3 <skill>/scripts/local_agent_evaluation.py \
    --agent app.agent.agent:root_agent \
    --dataset eval-dataset-<date>.jsonl \
    --metrics multi_turn_task_success,multi_turn_tool_use_quality
```

Run both from the agent's repository root, so its package imports.

**Both take `--metrics`, and it must be the same list.** The metrics decide the
dataset's columns and whether its rows are single- or multi-turn, so a dataset
is not scoreable in the abstract — it is scoreable by particular metrics.
Generating first and choosing metrics afterwards is how you pay for generation
*and* inference before learning the pairing never worked. The pairing is checked
before either script bills.

`--dry-run` on the generator prints the derived agent description and the exact
request body and bills nothing. Use it before the real call.

Four flags worth knowing:

- **`--model-location`** (default `global`) is where the *agent's own* model
  calls go, exported to ADK as `GOOGLE_CLOUD_LOCATION`. `--location` is the
  evals API region and is a different thing. Setting one environment variable to
  fix either one breaks the other, which is why they are separate arguments.
- **`--allow-cross-region-model`** on the generator. The scenario generator is
  backed by a preview model available only in `global`, so a regional
  `--location` is refused with `INVALID_ARGUMENT` until this is set. It routes
  the model call outside `--location` — so it does not satisfy a data-residency
  requirement, it opts out of one. Say that when you pass it.
- **`--environment-data @path`** on the generator, for facts the simulated user
  may rely on (inventory, policies, order ids). `@` reads a file, `@@` escapes a
  literal leading `@`.
- **`--canary`** on the runner scores one case first and stops on failure. It
  saves money on an unproven pairing over a large dataset and costs an extra
  inference and scoring pass. **Off by default, and it should stay off for
  demos**: a failing metric errors per case rather than hanging, so the run
  finishes in the same time either way.

Three things these do that a hand-written runner reliably gets wrong:

- **They pass `agent=`, not `model=`.** `run_inference(agent=<ADK agent>)`
  drives the agent through an ADK `Runner` and returns `response`,
  `intermediate_events` *and* `agent_data`. Passing a callable as `model=`
  returns `response` alone, which silently makes every tool-use and trajectory
  metric unscoreable — the agent's defining behaviour goes unmeasured while the
  remaining scores look fine.
- **They check metric inputs before billing**, against the dataset's *input*
  columns. `grounding` needs a `context` that inference does not produce.
  Checked afterwards, that surfaces as a `400` on every row with the money
  already spent.
- **They route the agent's model calls to Vertex.** Unset,
  `GOOGLE_GENAI_USE_VERTEXAI` reads as false and the agent's own calls go to the
  Gemini Developer API, which wants an API key nobody has — surfacing as
  `ValueError: No API Key was provided` from inside the eval, where it reads
  like a broken eval rather than a missing export.

**The runner names every metric that errored**, reading the service's
per-metric errors back, so a metric that scored nothing is never hidden inside a
mean. Report those alongside the scores.

**Never run evaluation through an inline `python3 -c` snippet**, even though the
flywheel's reference patterns are written as inline code. The safety gate
inspects script files; an inline payload is invisible to it. Invoking a shipped
script is what puts the command in front of the founder for approval — that is
the intended path, not an obstacle to work around.

Say plainly that evaluation bills: scoring and scenario generation are
LLM-as-judge calls against Google Cloud, and a local agent does not make them
free. Give the sample count and the metric count, since together those set the
cost.

## Boundaries

- **The agent must exist.** If it does not, this is `/gcp-design` — designing an
  agent and measuring one are different jobs.
- **Behaviour, not infrastructure.** Whether the agent is any good is this
  capability. Whether its infrastructure is secure, reliable or affordable is
  `/architecture-review`.
- **No agent changes.** Reading the agent's code to choose metrics is in scope.
  Editing it is not — that is a Conductor track.
- **No provisioning.** No deployment, no endpoints, no Terraform.

## Escalation

Say what would make sense next. Do not start it.

| Situation | Route to |
|---|---|
| Eval reveals a defect worth fixing properly | `/conductor:newTrack` |
| "What does this metric actually mean?" | `/gcp-ask` |
| Agent scores well, now ship it | `/gcp-do` |
| Infrastructure judgement wanted too | `/architecture-review` |

When routing to Conductor, print the command with the report named, so the
finding carries into the spec rather than being retyped:

```
/conductor:newTrack fix the failures recorded in ai-eval-<date>.md
```
