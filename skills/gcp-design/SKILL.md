---
name: gcp-design
description: Designs a Google Cloud architecture before anything is built — discovers requirements, then produces a solution architecture with a diagram, product choices and trade-offs. Use when the user is deciding how to build something on Google Cloud, including AI agent and multi-agent systems. Do not use to review an existing system, to write application code, or to provision resources.
---

# Architecture Design

Design before building. This capability produces exactly one artifact — an
architecture document — and stops there. Nothing is scaffolded, generated as
Terraform, or deployed.

## Pick one of two design skills

Google ships both, and each tells the agent not to use it for the other's job.
Route once and commit.

| What is being designed | Skill |
|---|---|
| An AI agent or multi-agent system | `google-cloud-solution-build-deploy-agents` |
| Anything else on Google Cloud | `google-cloud-solution-architecture` |

**The discriminator is what is being built, not whether AI is involved.** A
support assistant that holds a conversation, calls tools and remembers context
is an agent system. A batch pipeline that makes a Gemini call per row is a
pipeline — the general skill designs it better, because the hard parts are
ingestion, storage and scheduling rather than orchestration and memory.

The agent skill covers the surrounding platform too — frontend, Cloud Run
networking, databases, retrieval, short- and long-term memory, tools — so an
agent product does not also need the general skill. Do not run both; two
overlapping designs are worse than one.

When it is genuinely unclear, ask. It is one question, and routing wrong costs
the founder a full requirements interview.

## Protocol

1. **Read the profile** at `~/.startup-gcp-accelerator/profile.json` before
   asking anything. Stage, region, multi-region posture, budget ceiling,
   compliance obligations and primary stack are all non-functional requirements
   that Phase 1 would otherwise ask for. Supply them to the skill as known
   context and ask only about what the profile does not cover. Do not make the
   founder re-type what onboarding already recorded.

2. **Load the routed skill and follow its phases.** The skill owns the
   workflow — requirements discovery, technical decomposition, product mapping,
   diagram, design recommendations. Do not paraphrase it or run a design of your
   own invention.

   Respect its sequencing rule in particular: **no products, services or
   component mappings may be proposed until requirements are settled.** Both
   skills state this, and the reason is anchoring — a product named early
   becomes the answer regardless of fit.

3. **Make the runtime an explicit choice, not a default.** The agent skill
   recommends Gemini Enterprise Agent Runtime as its primary agent runtime, with
   Cloud Run and GKE as alternatives. All three are supported, and Cloud Run in
   particular is first-class throughout that skill — it owns the networking
   section and is the recommended frontend.

   So ask which the founder wants before the product-mapping step, and record
   the answer as a constraint. If they choose Cloud Run or GKE, say what follows
   from it: Agent Platform Sessions needs an Agent Runtime instance, so
   short-term memory moves to Memorystore, Firestore, or Cloud SQL via ADK's
   `DatabaseSessionService`. Note also that the skill's design principles are
   written around Cloud Run and say nothing about GKE — a GKE design gets its
   product mapping from this skill but its operational guidance from the
   `gke-*` skills, if installed.

4. **Stop at the architecture.** See below.

5. **Write the artifact** to `architecture-design-<date>.md` in the workspace,
   using the skill's own template. Both skills default to writing
   `solution-architecture.md`; use the dated name instead so a second design
   does not silently overwrite the first. State the path when you are done.

## The hard stop

Both skills continue past design into implementation. This capability does not.

| Skill | Run | Skip |
|---|---|---|
| `google-cloud-solution-architecture` | Phase 1 requirements, Phase 2 architecture, Phase 4 packaging | Phase 3 — it generates validation scripts |
| `google-cloud-solution-build-deploy-agents` | Phase 1 requirements, Phase 2 design | Phase 3 implementation plan and IaC, Phase 4 deployment validation |

Do not generate Terraform, deployment scripts, CI configuration or
`agents-cli scaffold` invocations, and do not run anything that provisions.
When the design is approved, say what the next step would be and let the
founder choose it. Do not start it.

This boundary is the point of a separate design stage. A design that arrives
with its own Terraform invites approving the architecture and the
implementation in a single decision, when the first is cheap to change and the
second is not.

## If a design skill is missing

Say so plainly and name the skill. Do not quietly design from your own
knowledge — an ungrounded architecture is indistinguishable from a grounded one
at a glance, which is exactly why it is dangerous. Re-running `bootstrap.sh`
reinstalls both skills.

## Boundaries

- **Design only.** No provisioning, no application code, no IaC.
- **No gcloud syntax from this skill.** The `gcloud` skill is the sole
  authority, and `/gcp-do` is where commands get proposed and approved.
- **Cost figures are estimates.** Give the cost model and shape — what scales
  with what — plus the pricing-page URL. Where the profile records a budget
  ceiling, say whether the design plausibly fits under it and which component
  dominates. Do not present a monthly total as authoritative.
- **Do not review an existing system here.** This designs something new. If
  they have a repo and want a judgement on it, that is `/architecture-review`.

## Escalation

Tell the founder which command to run next and why. Do not switch capabilities
on their behalf.

| Situation | Route to |
|---|---|
| "What does Cloud Run actually do?" mid-design | `/gcp-ask` |
| Design approved, build the feature | `/conductor:newTrack` |
| Design approved, provision the resources | `/gcp-do` |
| "Is what we already have any good?" | `/architecture-review` |

**When routing to Conductor, print the command with the filename already in it**,
so the founder can copy the line rather than remember to mention the document:

```
/conductor:newTrack implement the architecture in architecture-design-<date>.md
```

Conductor builds a spec by interviewing the founder. Handed the design, it starts
from the requirements and product decisions already settled here instead of asking
for them a second time. Naming the file is the whole handoff — do not summarise
the design into the chat for it, and do not run the command yourself.
