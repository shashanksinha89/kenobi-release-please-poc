# release-please evaluation — Writeup

**Ticket:** [COR-2622](https://linear.app/corestory/issue/COR-2622/evaluate-release-please-for-kenobi-c2s)
**POC repo:** [shashanksinha89/kenobi-release-please-poc](https://github.com/shashanksinha89/kenobi-release-please-poc)
**Date:** 2026-05-07

---

## TL;DR

**Recommendation: adopt with caveats.**

release-please works exactly as advertised for kenobi-c2s. The Release-PR pattern is a clean fit for our gated production-release flow, and the single-workflow `needs:` chain sidesteps the GitHub-App/PAT footgun entirely. The friction is migration overhead — Conventional-Commits + PR-title-lint contracts are the actual ask, not the tool itself. About a half-day of plumbing to land on kenobi-c2s; one day to also retrofit project-deploy if we want chart `appVersion` auto-bumping.

The thing that matters most for this team: **the version decision moves from someone's head into the commit log**. Today there's no audit trail on "should this be a minor or patch?" — with release-please there is.

---

## What the POC demonstrated end-to-end

5 commits, 3 releases, all bumped deterministically, all cut by humans merging the Release PR:

| # | Commit | Type | Effect | Resulting tag |
|---|--------|------|--------|---------------|
| 1 | `chore: Initial POC scaffold` | chore | No bump (Release PR doesn't open) | — |
| 2 | `fix: Return 200 from healthcheck stub` | fix | patch | (accumulated → PR #1) |
| 3 | `feat(api): Add tenant middleware stub` | feat | absorbed → minor | `1.23.0` after merge |
| 4 | `feat(api)!: Replace v1 endpoint with v2 contract` | feat! | major | `2.0.0` after merge |
| 5 | `docs: Add quick docs note (Release-As: 3.5.0)` | docs + footer override | forced | `3.5.0` after merge |

All tags emitted bare (no `v` prefix) via `include-v-in-tag: false`, which matches the existing kenobi-c2s tag history (`19.0.2-rc`, `19.0.1`, ...).

The downstream `build` job (a stub `echo` to demonstrate option #3 — same workflow, `needs:` chain) ran successfully on each merge with full access to `release-please.outputs.tag_name`, `version`, `major`, `minor`, `patch`. **No GitHub App, no PAT, no cross-workflow trigger needed.**

---

## Answers to the 7 ticket questions

### 1. Does the squash-merge → PR title flow play nicely?

**Yes.** GitHub's default squash-merge takes the PR title as the squash commit subject. release-please reads that subject for type/scope/breaking detection. Confirmed empirically — every merge in the POC was a squash merge and bumps were correctly identified.

**Required extra config:** none in release-please. The contract you're enforcing isn't on release-please's side — it's on the *humans* and the *PR title lint* (see Q2). Without lint, one bad squash-merge produces a wrong bump or no bump at all.

### 2. PR title lint — action and config?

**Action:** [`amannn/action-semantic-pull-request@v5`](https://github.com/amannn/action-semantic-pull-request).

**Config used in POC:** see `.github/workflows/pr-title-lint.yml`. Key choices:
- `types: feat, fix, docs, style, refactor, perf, test, build, ci, chore, revert` — matches release-please's known types
- `requireScope: false` — scopes are optional (`feat:` and `feat(api):` both valid)
- `subjectPattern: ^[A-Z].+$` — subject must start with capital letter, so changelog reads "Add foo" not "add foo"

**Can it block merge?** Yes — register the `pull_request` workflow as a required status check in branch protection. PRs whose titles don't match the pattern won't be mergeable. In the POC repo I left it advisory; in kenobi-c2s I'd make it required.

### 3. KENOBI-XXXX ticket prefixes — subject or footer?

**Recommendation: footer.** Tested both:

```
✗ feat(api): KENOBI-2371 Add tenant middleware  ← changelog reads "KENOBI-2371 Add..."
✓ feat(api): Add tenant middleware              ← changelog reads "Add tenant middleware"
   <body>
   KENOBI-2371                                  ← ticket searchable in commit log + PR
```

The footer route keeps the changelog clean (the ticket prefix isn't useful for end-users reading release notes), while still being searchable via `git log --grep` and visible in the PR/commit body. The POC commits used the footer convention (`KENOBI-9999`, `KENOBI-9998`).

If we want **enforcement** of ticket presence, that's a separate PR-body-lint action — release-please doesn't care.

### 4. Multi-package versioning?

**Not tested empirically, but well-documented.** release-please supports it via `packages` in `release-please-config.json`:

```json
{
  "packages": {
    "backend": { "release-type": "python", "package-name": "kenobi-backend" },
    "arq-worker": { "release-type": "python", "package-name": "kenobi-arq" },
    "helm": { "release-type": "helm", "package-name": "kenobi-c2s-chart" }
  },
  "plugins": ["linked-versions"]
}
```

Each package gets its own version + Release PR (or one bundled Release PR via `linked-versions` plugin). Tags are scoped via `include-component-in-tag: true` — e.g. `backend-1.5.0`, `arq-worker-2.1.0`.

**Practical answer for kenobi-c2s today:** single-package is right. We'd reach for multi-package only if backend and arq-worker version *independently*, which they don't currently. If that splits later, the migration is a config change, not a re-adoption.

### 5. Auth model — GitHub App needed?

**With option #3 (single workflow, `needs:` chain): NO.** This was the most consequential finding.

GitHub's default `GITHUB_TOKEN` cannot trigger downstream workflows — events created by it (tag push, release publish) are intentionally ignored by other workflows to prevent infinite loops. So `on: push: tags` or `on: release: published` build workflows would silently never fire when release-please is using the default token.

**The fix is option #3:** put the build job in the *same* workflow as release-please, with `needs: release-please` + `if: needs.release-please.outputs.release_created == 'true'`. Same workflow run, same auth context, no cross-workflow trigger needed. The downstream job just reads outputs.

**One thing that DID need a setting flip:** "Allow GitHub Actions to create and approve pull requests" must be enabled in repo settings → Actions → General. Default is off. First sign of trouble was the error `GitHub Actions is not permitted to create or approve pull requests.` — solved with one-time API call:

```bash
gh api -X PUT /repos/{owner}/{repo}/actions/permissions/workflow \
  -f default_workflow_permissions=write \
  -F can_approve_pull_request_reviews=true
```

For kenobi-c2s, this is the only repo-setting change required.

### 6. Pre-release support (RC channel from develop, stable from master)?

**Not tested empirically; documented support.** release-please supports per-branch config via the `prerelease: true` flag and `prerelease-type: rc` (or beta, etc.). Two approaches:

**Approach A — Two workflow files, branch-scoped:**
- `release-please-develop.yml`: `on: push: branches: [develop]`, config with `prerelease: true`, emits `1.23.0-rc.1`, `1.23.0-rc.2`...
- `release-please-master.yml`: `on: push: branches: [master]`, stable config, emits `1.23.0`

**Approach B — Single config with branches block:**
```json
{
  "branches": [
    { "name": "master" },
    { "name": "develop", "prerelease": true, "prerelease-type": "rc" }
  ]
}
```

The temporary semver-shape guard in PR #1461 already accepts `-rc.N` suffixes (`v1.2.3 or v1.2.3-rc.1`), so the existing prerelease-to-prod-blocker logic in `azure-build-promote.yml` would still apply as belt-and-suspenders.

**For trunk-based:** if we abandon develop/master entirely and go single-branch, you lose the stable/RC distinction at the branch level. You'd then use the manual `Release-As:` footer to mark a commit as "promote this to stable" — which is more friction. **My read:** keep develop+master if we want a clean RC channel; collapse to trunk only if we're confident every commit on main is shippable.

### 7. Migration — preserving existing tag history?

**No data loss.** release-please reads commit history, not tag history, to make bump decisions. Existing tags stay where they are — they're just frozen as "old releases." The `bootstrap-sha` config tells release-please which commit is the "first commit it should consider," so we can point it at a specific SHA (e.g. the PR-merge commit that adopts release-please) and avoid retroactively walking 200+ pre-adoption commits.

**The `v` prefix question** turned out to be moot — current kenobi-c2s tags are bare (`19.0.2-rc`, `19.0.1`), not v-prefixed. My earlier reply on PR #1461 about the `v` prefix being from existing history was wrong — corrected on the thread. release-please was configured with `include-v-in-tag: false` to match.

**Migration sequence I'd recommend:**
1. Land a PR with `release-please-config.json`, `release-please-manifest.json` (seeded at the chosen starting version — 1.22.0 per ticket), the workflow, and PR title lint.
2. Set `bootstrap-sha` to the merge commit SHA.
3. First Release PR opens covering only commits *after* that SHA.
4. Merge it → first auto-tag cut (e.g. `1.22.1` if there are fix-only commits since bootstrap).
5. Old `19.x` tags remain in the repo for archeology — nothing's deleted.

---

## Gotchas observed in the POC

1. **Repo permission flip required.** "Allow GitHub Actions to create and approve pull requests" defaults to off. First push fails with a generic "not permitted" error — fixable with one API call (above). Should be part of the migration runbook.

2. **GitHub Release name auto-prefixes `v`.** The tag is bare (`1.23.0`) but the GitHub Release *name* shows as `v1.23.0`. The release UI is cosmetic; consumers reading the tag via API or git get the bare value. Configurable via release-please options if it bothers reviewers — leaving as-is for the POC.

3. **`Release-As:` footer overrides type-based bump rules entirely.** A `docs:` commit (which would normally not produce a release at all) successfully forced version 3.5.0 via the footer. This is powerful but worth knowing — a misuse of `Release-As:` could cut an unintended major bump. Treat it as a privileged operation.

4. **`chore:` commits don't open a Release PR.** Initial scaffold commit (`chore:`) produced no Release PR until the first qualifying commit landed. Expected, but worth noting that a quiet release-please workflow doesn't mean broken — it might just be waiting for a `feat:` or `fix:`.

5. **Leftover release branch.** release-please uses a long-lived branch (`release-please--branches--main--components--kenobi-c2s`) for the Release PR. After merge, the branch isn't auto-deleted. Cosmetic; can be ignored or cleaned up via repo settings ("Auto-delete head branches").

6. **Node 20 deprecation warning** on `googleapis/release-please-action@v4`. Annoying-but-not-blocking. Action will likely cut a v5 before the September 2026 enforcement date.

---

## Cross-repo concern (out of scope for this POC, but flagged)

The kenobi-c2s release tag is the *image tag*. The Helm chart `appVersion` in `project-deploy/azure/helm-chart/kenobi-c2s/deployment-app/Chart.yaml` is **not currently maintained** (it shows `1.16.0` while real tags are at `19.x`). This wasn't broken by anything — it was never wired up.

If we want chart `appVersion` to track image releases automatically, two options:
- **Single source-of-truth**: kenobi-c2s emits a release → a follow-up workflow opens a PR in project-deploy bumping `Chart.yaml`. Not release-please's job.
- **Two-package release-please**: one in kenobi-c2s (Python), one in project-deploy (Helm). Each independent.

I'd default to option 1 — chart bump as a one-line follow-up PR triggered from kenobi-c2s release events. That's a Phase 2 ticket, not a blocker for adoption.

---

## What this doesn't solve

- **Slack/Teams notifications** for release events. Not release-please's job — straightforward to add a step in the same workflow.
- **Promoting a build between environments** (dev → qa → prod). release-please cuts the tag; how/when the tag deploys is the existing build-promote workflow's responsibility. The temporary semver-shape guard in PR #1461 stays useful.
- **Forcing engineers to use Conventional Commits.** PR title lint helps, but humans can still write a misleading subject. This is a culture/discipline concern.
