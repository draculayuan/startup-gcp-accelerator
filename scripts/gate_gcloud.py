#!/usr/bin/env python3
"""PreToolUse gate for Google Cloud mutations.

Reads an Antigravity PreToolUse event on stdin and writes a decision on stdout.

Policy, in order:
  1. Prohibited commands            -> deny
  2. Read-only Cloud commands       -> no decision (settings allowlist auto-approves)
  3. Mutation without prior
     `gcloud help <leaf>`           -> deny, with the exact remedy
  4. Everything else that can touch
     Google Cloud                   -> force_ask, with a rendered review block

`force_ask` is used rather than `ask` because it re-prompts even when a
permission rule or an earlier session grant would already have allowed the
command. That is what makes "the founder reviews every command" hold for a whole
session rather than until the first "allow always" click.

Exit code is always 0: a crashing hook must not wedge the agent. On an internal
error we fail closed with force_ask.
"""

import json
import re
import shlex
import sys
from pathlib import Path

STATE_DIR = Path.home() / ".startup-gcp-accelerator" / "state"
PROFILE = Path.home() / ".startup-gcp-accelerator" / "profile.json"

# Tools that can reach Google Cloud.
CLOUD_BINARIES = {"gcloud", "bq", "gsutil", "gcloud.cmd"}

# Verbs that only read. Anything not recognised at all is treated as a mutation.
READ_ONLY_VERBS = {
    "describe", "list", "get", "get-iam-policy", "get-value", "help",
    "version", "info", "show", "ls", "head", "cat", "stat", "check",
    "search", "lookup", "validate", "test-iam-permissions", "print-settings",
}

# Known mutating verbs. Used only to locate the verb inside a command; an
# unrecognised verb is still treated as a mutation.
MUTATION_VERBS = {
    "create", "delete", "update", "patch", "add", "remove", "set", "unset",
    "deploy", "apply", "enable", "disable", "import", "export", "submit",
    "start", "stop", "restart", "resize", "reset", "promote", "rollback",
    "undelete", "clone", "copy", "cp", "mv", "rm", "rsync", "run", "call",
    "add-iam-policy-binding", "remove-iam-policy-binding", "set-iam-policy",
    "mk", "load", "query", "insert", "migrate", "replace", "attach", "detach",
    "sign-blob", "sign-url", "login", "revoke", "configure-docker",
}

KNOWN_VERBS = READ_ONLY_VERBS | MUTATION_VERBS

# Product groups whose name is also a verb. `gcloud run services list` is a
# read-only Cloud Run call, not the verb "run"; without this, the group name is
# resolved as the verb and every read-only Cloud Run and Cloud Deploy command is
# misfiled as a mutation.
GROUP_ALIASES = {"run", "deploy"}

# Denied outright. Each entry is (regex, reason).
PROHIBITED = [
    (r"\bgcloud\b.*\s(-q|--quiet)\b",
     "--quiet suppresses gcloud's own confirmation prompt, defeating human review."),
    (r"\bbq\b.*\s--quiet\b",
     "--quiet suppresses bq's own confirmation prompt, defeating human review."),
    (r"\bgcloud\s+projects\s+delete\b",
     "Project deletion is irreversible after the recovery window and is never agent-initiated."),
    # The `application-default` variant prints a live ADC token just as readily as
    # the plain form. It reads like a harmless auth check, which is precisely why
    # it needs naming explicitly rather than being left to the help precondition.
    (r"\bgcloud\s+auth\s+(application-default\s+)?print-(access|identity)-token\b",
     "Printing raw credentials risks leaking them into transcripts and logs. "
     "To check whether ADC is configured, re-run bootstrap.sh - it performs the "
     "same check with the output discarded."),
    (r"\bgcloud\s+iam\s+service-accounts\s+keys\s+create\b",
     "Long-lived service-account keys are a credential-exfiltration risk; use workload identity or ADC."),
    (r"(\.config/gcloud/|antigravity-oauth-token|application_default_credentials\.json|"
     r"credentials\.db|access_tokens\.db|legacy_credentials)",
     "Reads credential material into the transcript, where it persists in logs and "
     "conversation history. Use `gcloud auth list` to check identity."),
]

