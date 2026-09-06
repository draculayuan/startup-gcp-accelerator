---
name: gcp-ask
description: Answers Google Cloud product questions from official Google documentation. Use when the user asks what a Google Cloud service does, how to configure it, what it costs, how services compare, which service fits a requirement, or about quotas, limits and regional availability. Do not use for generating gcloud commands or for reviewing an existing architecture.
---

# Google Cloud Q&A

Answer Google Cloud questions from official documentation, never from memory.

## Protocol

1. **Resolve ambiguity first, but only when it changes the answer.** If the question
   is answerable as asked, answer it. Ask a clarifying question only when different
   readings lead to materially different answers (for example "which database should
   I use" without any hint of workload shape).

2. **Delegate to the `gcp-answers` subagent** via `invoke_subagent`. Pass the
   question plus any relevant context from `startup-profile.md` — stage, existing
   stack, region, budget posture — so the answer is grounded in their situation.

   Delegate rather than researching inline. Documentation retrieval returns large
   payloads, and running it in the main conversation crowds out the user's working
   context for no benefit.

3. **Relay the subagent's answer, including its Sources list.** Do not silently drop
   citations, and do not add facts the subagent did not report.

## Batching related questions

If the user asks several independent questions at once, invoke one subagent per
question concurrently rather than serially. Merge the answers under one Sources
list, deduplicated.

## Escalation

Route elsewhere when the question is not really a docs question:

| Situation | Route to |
|---|---|
| "Is *my* setup right?" | `/architecture-review` |
| "Create / change this resource" | `/gcp-do` |
| "Build this feature" | `/conductor:newTrack` |

Escalate by telling the user which command to run and why. Do not silently switch
capabilities on their behalf.

## Boundaries

- **Never state gcloud syntax from this skill.** The `gcloud` skill is the sole
  authority and requires `gcloud help <leaf_command>` verification first.
- **Never present pricing figures as authoritative.** Give the pricing model plus
  the pricing-page URL and note that current figures must be confirmed.
- If documentation genuinely does not answer the question, say so and state what
  *is* documented. Do not fill the gap with plausible inference.
