#!/usr/bin/env python3
"""Evaluate a local ADK agent using Agent Platform Evaluation.

The flywheel ships two runners and both need something already deployed:
``endpoint_evaluation.py`` wants an endpoint URL, ``maas_evaluation.py`` a model
ID. An agent that has been built and not yet shipped has neither. This is the
third runner — it imports the agent object in process and hands it to
``client.evals.run_inference(agent=...)``, which drives it through an ADK
``Runner`` and records the full event trace, tool calls included.

Its companion is ``generate_eval_dataset.py``, which synthesises the dataset when
the founder has no traces to start from. Its output feeds ``--dataset`` here with
no conversion: it writes ``starting_prompt`` / ``conversation_plan`` rows, and
``run_inference`` engages its user simulator whenever a ``conversation_plan``
column is present.

Pass the agent as ``module:attribute``. The attribute may be the agent itself or
a zero-argument factory that returns one:

  python local_agent_evaluation.py \
      --agent app.agent.agent:root_agent \
      --dataset eval-dataset-2026-09-01.jsonl \
      --metrics tool_use_quality,final_response_quality,safety

Run it from the repository root so the agent's module is importable. No env
prefix is needed: the script exports what the agent's model client requires.

Two locations are in play and they are not interchangeable. ``--location`` is
the region of the evals API. ``--model-location`` (default ``global``) is where
the agent's own model calls go, and is what reaches ADK as
``GOOGLE_CLOUD_LOCATION``. Setting that variable in the shell to fix one of them
breaks the other, because both clients read it.

Scoring bills. Every metric is an LLM-as-judge call against Google Cloud, and a
local agent does not make those free — cost scales with samples x metrics.

Exit codes: 0 = results written, 1 = bad arguments or the run failed.
"""

import argparse
import datetime
import json
import os
import sys
from pathlib import Path

import _metrics
from _agent_loader import configure_vertex_env, fail, load_agent

# The vendored flywheel sits beside this skill; both land in the plugin's
# skills/ directory. Its helpers render the report so this script does not.
FLYWHEEL_SCRIPTS = (
    Path(__file__).resolve().parents[2] / "agent-platform-eval-flywheel" / "scripts"
)


def source_columns(src):
    """Column names of the dataset as given, without running inference.

    Pre-flight reads the *input* columns -- `reference` and `context` are things
    the dataset carries, not things inference produces -- so it can and must run
    before the billed call. It used to run on the post-inference frame, which
    meant a dataset that could never be scored was diagnosed only after paying
    to drive the agent across every row of it.
    """
    import pandas as pd

    if hasattr(src, "columns"):
        return set(src.columns)
    path = Path(src)
    if path.suffix == ".csv":
        return set(pd.read_csv(path, nrows=1).columns)
    return set(pd.read_json(path, lines=True, nrows=1).columns)


def preflight(columns, metric_names, allow_unverified=False):
    """Refuse metrics the dataset cannot support, before anything bills."""
    # First: was this metric ever seen to score an agent dataset at all? Ten of
    # the SDK's twenty-five were, and the rest fail for reasons no column check
    # would catch -- five of them because their own judge prompt returns prose
    # where the service expects JSON. Checked before the column rules so the
    # message names the real problem rather than a column that would not help.
    _metrics.require_verified(metric_names, allow_unverified)

    missing = _metrics.missing_columns(columns, metric_names)
    if missing:
        print("\nPre-flight: these metrics will error on every case.\n", file=sys.stderr)
        for name, needed in missing:
            print(f"  {name}: needs a '{needed}' column, which the dataset does not have.",
                  file=sys.stderr)
        # A chat-shaped metric is not one missing column away from working: it
        # reads a transcript instead of an agent trace, and this runner only
        # ever produces the trace. Saying "add the column" would send someone
        # off to fabricate a `history` that cannot exist.
        chat = [n for n, _ in missing if n in _metrics.CHAT_SHAPE]
        if chat:
            print(
                f"\n  {', '.join(chat)} read a chat transcript (prompt + history),\n"
                "  not the agent trace this runner records. Despite the "
                "multi_turn_ prefix they\n  are not agent metrics, and no column "
                "you add here will make them score.",
                file=sys.stderr,
            )
        print(
            "\nAdd the column to the dataset, or drop the metric. Do not substitute a\n"
            "different metric silently — the recommendation says what is being measured.\n",
            file=sys.stderr,
        )
        fail("dataset does not support the requested metrics")

    # Turn mode. A `conversation_plan` column is what makes run_inference drive
    # its user simulator, so its presence is the dataset's turn mode; a
    # single-turn metric meeting it fails per case with a 400, after billing.
    multi_turn_data = "conversation_plan" in set(columns)
    wanted = _metrics.turn_mode(metric_names)
    if wanted == "single" and multi_turn_data:
        names = [n for n in _metrics.normalise(metric_names)
                 if not _metrics.is_multi_turn(n)]
        swaps = "\n".join(f"    {n} -> {_metrics.CROSS_FAMILY[n]}" for n in names
                          if n in _metrics.CROSS_FAMILY)
        fail(
            f"single-turn metrics on a multi-turn dataset: {', '.join(names)}\n"
            "The dataset has a 'conversation_plan' column, so inference will run the "
            "user simulator and produce multi-turn traces, which these metrics reject "
            "per case with HTTP 400.\n"
            + (f"Nearest multi-turn equivalents:\n{swaps}\n" if swaps else "")
            + "Or drop the conversation_plan column to score these on single-turn "
            "traces. Either way, generate and score with the same --metrics."
        )
    if wanted == "multi" and not multi_turn_data:
        fail(
            "multi-turn metrics on a single-turn dataset. The dataset has no "
            "'conversation_plan' column, so every trace will be one turn and these "
            "metrics have no conversation to score. Regenerate it with the same "
            "--metrics you pass here."
        )


