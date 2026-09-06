---
trigger: always_on
description: Locates the startup's Google Cloud profile — project IDs and their dev/prod tags, region, budget, stage and compliance posture — and defines how to behave before it exists.
---

# Startup Profile

This harness is installed globally, so it knows nothing about the startup until
`/startup-onboard` has been run. The profile is the only thing that makes an
identical install behave differently for each company.

## Location

`~/.startup-gcp-accelerator/profile.json`, with a human-readable mirror at
`~/.startup-gcp-accelerator/profile.md`.

Read it before any Google Cloud work. Do not cache it across sessions — founders
add projects.

## What it holds

| Field | Used for |
|---|---|
| `company`, `stage` | Calibrating recommendations to team size and funding |
| `projects[]` — `id`, `env` (`dev`\|`prod`), `purpose` | Target selection and approval severity |
| `default_project` | The project assumed when a request names none |
| `region`, `multi_region` | Default region for new resources |
| `budget_monthly_usd` | Cost warnings before creating billable resources |
| `compliance` | Whether HIPAA / SOC 2 / GDPR constraints apply to review findings |
| `primary_stack` | Language and framework, for idiomatic examples |

## Using it

- **Never infer the target project from `gcloud config get-value project`.** That
  default is invisible to the founder and is how a dev change lands in prod. Use
  `default_project` from the profile, and if the request is ambiguous and more
  than one project exists, ask.
- Any project tagged `prod` triggers the production callout in the approval
  block, and the safety gate flags it independently.
- Before creating a billable resource, compare its monthly cost against
  `budget_monthly_usd` and say something if it is a material fraction of it.
- Let `compliance` shape architecture review severity: a public bucket is always
  P1, but under HIPAA it is an incident.

## If the profile does not exist

Do not guess, and do not silently proceed against whatever project happens to be
configured.

Say that the harness is not yet configured, offer to run `/startup-onboard`, and
if the founder declines, ask for the target project ID explicitly for this
session only.
