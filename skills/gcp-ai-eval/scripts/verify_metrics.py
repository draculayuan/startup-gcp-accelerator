#!/usr/bin/env python3
"""Find out which metrics actually score an agent dataset, by scoring one.

What each metric requires is documented, and `_metrics.py` quotes that page:

    https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/rubric-metric-details

Read it first. This script exists for the three things the page cannot tell you,
each of which has already cost a billed run that scored nothing:

- **Which metrics do not run in the installed release.** Five of the legacy
  metric prompt templates return prose where the service expects JSON, and
  `final_response_reference_free` answers HTTP 500 rather than naming the
  `rubric_groups` it needs. Neither is visible ahead of the call.
- **Which spec version the service actually serves.** It is not always the one
  the SDK asks for: unversioned metrics resolve to v2/v3 via the SDK's
  METRIC_LATEST_SPEC_NAME, and v1 has been observed coming back for all of
  them. `_metrics.PINNED_VERSION` makes the version explicit rather than
  leaving it to that resolution, and this script resolves metrics through
  `_metrics.resolve_metrics` so it measures the pinned specs the runner sends.
- **Whether the documented contract holds for a dataset this capability can
  produce.** A metric can be documented, available, and still have no scoreable
  input here.

    python3 verify_metrics.py --project <project>

Run it after any `agentplatform` upgrade, and paste the result into VERIFIED in
`_metrics.py`. `--json` writes the same thing machine-readably.

Cost: one inference pass per shape plus one judged row per metric -- tens of
rows in total, not hundreds. It bills, and it is far cheaper than finding the
same facts one failed eval at a time.
"""

import argparse
import json
import os
import sys

import _metrics
from _agent_loader import configure_vertex_env, fail

# Media metrics need image/video inputs this harness never produces, so they
# are out of scope rather than untested.
SKIP = {"gecko_text2image", "gecko_text2video"}


def build_agent():
    """A minimal agent with one tool, so tool-use metrics have something real."""
    from google.adk.agents import Agent

    def lookup_order(order_id: str) -> dict:
        """Look up an order by its id."""
        return {"order_id": order_id, "status": "shipped", "eta": "2026-09-05"}

    return Agent(
        name="verify_agent",
        model="gemini-2.5-flash",
        description="a customer support agent for an online store",
        instruction=(
            "Help customers with their orders. Always call lookup_order before "
            "answering a question about a specific order."
        ),
        tools=[lookup_order],
    )


# One row per shape is enough: a contract mismatch fails identically on every
# row, so a second row buys nothing but cost.
SHAPES = {
    "multi": [{
        "starting_prompt": "Where is order 1?",
        "conversation_plan": "Ask where order 1 is, then ask when it will arrive.",
    }],
    "single": [{"prompt": "Where is order 1? Look it up."}],
}


def verdict(result):
    """(spec_name, error) for this metric -- error None only if it truly scored.

    The pass test is `num_cases_valid`, from the service's own aggregate, not
    the absence of an `error_message`. Those differ: a metric that returns no
    result at all has nothing to carry an error message, so an absence-based
    test reports it as a pass and puts an unusable metric in VERIFIED. Requiring
    a positive count of valid cases cannot fail that way.

    The spec name is worth capturing because it is not the one the client asked
    for. `RubricMetric.HALLUCINATION` resolves through METRIC_LATEST_SPEC_NAME
    to `hallucination_v2`, and the service answers with `hallucination_v1`.
    Since v1 and v2 of a metric can differ in what they require, the table is
    only valid for the spec the service actually served -- record it, so a
    surprise later can be traced to a version rather than guessed at.
    """
    for case in getattr(result, "eval_case_results", None) or []:
        for cand in getattr(case, "response_candidate_results", None) or []:
            for res in (getattr(cand, "metric_results", None) or {}).values():
                message = getattr(res, "error_message", None)
                if message:
                    return None, " ".join(str(message).split())[:300]

    for agg in getattr(result, "summary_metrics", None) or []:
        spec = getattr(agg, "metric_name", None)
        if getattr(agg, "num_cases_valid", 0):
            return spec, None
        return spec, f"no error, but num_cases_valid=0 of {getattr(agg, 'num_cases_total', '?')}"
    return None, "the service returned no result for this metric at all"


def main():
    parser = argparse.ArgumentParser(
        description="Discover which metrics can score an agent dataset."
    )
    parser.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT"))
    parser.add_argument(
        "--location", default=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
    )
    parser.add_argument("--model-location", default="global")
    parser.add_argument("--json", help="Also write the matrix here as JSON.")
    parser.add_argument(
        "--metrics",
        help="Comma-separated subset to test. Default: every metric in the SDK.",
    )
    args = parser.parse_args()

    if not args.project:
        fail("no project. Pass --project or set GOOGLE_CLOUD_PROJECT.")

    configure_vertex_env(args.project, args.model_location)

    import pandas as pd
    import agentplatform
    from agentplatform import types

    client = agentplatform.Client(project=args.project, location=args.location)
    agent = build_agent()

    if args.metrics:
        names = [n.strip().lower() for n in args.metrics.split(",") if n.strip()]
    else:
        names = sorted(
            n.lower() for n in dir(types.RubricMetric) if n.isupper()
        )
    names = [n for n in names if n not in SKIP]

    # Inference once per shape, reused for every metric. Driving the agent 20+
    # times would dominate both the cost and the wall clock, and nothing about
    # a metric's contract depends on which run produced the trace.
    inferred = {}
    for shape, rows in SHAPES.items():
        print(f"Running inference: {shape}-turn shape ...", file=sys.stderr)
        inferred[shape] = client.evals.run_inference(
            agent=agent, src=pd.DataFrame(rows)
        )

    matrix = {}
    for name in names:
        # Test each metric in the shape its name implies. The turn families are
        # disjoint, so testing both ways would double the bill to re-learn what
        # the prefix already says.
        shape = "multi" if name.startswith("multi_turn_") else "single"
        spec = None
        try:
            # Resolve exactly as the runner does, pin included. Sweeping
            # unversioned metrics while the runner pins them would produce a
            # table describing specs no run ever uses.
            metric = _metrics.resolve_metrics([name])[0]
            result = client.evals.evaluate(
                dataset=inferred[shape], metrics=[metric]
            )
            spec, error = verdict(result)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            error = f"{type(exc).__name__}: {' '.join(str(exc).split())[:280]}"
        matrix[name] = {
            "shape": shape, "ok": error is None, "spec": spec, "error": error
        }
        served = f" [{spec}]" if spec and spec != f"{name}_v1" else ""
        print(
            f"  {'PASS' if error is None else 'FAIL'}  {name}{served}",
            file=sys.stderr,
        )

    print("\n" + "=" * 72)
    for shape in ("multi", "single"):
        good = [n for n, r in matrix.items() if r["shape"] == shape and r["ok"]]
        print(f"\nVERIFIED, {shape}-turn ({len(good)}):")
        for n in good:
            print(f"    {n}")
    print("\nFAILED:")
    for n, r in matrix.items():
        if not r["ok"]:
            print(f"    {n} [{r['shape']}]\n        {r['error']}")

    print("\n\nPaste into _metrics.py:\n")
    print("VERIFIED = {")
    for shape in ("multi", "single"):
        good = sorted(n for n, r in matrix.items() if r["shape"] == shape and r["ok"])
        print(f"    {shape!r}: {{")
        for n in good:
            print(f"        {n!r},")
        print("    },")
    print("}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(matrix, fh, indent=2)
        print(f"\nJSON: {args.json}")


if __name__ == "__main__":
    main()
