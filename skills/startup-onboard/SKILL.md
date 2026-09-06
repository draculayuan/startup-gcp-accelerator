---
name: startup-onboard
description: Configures the startup GCP accelerator harness for one company — collects project IDs and environments, region, budget, stage and compliance posture, verifies authentication, and writes the startup profile that every other capability reads. Run once per startup, and again whenever a project is added.
---

# Startup Onboarding

The harness installs identically for every startup and knows nothing about any of
them until this runs. Five minutes here is what makes the other three
capabilities specific rather than generic.

## Interview

Ask these one at a time. If the native `ask_question` GUI modal tool is
available, use it; otherwise ask in formatted text, sequentially.

1. **Company name and stage** — pre-seed, seed, Series A, later.
2. **Google Cloud projects.** For each: project ID, environment (`dev`, `staging`
   or `prod`), and a one-line purpose. Take as many as they have; most seed-stage
   startups have one or two. Do not accept a project name where an ID is needed —
   they differ, and only the ID works on the command line.
3. **Default project** — the one assumed when a request names none. If they have
   a prod project, do not default to it.
4. **Primary region** and whether multi-region matters yet.
5. **Monthly budget ceiling in USD.** Used for cost warnings, not enforcement.
   Approximate is fine.
6. **Compliance obligations** — HIPAA, SOC 2, GDPR, PCI, or none. "Not yet, but
   we will need SOC 2 for enterprise deals" is a real and common answer worth
   recording.
7. **Primary stack** — language, framework, and how they deploy today.

Do not interrogate. If they do not know their budget, record `null` and move on.

## Verify what they told you

Read-only, and allowed without approval:

```
gcloud auth list
gcloud projects list
gcloud config get-value project
```

Reconcile against what they said. If a project ID they gave does not appear in
`gcloud projects list`, tell them — usually it is a typo or the wrong account,
and finding out now is far cheaper than at the first mutation.

## Authentication

Application Default Credentials are needed for the `developer-knowledge` MCP
server that powers `/gcp-ask`. **Do not test them by printing a token.**
`gcloud auth application-default print-access-token` emits a live credential
straight into the transcript, and the safety gate denies it for that reason.
`bootstrap.sh` already ran the same check with the output discarded, which is the
right place for it.

So: assume ADC is fine. If `/gcp-ask` later fails with an authentication error,
tell them to run this themselves — it opens a browser and the agent cannot
complete it:

```
gcloud auth application-default login
```

## Write the profile

Write `~/.startup-gcp-accelerator/profile.json` from
`assets/profile-template.json`, and a readable mirror at `profile.md`.

```json
{
  "company": "Acme",
  "stage": "seed",
  "default_project": "acme-dev",
  "projects": [
    {"id": "acme-dev", "env": "dev", "purpose": "development and staging"},
    {"id": "acme-prod", "env": "prod", "purpose": "customer-facing production"}
  ],
  "region": "us-central1",
  "multi_region": false,
  "budget_monthly_usd": 2000,
  "compliance": ["soc2-planned"],
  "primary_stack": "Python / FastAPI, deployed to Cloud Run",
  "enforce_help_precondition": true
}
```

`enforce_help_precondition` must stay `true`. It is what makes the safety gate
require verified syntax before a mutation, and turning it off is not a supported
configuration.

If a profile already exists, show what is there and confirm each change rather
than overwriting silently — this skill is re-run to add projects, and clobbering
someone's prod tag is exactly the failure that tagging exists to prevent.

## Finish

Tell them what they now have, in one short list: `/gcp-ask`,
`/architecture-review`, `/gcp-do`, `/conductor:newTrack`. Point out that every
cloud mutation will come back to them for approval, and that this is deliberate.

Then offer to run `/architecture-review` if there is a repo open — it is the
fastest way to demonstrate the harness is doing something real.
