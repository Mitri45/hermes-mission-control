# Pi Recovery Checklist

Purpose: preserve all Pi-only work before attempting any merge, rebase, or restore of `origin/main`.

## Rules

1. Do not run `git reset --hard`.
2. Do not run `git push --force` or `git push --force-with-lease`.
3. Do not merge upstream into `main`.
4. Preserve first, compare later.

## 1. Inspect the current Pi state

Run:

```bash
git status
git branch --show-current
git branch --all
git remote -v
git log --oneline --decorate --graph --max-count=30 --all
git reflog --date=iso | sed -n '1,80p'
git stash list
git cherry -v origin/main
```

Record:

- current branch name
- whether there are uncommitted changes
- whether there are local commits not on `origin/main`
- any stashes

## 2. If there are uncommitted changes

Preserve them on a dedicated recovery branch:

```bash
git checkout -b recovery/pi-working-copy-$(date +%Y%m%d-%H%M%S)
git add -A
git commit -m "WIP: preserve Pi local recovery state"
git push origin HEAD
```

## 3. If there are committed but unpushed changes

Preserve them on a dedicated recovery branch:

```bash
git checkout -b recovery/pi-local-history-$(date +%Y%m%d-%H%M%S)
git push origin HEAD
```

If the current branch is already the unique work branch and has no uncommitted changes, pushing that branch is fine too:

```bash
git push origin HEAD
```

## 4. If there are stash entries

Do not apply them yet. First create a preservation branch and inspect each stash:

```bash
git stash list
git stash show -p stash@{0} | sed -n '1,200p'
```

If a stash contains unique work, create a branch for it:

```bash
git stash branch recovery/pi-stash-0 stash@{0}
git push origin HEAD
```

## 5. Report back with these exact outputs

The Pi agent should provide:

1. current branch
2. `git status --short`
3. any recovery branch names pushed
4. any stash branches created
5. whether there are local commits not on `origin/main`

## 6. Stop after preservation

Do not try to merge, rebase, restore `main`, or resolve conflicts yet.

The next step happens only after both of these exist remotely:

- `origin/recovery/pre-force-push-main` from the PC
- one or more `origin/recovery/pi-*` branches from the Pi