# Credential material that must never be read into a transcript. `settings.json`
# already carries a `read_file` deny for these paths, but that store is the CLI's
# and the desktop app keeps permissions per Project. The gate must hold on its
# own rather than assume Layer 1 is present on the surface in use.
CREDENTIAL_PATH = re.compile(
    r"(\.config/gcloud/|"
    r"antigravity-oauth-token|"
    r"application_default_credentials\.json|"
    r"credentials\.db|access_tokens\.db|legacy_credentials)"
)

# Tools that read file contents. `list_dir` is deliberately absent: knowing a
# credentials file exists is harmless, reading it is not.
FILE_READ_TOOLS = {"view_file", "read_file", "grep_search", "view_code_item"}

CREDENTIAL_REASON = (
    "Reads credential material into the transcript, where it persists in logs "
    "and conversation history. Use `gcloud auth list` to check identity, or ADC "
    "via a client library to use it."
)

# Wrappers that only launch another command. Stripped before the opaque-execution
# checks below so they see the command that actually runs. Without this, every
# anchored pattern below is a one-word bypass: `sudo make deploy` and
# `env FOO=1 ./deploy.sh` are the same actions as the forms that are caught.
LAUNCHER_PREFIX = re.compile(
    r"^\s*(?:"
    r"(?:sudo|nohup|command|exec|time|nice|stdbuf)(?:\s+-\S+)*\s+"
    r"|env(?:\s+-\S+)*\s+"
    r"|[A-Za-z_][A-Za-z0-9_]*=\S*\s+"
    r")+"
)

# Indirect execution: the gate cannot see what these will run.
OPAQUE_EXEC = [
    (r"^\s*(\./|bash\s+|sh\s+|zsh\s+)\S+\.(sh|bash)\b", "shell script"),
    (r"^\s*make\b", "Makefile target"),
    (r"^\s*(npm|pnpm|yarn)\s+run\b", "package script"),
]

# Tools whose mutating subcommand sits behind an arbitrary number of flags.
# `terraform -chdir=infra apply` and `kubectl -n prod apply -f x.yaml` are the
# ordinary way these are written, and a pattern that expects the subcommand in
# second position sees neither - so these are matched token-wise instead.
OPAQUE_SUBCOMMANDS = {
    "terraform": ({"apply", "destroy", "import"}, "Terraform state change"),
    "kubectl": ({"apply", "delete", "patch", "replace", "scale", "edit"},
                "Kubernetes mutation"),
    "helm": ({"install", "upgrade", "uninstall", "rollback"}, "Helm release change"),
    "skaffold": ({"run", "deploy", "delete"}, "Skaffold deployment"),
}

# Interpreters whose target file may call Cloud APIs directly, bypassing the CLI.
INTERPRETERS = {"python", "python3", "node", "deno", "bun", "ruby", "go"}
CLOUD_IMPORT = re.compile(
    r"(from\s+google\.cloud|import\s+google\.cloud|@google-cloud/|googleapis|"
    r"google\.auth|cloud\.google\.com/go|"
    # GenAI and evaluation SDKs. These bill for model and LLM-as-judge calls
    # without touching the gcloud CLI, so nothing above would catch them.
    r"\bagentplatform\b|google\.genai|google-genai|\bvertexai\b|"
    r"from\s+google\s+import\s+genai)",
    re.IGNORECASE,
)


def emit(payload):
    json.dump(payload, sys.stdout)
    sys.stdout.write("\n")
    sys.exit(0)


def allow_through():
    """Express no opinion and let the normal permission flow decide.

    This must be *silence*, not `{}`. Antigravity reads an empty JSON object as
    a decision it cannot interpret and denies the tool call outright - which
    would block every read-only command the gate is supposed to wave through.
    """
    sys.exit(0)


