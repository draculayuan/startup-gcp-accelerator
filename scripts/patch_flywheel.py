#!/usr/bin/env python3
"""Align the flywheel's synthesis examples with the pinned SDK release.

The vendored `agent-platform-eval-flywheel` skill shows
`generate_conversation_scenarios` in four places. This harness pins
`agentplatform 1.164.0`, and against that release two details of those examples
need adjusting before they run:

  1. Call shape. `references/sdk_patterns.md` Pattern 3 and
     `references/dataset_schema.md` pass `agents=`, `root_agent_id=` and
     `user_scenario_generation_config=` as top-level keyword arguments. In this
     release those are fields *of* `AgentInfo` and *of* the config, and the call
     signature takes `agent_info=` plus a required `config=`. `SKILL.md` already
     shows the current shape.
  2. Config field names. `sdk_patterns.md` Pattern 8 and `SKILL.md` use
     `user_scenario_count` and `simulation_instruction`. Those are the names
     this release sends on the wire; the names it reads from the caller are
     `count`, `generation_instruction` and `environment_context`. The server
     reports the wire name when a value is missing, so the client-side name is
     the one to set.

Both adjustments matter because synthesis is a billed call, and it is worth
getting the request right on the first one rather than iterating against the
service.

Run from bootstrap.sh after vendoring and before the plugin install: the
flywheel is build output -- gitignored, re-fetched every run -- so a hand-edit
of the installed copy is lost on the next bootstrap.

Idempotent, and non-fatal by design: a replacement that no longer matches means
the upstream text has moved on, which is a review task and not a reason to
block an install. Every skipped patch is reported.

    python3 patch_flywheel.py <path to agent-platform-eval-flywheel>

Exit codes: 0 always, unless the directory argument is missing or absent.
"""

import sys
from pathlib import Path

SDK_VERSION = "agentplatform 1.164.0"
MARKER = f"<!-- locally aligned with {SDK_VERSION}"

BANNER = f"""{MARKER} by startup-gcp-accelerator.
     The `generate_conversation_scenarios` examples below were adjusted to this
     SDK release: the call takes `agent_info=` (or `agent=`) plus a required
     `config=`, and the config fields read from the caller are `count`,
     `generation_instruction` and `environment_context`, which this release maps
     onto the wire names `user_scenario_count`, `simulation_instruction` and
     `environment_data`. Check both against the SDK version you have installed;
     a re-vendor at a new SKILLS_REF replaces this file. For a worked example,
     see skills/gcp-ai-eval/scripts/generate_eval_dataset.py, which asserts the
     request body locally before making the billed call. -->
"""

# The local-agent call in the shape this SDK release takes, shared by the two
# files that show the older one. Written out in full rather than reassembled
# from the original, so the result cannot inherit half of the original's shape.
def local_call(agent_id, instruction, sim, env):
    return f'''scenarios = client.evals.generate_conversation_scenarios(
    # `agent_info=`, not `agents=`/`root_agent_id=`: in this release those are
    # fields of AgentInfo. Flattening them raises TypeError locally.
    agent_info=types.evals.AgentInfo(
        agents={{
            "{agent_id}": types.evals.AgentConfig(
                agent_id="{agent_id}",
                instruction="{instruction}",
            ),
        }},
        root_agent_id="{agent_id}",
    ),
    # `config=` is required. Its caller-side field names differ from the wire
    # names this release sends: count -> user_scenario_count,
    # generation_instruction -> simulation_instruction, environment_context ->
    # environment_data. Set the caller-side names.
    config=types.evals.UserScenarioGenerationConfig(
        count=10,
        generation_instruction="{sim}",
        environment_context="{env}",
        model_name="gemini-2.5-flash",
    ),
    # The generator's model is preview-only in `global`; from a regional
    # location the call is refused with INVALID_ARGUMENT without this.
    allow_cross_region_model=True,
)'''


