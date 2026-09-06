---
trigger: always_on
description: Chooses which harness capability handles a Google Cloud request — question answering, architecture design, architecture review, AI agent evaluation and monitoring, live cloud operations, or spec-driven development.
---

# Capability Routing

Seven capabilities, deliberately separated because they need different tools and
different levels of trust. Picking the wrong one is not fatal, but it usually
means a slower, less grounded answer.

One capability per stage — **Learn → Design → Build → Eval → Review → Deploy →
Monitor**. It is a map for choosing between them, not a sequence to walk the
founder through. Do not tell a founder they are "in stage 3", do not gate one capability
on another having run, and do not assume an earlier stage happened. Eval and
Monitor apply only when the product is an AI agent.

| Stage | The founder wants | Route | Why |
|---|---|---|---|
| Learn | To understand something — what a service does, how it is priced, whether it supports X, how two products differ | `/gcp-ask` | Grounded in official docs via the `developer-knowledge` MCP; read-only; fast |
| Design | To decide how to build something not built yet — which products, how they fit together, what the trade-offs are | `/gcp-design` | Google's own solution-architecture workflows, agent-aware; produces a design document and stops |
| Build | To build a feature, or to implement an architecture that has been designed — plan it, implement it, track progress | `/conductor:newTrack` | Spec-driven loop with its own state; builds from a requirement or from an existing design document |
| Eval | To know whether an *agent they have built* actually works, before it ships | `/gcp-ai-eval` | Google's eval-flywheel skill over a local ADK agent; recommends metrics, scores them, writes artifacts and stops |
| Review | A judgement on their existing setup — is it secure, will it scale, what is wrong, are we ready for an audit | `/architecture-review` | Six WAF pillars in parallel over a repo inventory; scopable to named pillars if they ask |
| Deploy | To change something in their cloud — deploy, apply Terraform, provision, configure, debug live resources | `/gcp-do` | Approval-gated `gcloud` and `terraform` execution |
| Monitor | Alerting on an agent *already deployed* to Agent Runtime | `/gcp-ai-monitor` | Google's alert-configuration skill; derives thresholds from real traffic, writes Terraform and stops |

## Judgement calls

- **"How do I set up Cloud Run?"** is ambiguous. If they want to understand it,
  `/gcp-ask`. If they want it running today, `/gcp-do`. When unsure, ask which —
  it is one question and it saves doing the wrong one.
- **"Why is my bill so high?"** starts as `/gcp-ask` for the pricing model, but
  becomes `/architecture-review` if they want their actual spend diagnosed. Run
  the full review — the topic of the question is not a request to scope it, and
  overspend is routinely a reliability or performance finding wearing a cost
  costume. Scope down only if they ask.
- **"Is this secure?"** about one file is a direct answer. About their system, it
  is `/architecture-review`.
- **Design and review are the same question at different times.** If the thing
  does not exist yet, `/gcp-design`. If it exists and they want a verdict,
  `/architecture-review`. "How should we build X" is design even when they have
  a repo, because the repo is not the subject.
- **"Build me an agent"** is design first. `/gcp-design` decides the agent
  topology, the runtime and the memory story; writing the agent is a separate
  step the founder starts themselves. Do not skip to code because the request
  sounded like an instruction.
- **The agent capabilities split on how far along the agent is.** Not built is
  `/gcp-design`; built but not shipped is `/gcp-ai-eval`, which runs locally, so
  "I haven't deployed it" is no reason to defer; deployed to Agent Runtime is
  `/gcp-ai-monitor`, which configures alerting but cannot report current health
  — for that, send them to the Cloud Console.
- **`/architecture-review` says nothing about whether an agent works.** It reads
  infrastructure, so for a founder whose product *is* the agent it can return a
  clean report while the agent is failing. When the subject is agent quality,
  route to `/gcp-ai-eval`; run both when they want a verdict on the whole thing.
- A request that needs infrastructure *built as part of a feature* belongs in
  Conductor, with `/gcp-do` invoked for the provisioning steps inside it.
- **A design that has just been approved goes to Conductor with the document, not
  without it.** If `architecture-design-*.md` exists in the workspace, name it
  when routing to `/conductor:newTrack`. Re-interviewing a founder who has just
  finished a requirements interview is the most annoying thing this harness can
  do to them.
- **Durable versus one-off is what separates Build from Deploy.** Something the
  founder will want again next month — a service, a database, a pipeline —
  belongs in a Conductor track so it ends up described in the repo. A one-off
  operation, an investigation, a fix that is needed now, or applying Terraform
  that already exists is `/gcp-do`. When a founder wants something running
  immediately, give them that; do not push them into opening a track first.
  Offer the track afterwards if the resource looks like it should outlive the
  afternoon.

## Do not

- Do not answer Google Cloud product questions from memory when `/gcp-ask` can
  ground them. Cloud pricing, quotas and GA status change monthly.
- Do not run a one-pillar review and present it as an architecture review.
- Do not route a simple question through Conductor. It has setup cost and state;
  it earns that on multi-step feature work, not on a lookup.
- Do not chain capabilities unprompted. Finish what was asked, then offer the
  next step.
