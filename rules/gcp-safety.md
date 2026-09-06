---
trigger: always_on
description: Mandatory review protocol for every Google Cloud mutation. Governs how gcloud and bq commands are verified, presented for approval, and executed.
---

# Google Cloud Safety Protocol

Every command that changes state in a Google Cloud project is reviewed and
approved by a human before it runs. This is enforced by a `PreToolUse` hook, not
by your good intentions — but the hook only decides *whether* to ask. Making the
question answerable is your job.

## Verify before you propose

For any `gcloud` or `bq` command that mutates:

1. Run `gcloud help <leaf_command>` for the **specific leaf subcommand**.
   `gcloud help compute` does not authorise `gcloud compute instances create`.
2. Confirm every flag against that output. Your recollection of gcloud syntax is
   stale; the help text is the only authority. Never web-search for gcloud flags.
3. Check whether the command supports `--dry-run` or `--validate-only`. If it
   does, run it first.

**A mutation proposed without prior leaf help will be denied by the gate.** The
denial message names the exact help command to run. Run it, then re-propose.

## The approval block

Never ask "shall I run this?" without the following. A founder cannot approve
what they cannot evaluate.

- **What** — the exact command in a fenced block, no ellipses, no placeholders.
- **Why** — one sentence tying it to what they asked for.
- **Where** — the project ID, and whether it is tagged `dev` or `prod`.
- **Cost** — monthly billing impact at this configuration. "Free tier" is a valid
  answer. Silence is not.
- **Undo** — the reversing command, or an explicit "this is irreversible".

If the native `ask_question` GUI modal tool is in your allowed tools, render the
approval through it. Otherwise use formatted text and ask directly. Either way:
**one command per approval.** Never bundle.

## Prohibited, without exception

| Never | Because |
|---|---|
| `--quiet` / `-q` | Suppresses gcloud's own confirmation. The gate denies it. |
| `gcloud projects delete` | Irreversible at a scale no agent should reach for. |
| `gcloud auth print-access-token` / `print-identity-token`, including the `application-default` form | Credential exfiltration path. Prints a live token into the transcript. |
| Reading `~/.config/gcloud/*` or the Antigravity OAuth token by any means | Same exfiltration path, via the filesystem instead of the CLI. |
| `gcloud iam service-accounts keys create` | Long-lived keys. Use ADC, impersonation, or workload identity. |
| Running a script you have not displayed | The gate cannot read inside `deploy.sh`. You must show it first. |
| Widening IAM to unblock yourself | Name the specific role and scope, and ask. |

## Opaque execution

`./script.sh`, `make`, `npm run`, `terraform apply`, `kubectl apply`, `helm
install` — the gate cannot see what these do, so it forces a prompt. Before
proposing one, **display the file or manifest being executed** so the approval is
informed rather than nominal.

## When something fails

Stop. Do not retry with different flags and do not improvise recovery.

Report: the actual error text (quoted, not paraphrased), what state the resource
is now in, and the available options. Half-applied infrastructure is worse than
none, and the founder needs to know which they have.

## Production

When the target project is tagged `prod` in the startup profile, say so
explicitly in the approval block and confirm the founder intended production
rather than assuming it from the active `gcloud config` default.
