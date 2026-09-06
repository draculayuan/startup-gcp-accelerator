---
name: gcp-ai-monitor
description: Configures monitoring and alerting for an AI agent already deployed to Agent Runtime (Vertex AI Agent Engine) — checks telemetry, derives thresholds from real traffic, and writes Terraform alert policies. Use when the user wants alerting, monitoring or alarms on a deployed agent. Do not use for an agent that is not deployed yet, or for infrastructure unrelated to agents.
---

# AI Agent Monitoring

For an agent **already deployed to Agent Runtime** — a Vertex AI Agent Engine
reasoning engine. Not for a local agent, not for Cloud Run, not for anything
still being built.

This capability configures monitoring. It does not perform monitoring: once the
alert policies are applied, Google Cloud evaluates them continuously, which is
what keeps working after this session ends.

Two artifacts, then stop.

## The alert skill owns the method

Everything about *what* to watch and *at what threshold* — metrics, PromQL,
policy shapes, telemetry prerequisites — lives in
**`agent-platform-alert-configuration`**. Load it and follow it.

Do not restate its content or recall it from memory. It carries five families of
alert policy (reliability, cost, safety, security, quality) with the exact metric
names and query shapes, and those are not guessable.

**If the skill is absent, say so and name it.** Re-running `bootstrap.sh`
reinstalls it. Do not improvise alert policies — a plausible-looking threshold on
a metric that does not exist produces an alert that never fires, which is worse
than no alert because it reads as coverage.

### Use its scripts, do not reimplement them

| Need | Use |
|---|---|
| Identify the runtime, telemetry state, metric scopes | `scripts/gather_agent_info.py` |
| Confirm telemetry is actually exporting | `scripts/check_telemetry.py` |
| Derive thresholds from the agent's real traffic | `scripts/analyze_traffic.py` |
| Provision the quality Online Monitor | `scripts/create_online_monitor.py` |
| Check the generated Terraform | `scripts/lint_syntax.py`, `scripts/scan_duplicates.py` |

These need dependencies the harness does not install. Run
`pip install -r scripts/requirements.txt` in the skill's directory first, as its
own instructions require.

## What this capability adds

1. **Take the project and region from `~/.startup-gcp-accelerator/profile.json`
   and state them explicitly.** The skill refuses to infer a project and will
   only use one given to it, so pass it rather than letting it ask.

2. **Agent Runtime only.** The skill spans several runtimes. This capability is
   scoped to Vertex AI Agent Engine (`google_vertex_ai_reasoning_engine`). If
   the agent is somewhere else, say so and stop — do not silently widen.

3. **Run the free discovery first, and stop honestly if it fails.** Quality
   alerts need three telemetry environment variables set on the deployed agent,
   plus the Cloud Trace and Observability APIs. If telemetry is off, the fix is
   a redeploy the founder has to do. Say that plainly and stop rather than
   configuring alerts that will never receive data.

4. **Thresholds come from traffic, not from you.** Use `analyze_traffic.py` and
   the skill's has/no-historical-data playbooks. Never invent a number.

5. **Two artifacts, dated.** A second run must not overwrite the first.

   | Artifact | Path |
   |---|---|
   | What is watched and why | `ai-monitor-<date>.md` |
   | Alert policies | `alerts-<date>.tf` |

   The markdown is for a founder deciding whether these are the right alarms, so
   lead with what each one catches in plain language, not with PromQL.

6. **Write the Terraform, do not apply it.** Applying is `/gcp-do`, which runs
   it under the approval gate. Print the handoff and stop.

7. **Stop after the second artifact.** Do not tune, re-run, or start watching
   anything.

## Cost

Say plainly what bills before provisioning anything:

- The **Online Monitor** runs LLM-as-judge evaluations on sampled production
  traffic. Sampling defaults to 10% and is the main cost lever — name the
  percentage you are proposing.
- **Telemetry export** to Cloud Trace and Cloud Logging bills separately.

The skill requires explicit approval before provisioning either. That approval
is the founder's to give, in this conversation, before the script runs.

## Boundaries

- **The agent must be deployed.** If it is not, this is `/gcp-design` to design
  it or `/gcp-ai-eval` to evaluate it locally.
- **Configuration, not observation.** This capability cannot tell a founder how
  their agent is doing right now. Nothing here queries live metrics — for a
  current reading, point them at the Cloud Console dashboards.
- **No applying.** No `terraform apply`, no deployment, no agent changes.

## Escalation

Say what would make sense next. Do not start it.

| Situation | Route to |
|---|---|
| Apply the generated Terraform | `/gcp-do` |
| Agent is failing now — 403, 500, gateway errors | `agent-platform-troubleshooting`, via `/gcp-do` |
| "What does this metric mean?" | `/gcp-ask` |
| Quality is the worry, and the agent can run locally | `/gcp-ai-eval` |
| Telemetry needs enabling, so the agent must be redeployed | `/conductor:newTrack` |
