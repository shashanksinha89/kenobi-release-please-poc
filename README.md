# kenobi-release-please-poc

POC for evaluating [release-please](https://github.com/googleapis/release-please) as the release-automation tool for `kenobi-c2s`.

Tracks **[COR-2622](https://linear.app/corestory/issue/COR-2622/evaluate-release-please-for-kenobi-c2s)** — part of the *[Release Process v2 — Tooling Evaluation & Migration](https://linear.app/corestory/project/release-process-v2-tooling-evaluation-and-migration-78b062cb78d5)* project.

**Status:** evaluation complete. **Recommendation: adopt with caveats.** See WRITEUP.md.

---

## Where to start reading

| Doc | When to read |
|-----|--------------|
| **[WRITEUP.md](./WRITEUP.md)** | Full evaluation: TL;DR, answers to the 7 questions in the ticket, all 4 lifecycle scenarios tested, gotchas + recommendations. **Read this first.** |
| **[RELEASE_MANAGER_GUIDE.md](./RELEASE_MANAGER_GUIDE.md)** | Step-by-step walkthrough for someone reproducing the scenarios in this POC themselves. ~25 minutes end-to-end. |
| **[final-workflows/README.md](./final-workflows/README.md)** | What goes where for the actual kenobi-c2s migration. Production-ready workflow files with all real ACR logins, helm `--set` lines, secret wiring, tenant image build chain. |

---

## What this POC actually is

A scratch repo mirroring kenobi-c2s' Python package side (no Helm chart — the chart lives in `crowdbotics/project-deploy` and is out of scope here). Five demo commits + four scenarios were run end-to-end through six tags and five `promote.yml` dispatches to validate the full release lifecycle.

The workflows in `.github/workflows/` are **stubs that `echo` placeholder commands** — they exercise release-please mechanics and the workflow plumbing, not the real docker build / helm deploy. The production-ready versions are in [`final-workflows/`](./final-workflows/).

## Repo layout

```
.
├── pyproject.toml                       # release-please bumps `version` here (currently 3.6.1)
├── release-please-config.json           # release-please config: python type, no v-prefix
├── release-please-manifest.json         # tracks current released version
├── .github/workflows/                   # POC stubs (3 files, consolidated)
│   ├── main.yml                         # release-please + build-versioned-image + build-deploy-dev
│   ├── promote.yml                      # qa/prod helm upgrade (manual dispatch)
│   └── pr-title-lint.yml                # Conventional Commits enforcement
├── final-workflows/                     # PRODUCTION-READY files for kenobi-c2s
│   ├── main.yml                         # full version with ACR logins, tenant image build
│   ├── promote.yml                      # full helm --set matrix matching today's behaviour
│   ├── pr-title-lint.yml                # same as POC stub
│   ├── release-please-config.json       # same as POC
│   ├── release-please-manifest.json     # seeded at 1.22.0 (the agreed reset target)
│   └── README.md                        # what-goes-where + safe migration sequence
├── app/                                 # demo Python files used to drive commits
├── WRITEUP.md                           # evaluation findings (read first)
└── RELEASE_MANAGER_GUIDE.md             # step-by-step scenario walkthrough
```

## Workflow structure (3 files, consolidated)

After the parity work, the proposed kenobi-c2s structure is **3 workflow files** instead of today's 4:

| File | Trigger | Jobs |
|------|---------|------|
| `main.yml` | push to main | `release-please` (always) + `build-versioned-image` (gated on Release-PR merge) + `build-deploy-dev` (parallel, always). Per-job `permissions:` and `concurrency:` blocks preserve least-privilege and per-flow queueing. |
| `promote.yml` | manual dispatch | qa/prod helm upgrade with semver-shape, tag-existence, and prerelease-to-prod guards. |
| `pr-title-lint.yml` | pull_request | Conventional Commits enforcement (must be required status check on `main`). |

Replaces today's `azure-build-deploy-dev.yml`, `azure-build-on-tag.yml`, `azure-build-promote.yml`, and `azure-hotfix-ci.yml`.

## Tag convention

Tags are **bare semver** (`1.2.3`, `1.2.3-rc.1`) — no `v` prefix. This matches the existing kenobi-c2s tag history (`19.0.2-rc`, `19.0.1`, ...) and is achieved via `include-v-in-tag: false`. The semver-shape regex in `promote.yml` is anchored on bare semver to enforce this.

## Commit conventions

```
<type>(<optional-scope>): <Subject — capital first letter>

<body — optional, free-form>

<footers — KENOBI-XXXX goes here>
```

| Type | Bump |
|------|------|
| `fix:` | patch |
| `feat:` | minor |
| `feat!:` or `BREAKING CHANGE:` footer | major |
| `chore:`, `docs:`, `style:`, `refactor:`, `perf:`, `test:`, `build:`, `ci:` | none (hidden in changelog) |

Example:

```
feat(api): Add tenant-aware chat endpoint

Routes chat requests through the new TenantContext middleware so
per-org isolation is enforced at the orchestrator boundary.

KENOBI-2371
```

`Release-As: X.Y.Z` footer forces an explicit version (used for hotfixes).

## How the lifecycle flows

```
                push to main (any commit)
                          │
            ┌─────────────┼─────────────┐
            │             │             │
            ▼             ▼             ▼
       release-please   build-     (build-versioned-
       (always runs)    deploy-dev  image waits)
            │           (always
            │           runs;
            │           no needs:)
            │
        On Release-PR merge:
        cuts tag X.Y.Z + GitHub Release
            │
            ▼
       build-versioned-image
       (gated on release_created)
       builds X.Y.Z image + tenant image
```

Then **manual dispatch of `promote.yml`** to deploy the `X.Y.Z` tagged image to qa, then production. Same human-gated pattern as today.

## What was tested

| Scenario | Outcome |
|----------|--------|
| Merge to main → auto-deploy to dev | ✅ `build-deploy-dev` runs in parallel, even on non-bumping commits |
| Cut a release (Release PR merge) | ✅ tag cut, versioned image built, dev deploy also runs, all in one workflow run |
| Promote to QA / prod | ✅ all 6 sub-tests: stable→qa, stable→prod, bad-shape blocked, missing-tag blocked, prerelease→qa allowed, prerelease→prod blocked |
| Hotfix via `Release-As:` | ✅ cut 3.6.1 directly while manifest at 3.7.0-rc.1; promoted through qa→prod. **Footgun documented:** orphans the in-flight RC line; release-branch model is the cleaner alternative for that case. |

Six tags cut: `1.23.0`, `2.0.0`, `3.5.0`, `3.6.0`, `3.7.0-rc.1`, `3.6.1`, `3.7.0`. Detailed walkthrough in WRITEUP.md.

## Status

- ✅ Mechanics validated end-to-end
- ✅ All 7 evaluation questions answered (WRITEUP.md)
- ✅ Production-ready workflow files written (final-workflows/)
- ✅ Step-by-step reproduction guide (RELEASE_MANAGER_GUIDE.md)
- ⏭ Pending: team review + COR-2624 (decision ADR + Notion doc update)
- ⏭ Pending: empirical test of the release-branch hotfix model (currently only documented theoretically)