def metric_errors(result):
    """Collect {metric_name: error text} from a result, one entry per metric.

    A metric that fails its contract fails identically on every case, so the
    first error for each name is the whole story.
    """
    errors = {}
    for case in getattr(result, "eval_case_results", None) or []:
        for candidate in getattr(case, "response_candidate_results", None) or []:
            for name, res in (getattr(candidate, "metric_results", None) or {}).items():
                message = getattr(res, "error_message", None)
                if message and name not in errors:
                    errors[name] = str(message)
    return errors


def canary(client, agent, src, metrics, metric_names):
    """Score one case before committing to the dataset, and report what breaks.

    This exists because a metric's input contract cannot be predicted locally.
    It lives in a server-side spec, it is version-dependent, and no local API
    reports it: the SDK's own GCS loader covers only a dozen non-agent metrics
    and does not resolve in this release. Every attempt to encode the rules as
    a table has held until the next metric -- `tool_use_quality` on turn mode,
    then
    `final_response_quality` on the same, then `multi_turn_safety` on dataset
    shape, each one discovered by paying for a full run that scored nothing.

    So this stops guessing and asks. One case is scored, the service's own
    error is read back, and the run stops before the other N-1 cases are
    driven and judged. It costs one row and it generalises to metrics, SDK
    versions and failure modes nobody here has seen -- which the tables above,
    by construction, cannot.

    Those tables stay because they are free and their messages are better. This
    is the backstop that stops a gap in them costing a whole run.
    """
    print(f"Canary: scoring 1 case with {', '.join(metric_names)} before the rest.",
          file=sys.stderr)
    probe = client.evals.run_inference(agent=agent, src=src)
    result = client.evals.evaluate(dataset=probe, metrics=metrics)

    errors = metric_errors(result)
    if not errors:
        print("Canary: all metrics scored. Continuing.\n", file=sys.stderr)
        return

    print("\nCanary failed. The service rejected these metrics on the first "
          "case,\nand would reject them on every other one:\n", file=sys.stderr)
    for name, message in errors.items():
        print(f"  {name}\n    {message}\n", file=sys.stderr)
    print(
        "Nothing further was scored, so only the one case was billed.\n"
        "This is a contract mismatch between the metric and the dataset, not a\n"
        "verdict on the agent. Fix the pairing and re-run; do not swap a metric\n"
        "silently, because the recommendation says what is being measured.\n",
        file=sys.stderr,
    )
    fail(f"{len(errors)} metric(s) cannot score this dataset")


def render_report(result, json_path, html_path):
    """Print the summary and save HTML using the flywheel's own helpers."""
    sys.path.insert(0, str(FLYWHEEL_SCRIPTS))
    try:
        import inspect_results
    except ImportError:
        print(
            f"\nResults written to {json_path}. Read them with the flywheel's helper:\n"
            f"  python3 {FLYWHEEL_SCRIPTS / 'inspect_results.py'} "
            f"--result {json_path} --save-html {html_path}"
        )
        return

    print("\n" + inspect_results.render(result))
    try:
        inspect_results.save_html(json.loads(result.model_dump_json(fallback=str)),
                                  str(html_path))
        print(f"HTML report: {html_path}")
    except Exception as exc:  # pylint: disable=broad-exception-caught
        print(f"Could not render HTML ({exc}); the JSON result is at {json_path}.")


