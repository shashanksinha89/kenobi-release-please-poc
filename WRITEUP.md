# release-please evaluation — Writeup

**Ticket:** [COR-2622](https://linear.app/corestory/issue/COR-2622/evaluate-release-please-for-kenobi-c2s)
**POC repo:** [shashanksinha89/kenobi-release-please-poc](https://github.com/shashanksinha89/kenobi-release-please-poc)
**Date:** 2026-05-07 (updated 2026-05-08 with full kenobi-c2s lifecycle parity)

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
- **Forcing engineers to use Conventional Commits.** PR title lint helps, but humans can still write a misleading subject. This is a culture/discipline concern.

---

## Full kenobi-c2s lifecycle parity test (2026-05-08)

After validating release-please mechanics on day 1, the second round of testing wired up workflows mirroring the real kenobi-c2s structure to prove the four end-to-end lifecycle scenarios work without behavioural change for the team.

### Workflow mapping kenobi-c2s → POC

After consolidation: **3 workflow files** instead of 4. Both `release-please` mechanics and `build-deploy-dev` live in one `release-and-dev.yml` (both fire on `push: main`), with per-job `permissions:` and `concurrency:` blocks preserving least-privilege and per-flow queueing.

| kenobi-c2s | POC | Trigger | What it does |
|---|---|---|---|
| `azure-build-deploy-dev.yml` | `release-and-dev.yml :: build-deploy-dev` job | push to main | Build sha-tagged image, deploy to dev. **No `needs:` clause** — runs in parallel with `release-please` job; dev rollouts not blocked by release-please failures. |
| `azure-build-on-tag.yml` | `release-and-dev.yml :: build-versioned-image` job | push to main → Release PR merge | Build versioned image. Gated on `needs.release-please.outputs.release_created == 'true'`. Replaced by `needs:` chain instead of cross-workflow tag-trigger (avoids the `GITHUB_TOKEN` footgun). |
| `azure-build-promote.yml` | `promote.yml` | manual dispatch | Validate semver, verify tag exists, block prerelease→prod, helm upgrade. |
| `azure-hotfix-ci.yml` | (folded into Release-As flow + branch-config) | — | The current "build sha-tagged image as standalone hotfix path" is largely obsolete with release-please — see hotfix scenario below. |

### Scenario 1 — Merge to main → auto-deploy to dev

Pushed `feat(cache): Add cache stub` to main. Result: **both workflows fired in parallel**.

- `build-deploy-dev.yml` built `sha-1ef47d4` and deployed to dev (stub) — same behaviour as today.
- `release-please.yml` ran but only updated/opened a Release PR (`3.6.0`). No tag yet — that requires the Release PR merge.

**Key insight:** Dev cluster always reflects main HEAD on every merge, regardless of release cadence. Decoupling the two workflows preserves this property and matches what the team is used to today.

### Scenario 2 — Release cut

Merged the Release PR (`chore(main): release 3.6.0`). Two workflows fired on the merge commit:

- `release-please.yml` run: release-please job cut tag `3.6.0` + GitHub release. **build-versioned-image** job (in same workflow run) then ran via `needs:` chain — built versioned stub `kenobi-c2s:3.6.0`.
- `build-deploy-dev.yml` ALSO fired (because the merge commit is a push to main) — built `sha-0bdefe4` and stub-deployed to dev.

**Side-note worth flagging:** the merge commit IS the tag commit, so `kenobi-c2s:3.6.0` and `kenobi-c2s:sha-0bdefe4` are content-identical (same source). The pyproject.toml + manifest version bumps land in that same commit. Functionally, dev runs the 3.6.0 code, just tagged differently. Not a problem, but worth pointing out so people don't get confused looking at the registry.

### Scenario 3 — Promote to QA / prod (with the failure modes)

Manual dispatch of `promote.yml`. Six tests run, all behaving as designed:

| Test | Tag | Env | Expected | Actual |
|---|---|---|---|---|
| 3a | `3.6.0` | qa | succeed | ✓ deployed |
| 3b | `3.6.0` | production | succeed (stable) | ✓ deployed |
| 3c | `v3.6.0` | qa | **fail** semver-shape (no v prefix allowed) | ✓ blocked at validation |
| 3d | `99.99.99` | qa | **fail** tag-existence | ✓ blocked at "tag does not exist" |
| 3e | `3.7.0-rc.1` | qa | succeed (prereleases allowed in qa) | ✓ deployed |
| 3f | `3.7.0-rc.1` | production | **fail** prerelease-to-prod block | ✓ blocked |

The semver regex differs from kenobi-c2s' current `azure-build-promote.yml`: ours is anchored on bare semver (no `v` prefix). The temporary guard from PR #1461 in real kenobi-c2s graduates from "temporary" to permanent here — it now acts as belt-and-suspenders against someone manually pushing a non-semver tag.

### Scenario 4 — Hotfix

Pushed `fix(api): Patch null-pointer in tenant resolver` with `Release-As: 3.6.1` footer. Manifest was at `3.7.0-rc.1` from prior scenario; the footer overrode that and forced the next release to `3.6.1`.

- Release PR `chore(main): release 3.6.1` opened ✓
- Merged → tag `3.6.1` cut + build-versioned-image fired ✓
- `promote.yml` 3.6.1 → qa ✓ → production ✓

**Hotfix footgun discovered:** after the `Release-As: 3.6.1` merge, the manifest is now at `3.6.1`. The previously-cut `3.7.0-rc.1` prerelease is **orphaned** — the next normal `feat:` commit will bump from 3.6.1 to 3.7.0, NOT continue on the 3.7-rc line.

**Convenience: `Release-As:` in PR body as an alternative to commit footers.** Tested empirically 2026-05-08:

- Putting `Release-As: 5.0.0-rc.1` as a **PR body footer** + squashing with repo settings `squash_merge_commit_message=PR_BODY` → release-please respected the override and cut tag `5.0.0-rc.1` (skipped the natural `3.8.0`).
- Putting a `release-as: 5.0.0-rc.1` **PR label** on a feature PR before merge → label was **ignored**; release-please opened the natural `3.8.0` Release PR. The `release-as:` label is NOT a release-please feature.

So the supported override surfaces are:
1. `Release-As:` footer in the engineer's commit message — the canonical way
2. `Release-As:` footer in the PR body, only if repo squash settings carry PR body into the commit body — useful when the release manager wants to override without amending the engineer's commit

See `RELEASE_MANAGER_GUIDE.md` for the exact repo-settings command and a worked example.

Real consequence: if you have an in-flight prerelease `1.23.0-rc.1` (say, RC for an upcoming minor) and you need to ship a hotfix for currently-prod 1.22.0 → you'd `Release-As: 1.22.1` from main. After that, the next `feat:` on main produces `1.22.2` or `1.23.0` (depending on bump), and your RC line is broken until you `Release-As: 1.23.0-rc.2` or similar to rejoin it.

**The cleaner alternative — release-branch model:**

Maintain a long-lived `release-1.22.x` branch from the 1.22.0 tag. Configure release-please with branch-specific scope so commits on that branch produce 1.22.x patches independently of main. Hotfix flow becomes:

1. `git checkout -b release-1.22.x v1.22.0`
2. Cherry-pick or land hotfix commit on that branch
3. release-please opens a Release PR on `release-1.22.x` for `1.22.1`
4. Merge → tag `1.22.1` cut from the release branch, not from main
5. `promote.yml 1.22.1 → production` — prod now on hotfix; main is untouched and the RC line continues

This is the pattern that's robust against the in-flight-prerelease problem. Setup cost: one config change + branch protection rule. **Recommendation: use Release-As for trunk-only hotfixes when there's no in-flight RC; use a release branch when RC + hotfix collision is a real risk.**

### What the team needs to do differently (final answer)

Compared to today:
- **Same:** push to main auto-deploys to dev. Dispatching a manual workflow promotes to qa/prod. Tag format. Semver enforcement. Prerelease block.
- **New:** instead of hand-cutting `git tag v1.2.3 && git push --tags`, the engineer merges a release-please-generated PR. The PR shows exactly what's about to ship (changelog + version bump diff) — strictly more information than the current manual-tag flow.
- **New constraint:** PR titles must follow Conventional Commits. PR title lint blocks merges that don't.
- **New workflow file structure (3 files total):**
  - `release-and-dev.yml` — single workflow on `push: main` containing 3 jobs: `release-please`, `build-versioned-image` (gated on Release PR merge), `build-deploy-dev` (parallel, always runs). Replaces `azure-build-deploy-dev.yml` + `azure-build-on-tag.yml`.
  - `promote.yml` — manual dispatch, qa/prod helm upgrade. Replaces `azure-build-promote.yml` (regex updated for bare semver, `create_release` input dropped since release-please creates the GitHub Release at merge time).
  - `pr-title-lint.yml` — pull_request trigger, Conventional Commits enforcement. New requirement.
  - **Retire:** `azure-build-on-tag.yml`, `azure-hotfix-ci.yml`. The Release-As footer covers trunk-only hotfixes; release branches cover the in-flight-RC case.

### Final POC repo state

After day-2 testing, 7 tags cut total, 5 promote.yml dispatches, 2 hotfix scenarios validated:

```
3.6.1        ← hotfix via Release-As (current manifest)
3.7.0-rc.1   ← prerelease via Release-As (orphaned by hotfix)
3.6.0        ← normal minor bump via feat: commit
3.5.0        ← Release-As docs override (day 1)
2.0.0        ← major bump via feat!: (day 1)
1.23.0       ← minor bump via feat: (day 1)
```

All tags emitted bare (no `v` prefix). Dev was deployed on every main push. QA and production deploys exercised guards correctly. Hotfix flow ran end-to-end with documented footgun + mitigation.
