#!/usr/bin/env python3
"""Synthesise an evaluation dataset for a local ADK agent (cold start).

The companion to ``local_agent_evaluation.py``. That script exists so nobody
writes a bespoke *runner*; this one exists so nobody writes a bespoke *dataset
generator*, which was the remaining place this capability improvised. Everything
below is mechanical -- the agent object already carries every field the API
wants -- so it is a script, not a reasoning task.

  python3 generate_eval_dataset.py \
      --agent app.agent.agent:root_agent \
      --metrics multi_turn_task_success,multi_turn_tool_use_quality \
      --count 10 \
      --output eval-dataset-2026-09-03.jsonl

Then score the result with the shipped runner, passing the same metrics:

  python3 local_agent_evaluation.py \
      --agent app.agent.agent:root_agent \
      --dataset eval-dataset-2026-09-03.jsonl \
      --metrics multi_turn_task_success,multi_turn_tool_use_quality

``--metrics`` is required, and is the same list the runner will be given. A
dataset is not scoreable in the abstract: it is scoreable *by particular
metrics*, which decide both the columns it must carry and whether its rows are
single- or multi-turn. Generating first and choosing metrics afterwards is how
you pay for generation and inference before learning the pairing never worked --
so the constraints are checked here, before the billed call. See ``_metrics``.

Four things this encodes that are easy to get wrong by hand:

- **The call shape.** ``generate_conversation_scenarios`` is keyword-only and
  takes ``agent_info=`` (an ``AgentInfo``) or ``agent=`` (a managed-agent
  resource name), plus a required ``config=``. It does *not* take ``agents=``,
  ``root_agent_id=`` or ``user_scenario_generation_config=`` at the top level --
  those are fields *of* ``AgentInfo`` and of the config object. Flattening them
  into keyword arguments raises ``TypeError`` on the first call.
- **The config's field names are not the wire's.** The SDK renames three of the
  four on the way out, so a config field set to a destination name does not
  reach the request. ``user_scenario_count`` -- the name the *server* uses, and
  the natural guess from its error message -- leaves the value unset, and the
  call fails with ``user_scenario_generation_config.user_scenario_count cannot
  be none`` after billing has begun. ``count`` is the field to set. See
  ``CLIENT_TO_WIRE`` below for the full map and the two other renamed fields.
- **The output columns are load-bearing.** ``run_inference`` engages its user
  simulator when a ``conversation_plan`` column is present, and not otherwise.
  So that column alone decides the turn mode: keep it and the rows are
  multi-turn, drop it and they are single-turn prompts. Rename it and multi-turn
  metrics silently become unscoreable.
- **The metrics decide the shape, so they are an input.** A single-turn metric
  handed a conversation plan fails per case with ``Single-turn metric ...
  received agent_eval_data with 2 turns``, after billing; ``tool_use_quality``
  is the one that bites, because its name looks like the default choice and
  ``multi_turn_tool_use_quality`` is the metric that pairs with a plan. And a
  metric needing a column the generator cannot invent -- ``final_response_match``
  wants a golden ``reference`` -- can never score a synthesised dataset at all.
  Both are refused up front rather than discovered per row.

Generation bills: it is an LLM call against Google Cloud, priced by scenario
count. ``--dry-run`` prints the derived agent description and the exact call and
bills nothing.

Exit codes: 0 = dataset written (or dry run complete), 1 = bad arguments or the
call failed.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import _metrics
from _agent_loader import configure_vertex_env, fail, load_agent


# The SDK renames three of the four config fields on the way to the wire, and
# ignores the client-side field that carries each destination's name. Setting
# the name the *server* uses is therefore the way to send nothing at all:
#
#     client field             wire field                read by the transformer
#     count                 -> user_scenario_count       yes
#     generation_instruction-> simulation_instruction    yes
#     environment_context   -> environment_data          yes
#     model_name            -> model_name                yes
#     user_scenario_count      (dropped)                 no
#     simulation_instruction   (dropped)                 no
#     environment_data         (dropped)                 no
#
# The model has `extra="forbid"`, so the dropped three are real fields and a
# typo would have raised -- they are accepted in silence and never sent. Read
# off agentplatform._genai._transformers.t_user_scenario_generation_config;
# re-check it after an SDK upgrade, which is what wire_payload() below is for.
CLIENT_TO_WIRE = "see t_user_scenario_generation_config in the installed SDK"


def wire_payload(config):
    """Render the config as the request body the service will actually receive.

    Uses the SDK's own transformer rather than reimplementing the mapping, so
    this cannot drift from it. Returns None if the private module has moved --
    the caller then skips both the guard and the exact preview, because a
    check that cannot run must not fail a run that would otherwise work.
    """
    try:
        from agentplatform._genai import _transformers

        return _transformers.t_user_scenario_generation_config(config)
    except Exception:  # pylint: disable=broad-exception-caught
        return None


def read_maybe_file(value):
    """Resolve an argument that may be `@path` into the file's contents.

    `--environment-data` is the one argument whose realistic value is bulk --
    an inventory, a policy document, a table of order ids. A shell argument is
    the wrong channel for that, and an agent that cannot pass it is an agent
    that goes back to writing its own generator. `@` follows curl's convention;
    `@@` escapes a value that genuinely starts with one.
    """
    if value is None or not value.startswith("@"):
        return value
    if value.startswith("@@"):
        return value[1:]
    path = Path(value[1:])
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        fail(f"cannot read {path}: {exc}")


def _text(value):
    """ADK accepts a str or an InstructionProvider callable for `instruction`."""
    if value is None or isinstance(value, str):
        return value
    return None if callable(value) else str(value)


def _tool_names(agent):
    names = []
    for tool in getattr(agent, "tools", None) or []:
        name = getattr(tool, "name", None) or getattr(tool, "__name__", None)
        names.append(name or type(tool).__name__)
    return names


def describe_agent(agent):
    """Turn an ADK agent tree into the AgentInfo the generator expects.

    Sub-agents are included because a scenario written against the root alone
    will not exercise a delegation the founder cares about.
    """
    from agentplatform import types

    agents, seen = {}, set()

    def walk(node):
        agent_id = getattr(node, "name", None) or type(node).__name__
        if agent_id in seen:
            return agent_id
        seen.add(agent_id)
        children = [walk(child) for child in getattr(node, "sub_agents", None) or []]
        agents[agent_id] = types.evals.AgentConfig(
            agent_id=agent_id,
            instruction=_text(getattr(node, "instruction", None)),
            description=_text(getattr(node, "description", None)),
            sub_agents=children or None,
        )
        return agent_id

    root_id = walk(agent)
    return types.evals.AgentInfo(agents=agents, root_agent_id=root_id)


def scenario_rows(dataset, mode):
    """Flatten generated scenarios to the columns the runner reads back.

    `starting_prompt` and `conversation_plan` are the canonical names the SDK
    itself uses when it converts eval cases to a frame; matching them is what
    lets `local_agent_evaluation.py --dataset <this file>` work with no changes.

    `mode` is the turn mode the metrics demand. Under 'single' the conversation
    plan is dropped, which is the whole of what makes a row single-turn: without
    that column `run_inference` never starts its user simulator, so the agent
    answers the starting prompt once and the trace has one turn in it. The plan
    is discarded rather than never requested because the service generates
    conversation scenarios either way -- there is no cheaper single-turn call.

    The prompt column is renamed to `prompt` in that mode, and this is not
    cosmetic. `starting_prompt` is accepted for *inference* -- it is the third
    fallback in the primary-prompt search (_evals_common.py) -- but the eval
    case it produces does not populate the `prompt` variable the single-turn
    metric templates render, so scoring fails per case with
    `Variable prompt is required but not provided`. Inference succeeds, the
    money is spent, and nothing is scored. `prompt` is the canonical name and
    is matched ahead of `starting_prompt`, so it satisfies both.
    """
    rows = []
    for case in dataset.eval_cases or []:
        scenario = getattr(case, "user_scenario", None)
        if scenario is None:
            continue
        row = {}
        if scenario.starting_prompt:
            key = "prompt" if mode == "single" else "starting_prompt"
            row[key] = scenario.starting_prompt
        if scenario.conversation_plan and mode != "single":
            row["conversation_plan"] = scenario.conversation_plan
        if row:
            rows.append(row)
    return rows


def main():
    parser = argparse.ArgumentParser(
        description="Synthesise an evaluation dataset for a local ADK agent."
    )
    parser.add_argument(
        "--agent",
        required=True,
        help="The agent as 'module:attribute', e.g. app.agent.agent:root_agent.",
    )
    parser.add_argument(
        "--metrics",
        required=True,
        help="The metrics this dataset will be scored with, comma-separated and "
             "identical to the runner's --metrics. Required: they decide the "
             "columns and the turn mode, so a dataset built without them is only "
             "scoreable by luck.",
    )
    parser.add_argument(
        "--count",
        type=int,
        required=True,
        help="How many scenarios to generate (1-100). Required: this is the "
             "number the founder approved, and it must not be guessed.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Where to write the dataset, e.g. eval-dataset-2026-09-03.jsonl.",
    )
    parser.add_argument(
        "--simulation-instruction",
        help="How the simulated user should behave. Defaults to a neutral "
             "instruction derived from the agent's own description.",
    )
    parser.add_argument(
        "--environment-data",
        help="Facts the simulated user may rely on (inventory, policies, ids). "
             "Use @path to read it from a file, which is the sane channel for "
             "anything longer than a sentence; @@ escapes a literal leading @.",
    )
    parser.add_argument(
        "--environment-context",
        help="Context for the generator. Defaults to the agent's tool names, so "
             "scenarios exercise the tools rather than only the prompt.",
    )
    parser.add_argument(
        "--model",
        help="Model backing the generator, e.g. gemini-2.5-flash. "
             "Defaults to the service default.",
    )
    parser.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT"))
    parser.add_argument(
        "--location",
        default=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
        help="Region for the generation API, not for the agent's own model.",
    )
    parser.add_argument(
        "--model-location",
        default="global",
        help="Region the agent's model calls would use, exported as "
             "GOOGLE_CLOUD_LOCATION. Generation does not run the agent, but "
             "importing its module can build the client, so it is set here too.",
    )
    parser.add_argument(
        "--allow-cross-region-model",
        action="store_true",
        help="Authorise the generator's model call to run outside --location. "
             "The scenario generator is backed by a preview model that is only "
             "available in 'global', so a request from a regional --location is "
             "refused with INVALID_ARGUMENT until this is set. It keeps the eval "
             "client, the dataset resource and billing in --location while the "
             "model call itself routes to 'global' -- so it does not satisfy a "
             "data-residency requirement, it opts out of one.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the derived agent description and the call, and bill nothing.",
    )
    args = parser.parse_args()

    if not 1 <= args.count <= 100:
        fail(f"--count must be between 1 and 100, got {args.count}")
    if not args.project:
        fail("no project. Pass --project or set GOOGLE_CLOUD_PROJECT.")

    from agentplatform import types

    # Everything the metrics decide, settled before the billed call: that the
    # names exist, that each was observed to score an agent dataset, and which
    # turn mode the rows have to be in. Generation has no --allow-unverified
    # escape hatch -- that flag is for a hand-written dataset carrying a column
    # this script cannot invent, so there is nothing here for it to unlock.
    metrics = _metrics.normalise(args.metrics)
    _metrics.resolve_metrics(metrics)
    _metrics.require_verified(metrics)
    mode = _metrics.turn_mode(metrics) or "multi"

    configure_vertex_env(args.project, args.model_location)
    agent = load_agent(args.agent)
    agent_info = describe_agent(agent)
    tools = _tool_names(agent)

    context = args.environment_context
    if context is None and tools:
        context = "The agent can call these tools: " + ", ".join(tools) + "."

    # `environment_context` is the only client field that reaches the wire's
    # environment_data, so the two flags share it rather than getting a field
    # each. See CLIENT_TO_WIRE.
    data = read_maybe_file(args.environment_data)
    if data:
        context = f"{context}\n\n{data}" if context else data

    instruction = args.simulation_instruction
    if instruction is None:
        purpose = _text(getattr(agent, "description", None)) or "this agent"
        instruction = (
            f"Simulate realistic users interacting with {purpose}. Vary intent and "
            "phrasing, and include cases the agent is likely to find difficult."
        )
    # Say what is about to be measured. Structural fitness is not enough: a
    # generator told only to simulate realistic users writes scenarios that
    # never reach a tool, and a tool-use metric then scores conversations with
    # no tool calls in them -- true, and about nothing. Appended to a founder's
    # own --simulation-instruction rather than replacing it.
    instruction += (
        "\n\nThese conversations will be scored on: "
        + "; ".join(_metrics.describe(metrics))
        + ". Write scenarios that give each of those something to measure."
    )
    if mode == "single":
        instruction += (
            " Each scenario must be answerable in a single exchange: one user "
            "message, one agent reply, no follow-up."
        )

    config = types.evals.UserScenarioGenerationConfig(
        count=args.count,
        generation_instruction=instruction,
        environment_context=context,
        model_name=args.model,
    )

    payload = wire_payload(config)
    if payload is not None and payload.get("user_scenario_count") is None:
        fail(
            "the request would leave user_scenario_count unset, which the service "
            "rejects with 400 INVALID_ARGUMENT after billing has started. The SDK's "
            "client-to-wire mapping has changed; see CLIENT_TO_WIRE in this file."
        )

    if args.dry_run:
        print(f"agent      : {args.agent}")
        print(f"root       : {agent_info.root_agent_id}")
        print(f"sub-agents : {len(agent_info.agents) - 1}")
        print(f"tools      : {', '.join(tools) or 'none detected'}")
        print(f"metrics    : {', '.join(metrics)}")
        print(f"turn mode  : {mode}  (columns: starting_prompt"
              + ("" if mode == "single" else " + conversation_plan") + ")")
        print(f"project    : {args.project} / {args.location}")
        print(f"scenarios  : {args.count}  -> {args.output}")
        print("\nWould call, and bill for:\n")
        print("  client.evals.generate_conversation_scenarios(")
        print("      agent_info=<AgentInfo: "
              f"{', '.join(sorted(agent_info.agents))}>,")
        # The payload, not the config object. A field set on the object but not
        # carried to the wire is exactly what this preview is here to reveal,
        # and printing model_dump() would show the object instead. Long
        # environment_data is elided so the rest stays readable.
        shown = dict(payload) if payload is not None else config.model_dump(
            exclude_none=True)
        blob = shown.get("environment_data")
        if blob is not None and len(blob) > 200:
            shown["environment_data"] = f"<{len(blob)} chars: {blob[:120]}...>"
        print("      config=<request body, after the SDK's client-to-wire mapping>")
        for key in sorted(shown):
            print(f"          {key}: {shown[key]!r}")
        # Shown as its own argument because that is what it is. A reader
        # checking where their data goes should see it here, not have to know
        # it is absent from the config body printed above.
        print(f"      allow_cross_region_model={args.allow_cross_region_model!r},")
        print("  )")
        if not args.allow_cross_region_model and args.location != "global":
            print(
                f"\nNOTE: --location is {args.location} and cross-region routing "
                "is off. The generator's model is preview-only in 'global', so "
                "this call is likely to be refused with INVALID_ARGUMENT. Pass "
                "--allow-cross-region-model to authorise it, or set "
                "--location global.",
                file=sys.stderr,
            )
        return

    import agentplatform

    client = agentplatform.Client(project=args.project, location=args.location)
    # A top-level argument of the call, not a field of the config: it is absent
    # from UserScenarioGenerationConfig, so setting it on the config object sets
    # nothing and the call still fails. Passed only when asked for, so the
    # default stays the SDK's own False and no data leaves --location unbidden.
    dataset = client.evals.generate_conversation_scenarios(
        agent_info=agent_info,
        config=config,
        allow_cross_region_model=args.allow_cross_region_model,
    )

    rows = scenario_rows(dataset, mode)
    if not rows:
        fail(
            "the generator returned no usable scenarios. Nothing was written; "
            "re-run with --dry-run to see the request that produced this."
        )

    out = Path(args.output)
    if out.parent != Path(""):
        out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")

    print(f"Wrote {len(rows)} scenario(s) to {out}")
    if len(rows) != args.count:
        print(
            f"NOTE: asked for {args.count}, the service returned {len(rows)}. "
            "Report the number written, not the number requested.",
            file=sys.stderr,
        )
    # The metrics are echoed into the command rather than left as a placeholder:
    # this file was shaped for exactly this list, and scoring it with a different
    # one is the mismatch the --metrics argument exists to prevent.
    print(
        "\nScore it with the shipped runner, from the agent's repository root:\n"
        f"  python3 {Path(__file__).with_name('local_agent_evaluation.py')} \\\n"
        f"      --agent {args.agent} \\\n"
        f"      --dataset {out} \\\n"
        f"      --metrics {','.join(metrics)}"
    )


if __name__ == "__main__":
    main()