def sanitize_agent_dataset(dataset):
    """Filter out events with missing or null content from multi-turn traces.

    The Vertex AI Evaluation backend strictly requires `event.content` on all
    events in `agent_eval_data.turns[].events[]`. Multi-agent delegation in ADK
    can emit internal transfer/state events that lack content, leading to
    400 INVALID_ARGUMENT during scoring if not sanitized.
    """
    df = getattr(dataset, "eval_dataset_df", None)
    if df is None or "agent_data" not in df.columns:
        return
    for idx in df.index:
        raw = df.at[idx, "agent_data"]
        is_str = isinstance(raw, str)
        agent_data = json.loads(raw) if is_str else raw
        if isinstance(agent_data, dict) and "turns" in agent_data:
            for turn in agent_data.get("turns", []):
                if isinstance(turn, dict) and "events" in turn:
                    turn["events"] = [
                        ev
                        for ev in turn["events"]
                        if isinstance(ev, dict) and ev.get("content") is not None
                    ]
            df.at[idx, "agent_data"] = json.dumps(agent_data) if is_str else agent_data


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate a local ADK agent with Agent Platform Evaluation."
    )
    parser.add_argument(
        "--agent",
        required=True,
        help="The agent as 'module:attribute', e.g. app.agent.agent:root_agent.",
    )
    parser.add_argument(
        "--dataset",
        required=True,
        help="Path to the evaluation dataset (.jsonl or .csv).",
    )
    parser.add_argument(
        "--metrics",
        required=True,
        help="Comma-separated registry metric names, e.g. tool_use_quality,safety.",
    )
    parser.add_argument(
        "--project",
        default=os.environ.get("GOOGLE_CLOUD_PROJECT"),
        help="Google Cloud project. Defaults to $GOOGLE_CLOUD_PROJECT.",
    )
    parser.add_argument(
        "--location",
        default=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
        help="Region for the evals API. Defaults to $GOOGLE_CLOUD_LOCATION. "
             "This is not where the agent's own model runs — see "
             "--model-location.",
    )
    parser.add_argument(
        "--model-location",
        default="global",
        help="Region the agent's own model calls use, exported to the ADK "
             "runner as GOOGLE_CLOUD_LOCATION. Defaults to 'global', where "
             "Gemini models are reachable; a specific region often is not.",
    )
    parser.add_argument(
        "--output-dir",
        default="artifacts/eval",
        help="Where to write the result JSON and HTML. Default: artifacts/eval.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Score only the first N rows. Use for a cheap smoke test.",
    )
    parser.add_argument(
        "--allow-unverified",
        action="store_true",
        help="Run a metric that verify_metrics.py did not see score. For a "
             "hand-written dataset carrying a 'reference' or 'context' column, "
             "which the sweep never tested. Not a way past a refusal.",
    )
    parser.add_argument(
        "--canary",
        action="store_true",
        help="Score one case and stop if any metric errors, before running the "
             "rest. Saves money on an unproven metric pairing; costs an extra "
             "inference and scoring pass in wall-clock time. Off by default, "
             "because a failing metric costs the same time either way — the "
             "run completes and reports the error regardless.",
    )
    args = parser.parse_args()

    if not args.project:
        fail("no project. Pass --project or set GOOGLE_CLOUD_PROJECT.")
    if not Path(args.dataset).is_file():
        fail(f"dataset not found: {args.dataset}")

    import agentplatform

    metric_names = _metrics.normalise(args.metrics)
    metrics = _metrics.resolve_metrics(metric_names)

    # Before load_agent: importing the agent's module can build its model
    # client, and that client reads the environment once.
    configure_vertex_env(args.project, args.model_location)
    agent = load_agent(args.agent)

    client = agentplatform.Client(project=args.project, location=args.location)

    import pandas as pd

    frame = pd.read_json(args.dataset, lines=True)
    if args.limit:
        frame = frame.head(args.limit)
    src = args.dataset if not args.limit else frame

    # Free checks first: what is known statically, with the better messages.
    # Before inference either way, because driving the agent across a dataset
    # these metrics cannot score buys nothing.
    preflight(source_columns(src), metric_names, args.allow_unverified)

    # Then the one that cannot be wrong -- but only when asked. It trades time
    # for money, and those do not always point the same way: a metric that
    # cannot score this dataset still errors per case rather than hanging, so
    # the full run costs the same wall clock whether the pairing works or not.
    # The trial is therefore pure added latency in exchange for not paying to
    # judge rows that will fail. Worth it for an unproven pairing on a large
    # dataset; wrong for a demo, where the clock is the scarce thing.
    # metric_errors() below reports the same failures either way, for free.
    if args.canary and len(frame) > 1:
        canary(client, agent, frame.head(1), metrics, metric_names)

    # run_inference drives the agent through an ADK Runner and returns response,
    # intermediate_events and agent_data. Passing the agent as model=<callable>
    # instead returns response only, which silently makes the tool-use and
    # trajectory metrics unscoreable.
    dataset = client.evals.run_inference(agent=agent, src=src)
    sanitize_agent_dataset(dataset)

    result = client.evals.evaluate(dataset=dataset, metrics=metrics)

    # The canary proves the contract, not the run. A metric can still fail on a
    # particular case, and a mean computed over the survivors reads as a pass.
    late = metric_errors(result)
    if late:
        print("\nNOTE: these metrics errored on some cases and are excluded from "
              "their own means:", file=sys.stderr)
        for name, message in late.items():
            print(f"  {name}: {message}", file=sys.stderr)
        print("Read the per-case counts, not the mean.\n", file=sys.stderr)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = out_dir / f"results_{stamp}.json"
    json_path.write_text(result.model_dump_json(fallback=str))

    render_report(result, json_path, out_dir / f"results_{stamp}.html")
    print(f"Result JSON: {json_path}")


if __name__ == "__main__":
    main()
