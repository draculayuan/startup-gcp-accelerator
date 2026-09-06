---
name: architecture-review
description: Reviews a codebase or architecture diagram against the six pillars of the Google Cloud Well-Architected Framework and produces a prioritised findings report. Defaults to all six pillars and can be scoped to named ones on request. Use when the user asks whether their architecture is sound, wants a security or cost or reliability review, asks to review one named pillar, is preparing for scale or an audit, or asks what is wrong with their Google Cloud setup.
---

# Architecture Review

A two-stage review: map the footprint once, then evaluate it against the WAF
pillars in parallel.

## Scope — which pillars to run

**Default to all six.** Run a subset only when the user has *explicitly* asked to
scope the review: "security only", "just cost and reliability", "skip
sustainability".

**Never infer a narrow scope from the subject of the question.** "Is this
secure?" and "why is my bill so high?" are reasons to *start* a review, not
instructions to run one pillar. A founder asking about security is still well
served by learning their database has no backups. Narrowing on a topic silently
removes coverage they never agreed to give up.

When you do scope it, **name the pillars you are running before you start**, so
an unintended narrowing gets corrected in the first seconds rather than
discovered in the report.

A scoped review produces a **different report, not a partial one** (Stage 3).

## Stage 1 — Inventory

Invoke the **`architecture-cartographer`** subagent over the workspace. It returns
a structured inventory with `path:line` evidence.

If the user supplied an **architecture diagram** instead of (or alongside) a repo,
attach the image and have the cartographer reconcile diagram against code. Where
they disagree, the code wins — say so in the report, because the divergence is
itself a finding.

Do not proceed until the inventory exists. Reviewers built on a guessed inventory
produce plausible fiction, one set per pillar. This stage runs identically
whatever the scope — the inventory is the fixed cost of a review, which is why
scoping saves tokens rather than wall-clock.

## Stage 2 — Parallel pillar reviews

Invoke **`waf-pillar-reviewer` once per in-scope pillar, all concurrently**, with
`invoke_subagent`. Do not run them sequentially: they are independent, and serial
execution both wastes time and lets earlier pillars crowd the context of later
ones.

Each invocation gets: the pillar name, the full inventory, and the workspace path.

| Pillar | Skill the reviewer loads |
|---|---|
| security | `google-cloud-waf-security` |
| reliability | `google-cloud-waf-reliability` |
| cost-optimization | `google-cloud-waf-cost-optimization` |
| operational-excellence | `google-cloud-waf-operational-excellence` |
| performance-optimization | `google-cloud-waf-performance-optimization` |
| sustainability | `google-cloud-waf-sustainability` |

If a reviewer fails or returns nothing, note the pillar as **not reviewed** in the
report. Never silently drop a pillar — a missing pillar reads as a clean pillar.
*Not reviewed* and *not in scope* are different states and the report must not
conflate them.

### Do not let one straggler hold the report

Pillar reviews finish at very different rates, and the slowest can take several
times the median.

**When four or more pillars are in scope, write the report once all but one have
returned.** Mark the outstanding pillar as *not reviewed — did not complete in
time* and offer to run it on its own afterwards. A report delivered with five
pillars beats a sixth pillar the founder never sees because the run timed out.
This matters most in the IDE, where the whole review is one long-running turn.

**When three or fewer are in scope, wait for all of them.** The founder named
these pillars specifically; dropping one of three is dropping a third of what
they asked for, and there is no long tail to escape when the fan-out is small.

## Stage 3 — Merge

1. **Deduplicate.** The same root cause often surfaces in several pillars (a
   default service account is both Security and Operational Excellence). Merge
   into one finding and list every pillar it touches.
2. **Rank** by severity first, then by reversibility — an expensive-to-reverse P2
   outranks a cheap-to-fix P1 in the *Fix first* list, because the window to fix
   it cheaply is closing.
3. **Do not inflate.** If the reviewers found four real issues, report four.
4. **On a scoped review, keep the `cross_pillar` tags that point outside the
   scope.** A security finding tagged `reliability` is the strongest possible
   argument for running reliability next. Collect them into the *Not assessed*
   section as named suggestions rather than discarding them.

Write the report to `architecture-review-<YYYY-MM-DD>.md` using
`assets/report-template.md`, then summarise the top three findings in chat.

**A scoped review writes `architecture-review-<YYYY-MM-DD>-<pillars>.md`** —
e.g. `architecture-review-2026-08-29-security.md`. A scoped run must never
overwrite a full review from the same day; the full report is the more valuable
artifact and it is the one that would be lost.

## Calibration

These are early-stage startups. The review is useful only if it is actionable this
quarter. Lead with what is exposed, what will break at 10x, and what gets
expensive to change later. A single-region deployment at seed stage is a noted
trade-off with a trigger point, not a defect.

## Follow-through

Offer to convert the findings into Conductor tracks via `/conductor:newTrack`, one
track per P1. Offer — do not do it unprompted.
