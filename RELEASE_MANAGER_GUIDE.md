# Release Manager Guide — release-please POC

A hands-on walkthrough for a release manager (or anyone evaluating this) to reproduce every scenario covered in WRITEUP.md and *understand* what each step does mechanically.

**Estimated time to run all 4 scenarios end-to-end: ~25 minutes.**

---

## Part 1 — How this is working (read first)

Before pushing anything, get this picture in your head. The mechanics matter more than the commands.

### The four moving parts

```
┌──────────────────────┐    ┌──────────────────────┐    ┌──────────────────────┐
│   You (engineer)     │    │   You (engineer)     │    │  release-manager     │
│   open a regular PR  │    │   merge that PR      │    │  merges Release PR   │
└──────────┬───────────┘    └──────────┬───────────┘    └──────────┬───────────┘
           │                           │                           │
           ▼                           ▼                           ▼
   PR title lint runs         build-deploy-dev: builds         release-please:
   (action-semantic-PR)        sha-tagged image, deploys       cuts tag + GitHub
   blocks merge if title       to dev (always)                 release in same job
   isn't conventional                  +                                  +
                              release-please: opens or         build-versioned-image:
                              UPDATES the long-lived           builds versioned image
                              "Release PR" with the new        (needs: release-please,
                              accumulated commits +            same workflow run)
                              version bump                                +
                                                              build-deploy-dev: ALSO
                                                              fires (this merge is
                                                              still a push to main)
```

### What is "the Release PR"?

release-please maintains **one long-lived PR** at any given time, on a branch named like `release-please--branches--main--components--kenobi-c2s`. The PR title looks like `chore(main): release 3.6.0`. It contains:

- The version bump in `pyproject.toml` and `release-please-manifest.json`
- The auto-generated `CHANGELOG.md` entry
- Nothing else