def load_profile():
    try:
        return json.loads(PROFILE.read_text())
    except Exception:
        return {}


def state_path(conversation_id):
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", conversation_id or "unknown")
    return STATE_DIR / f"{safe}.json"


def load_state(conversation_id):
    try:
        return json.loads(state_path(conversation_id).read_text())
    except Exception:
        return {"helped": []}


def record_help(conversation_id, leaf):
    state = load_state(conversation_id)
    if leaf not in state["helped"]:
        state["helped"].append(leaf)
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        state_path(conversation_id).write_text(json.dumps(state))
    except Exception:
        pass  # A read-only home must not break the gate.


# `-c`, and the combined short-flag clusters a shell accepts for it: `bash -lc`,
# `sh -ec`. Matching only the exact token `-c` left one extra letter enough to
# hide the payload from the scan below.
DASH_C = re.compile(r"^-[A-Za-z]*c$")

SHELL_LAUNCHERS = {"bash", "sh", "zsh", "dash", "ksh", "env"}

# `$(...)` and backticks run a command whose text never appears in command
# position, so it has to be lifted out and examined on its own.
SUBSTITUTION = re.compile(r"\$\(([^()]*)\)|`([^`]*)`")

ASSIGNMENT = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(\S*)$")


def collect_assignments(parts):
    """Map VAR -> value for the literal `VAR=value` statements on a line.

    `X=gcloud; $X compute instances delete vm1` puts the binary somewhere the
    token scan never looks. Only single-word literal assignments are resolved,
    which is enough to stop the indirection from reading as a different command.
    """
    env = {}
    for part in parts:
        try:
            tokens = shlex.split(part)
        except ValueError:
            continue
        for token in tokens:
            match = ASSIGNMENT.match(token)
            if not match:
                break  # assignments only ever lead a command
            env[match.group(1)] = match.group(2)
    return env


def expand(part, env):
    """Substitute known `$VAR` / `${VAR}` references. Literal, not a shell."""
    if not env or "$" not in part:
        return part
    for name, value in env.items():
        pattern = r"\$\{%s\}|\$%s\b" % (re.escape(name), re.escape(name))
        part = re.sub(pattern, lambda _match, v=value: v, part)
    return part


def split_segments(command_line, depth=0):
    """Flatten a command line into individual command segments.

    Splits on shell separators and lifts out everything that hides a command
    from command position: `bash -c` / `-lc` payloads, `$(...)` and backtick
    substitutions, and variables assigned the name of a binary.

    This reads shell syntax on a best-effort basis; it is not a shell and not a
    sandbox. Its job is to stop ordinary phrasing from slipping past the review
    prompt, not to defeat someone deliberately hiding a command from it.
    """
    if depth > 3:
        return [command_line]

    parts = re.split(r"(?:\|\||&&|[;\n|&])", command_line)
    env = collect_assignments(parts)
    segments = []
    for part in parts:
        part = expand(part.strip(), env)
        if not part:
            continue
        segments.append(part)

        for match in SUBSTITUTION.finditer(part):
            inner = match.group(1) or match.group(2) or ""
            if inner.strip():
                segments.extend(split_segments(inner, depth + 1))

        # A shell may itself be wrapped (`sudo bash -lc ...`), so resolve the
        # launcher against the unwrapped form.
        try:
            tokens = shlex.split(LAUNCHER_PREFIX.sub("", part))
        except ValueError:
            continue
        if not tokens or tokens[0].rsplit("/", 1)[-1] not in SHELL_LAUNCHERS:
            continue
        for i, token in enumerate(tokens[:-1]):
            if DASH_C.match(token):
                segments.extend(split_segments(tokens[i + 1], depth + 1))
    return segments


def tokenize(segment):
    try:
        return shlex.split(segment)
    except ValueError:
        return segment.split()


