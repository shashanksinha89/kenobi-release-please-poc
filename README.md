# kenobi-release-please-poc

POC scaffold for evaluating [release-please](https://github.com/googleapis/release-please) as the release-automation tool for `kenobi-c2s`.

Tracks COR-2622 (part of the [Release Process v2 — Tooling Evaluation & Migration](https://linear.app/corestory/project/release-process-v2-tooling-evaluation-and-migration-78b062cb78d5) project).

## Why a separate repo

`kenobi-c2s` ships:

- A Python FastAPI backend (in `crowdbotics/kenobi-c2s`)
- A Docker image built from that source
- (Indirectly) consumed by Helm charts that live in **`crowdbotics/project-deploy`**, NOT in kenobi-c2s itself

This POC mirrors only the kenobi-c2s side (a single Python package, no Helm chart). Cross-repo bumping (project-deploy `Chart.yaml.appVersion` follows kenobi-c2s release tags) is documented as a separate concern in the writeup.

## What's in here

| File | Purpose |
|------|---------|
| `pyproject.toml` | Mirrors kenobi-c2s — release-please bumps `version` here |
| `release-please-config.json` | release-please configuration (Python release-type, no `v` prefix on tags, hidden chore/docs/etc. sections in changelog) |
| `release-please-manifest.json` | Tracks the current released version (seeded at 1.22.0 — agreed reset target post COR-2560) |
| `.github/workflows/release-please.yml` | The release-please workflow + a stub downstream `build` job using `needs:` chain (option #3 from the discussion) |
| `.github/workflows/pr-title-lint.yml` | `amannn/action-semantic-pull-request` enforcing Conventional Commits in PR titles (squash-merge → PR title becomes the commit subject) |

## Tag convention

Tags emitted by release-please here follow the **existing kenobi-c2s convention** — bare semver, no `v` prefix (`19.0.2-rc`, `19.0.1`, ...) — via `include-v-in-tag: false`. The temporary regex in `azure-build-promote.yml` (PR #1461) accepts `v` prefix today but the final state is bare semver.

## Commit conventions (proposed)

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
| `chore:`, `docs:`, `style:`, `refactor:`, `perf:`, `test:`, `build:`, `ci:` | none |

Example:

```
feat(api): Add tenant-aware chat endpoint

Routes chat requests through the new TenantContext middleware so
per-org isolation is enforced at the orchestrator boundary.

KENOBI-2371
```

For pre-1.0 (0.x) packages, release-please **does not** auto-promote on `feat!:` — you must explicitly bless 1.0 via a `Release-As: 1.0.0` footer. We're starting at 1.22.0, so this doesn't apply, but worth knowing.

## How the flow works

1. Push a Conventional Commit to `main` (typically via PR squash-merge).
2. `release-please` workflow runs, parses commits since the last tag, decides the next bump, and either:
   - Opens (or updates) a long-lived **Release PR** titled e.g. `chore(main): release 1.23.0` — contains the version bump in `pyproject.toml`, the manifest update, and the generated `CHANGELOG.md` entry.
   - Or, if no qualifying commits exist, does nothing.
3. When a human merges the Release PR, release-please tags `1.23.0` and creates a GitHub Release in the same job.
4. Because the `build` job uses `needs: release-please` + `if: release_created == 'true'`, it runs in the same workflow run — no GitHub App / PAT needed (avoids the `GITHUB_TOKEN`-can't-trigger-other-workflows footgun).

## Demo timeline

Demo commits land sequentially after the initial seed; check the [Releases tab](../../releases) and [Pull Requests](../../pulls?q=is%3Apr+chore%3A+release) for the resulting tags + Release PR contents. See `WRITEUP.md` (added at the end of the evaluation) for the full walkthrough and answers to the 7 questions in COR-2622.
