# Project instructions

Working rules for this project. First written for Phase 6 (the original
`docs/phase6_instructions.md` was never committed and was lost in a
Codespace restart). Now applies to Phase 7 and everything after it.

1. Never guess - verify current state first with real commands.
2. Small, isolated changes, one at a time.
3. Real tests with real output after every change - never claim something works without proof.
4. Full errors/tracebacks, not summaries.
5. Commit only after verification - one commit per verified step.
6. Package manager uv only. New branch: phase-7/production-hardening, cut from develop.
7. Document any real bugs/gaps found honestly.
8. After each step: stop, give a clear summary (what was required, what you found, what you changed, real test + real output, commit message), wait for confirmation before the next step.
9. If the Codespace stops/restarts mid-work (this has happened repeatedly this session), verify actual git/file state first before resuming - don't assume, don't redo completed work.