def cloud_invocation(tokens):
    """Return (binary, subcommand_words) if this segment calls a Cloud CLI."""
    for i, token in enumerate(tokens):
        base = token.rsplit("/", 1)[-1]
        if base in CLOUD_BINARIES:
            words = []
            for word in tokens[i + 1:]:
                if word.startswith("-"):
                    break
                words.append(word)
            return base, words
    return None, None


def resolve_verb(words):
    """Locate the verb in a Cloud CLI invocation.

    Cloud CLIs follow `<binary> GROUP... VERB [POSITIONAL...]`, so the verb is
    the first recognised verb token - not the last word, which is usually a
    resource name (`gcloud sql instances describe mydb`).

    A leading GROUP_ALIASES token is skipped: in `gcloud run services list` the
    first word is the Cloud Run group, and the real verb is `list`. It is only
    skipped in first position and only when something follows, so bare verb
    invocations like `gcloud version` still resolve.

    Returns (verb, index) or (None, -1) when no known verb appears, which the
    caller treats as a mutation.
    """
    for index, word in enumerate(words):
        if index == 0 and word in GROUP_ALIASES and len(words) > 1:
            continue
        if word in KNOWN_VERBS:
            return word, index
    return None, -1


def project_environments(profile):
    """Map project id -> environment tag, tolerating either profile shape.

    `projects` may be a list of objects (the documented shape) or a flat
    id -> env mapping. Both appear in the wild once founders hand-edit the file,
    and an unparsed profile must not silently downgrade a prod command to
    "environment UNKNOWN".
    """
    projects = profile.get("projects")
    envs = {}
    if isinstance(projects, dict):
        for pid, value in projects.items():
            envs[pid] = value.get("env") if isinstance(value, dict) else value
    elif isinstance(projects, list):
        for entry in projects:
            if isinstance(entry, dict) and entry.get("id"):
                envs[entry["id"]] = entry.get("env")
    return {k: v for k, v in envs.items() if isinstance(v, str)}


def target_project(tokens, profile):
    """Resolve the project this command targets, and whether it is production."""
    project = None
    for i, token in enumerate(tokens):
        if token.startswith("--project="):
            project = token.split("=", 1)[1]
        elif token == "--project" and i + 1 < len(tokens):
            project = tokens[i + 1]
    if not project:
        project = profile.get("default_project")
    return project, project_environments(profile).get(project, "unknown")


def review_block(command_line, binary, words, project, env, extra=None):
    verb, _ = resolve_verb(words)
    lines = [
        "REVIEW REQUIRED - Google Cloud mutation",
        "",
        f"  Command : {command_line.strip()}",
        f"  Tool    : {binary}",
        f"  Action  : {' '.join(words) if words else '(unparsed)'}",
        f"  Project : {project or '(not specified - will use active gcloud config)'}"
        + (f"  [{env.upper()}]" if env != "unknown" else "  [environment UNKNOWN]"),
    ]
    if extra:
        lines += ["", f"  Note    : {extra}"]
    if env == "prod":
        lines += ["", "  *** This targets a PRODUCTION project. ***"]
    if verb in {"delete", "destroy", "remove", "purge"}:
        lines += ["", "  *** Destructive verb - confirm this is reversible before approving. ***"]
    lines += [
        "",
        "Confirm the project, the resource, and the blast radius before approving.",
    ]
    return "\n".join(lines)


