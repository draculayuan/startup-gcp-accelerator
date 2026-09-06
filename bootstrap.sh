#!/usr/bin/env bash
#
# startup-gcp-accelerator — global install for Google Antigravity 2.0.
#
# This is not an officially supported Google product. Unofficial project, no
# warranty, no support commitment.
#
#   ./bootstrap.sh              install or repair
#   ./bootstrap.sh --dry-run    print every action, change nothing
#   ./bootstrap.sh --update     reinstall pinned dependencies at current refs
#   ./bootstrap.sh --uninstall  remove this harness (leaves Google plugins)
#
# Idempotent: safe to re-run. Merges into existing settings rather than
# replacing them — founders have their own configuration and we do not own it.

set -euo pipefail

# --- Pinned dependency refs -------------------------------------------------
# Bumping these is a deliberate act. Upstream plugins change without notice and
# an unpinned install means two startups in the same batch get different tools.
SKILLS_REF="c4386c398f1f5f0b78d493612df5dbd0bd8baf49"   # google/skills @ main, 2026-08-26
CONDUCTOR_REF="conductor-v0.4.1"

# There is deliberately no google/skills URL here. SKILLS_REF is a commit SHA,
# and installing a GitHub URL resolves its ref by cloning that ref as a branch —
# `git clone --branch <sha>` is not a thing, so a pinned URL fails with "Could
# not find remote branch". Section 2 fetches the archive at the SHA instead.
# Conductor keeps its URL: CONDUCTOR_REF is a tag, which clones fine.
CONDUCTOR_REPO="https://github.com/gemini-cli-extensions/conductor/tree/${CONDUCTOR_REF}"

PLUGIN_NAME="startup-gcp-accelerator"
GEMINI_HOME="${HOME}/.gemini"
PLUGIN_DIR="${GEMINI_HOME}/config/plugins"
SETTINGS="${GEMINI_HOME}/antigravity-cli/settings.json"
MCP_CONFIG="${GEMINI_HOME}/config/mcp_config.json"
GLOBAL_RULES="${GEMINI_HOME}/GEMINI.md"
STATE_HOME="${HOME}/.startup-gcp-accelerator"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DK_API="developerknowledge.googleapis.com"
# Quota project for the docs MCP. Per-founder, resolved at install time and
# never committed.
QUOTA_PROJECT="$(gcloud config get-value project 2>/dev/null || true)"
[[ "$QUOTA_PROJECT" == "(unset)" ]] && QUOTA_PROJECT=""

RULE_BEGIN="<!-- BEGIN startup-gcp-accelerator -->"
RULE_END="<!-- END startup-gcp-accelerator -->"

DRY_RUN=0
UPDATE=0
UNINSTALL=0

for arg in "$@"; do
  case "$arg" in
    --dry-run)   DRY_RUN=1 ;;
    --update)    UPDATE=1 ;;
    --uninstall) UNINSTALL=1 ;;
    -h|--help)   sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)           echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

