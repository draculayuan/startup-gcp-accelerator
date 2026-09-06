# Startup GCP Accelerator

> **This is not an officially supported Google product.** It is an unofficial
> project that packages Google Cloud tooling and Google's published skills into
> one install. It carries no warranty and no support commitment, and nothing
> here speaks for Google. For anything authoritative, go to the official
> [Google Cloud documentation](https://cloud.google.com/docs).

An [Antigravity 2.0](https://antigravity.google) harness for early-stage startups
building on Google Cloud. One install gives you seven capabilities, one per
stage:

| Stage | Command | What it does |
|---|---|---|
| Learn | `/gcp-ask` | Answers Google Cloud questions from the official documentation, with citations |
| Design | `/gcp-design` | Designs an architecture before you build it — including AI agent systems |
| Build | `/conductor:newTrack` | Spec-driven development: plan, build, track |
| Eval | `/gcp-ai-eval` | Measures whether an AI agent you built actually works — metrics, dataset, scores |
| Review | `/architecture-review` | Reviews your repo against all six Well-Architected Framework pillars |
| Deploy | `/gcp-do` | Creates and operates cloud resources — **every change comes to you for approval** |
| Monitor | `/gcp-ai-monitor` | Configures alerting for an agent you deployed to Agent Runtime |

## The seven stages are a map, not a pipeline

Learn → Design → Build → Eval → Review → Deploy → Monitor is roughly the order
things happen in, and naming the stages makes it easier to see which capability
to reach for. That is all it is. Nothing here enforces the sequence and nothing
tracks where you are.

Start wherever you actually are, and skip the stages that do not apply — Eval and
Monitor are for founders whose product is an AI agent, so if yours is not, this is
five stages rather than seven. Review before you deploy or after — the review
reads your repo, so it works either way, and it is worth re-running every few
months rather than once. Go back to Design when the product changes. Most weeks
you will use two of them.

**Eval and Review are adjacent because they are different questions.** Eval asks
whether your agent works. Review asks whether your infrastructure is sound.
`/architecture-review` can hand you a clean report while your agent is quietly
failing, because whether an agent works is not visible in Terraform. If your
product is an agent, you want both — and you want them before you deploy, which
is why Deploy comes after.

Each capability **assists with a stage rather than owning it.** This is not seven
robots that do your job in sequence. `/gcp-design` writes a design document and
stops, and you decide whether it is right. `/architecture-review` hands you a
ranked report, not a branch of merged fixes. `/gcp-do` proposes a command and
waits for you. Conductor plans and implements, and you review every step.

None of them hand off to the next stage on your behalf, either. Each one finishes,
tells you what it would make sense to do next, and stops there — because which
stage you want next is your call.

## Install

You need the Antigravity CLI (`agy`), the `gcloud` CLI, and Python 3.

```bash
git clone <this-repo> startup-gcp-accelerator
cd startup-gcp-accelerator
./bootstrap.sh
```

Then, once:

```bash
agy
```
```
/startup-onboard
```

Onboarding asks about your projects, region, budget and stack, and writes
`~/.startup-gcp-accelerator/profile.json`. Everything else reads it — this is
what makes an identical install behave correctly for *your* company.

### Using it in the Antigravity 2.0 app

**There is no separate install for the app.** `bootstrap.sh` installs into
`~/.gemini/config/plugins/`, which is a global location that both the `agy` CLI
and the desktop app read. Run it once and both surfaces have the harness.

So the app path is:

1. Run `./bootstrap.sh` in a terminal, as above. This is the only install step,
   and it is the same one CLI users run.
2. Run `/startup-onboard` once — in the CLI or in the app, either is fine. It
   writes `~/.startup-gcp-accelerator/profile.json`, which both surfaces read.
3. Restart the app if it was already open. Plugins are read at startup, so a
   running app will not see a fresh install.
4. Open **Customizations** and check that **startup-gcp-accelerator** is listed
   and switched on.

Then the same seven commands work in the app's chat box that work in `agy`.

Two things worth knowing. **Leave the plugin switched on in Customizations** —
turning it off disables the approval gate along with the commands, and leaves
behind the broad `gcloud` grants that only the gate makes safe. And everything in
this README is **verified on the CLI**; the app loads the same plugin, the same
rules and the same hooks, so the gate should behave identically, but it has not
yet been exercised there. If you are the first to run it in the app, try one
mutating command — say, asking `/gcp-do` to create a bucket — and confirm you
get an approval prompt before it runs.

IDE extensions are not supported.

`./bootstrap.sh --dry-run` shows every action without changing anything.
`--update` refreshes the pinned Google plugins. `--uninstall` removes the
harness and revokes every permission grant it installed — so gcloud goes back to
prompting on everything, rather than running unreviewed — and leaves your
profile and audit log in place.

## The approval gate

Every `gcloud` or `bq` command that changes state is shown to you before it runs,
with the target project, the cost, and how to undo it. You approve or you don't.

This is enforced by a `PreToolUse` hook, not by asking the model nicely. The hook
also:

- **denies** a mutation if the agent has not first verified the syntax with
  `gcloud help <command>` — the agent's memory of gcloud flags is unreliable, so
  it has to check;
- **denies** `--quiet`/`-q`, project deletion, token printing, and service-account
  key creation outright;
- **denies** reading your credentials — `~/.config/gcloud/*` and the Antigravity
  OAuth token — whether by `cat`, by `grep`, or with the file-read tool. Those
  files end up in transcripts and logs if they are ever opened;
- **forces a prompt** for anything it cannot read inside — `./deploy.sh`, `make`,
  `terraform apply`, `kubectl apply`, `helm install`, and scripts that import
  Google Cloud libraries.

Read-only commands (`describe`, `list`, `get-iam-policy`) run without prompting,
and so does local `git` — `status`, `diff`, `add`, `commit` and friends — along
with `terraform plan`/`validate`/`fmt`. That is deliberate: a gate that
interrupts fifty times an hour gets clicked through, which is worse than no
gate. One Conductor track was measured issuing 48 plain `git` commands to land a
single small fix. The line is simple: **local git is not gated; anything that
touches your cloud or leaves your machine is.** `git push` still prompts, and so
does `terraform apply`.

Every cloud command is appended to `~/.startup-gcp-accelerator/audit/commands.jsonl`.

### Two things you must not do

**Do not run `agy --dangerously-skip-permissions`.**

It disables the approval gate entirely, and nothing in this harness can override
it. Everything above stops applying — a mistyped project ID will delete
production without asking.

**Do not remove the harness by deleting the plugin by hand.** `settings.json`
grants `gcloud` and `bq` broadly, because the hook — not the permission list —
is what decides which commands need your approval. Delete the plugin without
running `./bootstrap.sh --uninstall` and you keep the grants but lose the gate,
which is worse than never having installed it.

## What each capability actually does

**`/gcp-ask`** delegates to a read-only subagent that queries Google's
`developer-knowledge` MCP server. It cites sources, distinguishes GA from
Preview, and won't quote prices as authoritative. It falls back to searching
`cloud.google.com` only when the docs corpus doesn't cover the question — the
corpus excludes blogs, release notes and YouTube.

**`/gcp-design`** runs Google's own solution-architecture workflow: it
interviews you for requirements, refuses to name a product until they are
settled, then produces a technical decomposition, a product mapping with
trade-offs, a Mermaid diagram and design recommendations — written to
`architecture-design-<date>.md`.

It routes on what you are building. An AI agent or multi-agent system gets the
agent design workflow, which covers agent topology, tools, retrieval, and
short- and long-term memory. Anything else gets the general one. **You choose
the runtime** — Agent Runtime, Cloud Run and GKE are all supported, and it will
ask rather than assume.

It stops at the design. No Terraform, no scaffolding, no deployment. Approving
an architecture and approving its implementation are two decisions, and the
first is far cheaper to change than the second.

**Conductor** is the build stage, installed unmodified. Point it at a requirement
in your own words, or at the `architecture-design-<date>.md` that `/gcp-design`
just wrote, and it turns that into a spec, a plan and an implementation — one
reviewable step at a time.

Read the spec before you let it implement. Conductor runs its own requirements
interview and knows nothing about Google Cloud, so a decision from your design can
quietly fail to carry over — a runtime or a product that became something else
along the way — and the spec is a far easier place to fix that than a finished
implementation.

Infrastructure-as-code stays yours. Conductor writes Terraform where a track calls
for it, and you can have Antigravity draft it outside a track or write it
yourself. The harness does not take ownership of your IaC — whatever ends up in
the repo is what `/architecture-review` reads and what you deploy.

**`/gcp-ai-eval`** is the Eval stage, for founders whose product is an AI agent.
It measures whether the thing you just built actually works — which is not
something `/architecture-review` can tell you, because whether an agent works is
not visible in Terraform.

Point it at an agent you have built and it recommends metrics for *that* agent
— reading your code to see whether it calls tools, holds a conversation, or
retrieves — then writes `ai-eval-<date>.md` and, if you want one, a synthetic
dataset (it asks whether, and how many samples).

The eval itself runs through a **shipped runner**, not a script written fresh
each time. It imports your ADK agent, runs it over the dataset, scores the
result, and saves a JSON and HTML report. The one thing it needs from you is
where your agent object lives — `--agent app.agent.agent:root_agent`.

**It works on a local ADK agent.** No deployment, no endpoint, nothing in Cloud
Run — so you can measure the thing before you ship it, which is the only point
at which the measurement is cheap. Evaluation itself does bill: scoring runs
LLM-as-judge calls, and the command comes to you for approval before it runs
like any other that costs money.

It stops at the scores. It will not tune your agent for you.

*Status.* The runner and the metric selection are exercised. The synthetic
dataset path is not: generating one makes a billed call, so no end-to-end
synthesis run has happened in this harness yet. Every dataset scored so far was
hand-written or parsed from traces. Treat the first `--count` you approve as the
thing being tested as much as the agent, and start small.

**`/architecture-review`** maps your repo into a structured inventory
(Terraform, k8s manifests, `app.yaml`, CI config, deploy scripts), then runs six
reviewers in parallel — one per WAF pillar — each read-only by construction. The
result is a ranked report at `architecture-review-<date>.md`, calibrated to
startup stage: single-region deployment is a noted trade-off with a trigger
point, not a P1 defect. Security exposure is always P1.

Point it at an architecture diagram too, if you have one. Where the diagram and
the code disagree, the code wins and the divergence is itself a finding.

**You can scope it to the pillars you care about** — "review my architecture,
security and reliability only" — and it writes a separate
`architecture-review-<date>-<pillars>.md` so it never overwrites a full review.
Note that this saves tokens and reading time rather than wall-clock: the pillars
run concurrently, so six take about as long as one. Asking *about* security is
not the same as scoping to it — the review stays full unless you say otherwise,
because the pillar that catches your outage is rarely the one you were worried
about.

**`/gcp-do`** operates your cloud without you needing to remember gcloud syntax.
Say what you want in plain language — "give this service account read access to
the policy bucket", "roll back to the previous revision", "why is this returning
403" — and it works out the command, shows you what it does and to which project,
and waits for you.

It is the deploy stage, and it is also every day after. `terraform plan` and
`validate` run without prompting so you can see what is coming; `terraform apply`
comes to you for approval like any other change. It will offer once to write
Terraform rather than run an imperative command — console and CLI changes are
invisible to the next review and to the next engineer you hire.

**If your build already produced a `deploy.sh` or Terraform, this is still what
you reach for.** A script describes what your infrastructure should look like. It
cannot tell you what is running right now, why the deploy stopped halfway and
what it left behind, which revision to roll back to, or what is driving this
month's bill. Those are questions and one-off actions, and they are most of the
work after the first deploy.

**`/gcp-ai-monitor`** picks up after you deploy. Point it at an agent running
on Agent Runtime (Vertex AI Agent Engine) and it checks what telemetry your
agent is actually emitting, derives thresholds from your real traffic rather
than guessing them, and writes `ai-monitor-<date>.md` explaining what each
alarm catches plus `alerts-<date>.tf` with the policies. Apply it with
`/gcp-do`.

It covers latency, error rates, cost and token usage, safety and security —
and, if your agent exports traces, response quality, tool-use quality and
hallucination. Those quality alarms need a Vertex AI Online Monitor, which
scores a sample of live traffic with LLM-as-judge calls and bills for them,
so it tells you the cost and asks first.

**It configures monitoring; it does not watch anything itself.** Once applied,
Google Cloud evaluates the policies around the clock — which is the point, as
nothing that only runs while you have a chat window open can notice a 3am
outage. For how your agent is doing right now, the Cloud Console has it.

## Requirements

- `agy` (Antigravity CLI), signed in
- `gcloud`, authenticated, with application default credentials
  (`gcloud auth application-default login`)
- the Developer Knowledge API, which is what `/gcp-ask` reads. `bootstrap.sh`
  enables it on your default project for you — but that needs the
  **`serviceusage.services.enable`** permission on that project, which is the
  one requirement here you may not already have. See below
- Python 3.8+

### The one IAM permission you need

Enabling the Developer Knowledge API requires **`serviceusage.services.enable`**
on the project you are enabling it against. It is in `roles/serviceusage.serviceUsageAdmin`,
and also in `roles/editor` and `roles/owner` — so on your own sandbox project you
almost certainly have it, and on a shared or corporate project you may well not.

If you do not, `bootstrap.sh` says so and prints the exact command to hand to
someone who does:

```bash
gcloud services enable developerknowledge.googleapis.com --project=<your-project>
```

The rest of the install completes either way. What you lose until the API is on
is `/gcp-ask` reading the documentation corpus — it falls back to plain web
search, which looks similar and is not the same thing. Everything else works.

Two other ways through it: point the harness at a project you do control, or ask
your admin for `roles/serviceusage.serviceUsageAdmin` so you can enable it
yourself next time. The API is read-only and free, which usually makes it an
easy ask.

## What gets installed

```
~/.gemini/config/plugins/
├── startup-gcp-accelerator/          this harness
│   └── skills/                        four vendored Google skills    (pinned)
├── google-cloud-core/                gcloud safety skill             (pinned)
├── google-cloud-well-architected/    six WAF pillars                 (pinned)
└── conductor/                        spec-driven development         (pinned)

~/.gemini/GEMINI.md                   always-on rules, in a marked block
~/.gemini/antigravity-cli/settings.json   permissions (merged, not replaced)
~/.gemini/config/mcp_config.json      docs MCP server (merged, not replaced)
~/.startup-gcp-accelerator/           your profile, gate state, audit log
```

Google's plugins are installed at pinned refs and are not modified. Bumping them
is deliberate — see the top of `bootstrap.sh`.

The install makes exactly one change outside your machine: it enables
`developerknowledge.googleapis.com` on your default project, because `/gcp-ask`
cannot read the documentation corpus without it. The API is read-only and free.
`--uninstall` leaves it enabled — by then other things may depend on it, and
turning off an API on your project is not the installer's call.

## Which Google skills you get

Thirteen, all pinned:

| From | Skills |
|---|---|
| `google-cloud-core` | `gcloud`, `google-cloud-recipe-auth`, `google-cloud-recipe-onboarding` |
| `google-cloud-well-architected` | the six WAF pillars |
| vendored for `/gcp-design` | `google-cloud-solution-architecture`, `google-cloud-solution-build-deploy-agents` |
| vendored for `/gcp-ai-eval` | `agent-platform-eval-flywheel` |
| vendored for `/gcp-ai-monitor` | `agent-platform-alert-configuration` |

The [`google/skills`](https://github.com/google/skills) catalogue is much larger
— 127 skills covering GKE, BigQuery, Cloud SQL, Spanner, Vertex and more. This
harness deliberately does **not** install them or discover them at runtime. A
small, known set behaves the same way for every startup in the batch, and skills
you did not choose are skills you cannot predict.

The two design skills are vendored rather than installed because upstream files
them under `skills/cloud/`, which belongs to no plugin, so `agy plugin install`
cannot reach them. `bootstrap.sh` fetches them at the pinned ref on every run.

`agent-platform-eval-flywheel` and `agent-platform-alert-configuration` are
vendored for a different reason: they *are* in a plugin, but that plugin ships
fifteen skills, and installing it to get two would put thirteen you did not
choose — tuning, model registry, prompt management — in front of you. Same
fetch, same pinned ref, same no-fork rule.

To add more, edit the pinned list at the top of `bootstrap.sh` and re-run. Whole
plugins — `google-cloud-gke` (13 skills), `google-cloud-gke-workloads` (16),
`google-cloud-run`, `gemini-enterprise-agent-platform` (15) — install cleanly
that way.

## Troubleshooting

**"Pre-flight syntax check needed" — a command came back refused.**

Nothing is wrong. Before a `gcloud` command it has not seen this session, the
agent has to check the flags with `gcloud help` first. Approve the help command
and it will re-propose the real one straight after.

**`/gcp-ask` answers with no citations, or cites only plain `cloud.google.com`
pages.**

It has lost the documentation corpus and fallen back to web search. Re-run
`./bootstrap.sh`, which tests the connection and prints what to fix. It is
usually one of two things: the Developer Knowledge API is not enabled on your
project — enabling it needs the `serviceusage.services.enable` permission, so on
a shared project you may need an admin — or you have no application default
credentials, which is `gcloud auth application-default login`.

**A cloud command ran without asking your approval.**

Check the plugin is still switched on in **Customizations**. Turning it off
removes the gate but leaves behind the broad `gcloud` permissions that only the
gate makes safe, so commands run unreviewed. Also confirm the session was not
started with `--dangerously-skip-permissions`, which bypasses every prompt. If
neither explains it, treat it as a bug worth reporting — this is the one thing
the harness exists to prevent. (`python3 scripts/test_gate.py` re-runs the
gate's own checks if you want to confirm it locally.)

**An architecture review does not mention resources you know you have.**

Reviews read your repository, so anything created by hand in the Cloud Console
is invisible to them. The report lists what it could not see under *Not
assessed* — read that section before treating a clean review as an all-clear.

## Design

The architecture in one line: `rules/` are always-on instructions, `skills/` are
the entry points, `agents/` are the read-only subagents they delegate to,
and `scripts/gate_gcloud.py` is the `PreToolUse` hook that every shell command
passes through before it runs. `bootstrap.sh` wires all of it into
`~/.gemini/`.

The gate's own test suite documents the security model better than prose does —
`scripts/test_gate.py` has 73 adversarial cases covering each known bypass path
(`bash -c` and `-lc`, command substitution, variable indirection, `sudo`/`env`
wrappers, `xargs`, opaque scripts and Makefile targets, flag-separated
`terraform`/`kubectl`/`helm` mutations, Python using `google.cloud.*`, data
MCPs). Read it if you want to know exactly what is and isn't stopped.