def main():
    try:
        event = json.load(sys.stdin)
    except Exception:
        emit({"decision": "force_ask", "reason": "Safety gate could not parse the event; review manually."})

    tool_call = event.get("toolCall") or {}
    tool_name = tool_call.get("name")
    args = tool_call.get("args") or {}

    if tool_name != "run_command":
        # The argument key for a path differs between tools and surfaces, so
        # scan every string value rather than guessing a field name.
        if tool_name in FILE_READ_TOOLS:
            for value in args.values():
                if isinstance(value, str) and CREDENTIAL_PATH.search(value):
                    emit({"decision": "deny",
                          "reason": f"Blocked by harness policy: {CREDENTIAL_REASON}"})
        allow_through()

    command_line = args.get("CommandLine") or ""
    if not command_line.strip():
        allow_through()

    conversation_id = event.get("conversationId", "")
    profile = load_profile()
    enforce_help = profile.get("enforce_help_precondition", True)

    for pattern, reason in PROHIBITED:
        if re.search(pattern, command_line):
            emit({"decision": "deny", "reason": f"Blocked by harness policy: {reason}"})

    for segment in split_segments(command_line):
        tokens = tokenize(segment)
        if not tokens:
            continue

        binary, words = cloud_invocation(tokens)

        if binary:
            if binary == "gcloud" and words and words[0] == "help":
                record_help(conversation_id, " ".join(words[1:]))
                allow_through()

            verb, verb_index = resolve_verb(words)
            # The leaf is the group path up to and including the verb, with
            # resource names dropped, so it matches what `gcloud help` takes.
            leaf = " ".join(words[: verb_index + 1]) if verb_index >= 0 else " ".join(words)

            if verb in READ_ONLY_VERBS:
                continue  # settings allowlist handles read-only

            project, env = target_project(tokens, profile)

            if enforce_help and binary == "gcloud":
                helped = load_state(conversation_id)["helped"]
                if not any(leaf.startswith(h) or h.startswith(leaf) for h in helped if h):
                    emit({
                        "decision": "deny",
                        "reason": (
                            f"Pre-flight syntax check needed for `gcloud {leaf}`.\n"
                            f"This is a routine step, not a refusal - nothing is wrong. "
                            f"Run `gcloud help {leaf}`, confirm the flags and whether "
                            f"--dry-run or --validate-only is supported, then propose the "
                            f"command again and it will go to the user for approval."
                        ),
                    })

            emit({
                "decision": "force_ask",
                "reason": review_block(command_line, binary, words, project, env),
            })

        # `sudo`, `env FOO=1` and friends only wrap the real command. The checks
        # below have to see what actually runs, not the wrapper.
        bare = LAUNCHER_PREFIX.sub("", segment)
        bare_tokens = tokenize(bare)

        def opaque(kind):
            emit({
                "decision": "force_ask",
                "reason": (
                    f"REVIEW REQUIRED - opaque execution ({kind})\n\n"
                    f"  Command : {segment}\n\n"
                    f"The safety gate cannot see which Cloud commands this will run.\n"
                    f"Show the file's contents and summarise its Cloud side effects "
                    f"before approving."
                ),
            })

        for pattern, kind in OPAQUE_EXEC:
            if re.search(pattern, bare):
                opaque(kind)

        if bare_tokens:
            verbs, kind = OPAQUE_SUBCOMMANDS.get(
                bare_tokens[0].rsplit("/", 1)[-1], (None, None))
            if verbs and any(word in verbs for word in bare_tokens[1:]):
                opaque(kind)

        base = bare_tokens[0].rsplit("/", 1)[-1] if bare_tokens else ""
        if base in INTERPRETERS:
            for token in bare_tokens[1:]:
                if token.startswith("-"):
                    continue
                candidate = Path(token)
                try:
                    if candidate.is_file() and CLOUD_IMPORT.search(candidate.read_text(errors="ignore")):
                        emit({
                            "decision": "force_ask",
                            "reason": (
                                f"REVIEW REQUIRED - script calls Google Cloud APIs directly\n\n"
                                f"  Command : {segment}\n"
                                f"  File    : {candidate}\n\n"
                                f"This bypasses the gcloud CLI and its confirmation prompts."
                            ),
                        })
                except Exception:
                    pass
                break

    allow_through()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # fail closed
        emit({"decision": "force_ask", "reason": f"Safety gate error ({exc}); review manually."})
