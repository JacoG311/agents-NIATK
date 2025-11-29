Quarantine directory for suspicious or unverified instruction files.

Policy:
- Files placed in this directory are isolated and must not be used by runtime code until verified.
- Verification steps:
  1. Identify the source author (git history, email metadata, repository origin).
  2. If the source is verified (internal/Nordstrom), move the file back to its intended location and record verification in `QUARANTINE_LOG.md`.
  3. If the source cannot be verified or is external without authorization, the file should be deleted and an incident note added to the log.

How to verify:
- Check `git log --follow -- <original-path>` to find creation author and commit message.
- Inspect email/repo metadata or cross-check with known internal templates.

To restore a file after verification:
- Move the file from `quarantine/` to the original location
- Add an entry to `quarantine/QUARANTINE_LOG.md` with verdict=verified and author details
- Optionally update `agent-config.yaml` or relevant configs to point to the now-verified file

To permanently remove (destroy) a file:
- `git rm --cached <file>` and then delete the file; document action in `QUARANTINE_LOG.md`.

Pre-commit hook enforcement:
- This repo includes a local hooks script `.githooks/pre-commit` (not active by default). To enable local blocking, run:
  `git config core.hooksPath .githooks`

If you need assistance verifying this file, ask me to run the verification steps and I'll gather git history and context.