# --- Output -----------------------------------------------------------------
step()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
info()  { printf '    %s\n' "$*"; }
warn()  { printf '    \033[33mwarning:\033[0m %s\n' "$*" >&2; }
fail()  { printf '\n\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }

run() {
  if [[ $DRY_RUN -eq 1 ]]; then
    printf '    \033[2m[dry-run] %s\033[0m\n' "$*"
  else
    "$@"
  fi
}

# --- Python packages for /gcp-ai-eval ---------------------------------------
# The eval scripts import these; nothing else in the harness does. This was
# invisible for a long time because the harness was built on a Vertex AI
# Workbench image, which preinstalls all four — "needs no Python setup" is
# indistinguishable from "does no Python setup" until someone runs it on a
# plain VM and /gcp-ai-eval dies with ModuleNotFoundError.
#
# Installed into whatever `python3` resolves to, deliberately: the agent runs
# these scripts as `python3 <path>`, so a venv here would need activating by
# something that never sees it. Only missing modules are installed, so a
# working image is left exactly as it is, and a failure warns rather than
# exits — the other capabilities need none of this.
#
# `agentplatform` is a module *inside* google-cloud-aiplatform, not a
# distribution: `pip install agentplatform` is the wrong turn the import error
# invites, and it installs an unrelated package. See scripts/requirements.txt,
# which carries the same list for anyone installing by hand.
PYDEPS=(
  "google.adk:google-adk==2.8.0"
  "agentplatform:google-cloud-aiplatform==1.164.0"
  "pandas:pandas>=2.0"
  "requests:requests>=2.31"
)

check_pydeps() {
  local missing=() pair module spec
  for pair in "${PYDEPS[@]}"; do
    module="${pair%%:*}"
    spec="${pair#*:}"
    python3 -c "import ${module}" 2>/dev/null || missing+=("$spec")
  done

  if [[ ${#missing[@]} -eq 0 ]]; then
    info "eval dependencies present"
    return
  fi

  # Version specifiers contain '>=', so the *printed* command needs quoting or
  # a copy-paste redirects into a file called '=2.0'. The install below passes
  # the array directly and needs none.
  local quoted=""
  for spec in "${missing[@]}"; do quoted+=" '$spec'"; done

  if [[ $DRY_RUN -eq 1 ]]; then
    printf '    \033[2m[dry-run] python3 -m pip install%s\033[0m\n' "$quoted"
    return
  fi

  info "installing: ${missing[*]}"
  if python3 -m pip install --quiet "${missing[@]}" 2>/dev/null \
     || python3 -m pip install --quiet --user "${missing[@]}"; then
    info "eval dependencies installed"
  else
    warn "Could not install: ${missing[*]}
    /gcp-ai-eval will fail at import until they are present. Install them into
    the same interpreter the agent runs ($(command -v python3)):
      python3 -m pip install${quoted}
    On a PEP 668 'externally managed' interpreter, add --break-system-packages
    or point python3 at a virtualenv that has them."
  fi
}

# --- Uninstall --------------------------------------------------------------
if [[ $UNINSTALL -eq 1 ]]; then
  step "Removing ${PLUGIN_NAME}"
  run agy plugin uninstall "${PLUGIN_NAME}" || warn "plugin was not installed"
  if [[ -f "$GLOBAL_RULES" ]] && grep -qF "$RULE_BEGIN" "$GLOBAL_RULES"; then
    run python3 - "$GLOBAL_RULES" "$RULE_BEGIN" "$RULE_END" <<'PY'
import re, sys
path, begin, end = sys.argv[1:4]
text = open(path).read()
open(path, "w").write(re.sub(re.escape(begin) + r".*?" + re.escape(end) + r"\n?", "", text, flags=re.S))
PY
    [[ $DRY_RUN -eq 1 ]] || info "removed harness rules from GEMINI.md"
  fi
  # The broad gcloud/bq grants are safe only because the PreToolUse hook
  # force_asks every mutation. Removing the hook while leaving them in place
  # would silently convert this into an unreviewed-execution setup.
  if [[ -f "$SETTINGS" ]]; then
    run python3 - "$SETTINGS" "${SRC}/settings.defaults.json" <<'PY'
import json, pathlib, sys
p = pathlib.Path(sys.argv[1])
s = json.loads(p.read_text())
# Derive the grant list from settings.defaults.json rather than repeating it.
# A hardcoded copy drifts the moment a rule is added there, silently orphaning
# grants on uninstall. Fall back to the broad pair if the defaults are missing:
# those are the ones that actually matter, since leaving them without the hook
# would convert this into an unreviewed-execution setup.
grants = {"command(gcloud)", "unsandboxed(gcloud)", "command(bq)", "unsandboxed(bq)"}
defaults = pathlib.Path(sys.argv[2])
if defaults.is_file():
    raw = defaults.read_text().replace("${HOME}", str(pathlib.Path.home()))
    try:
        grants |= set(json.loads(raw).get("permissions", {}).get("allow", []))
    except json.JSONDecodeError:
        pass
perms = s.get("permissions")
allow = perms.get("allow", []) if isinstance(perms, dict) else []
removed = [r for r in allow if r in grants]
if removed:
    perms["allow"] = [r for r in allow if r not in grants]
    p.write_text(json.dumps(s, indent=2) + "\n")
print("    revoked broad grants:", ", ".join(removed) if removed else "none")
PY
  fi

  # We created this registration, so we remove it. google-cloud-core ships its
  # own developer-knowledge entry, so docs lookups degrade rather than vanish.
  if [[ -f "$MCP_CONFIG" ]]; then
    run python3 - "$MCP_CONFIG" <<'PY'
import json, pathlib, sys
p = pathlib.Path(sys.argv[1])
try:
    s = json.loads(p.read_text())
except Exception:
    sys.exit(0)
servers = s.get("mcpServers")
if isinstance(servers, dict) and servers.pop("developer-knowledge", None) is not None:
    p.write_text(json.dumps(s, indent=2) + "\n")
    print("    removed mcpServers.developer-knowledge")
else:
    print("    no developer-knowledge entry to remove")
PY
  fi

  info "left in place: Google plugins, and ${STATE_HOME} (profile + audit log)"
  # Deliberately not disabled: other things on the project may use it by now,
  # and turning off an API is not ours to decide.
  info "${DK_API} stays enabled; disable it yourself if you want it off"
  exit 0
fi

# --- 1. Preflight -----------------------------------------------------------
step "Preflight"

command -v python3 >/dev/null 2>&1 || fail "python3 is required (the safety hooks are Python)."

if ! command -v agy >/dev/null 2>&1; then
  fail "The Antigravity CLI ('agy') is not on PATH.
    Install it, sign in once with 'agy', then re-run this script."
fi
info "agy      $(agy --version 2>/dev/null || echo 'version unknown')"

if ! command -v gcloud >/dev/null 2>&1; then
  fail "The gcloud CLI is not on PATH.
    Install it from https://cloud.google.com/sdk/docs/install and re-run."
fi
info "gcloud   $(gcloud version 2>/dev/null | awk '/Google Cloud SDK/{print $NF; exit}' || echo 'version unknown')"
info "python3  $(python3 --version 2>&1 | awk '{print $2}')"

# --- 2. The pinned google/skills archive ------------------------------------
# One download serves both the dependency plugins and the vendored skills.
#
# Everything comes out of the archive at the pinned SHA rather than being
# installed from a GitHub URL, because a URL install clones its ref as a branch
# and SKILLS_REF is a commit. google/skills publishes no tags, so there is no
# stable name to pin to instead — extracting the plugin directory and installing
# it from disk is what keeps the exact pin. `agy plugin install` copies the
# directory it is given, so a temporary extraction is safe.
step "Fetching google/skills at the pinned ref"

SKILLS_PLUGINS=(
  google-cloud-core
  google-cloud-well-architected
)

# Vendored rather than installed for two different reasons. The first two live
# under skills/cloud/ upstream, which belongs to no plugin, so no plugin install
# can reach them. The last two *are* in a plugin — gemini-enterprise-agent-
# platform — but it ships fifteen skills, and installing it to get two would put
# thirteen unrelated ones (tuning, model registry, prompt management) in front of
# every founder, against the small-known-set decision.
#
# Either way they are build output, not source: .gitignore excludes them, every
# run re-fetches, and the harness carries no forked copy to drift out of date.
VENDORED_SKILLS=(
  google-cloud-solution-architecture
  google-cloud-solution-build-deploy-agents
  agent-platform-eval-flywheel
  agent-platform-alert-configuration
)

WORK_DIR=""
PAYLOAD=""
trap '[[ -n "$WORK_DIR" ]] && rm -rf "$WORK_DIR"' EXIT

fetch_skills_archive() {
  local paths=() p
  WORK_DIR="$(mktemp -d)"

  curl -sSL --max-time 180 \
    "https://github.com/google/skills/archive/${SKILLS_REF}.tar.gz" \
    -o "${WORK_DIR}/skills.tar.gz" || return 1

  for p in "${SKILLS_PLUGINS[@]}";  do paths+=("skills-${SKILLS_REF}/plugins/cloud/${p}"); done
  for p in "${VENDORED_SKILLS[@]}"; do paths+=("skills-${SKILLS_REF}/skills/cloud/${p}");  done
  tar -xzf "${WORK_DIR}/skills.tar.gz" -C "$WORK_DIR" "${paths[@]}" 2>/dev/null || return 1

  PAYLOAD="${WORK_DIR}/skills-${SKILLS_REF}"
}

if [[ $DRY_RUN -eq 1 ]]; then
  printf '    \033[2m[dry-run] fetch google/skills@%s\033[0m\n' "${SKILLS_REF:0:8}"
elif ! command -v curl >/dev/null 2>&1 || ! command -v tar >/dev/null 2>&1; then
  warn "curl and tar are required to fetch google/skills at a pinned commit.
    Both the dependency plugins and the vendored skills will be skipped."
elif fetch_skills_archive; then
  info "google/skills@${SKILLS_REF:0:8}  fetched"
else
  PAYLOAD=""
  warn "Could not fetch google/skills@${SKILLS_REF:0:8}. Re-run to retry."
fi

# --- 2a. Dependency plugins --------------------------------------------------
step "Installing dependency plugins (pinned)"

installed_plugins="$(agy plugin list 2>/dev/null || echo '{}')"

install_plugin() {
  local name="$1" source="$2"
  if [[ $UPDATE -eq 0 ]] && grep -q "\"${name}\"" <<<"$installed_plugins"; then
    info "${name} — already installed, skipping (use --update to refresh)"
    return 0
  fi
  info "${name} <- ${source}"
  run agy plugin install "$source" || warn "failed to install ${name}; continuing"
}

for p in "${SKILLS_PLUGINS[@]}"; do
  if [[ $DRY_RUN -eq 1 ]]; then
    install_plugin "$p" "google/skills@${SKILLS_REF:0:8} plugins/cloud/${p}"
  elif [[ -n "$PAYLOAD" && -d "${PAYLOAD}/plugins/cloud/${p}" ]]; then
    install_plugin "$p" "${PAYLOAD}/plugins/cloud/${p}"
  else
    warn "${p} was not fetched, so it cannot be installed. /architecture-review
    needs google-cloud-well-architected for its six pillars and /gcp-do needs
    google-cloud-core. Re-run bootstrap.sh once the fetch succeeds."
  fi
done

install_plugin conductor "${CONDUCTOR_REPO}"

# --- 2b. Vendored Google skills ---------------------------------------------
step "Vendoring Google skills into this plugin"

if [[ $DRY_RUN -eq 1 ]]; then
  printf '    \033[2m[dry-run] vendor %s\033[0m\n' "${VENDORED_SKILLS[*]}"
elif [[ -z "$PAYLOAD" ]]; then
  warn "Not fetched. /gcp-design, /gcp-ai-eval and /gcp-ai-monitor will report
    their skills as missing rather than working from memory."
else
  for s in "${VENDORED_SKILLS[@]}"; do
    if [[ -f "${PAYLOAD}/skills/cloud/${s}/SKILL.md" ]]; then
      rm -rf "${SRC}/skills/${s}"
      mv "${PAYLOAD}/skills/cloud/${s}" "${SRC}/skills/${s}"
      info "${s} <- google/skills@${SKILLS_REF:0:8}"
    else
      warn "${s} is not in the archive at this ref. The capability that needs it
    will say so rather than working from memory."
    fi
  done

  # The flywheel shows generate_conversation_scenarios four times, and against
  # the agentplatform release this harness pins those examples need two
  # adjustments: the call signature moved to `agent_info=` plus a required
  # `config=`, and the config fields read from the caller are `count` /
  # `generation_instruction` / `environment_context` rather than the wire names.
  # Synthesis is a billed call, so it is worth getting right on the first one.
  # Adjusted here rather than by hand because the flywheel is build output: it
  # is re-fetched on every run, so an edit to the installed copy is gone by the
  # next bootstrap. Runs before the plugin install so the aligned text is what
  # ships. Non-fatal — a passage that no longer matches is a review task, not a
  # reason to block an install. See scripts/patch_flywheel.py.
  if [[ -d "${SRC}/skills/agent-platform-eval-flywheel" ]]; then
    run python3 "${SRC}/scripts/patch_flywheel.py" \
      "${SRC}/skills/agent-platform-eval-flywheel" \
      || warn "flywheel alignment did not apply cleanly; see above."
  fi
fi

# --- 3. This harness --------------------------------------------------------
step "Installing ${PLUGIN_NAME}"

[[ -f "${SRC}/plugin.json" ]] || fail "plugin.json not found in ${SRC} — run this script from the harness repo."

# A local install copies the source directory verbatim, so scrub build detritus
# that would otherwise ship inside the plugin.
run find "${SRC}" -type d \( -name __pycache__ -o -name .ipynb_checkpoints \) -prune -exec rm -rf {} + 2>/dev/null || true

run agy plugin validate "${SRC}" || fail "plugin validation failed; fix the errors above and re-run."

# Local install copies the directory, so remove any previous copy first —
# otherwise deleted files survive as stale components.
if [[ -d "${PLUGIN_DIR}/${PLUGIN_NAME}" ]]; then
  run agy plugin uninstall "${PLUGIN_NAME}" >/dev/null 2>&1 || true
  run rm -rf "${PLUGIN_DIR}/${PLUGIN_NAME}"
fi
run agy plugin install "${SRC}"

# An absent entry in config.json's plugin map currently defaults to enabled, but
# the desktop app renders its Customizations list from that map. Write the entry
# explicitly so the plugin is visibly on there rather than relying on a default.
# Disabling it stops the hooks loading entirely, so this state is load-bearing.
run agy plugin enable "${PLUGIN_NAME}" >/dev/null 2>&1 || warn "could not mark ${PLUGIN_NAME} as enabled"

# Maintainer docs are not plugin components, but a local install copies the
# directory verbatim and they end up inside the installed plugin as clutter the
# agent may surface. Remove them from the installed copy, never from ${SRC}.
if [[ $DRY_RUN -eq 0 && -d "${PLUGIN_DIR}/${PLUGIN_NAME}" ]]; then
  for doc in DESIGN.md README.md high_level_requirements.txt bootstrap.sh settings.defaults.json .gitignore; do
    rm -f "${PLUGIN_DIR}/${PLUGIN_NAME}/${doc}"
  done
  # Editor and interpreter droppings. .gitignore keeps these out of the repo but
  # not out of a local install, which copies the working tree as it stands — so
  # a checkpoint of a SKILL.md would install beside the real one as a second,
  # stale copy of the same skill.
  find "${PLUGIN_DIR}/${PLUGIN_NAME}" \
    \( -name '.ipynb_checkpoints' -o -name '__pycache__' \) -type d -prune \
    -exec rm -rf {} + 2>/dev/null || true
fi

# --- 4. Global rules --------------------------------------------------------
# 'rules' is not one of the plugin component types Antigravity loads (skills,
# agents, commands, mcpServers, hooks), so always-on rules are concatenated into
# the global GEMINI.md between markers. Re-running replaces only our block.
step "Installing always-on rules into GEMINI.md"

if [[ $DRY_RUN -eq 1 ]]; then
  info "[dry-run] would write harness rules block into ${GLOBAL_RULES}"
else
  mkdir -p "$GEMINI_HOME"
  touch "$GLOBAL_RULES"
  python3 - "$GLOBAL_RULES" "$SRC" "$RULE_BEGIN" "$RULE_END" <<'PY'
import re, sys, pathlib

target, src, begin, end = sys.argv[1:5]
rules_dir = pathlib.Path(src) / "rules"

# Only always_on rules belong here; the 12,000 character budget for global rules
# is small and every character is charged to every conversation. Guidance that is
# situational ships as a skill instead, so progressive disclosure pays for it.
parts = []
for name in ("startup-profile.md", "gcp-safety.md", "capability-routing.md"):
    path = rules_dir / name
    if not path.exists():
        continue
    body = path.read_text()
    body = re.sub(r"\A---\n.*?\n---\n", "", body, flags=re.S)  # strip frontmatter
    parts.append(body.strip())

block = "\n".join([begin, "", "\n\n---\n\n".join(parts), "", end, ""])

text = pathlib.Path(target).read_text()
pattern = re.escape(begin) + r".*?" + re.escape(end) + r"\n?"
if re.search(pattern, text, flags=re.S):
    text = re.sub(pattern, block, text, flags=re.S)
else:
    text = (text.rstrip() + "\n\n" if text.strip() else "") + block

pathlib.Path(target).write_text(text)

size = len(block)
print(f"    wrote {size} characters of always-on rules")
if size > 12000:
    print(f"    warning: exceeds the 12,000 character global rules limit", file=sys.stderr)
PY
fi

# --- 5. Settings ------------------------------------------------------------
step "Merging permissions into settings.json"

if [[ $DRY_RUN -eq 1 ]]; then
  info "[dry-run] would merge ${SRC}/settings.defaults.json into ${SETTINGS}"
else
  mkdir -p "$(dirname "$SETTINGS")"
  python3 - "$SETTINGS" "${SRC}/settings.defaults.json" <<'PY'
import json, pathlib, sys

target, defaults_path = (pathlib.Path(p) for p in sys.argv[1:3])
raw = defaults_path.read_text()
# read_file targets must be absolute; a literal "~" makes the sandbox refuse to
# start with "non-absolute file path", which blocks every command in the session.
raw = raw.replace("${HOME}", str(pathlib.Path.home()))
defaults = json.loads(raw)
for key in [k for k in defaults if k.startswith("_")]:
    defaults.pop(key)

try:
    current = json.loads(target.read_text())
    if not isinstance(current, dict):
        raise ValueError
except Exception:
    current = {}

changed = []

for key, value in defaults.items():
    if key == "permissions":
        continue
    # Do not overwrite a founder's deliberate choice; only fill in what is absent.
    if key not in current:
        current[key] = value
        changed.append(f"{key} = {json.dumps(value)}")

perms = current.setdefault("permissions", {})
for bucket, entries in defaults.get("permissions", {}).items():
    existing = perms.setdefault(bucket, [])
    for entry in entries:
        if entry not in existing:
            existing.append(entry)
            changed.append(f"permissions.{bucket} += {entry}")

if target.exists():
    backup = target.with_suffix(".json.bak")
    backup.write_text(target.read_text())

target.write_text(json.dumps(current, indent=2) + "\n")

if changed:
    for line in changed:
        print(f"    + {line}")
else:
    print("    already up to date")
PY
fi

# --- 6. Docs MCP server ------------------------------------------------------
step "Enabling the Developer Knowledge API"

# /gcp-ask is grounded in this API. Without it every documentation lookup gets a
# 403 and the agent quietly falls back to web search. Enabling is free, scoped to
# a single read-only API, and reversible, so the installer does it rather than
# printing a command for the founder to paste.
if [[ -z "$QUOTA_PROJECT" ]]; then
  warn "No default gcloud project is set, so ${DK_API} cannot be
    enabled automatically. Set one and re-run this script:
      gcloud config set project <your-project>"
elif [[ $DRY_RUN -eq 1 ]]; then
  info "[dry-run] would ensure ${DK_API} is enabled on ${QUOTA_PROJECT}"
elif gcloud services list --enabled --project="$QUOTA_PROJECT" \
       --filter="config.name=${DK_API}" --format='value(config.name)' 2>/dev/null \
     | grep -q "$DK_API"; then
  info "already enabled on ${QUOTA_PROJECT}"
else
  info "enabling ${DK_API} on ${QUOTA_PROJECT} — this can take a minute"
  # Not fatal: a founder on a shared project may not hold
  # serviceusage.services.enable, and everything else here still works.
  if gcloud services enable "$DK_API" --project="$QUOTA_PROJECT" 2>/dev/null; then
    info "enabled"
  else
    warn "Could not enable ${DK_API} on ${QUOTA_PROJECT}.
    You most likely lack the serviceusage.services.enable permission. /gcp-ask
    will fall back to web search until someone with rights on the project runs:
      gcloud services enable ${DK_API} --project=${QUOTA_PROJECT}"
  fi
fi

step "Registering the developer-knowledge MCP server"

# google-cloud-core registers this server too, without credentials attached, so
# tools/call returns 401 in this setup and /gcp-ask falls back to web search. We
# register our own entry with ADC so the auth story is explicit and does not
# depend on a config we do not pin.
if [[ $DRY_RUN -eq 1 ]]; then
  info "[dry-run] would register developer-knowledge in ${MCP_CONFIG}"
else
  python3 - "$MCP_CONFIG" "$QUOTA_PROJECT" <<'PY'
import json, pathlib, sys

target, quota_project = pathlib.Path(sys.argv[1]), sys.argv[2]

# Use `serverUrl`: that is the key this agy version reads. `httpUrl` appears in
# other MCP configs, including google-cloud-core's gemini-extension.json, and an
# entry keyed that way is kept in the file but registers as type `stdio` with no
# command, so calls fail. Confirmed with `agy mcp add`, which writes `serverUrl`.
desired = {
    "serverUrl": "https://developerknowledge.googleapis.com/mcp",
    "authProviderType": "google_credentials",
    "timeout": 30000,
    "disabled": False,
}
# Sets the billing/quota project for the API. Derived at install time because
# the correct value is per-founder and must never be committed.
if quota_project:
    desired["headers"] = {"X-goog-user-project": quota_project}

try:
    current = json.loads(target.read_text())
    if not isinstance(current, dict):
        raise ValueError
except Exception:
    current = {}

servers = current.setdefault("mcpServers", {})
if servers.get("developer-knowledge") == desired:
    print("    already up to date")
else:
    if target.is_file() and target.read_text().strip():
        target.with_suffix(".json.bak").write_text(target.read_text())
    servers["developer-knowledge"] = desired
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(current, indent=2) + "\n")
    print("    + mcpServers.developer-knowledge (ADC via google_credentials)")
PY
fi

# --- 7. State directory -----------------------------------------------------
step "Preparing state directory"
run mkdir -p "${STATE_HOME}/state" "${STATE_HOME}/audit"
info "profile   ${STATE_HOME}/profile.json"
info "audit log ${STATE_HOME}/audit/commands.jsonl"

# --- 7b. Python packages for /gcp-ai-eval ------------------------------------
step "Checking the eval capability's Python packages"
check_pydeps

# The metric table in skills/gcp-ai-eval/scripts/_metrics.py is a snapshot of a
# server-side contract, measured against one agentplatform release. Which
# metrics work and which spec version the service serves both move between
# releases, so a pin bump invalidates it — and a stale VERIFIED table refuses
# metrics that now work, or admits metrics that now do not. Only surfaced under
# --update, because that is the run where the pin actually moved.
if [[ $UPDATE -eq 1 ]]; then
  info "pins reinstalled — if the agentplatform pin moved, re-verify the metric table:"
  info "    cd ${SRC}/skills/gcp-ai-eval/scripts && python3 verify_metrics.py --project <project>"
  info "  then paste its VERIFIED block into _metrics.py. It bills one judged row per metric."
fi

# --- 8. Verification --------------------------------------------------------
step "Verification"

if [[ $DRY_RUN -eq 1 ]]; then
  info "[dry-run] skipping verification"
else
  # The safety gate is the load-bearing component. If its self-test fails, the
  # harness must not be reported as installed.
  if python3 "${SRC}/scripts/test_gate.py" >/dev/null 2>&1; then
    info "safety gate self-test  ok"
  else
    fail "The safety gate self-test FAILED. Do not use this install for cloud
    operations. Run: python3 ${SRC}/scripts/test_gate.py"
  fi

  registered="$(agy plugin list 2>/dev/null || echo '{}')"

  if grep -q '"'"${PLUGIN_NAME}"'"' <<<"$registered"; then
    info "plugin registered      ok"
  else
    warn "plugin does not appear in 'agy plugin list'"
  fi

  # The dependency plugins were previously installed with a warn-and-continue
  # and never checked afterwards, so a failed install scrolled past and the run
  # still reported success. That cost the six WAF pillars silently.
  missing_deps=()
  for p in "${SKILLS_PLUGINS[@]}" conductor; do
    grep -q "\"${p}\"" <<<"$registered" || missing_deps+=("$p")
  done
  if [[ ${#missing_deps[@]} -eq 0 ]]; then
    info "dependency plugins     ok ($(( ${#SKILLS_PLUGINS[@]} + 1 )) installed)"
  else
    warn "Dependency plugins missing: ${missing_deps[*]}
    /architecture-review needs google-cloud-well-architected for its six
    pillars, /gcp-do needs google-cloud-core, and Conductor owns Build.
    Re-run bootstrap.sh to retry."
  fi

  # Checked against the installed copy, not the source tree. A fetch that
  # succeeded into SRC but never reached the plugin directory is exactly the
  # kind of gap that made the old docs-MCP check meaningless.
  missing_vendored=()
  for s in "${VENDORED_SKILLS[@]}"; do
    [[ -f "${PLUGIN_DIR}/${PLUGIN_NAME}/skills/${s}/SKILL.md" ]] || missing_vendored+=("$s")
  done
  if [[ ${#missing_vendored[@]} -eq 0 ]]; then
    info "vendored skills        ok (${#VENDORED_SKILLS[@]} installed)"
  else
    warn "Vendored skills missing: ${missing_vendored[*]}
    The capability that needs it will say so rather than work from memory.
    Re-run bootstrap.sh to retry."
  fi

  if gcloud auth application-default print-access-token >/dev/null 2>&1; then
    info "application default credentials  ok"
  else
    warn "No application default credentials. /gcp-ask needs them. Run:
      gcloud auth application-default login"
  fi

  # An earlier version of this check grepped a string out of a config file and
  # reported "ok" while every documentation lookup was in fact returning 401.
  # A capability check has to exercise the capability, so this one really calls
  # the server. The HTTP status is unambiguous: 200 works, 403 means the API is
  # not enabled, 401 means no credentials reached it.
  if ! command -v curl >/dev/null 2>&1; then
    warn "curl not found; skipping the docs MCP probe. /gcp-ask may be degraded."
  else
    dk_token="$(gcloud auth application-default print-access-token 2>/dev/null || true)"
    if [[ -z "$dk_token" ]]; then
      warn "Skipping the docs MCP probe: no application default credentials."
    else
      dk_code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 \
        -X POST "https://${DK_API}/mcp" \
        -H "Authorization: Bearer ${dk_token}" \
        -H "X-goog-user-project: ${QUOTA_PROJECT}" \
        -H "Content-Type: application/json" \
        -H "Accept: application/json, text/event-stream" \
        -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"search_documents","arguments":{"query":"Cloud Run"}}}' \
        2>/dev/null || echo 000)"
      unset dk_token
      case "$dk_code" in
        200) info "docs MCP server        ok (answered a live query)" ;;
        403) warn "The Developer Knowledge API is not enabled${QUOTA_PROJECT:+ on ${QUOTA_PROJECT}}.
    /gcp-ask will fall back to web search and its answers will not be grounded
    in the official corpus. Enable it with:
      gcloud services enable ${DK_API}${QUOTA_PROJECT:+ --project=${QUOTA_PROJECT}}" ;;
        401) warn "The docs MCP server rejected our credentials (401). Check that
    ${MCP_CONFIG} sets authProviderType=google_credentials on the
    developer-knowledge entry, and that it uses the serverUrl key (not httpUrl)." ;;
        *)   warn "The docs MCP probe returned HTTP ${dk_code}. /gcp-ask may be degraded." ;;
      esac
    fi
  fi
fi

# --- Done -------------------------------------------------------------------
if [[ $DRY_RUN -eq 1 ]]; then
  printf '\n  Dry run complete. Nothing was changed. Re-run without --dry-run to install.\n\n'
  exit 0
fi

cat <<EOF

  Installed.

  Next:  agy            then run  /startup-onboard

  Capabilities
    /gcp-ask              questions about Google Cloud, answered from official docs
    /gcp-design           design an architecture, including AI agent systems
    /conductor:newTrack   spec-driven feature development
    /architecture-review  six-pillar Well-Architected review of this repo
    /gcp-ai-eval          measure whether an AI agent you built actually works
    /gcp-ai-monitor       configure alerting for an agent on Agent Runtime
    /gcp-do               create and operate cloud resources, every change reviewed

  Every gcloud and bq command that changes anything will be shown to you for
  approval before it runs. Do not use --dangerously-skip-permissions: it turns
  that off, and the harness cannot turn it back on.

EOF
