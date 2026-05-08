# Final workflows for kenobi-c2s — production-ready

These are the **actual files** that should land in `crowdbotics/kenobi-c2s` to adopt release-please. Unlike the stub workflows at the root of this POC repo (which use `echo` placeholders for the build/deploy steps), these contain the real ACR logins, helm `--set` lines, secret/var wiring, and tenant image build chain — copied 1:1 from the existing kenobi-c2s workflows where the behaviour is unchanged.

## What goes where

| File here | Goes to | Replaces |
|---|---|---|
| `main.yml` | `kenobi-c2s/.github/workflows/main.yml` | `azure-build-deploy-dev.yml` + `azure-build-on-tag.yml` |
| `promote.yml` | `kenobi-c2s/.github/workflows/promote.yml` | `azure-build-promote.yml` |
| `pr-title-lint.yml` | `kenobi-c2s/.github/workflows/pr-title-lint.yml` | (new — required) |
| `release-please-config.json` | `kenobi-c2s/release-please-config.json` (repo root) | (new) |
| `release-please-manifest.json` | `kenobi-c2s/release-please-manifest.json` (repo root) | (new) |

## What gets deleted from kenobi-c2s

| File | Why |
|---|---|
| `.github/workflows/azure-build-deploy-dev.yml` | Folded into `main.yml :: build-and-deploy-dev` job |
| `.github/workflows/azure-build-on-tag.yml` | Folded into `main.yml :: build-versioned-image` job (gated on Release-PR merge) |
| `.github/workflows/azure-build-promote.yml` | Replaced by `promote.yml` (regex updated for bare semver, `create_release` input dropped) |
| `.github/workflows/azure-hotfix-ci.yml` | Replaced by `Release-As:` footer (trunk hotfix) or release branch (in-flight RC) |

## Job graph in `main.yml`

```
                 push to main
                       │
        ┌──────────────┼──────────────────┐
        │              │                  │
        ▼              ▼                  ▼
  release-please   build-and-       (release-please
  (always)         deploy-dev        only — no parallel
        │          (always,           job for chore: etc.)
        │          parallel —
        │          no `needs:`)
        ▼
  build-versioned-image     ◄── if release_created == 'true'
        │                       (i.e. only on Release-PR merge)
        ▼
  build-versioned-tenant
                                  (build-tenant-image-sha
                                   chains off
                                   build-and-deploy-dev too)
```

- **`release-please`**: opens/updates the Release PR. On Release-PR merge, cuts the tag + GitHub Release.
- **`build-versioned-image`**: builds the versioned base image (tagged `1.2.3`, `latest`). Fires only on Release-PR merge.
- **`build-versioned-tenant-image`**: builds the Nuitka tenant image for the versioned base.
- **`build-and-deploy-dev`**: sha-tagged build + dev rollout. Runs on EVERY main push including the Release-PR merge commit.
- **`build-tenant-image-sha`**: tenant image build chain off the sha-tagged dev image.

## What stays unchanged from current kenobi-c2s

These workflows are orthogonal to release process and don't move:
- `auto-assign-reviewers.yml`
- `auto-label-paths.yml`
- `azure-review-app.yml`, `azure-review-app-cleanup.yml`
- `azure-tenant-build.yml`
- `daily-status.yaml`, `weekly-roundup.yaml`, `monthly-roundup.yaml`
- `label-approved-prs.yml`
- `llm-observability-coverage.yml`
- `migration_check.yaml`
- `needs-attention.yml`
- `notify-slack-on-paths.yml`
- `playwright-qa.yml`
- `pre-commit.yaml`
- `run-tests.yml`
- `security-scan.yaml`
- `update-skill-reference.yml`

## One-time repo settings to flip

```bash
# Allow GitHub Actions to create and approve PRs (release-please needs this).
# Without this, the first push fails with "GitHub Actions is not permitted to
# create or approve pull requests".
gh api -X PUT /repos/crowdbotics/kenobi-c2s/actions/permissions/workflow \
  -f default_workflow_permissions=write \
  -F can_approve_pull_request_reviews=true
```

## Branch protection on `main`

Add **`pr-title-lint / validate`** as a required status check. This is the only enforcement preventing a non-conventional PR title from landing and silently breaking the bump computation.

## Migration sequencing (recommended)

A safe, reversible cutover:

1. Open one PR that:
   - Adds `release-please-config.json` + `release-please-manifest.json` (seeded at the current released kenobi-c2s version)
   - Adds the three new workflows (`main.yml`, `promote.yml`, `pr-title-lint.yml`)
   - **Does NOT delete the old workflows yet**
2. After merge, push a `chore:` (or any commit) and verify:
   - `main.yml` ran with all expected jobs
   - `azure-build-deploy-dev.yml` also ran (still present — duplicate dev deploy is safe)
   - The Release PR opens correctly when a `feat:` lands
3. Cut one release end-to-end via the Release PR. Verify versioned image + tenant image are built. Verify `promote.yml qa → production` works for the new bare-semver tag.
4. Open a second PR that **deletes** the old `azure-build-*.yml` files. After this, only the new workflows remain.
5. Update branch protection to require `pr-title-lint / validate`.

This order means the new system runs in shadow alongside the old for a brief period — easy to roll back if something unexpected surfaces. After the migration completes (typically 1–2 days), step 4 finishes the transition.

## Things that intentionally do NOT move into release-please

| Concern | Why it stays separate |
|---|---|
| Helm chart `appVersion` (in project-deploy) | Different repo, different release cadence. If we want chart-bump-on-kenobi-release, it's a one-line follow-up PR triggered from kenobi-c2s release events — not a second release-please instance. |
| OnTenant ACR image copies | Already handled in the tenant-build jobs as in current kenobi-c2s. No change. |
| Slack notifications | Same `crowdbotics/github-actions/slack-notify@master` action, same secrets. |
| Pod `predeploy-job` diagnostics | Same diagnostic dump as current azure-build-deploy-dev.yml. |

## What "feels" different to engineers

- **PR titles must be Conventional Commits.** PR title lint blocks otherwise. This is the biggest behavioural change.
- **Cutting a release** is now: merge a PR (the auto-generated "Release PR"), instead of `git tag X.Y.Z && git push --tags`.
- **Tag format** is bare semver (`1.2.3`) instead of v-prefixed (`v1.2.3`). The existing `19.x` history stays where it is.
- **Hotfix flow** uses `Release-As:` footer for the trunk-only case, or a release branch when there's an in-flight RC.

Everything else — dev auto-deploy, qa/prod helm upgrade, secret wiring, tenant image build, Slack notifications — works identically to today.
