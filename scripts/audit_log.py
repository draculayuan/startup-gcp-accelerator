#!/usr/bin/env python3
"""PostToolUse audit logger for Google Cloud commands.

Appends one JSON object per executed Cloud command to
~/.startup-gcp-accelerator/audit/commands.jsonl

The log is the only durable record of what the agent actually ran. It matters
more here than in a single-team setup: across a batch of startups it is how you
spot a harness gap before it becomes an incident.

Timestamps come from the event where available rather than from the clock, so
the log stays meaningful when replayed.
"""

import json
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from gate_gcloud import CLOUD_IMPORT, INTERPRETERS
except Exception:  # pylint: disable=broad-exception-caught
    CLOUD_IMPORT, INTERPRETERS = None, ()

AUDIT_DIR = Path.home() / ".startup-gcp-accelerator" / "audit"
AUDIT_FILE = AUDIT_DIR / "commands.jsonl"

CLOUD_MARKERS = ("gcloud", "bq ", "gsutil", "kubectl", "terraform", "helm")


def cloud_script(command_line, cwd=None):
    """Path of an interpreted script that calls Cloud APIs directly, if any.

    CLOUD_MARKERS names CLI binaries, so `python3 run_eval.py` matched nothing
    and the log was silent about it. The gate is not: it force_asks that command
    via CLOUD_IMPORT, because a script importing agentplatform or vertexai bills
    for model and LLM-as-judge calls without the CLI ever being involved. So the
    log recorded every command the gate waved through on a marker and missed the
    one capability that bills per row.

    The test is imported from the gate rather than restated, for the reason the
    eval scripts share `_agent_loader`: two copies of a rule drift, and the
    direction this one drifts is a command reviewed by the founder and then
    absent from the only durable record that it happened.

    Relative paths are resolved against the command's own `cwd` rather than the
    hook process's. The agent runs these from the founder's repository root and
    the hook does not, so `python3 skills/.../local_agent_evaluation.py` is a
    path that exists for the command and not for us.
    """
    if CLOUD_IMPORT is None:
        return None
    try:
        tokens = shlex.split(command_line)
    except ValueError:
        tokens = command_line.split()
    for i, token in enumerate(tokens):
        if token.rsplit("/", 1)[-1] not in INTERPRETERS:
            continue
        for candidate in tokens[i + 1:]:
            if candidate.startswith("-"):
                continue
            try:
                path = Path(candidate)
                if not path.is_absolute() and cwd:
                    path = Path(cwd) / path
                if path.is_file() and CLOUD_IMPORT.search(
                    path.read_text(errors="ignore")
                ):
                    return str(path)
            except Exception:  # pylint: disable=broad-exception-caught
                pass
            break
    return None


def main():
    try:
        event = json.load(sys.stdin)
    except Exception:
        return

    tool_call = event.get("toolCall") or {}
    if tool_call.get("name") != "run_command":
        return

    args = tool_call.get("args") or {}
    command_line = args.get("CommandLine") or ""
    script = cloud_script(command_line, args.get("Cwd"))
    if not script and not any(marker in command_line for marker in CLOUD_MARKERS):
        return

    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "conversationId": event.get("conversationId"),
        "stepIdx": event.get("stepIdx"),
        "model": event.get("modelName"),
        "cwd": args.get("Cwd"),
        "command": command_line,
        # Which rule caught it. A reader auditing spend needs to tell a gcloud
        # call apart from a script that billed the evals API without one.
        "via": "script" if script else "cli",
        "script": script,
        "error": event.get("error") or None,
        "outcome": "error" if event.get("error") else "ok",
    }

    try:
        AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        with AUDIT_FILE.open("a") as handle:
            handle.write(json.dumps(record) + "\n")
    except Exception:
        pass  # Never break the agent over a logging failure.


if __name__ == "__main__":
    main()
    json.dump({}, sys.stdout)