Every push to `main` runs the release-please action. It walks all commits since the last release tag and decides:
- Any qualifying commits (`feat:`, `fix:`, breaking)? → open or update the Release PR with the latest accumulated changes
- No qualifying commits? → do nothing (Release PR stays as-is, or doesn't open)

**Important:** the Release PR doesn't tag anything. It just shows you what *would* be released if you merged it.

### What types of commits qualify for a bump?

| Commit subject prefix | Bump type | Shows in changelog? |
|---|---|---|
| `feat:` | minor (1.2.0 → 1.3.0) | yes, "Features" |
| `fix:` | patch (1.2.0 → 1.2.1) | yes, "Bug Fixes" |
| `feat!:` or `BREAKING CHANGE:` footer | major (1.2.0 → 2.0.0) | yes, "BREAKING CHANGES" |
| `perf:`, `refactor:`, `revert:` | patch | yes |
| `chore:`, `docs:`, `style:`, `test:`, `build:`, `ci:` | none | hidden |

If you push a `chore: ...` commit, release-please will run, look at the commits, and decide nothing needs a release. The Release PR (if open) stays the same. If you push a `feat: ...` commit, release-please updates the Release PR to bump minor.

### The `Release-As:` footer override

Any commit can include a footer like:
```
Release-As: 3.6.1
```

This **forces** the next release to be the version you specify, regardless of bump rules. Useful for:
- Hotfixes (force a patch number while skipping ahead/back)
- Stabilizing a prerelease (`Release-As: 1.0.0` to bless a 0.x as stable)
- Coordinating with externally-mandated versions

⚠️ Comes with a footgun — see Scenario 4.

### What does "merging the Release PR" actually do?

When the release manager merges PR `chore(main): release 3.6.0`:

1. The version-bump commit lands on main
2. release-please immediately runs again (because main was pushed)
3. This run creates the git tag (`3.6.0`) + GitHub Release in the same job step
4. The `build-versioned-image` job (gated on `if: release_created == 'true'`) runs in the **same workflow run**
5. Separately, `main.yml :: build-deploy-dev` job also fires (because the merge is a push to main) and rolls dev with the new sha-tag

So one merge = one tag + one GitHub release + one versioned-image build + one dev rollout, all from the same commit.

### Why the build job is in the same workflow as release-please

Default `GITHUB_TOKEN` events created by one workflow do **not** trigger other workflows. So `on: push: tags` or `on: release: published` triggers would silently never fire. Putting the build job inside the same workflow run, gated on `needs.release-please.outputs.release_created`, sidesteps this entirely. No GitHub App, no PAT.

---

## Part 2 — Setup (one-time, ~3 minutes)

### Fork or clone the POC repo for testing

```bash
gh repo fork shashanksinha89/kenobi-release-please-poc --clone --remote
cd kenobi-release-please-poc
```

If you're going to push test commits, you need the repo to be yours so you don't pollute the original.

### Required repo settings in your fork

```bash
# Allow GitHub Actions to create and approve PRs (required for release-please)
gh api -X PUT /repos/<your-username>/kenobi-release-please-poc/actions/permissions/workflow \
  -f default_workflow_permissions=write \
  -F can_approve_pull_request_reviews=true

# Create the GitHub Environments that promote.yml references
gh api -X PUT /repos/<your-username>/kenobi-release-please-poc/environments/qa
gh api -X PUT /repos/<your-username>/kenobi-release-please-poc/environments/production
```

### Verify the workflows are in place

```bash
ls .github/workflows/
# Should show:
#   main.yml          ← release-please + build-versioned-image + build-deploy-dev
#   pr-title-lint.yml
#   promote.yml
```

**`main.yml` contains three jobs:**

| Job | When it runs | Why |
|---|---|---|
| `release-please` | every push to main | Manage the Release PR; cut tag on its merge |
| `build-versioned-image` | only when release-please cut a tag (`needs:` chain) | Build versioned image. Replaces `azure-build-on-tag.yml`. |
| `build-deploy-dev` | every push to main, **in parallel** with release-please (no `needs:`) | sha-tagged build + dev rollout. Decoupled from release outcome. |

Per-job `permissions:` and `concurrency:` blocks keep least-privilege and per-flow queueing intact even though everything's in one file.

---

## Part 3 — Scenario walkthroughs

Run these in order. Each scenario builds on the previous state.

### Scenario 1 — Push to main → dev auto-deploys

**Goal:** prove that every push to main rolls dev, regardless of whether release-please decides to release.

```bash
# 1. Make a tiny change with a non-bumping commit type (chore:)
echo "// tiny" > app/scratch.txt
git add -A
git commit -m "chore: Add scratch file for scenario 1 testing"
git push origin main
```

**What you should see:**

```bash
sleep 10
gh run list --limit 3
gh run view <latest-run-id>
```

ONE workflow run (`main`) fires for the commit, with two jobs running in parallel:
- ✅ `build-deploy-dev` — builds sha-tagged image, deploys to dev (stub)
- ✅ `release-please` — runs, but **does not open a Release PR** (because `chore:` doesn't qualify)
- ⊘ `build-versioned-image` — skipped (no tag was cut, so the `if: release_created == 'true'` gate is false)

**Verify:**

```bash
# No Release PR opens for chore: commit
gh pr list --state open
# Output: empty
```

**What this proves:** dev cluster is decoupled from release cadence. Every merge to main is a dev deploy. Engineers don't need to think about release semantics for routine work.

---

### Scenario 2 — Cut a real release (the happy path)

**Goal:** push a `feat:` commit, watch release-please open a Release PR, merge it, see the tag + GitHub release + versioned image + dev deploy all happen.

```bash
# 1. Push a feat: commit
cat > app/new_feature.py <<'EOF'
def new_endpoint():
    return {"hello": "world"}
EOF
git add -A
git commit -m "feat(api): Add new endpoint for X

KENOBI-1234"
git push origin main
```

**Wait for release-please run:**

```bash
sleep 20
gh run list --workflow main.yml --limit 1
gh pr list --state open
```

You should see:
- ✅ `release-please` workflow ran successfully
- ✅ A new Release PR opened: `chore(main): release X.Y.Z` (where X.Y.Z is current-minor + 1)

**Inspect the Release PR before merging — this is the key review artifact:**

```bash
PR_NUM=$(gh pr list --state open --search "chore(main): release" --json number --jq '.[0].number')
gh pr view $PR_NUM
gh pr diff $PR_NUM
```

The diff shows:
- `pyproject.toml`: version bumped
- `release-please-manifest.json`: version bumped
- `CHANGELOG.md`: new entry generated from the commit subject + ticket reference

**This is the moment the release manager makes a decision.** Does the changelog look right? Is this the version we want to ship? If yes, merge:

```bash
gh pr merge $PR_NUM --squash --auto
```

**What happens after the merge:**

```bash
sleep 30
gh run list --limit 3
gh release list --limit 3
```

You should see:
- ✅ ONE new `main` workflow run fired on the merge commit, with all three jobs running:
  - `release-please` (cut the tag)
  - `build-versioned-image` (gated path — runs because `release_created == 'true'`)
  - `build-deploy-dev` (parallel path — rolled dev with the merge commit's sha)
- ✅ A new tag exists in `gh release list` (e.g. `3.6.0`)

**Inspect the build-versioned-image job:**

```bash
RUN_ID=$(gh run list --workflow main.yml --limit 1 --json databaseId --jq '.[0].databaseId')
gh run view $RUN_ID --log | grep -E "Cut tag|Version|Components"
```

You'll see the tag name + version + bump components passed via outputs into the build job. In real kenobi-c2s, this is where the docker build/push runs.

**What this proves:** the entire "cut a release" flow is one merge action by the release manager. No manual `git tag`, no separate workflow trigger.

---

### Scenario 3 — Promote a tagged release to QA, then production

**Goal:** verify the manual promotion flow + all four guards.

You need the tag from Scenario 2. Set it as `TAG`:

```bash
TAG=$(gh release list --limit 1 --json tagName --jq '.[0].tagName')
echo "Promoting tag: $TAG"
```

#### 3a — Happy path: promote to QA

```bash
gh workflow run promote.yml -f image_tag=$TAG -f environment=qa
sleep 10
LATEST=$(gh run list --workflow promote.yml --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch $LATEST --exit-status
gh run view $LATEST --log | grep "qa now running"
```

✅ Should show `qa now running <TAG>`.

#### 3b — Happy path: promote to production (stable tag)

```bash
gh workflow run promote.yml -f image_tag=$TAG -f environment=production
sleep 10
LATEST=$(gh run list --workflow promote.yml --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch $LATEST --exit-status
gh run view $LATEST --log | grep "production now running"
```

✅ Should show `production now running <TAG>`. The "Block prerelease" step ran and passed because the tag is stable.

#### 3c — Failure mode: bad semver shape (`v` prefix)

```bash
gh workflow run promote.yml -f image_tag="v$TAG" -f environment=qa
sleep 10
LATEST=$(gh run list --workflow promote.yml --limit 1 --json databaseId --jq '.[0].databaseId')
gh run view $LATEST --log-failed | grep -E "must be valid|::error::" | head -3
```

❌ Should fail with `image_tag must be valid bare semver`. The regex rejects the `v` prefix because release-please emits bare semver tags.

**Why this matters:** if someone gets used to typing `v1.2.3` (the kenobi-c2s convention pre-release-please), they'll fail fast at validation rather than producing a malformed deploy.

#### 3d — Failure mode: tag doesn't exist

```bash
gh workflow run promote.yml -f image_tag="99.99.99" -f environment=qa
sleep 10
LATEST=$(gh run list --workflow promote.yml --limit 1 --json databaseId --jq '.[0].databaseId')
gh run view $LATEST --log-failed | grep -E "does not exist|::error::" | head -3
```

❌ Should fail with `Git tag 99.99.99 does not exist on origin`. Catches typos and "I haven't merged the Release PR yet" mistakes.

#### 3e — Cut a prerelease, promote to QA (allowed)

Push a `Release-As:` prerelease commit:

```bash
echo "# prerelease test" > app/prerelease.txt
git add -A
git commit -m "chore: Test prerelease cut

Release-As: 9.0.0-rc.1"
git push origin main

# Wait for Release PR to open, then merge it
sleep 20
PR_NUM=$(gh pr list --state open --search "chore(main): release 9.0.0-rc.1" --json number --jq '.[0].number')
gh pr merge $PR_NUM --squash --auto
sleep 25
```

Now promote the prerelease:

```bash
gh workflow run promote.yml -f image_tag=9.0.0-rc.1 -f environment=qa
sleep 10
LATEST=$(gh run list --workflow promote.yml --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch $LATEST --exit-status
gh run view $LATEST --log | grep "qa now running"
```

✅ Should succeed. Prereleases are allowed in qa.

#### 3f — Failure mode: prerelease promotion to production (blocked)

```bash
gh workflow run promote.yml -f image_tag=9.0.0-rc.1 -f environment=production
sleep 10
LATEST=$(gh run list --workflow promote.yml --limit 1 --json databaseId --jq '.[0].databaseId')
gh run view $LATEST --log-failed | grep -E "Refusing|::error::" | head -3
```

❌ Should fail with `Refusing to promote prerelease tag 9.0.0-rc.1 to production`. The block fires only when the tag contains a hyphen *and* the target is production.

**What this proves:** all four guards in `promote.yml` work as intended. The flow is functionally identical to today's `azure-build-promote.yml`, just with bare-semver tags.

---

### Scenario 4 — Hotfix flow (and the footgun)

**Goal:** ship a critical patch out-of-band using `Release-As:`, then understand what it does to the manifest.

State check before starting:

```bash
gh release list | head -3
cat release-please-manifest.json
# Note: manifest is at 9.0.0-rc.1 from scenario 3
```

#### 4a — Hotfix via `Release-As:` footer

Imagine production is on 3.6.0 (an older stable) and there's a security fix that needs to ship as 3.6.1 — without picking up any of the in-flight 9.0.0-rc.1 work.

```bash
cat > app/security_patch.py <<'EOF'
def patched():
    return "fixed"
EOF
git add -A
git commit -m "fix(security): Patch null-pointer in tenant resolver

KENOBI-1235

Release-As: 3.6.1"
git push origin main
```

**Wait for release-please:**

```bash
sleep 20
gh pr list --state open
```

✅ A Release PR `chore(main): release 3.6.1` opens — even though the manifest currently shows 9.0.0-rc.1. The `Release-As:` footer is a hard override.

**Merge it:**

```bash
PR_NUM=$(gh pr list --state open --search "chore(main): release 3.6.1" --json number --jq '.[0].number')
gh pr merge $PR_NUM --squash --auto
sleep 25
```

**Verify the tag:**

```bash
gh release list | head -3
```

✅ Tag `3.6.1` now exists alongside `9.0.0-rc.1`, `3.6.0`, etc.

**Promote to production:**

```bash
gh workflow run promote.yml -f image_tag=3.6.1 -f environment=production
sleep 10
LATEST=$(gh run list --workflow promote.yml --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch $LATEST --exit-status
gh run view $LATEST --log | grep "production now running"
```

✅ Production is now on 3.6.1.

#### 4b — The footgun: manifest moved sideways

Now look at the manifest:

```bash
git pull origin main
cat release-please-manifest.json
# Output: { ".": "3.6.1" }
```

**The manifest moved from `9.0.0-rc.1` to `3.6.1`.** The 9.0.0-rc.1 prerelease is now **orphaned** — release-please considers `3.6.1` the latest released version.

**What happens next time someone pushes a `feat:` to main?**

The next bump is computed from `3.6.1`, not from `9.0.0-rc.1`. So a `feat:` produces `3.7.0`, NOT `9.1.0` and NOT `9.0.0-rc.2`. To get back on the 9.x RC line, you'd have to use another `Release-As:` to force it.

**When this matters:** if you have a real in-flight RC and a hotfix collides with it. Most teams don't, most of the time — but it's the kind of thing that hits you once a quarter and leaves a confused trail.

#### 4c — The cleaner alternative: release-branch model (not in this POC)

The robust pattern is to maintain a long-lived `release-3.6.x` branch from the 3.6.0 tag. Hotfixes go there, with release-please configured for branch-scoped releases. Main keeps moving forward independently.

```bash
# (NOT executed — this is what you'd do)
git checkout -b release-3.6.x 3.6.0
# add release-please-config that includes branches: [{name: release-3.6.x}]
# cherry-pick the security fix
# release-please opens a Release PR on release-3.6.x for 3.6.1
# merge → tag 3.6.1 cut from release branch, main untouched
```

This wasn't tested empirically in the POC. If we adopt release-please, the release-branch hotfix path is worth proving in a follow-up half-day spike.

**Heuristic for which to use:**
- Trunk has no in-flight RC → `Release-As:` is fine
- Trunk has an in-flight RC you don't want to disturb → use a release branch

---

## Part 4 — Reset / cleanup (optional)

If you want to start over for another round of testing:

```bash
# Delete all tags + releases (be careful — destructive)
gh release list --json tagName --jq '.[].tagName' | xargs -I {} gh release delete {} --yes --cleanup-tag

# Reset manifest to a known starting version
cat > release-please-manifest.json <<EOF
{ ".": "1.22.0" }
EOF
sed -i '' 's/^version = .*/version = "1.22.0"/' pyproject.toml
git add -A
git commit -m "chore: Reset manifest for fresh test run"
git push origin main
```

After this, the next push of a qualifying commit type will open a fresh Release PR starting from 1.22.0.

---

## Part 5 — Quick reference

### What to check after each scenario

| Question | Command |
|---|---|
| Did release-please run? | `gh run list --workflow main.yml --limit 1` |
| Is there a Release PR open right now? | `gh pr list --state open --search 'chore(main): release'` |
| What tag was last cut? | `gh release list --limit 1` |
| Did the build-versioned-image job run? | `gh run view <run-id>` (look for both jobs in the JOBS list) |
| Did dev get a new sha-tagged build? | `gh run view <main-run-id>` (look at `build-deploy-dev` job status) |
| Was the promote dispatch successful? | `gh run list --workflow promote.yml --limit 1` |

### Mental model summary

| Action | Effect |
|---|---|
| Engineer opens regular PR with `feat:` title | PR title lint passes |
| Engineer merges that PR | Dev rolled (sha-tag); Release PR opens or updates with the new commit's bump |
| Release manager merges the Release PR | Tag cut + GitHub release + versioned image built + dev rolled (new sha-tag, same content) |
| Release manager dispatches `promote.yml` with a tag | Helm upgrade in qa or production (with semver/existence/prerelease guards) |
| Engineer pushes a commit with `Release-As: X.Y.Z` footer | Next release is forced to X.Y.Z, regardless of normal bump rules |

That's the whole flow.
