---
name: gcp-do
description: Creates, configures, operates and troubleshoots Google Cloud resources using the gcloud CLI, with every mutating command presented for human approval. Use when the user wants to provision infrastructure, change a configuration, deploy a service, inspect live resources, or debug something running on Google Cloud.
---

# Google Cloud Operations

Run real operations against the startup's Google Cloud projects under mandatory
human review.

## Before anything else

1. **Confirm the target project.** Read `startup-profile.md`. If the request does
   not name a project and more than one is configured, ask. Never let the active
   `gcloud config` default decide silently — that is how a dev change lands in
   prod.
2. **Load the `gcloud` skill.** It is the authority on command syntax and it is
   enforced by a hook.
3. **Load a product skill only if one is actually installed.** This harness ships
   a deliberately small set, and per-product skills for GKE, BigQuery, Cloud SQL
   and the rest are **not** among them. Do not go looking for one, and do not
   treat its absence as permission to reason from memory — the `gcloud` skill's
   `gcloud help <leaf>` protocol is the grounding, and it is enforced by the
   gate either way.

## Execution

Delegate to the **`gcp-operator`** subagent, which owns the four-step protocol:
`gcloud help <leaf>` → verify flags → dry run → propose for approval.

A mutating command **will be denied by the safety gate** if syntax was not
verified first. That is by design; the denial message states the remedy.

## What the founder sees before approving

Every mutation is presented with: the exact command, why it is being run, the
target project and its environment tag, the monthly cost impact, and the undo
command (or an explicit statement that it is irreversible).

One command per approval. Never batch.

## Multi-step work

Present the full plan and get agreement on its shape before executing step one.
Then one step at a time, reporting each result. On failure: stop, report the
actual error and the resulting state, and offer options. Do not improvise
recovery.

## Prefer infrastructure-as-code

For anything the startup will need again — a service, a database, a network —
offer to write Terraform instead of running imperative commands. Console and CLI
changes are invisible to the next architecture review and to the next engineer
they hire.

Run the imperative command when they want it. Just make the offer once.

## Boundaries

- No `--quiet` / `-q`. No long-lived service-account keys. No printing tokens.
- Never widen IAM to unblock something. Name the specific role and scope, and ask.
- Never run a script you have not shown the user — the gate cannot see inside it.
- If a request would create a resource whose cost is materially above what their
  stage warrants, say so once before they approve, then respect their decision.

## Escalation

| Situation | Route to |
|---|---|
| "What does this service do / cost?" | `/gcp-ask` |
| "Is my whole setup sound?" | `/architecture-review` |
| "Build this feature" | `/conductor:newTrack` |
