# Private GitHub Source Backup

**Target private account repository:** `Dfederale/Whispershell` (confirmed listed as `private` by the linked GitHub account on 21 October 2026).

The new ORIGINAL foundation should be archived without altering the earlier/public `Dfederale/Minus-Alex-` contest repository. If a separate new repository is preferred in future, keep it private as well.

## Recommended workflow

Keep one **source checkout** and one **runtime copy**. The source checkout contains code, docs, tests, and safe templates. The runtime copy contains live `.sqlite3` and memory/configuration state. An archive may include the same source tree for ease of extraction, but never upload sensitive runtime data by accident.

### Use the existing private repository (from inside the extracted folder)

```powershell
git init
git branch -M main
git add .
git status
git commit -m "WhisperShell ORIGINAL foundation, expandable blocks and engineering manual"
git remote add origin https://github.com/Dfederale/Whispershell.git
git push -u origin main
```

If the repository already contains commits, do **not** blindly force-push. First clone the existing repository or add it as a remote and pull/reconcile its branch. Never use `--force` over personal archives. The repository was listed as size zero on inspection, but its push state must be checked at the time of upload.

A second option, when `gh` CLI is already authenticated, is to create a **separate** new repository using `gh repo create DINS-WhisperShell-ORIGINAL --private --source=. --push` (not needed if using the existing private repo).

## Checklist before committing

- `git status` shows no `*.sqlite3*`, tokens, saved runtime profiles, `.env`, logs, personal data or customer files.
- `python -m unittest discover -s tests -v` passes.
- The intended GitHub repository visibility is **Private**.
- The revision under commit is the tested one.
- Keep stable connection identities unchanged. Describe migrations explicitly in commit messages and `docs/BUILD_LOG.md`.

## Working rule

A working foundation change gets **code + tests + a written explanation + a private commit**. Source changes should not silently alter the connection contract. Preserve previous working commits so we can return to them.

### If using the provided `.bundle` backup

The release includes a separate Git bundle containing a complete initial source commit. It can restore an actual Git repository offline:

```powershell
git clone DINS-WhisperShell-ORIGINAL-Step05.bundle DINS-WhisperShell-ORIGINAL
cd DINS-WhisperShell-ORIGINAL
git remote set-url origin https://github.com/Dfederale/Whispershell.git
git push -u origin main
```

Run the commands only after confirming the existing remote does not have unrelated commits. Unlike the extracted source ZIP, the bundle carries the tested commit and Git history. Do not upload the bundle to a public service.

**Connector status on 21 October 2026:** The connected GitHub account listed the private repository, but GitHub API reads/writes to that particular private repository returned HTTP 404. **No remote upload was completed.** Re-authorizing GitHub's access to the private repository or pushing from an authenticated local Git installation may resolve this.

## Step 05 archival update

The new bundle contains **three local Git commits**, including the ten historical schematic PNG files, master-plan registry, implementation audit and tests. It has **NOT** been uploaded to the private GitHub repository. The latest single extraction ZIP has the same working tree *without* `.git` history; use the bundle only when you actually want a local Git clone with history.