PATCHES = {
    "references/sdk_patterns.md": [
        (
            '''scenarios = client.evals.generate_conversation_scenarios(
    agents={
        "agent": types.evals.AgentConfig(
            agent_id="agent",
            instruction="You are a customer support agent for an airline.",
        ),
    },
    root_agent_id="agent",
    user_scenario_generation_config=types.evals.UserScenarioGenerationConfig(
        user_scenario_count=10,
        simulation_instruction="Simulate customers with flight booking issues.",
        environment_data="Flights available: NYC-LAX, NYC-SFO. Cancellation policy: free within 24h.",
        model_name="gemini-2.5-flash",
    ),
)''',
            local_call(
                "agent",
                "You are a customer support agent for an airline.",
                "Simulate customers with flight booking issues.",
                "Flights available: NYC-LAX, NYC-SFO. Cancellation policy: free within 24h.",
            ),
        ),
        # Pattern 8, managed agents. The call shape already matches this
        # release; the dict config carries the wire names, and a dict is read
        # by the same keys as the config model.
        (
            '''    config={
        "user_scenario_count": 5,
        "simulation_instruction": "Create agent scenarios",
    },''',
            '''    config={
        # Caller-side names for agentplatform 1.164.0. These are sent as
        # "user_scenario_count" and "simulation_instruction"; setting the wire
        # names here leaves the values unset on the request.
        "count": 5,
        "generation_instruction": "Create agent scenarios",
    },''',
        ),
    ],
    "references/dataset_schema.md": [
        (
            '''scenarios = client.evals.generate_conversation_scenarios(
    agents={
        "my_agent": types.evals.AgentConfig(
            agent_id="my_agent",
            instruction="You are a helpful customer support agent.",
        )
    },
    root_agent_id="my_agent",
    user_scenario_generation_config=types.evals.UserScenarioGenerationConfig(
        user_scenario_count=10,
        simulation_instruction="Simulate a customer asking about order status.",
        environment_data="Orders can be: pending, shipped, delivered, cancelled.",
        model_name="gemini-2.5-flash",
    ),
)''',
            local_call(
                "my_agent",
                "You are a helpful customer support agent.",
                "Simulate a customer asking about order status.",
                "Orders can be: pending, shipped, delivered, cancelled.",
            ),
        ),
    ],
    "SKILL.md": [
        (
            '''required. The config class is `types.evals.UserScenarioGenerationConfig`,
    not `types.UserScenarioGenerationConfig`. Set its `user_scenario_count`
    (1-100): it defaults to None, the client accepts that, and the server
    rejects the call with `400 INVALID_ARGUMENT`. `count` is a separate field
    and does not substitute for it. Stage 2 plays the scenarios out.''',
            '''required. The config class is `types.evals.UserScenarioGenerationConfig`,
    not `types.UserScenarioGenerationConfig`. On `agentplatform 1.164.0`, set
    its **`count`** (1-100): it defaults to None, the client accepts that, and
    the server rejects the call with `400 INVALID_ARGUMENT`. That error names
    `user_scenario_count`, which is the *wire* field `count` maps onto -- so
    the field to set is `count`, not the one the message quotes. The same pair
    of names applies to `generation_instruction` (wire:
    `simulation_instruction`) and `environment_context` (wire:
    `environment_data`). Stage 2 plays the scenarios out.''',
        ),
    ],
}


def insert_banner(text, path):
    """Put the banner where a reader will see it, without breaking frontmatter."""
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            cut = end + len("\n---\n")
            return text[:cut] + "\n" + BANNER + text[cut:]
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("# "):
            return "\n".join(lines[: i + 1]) + "\n\n" + BANNER + "\n".join(lines[i + 1 :])
    return BANNER + text


def main():
    if len(sys.argv) != 2:
        print(f"usage: {Path(sys.argv[0]).name} <flywheel dir>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1])
    if not root.is_dir():
        print(f"    warning: {root} is not a directory; nothing patched", file=sys.stderr)
        return 0

    for rel, replacements in PATCHES.items():
        path = root / rel
        if not path.is_file():
            print(f"    warning: {rel} is not in the flywheel at this ref; skipped",
                  file=sys.stderr)
            continue
        text = original = path.read_text(encoding="utf-8")
        if MARKER in text:
            print(f"    {rel} already aligned")
            continue

        applied = 0
        for old, new in replacements:
            if old not in text:
                print(f"    warning: {rel}: a passage no longer matches and was left "
                      f"alone. Upstream text changed; re-check it against "
                      f"{SDK_VERSION}.", file=sys.stderr)
                continue
            text = text.replace(old, new, 1)
            applied += 1

        if applied == 0:
            print(f"    warning: {rel}: nothing matched; left unmodified", file=sys.stderr)
            continue

        path.write_text(insert_banner(text, path), encoding="utf-8")
        print(f"    {rel} aligned ({applied}/{len(replacements)})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
