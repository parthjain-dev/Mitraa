# Mitraa

*Tell Mitraa what you want done. It remembers your context, plans the work with real optimization math, uses tools on your machine, and asks before doing anything risky.*

Mitraa is a local-first personal AI agent built on NVIDIA Nemotron (served by Nebius Token Factory). The build follows [NOVA_BUILD_PLAN.md](NOVA_BUILD_PLAN.md), where the agent is called NOVA; it was renamed Mitraa.

## Status

| Phase | Scope | Status |
|---|---|---|
| 1 | Agent core and file control | ✅ Done |
| 2 | Memory and project intelligence | ✅ Done |
| 3 | Research and documents | — |
| 4 | Web UI, integration and demo | — |

## Quick start

The desktop tray now includes **My responsibilities** for local capture, next actions,
deadlines, completion confirmation, and follow-up reminders. **AI connection** configures
chat without editing files by hand. Local tracking and reminders do not need an API key.
Reminders require Mitraa running and catch up after a missed time or restart.

**Drafts & review** on a saved responsibility adds local checklists, editable
text/Markdown drafts, revision history, diffs, source references, missing-fact
questions, and explicit review decisions. Local drafting works without an API;
AI-assisted preparation uses the configured provider. Reviewing a draft does not
submit it or complete the responsibility.

**Coding jobs** prepares bounded source edits through the configured provider.
Review selected text and approve the job before any remote request. Proposed
changes go into an isolated job folder with diffs and static syntax checks;
original files stay unchanged. See the backend README for limits and review steps.

```powershell
cd backend
python -m venv .venv; .venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env    # add your Nebius key, base URL and Nemotron model id
python -m mitraa.assistant --preview  # offline adaptive orb/dock preview
python -m mitraa.assistant            # hold Ctrl alone for 3s to summon
python -m mitraa.cli      # terminal chat
python -m mitraa.main     # API on http://127.0.0.1:8000
python -m pytest          # tests
```

See [backend/README.md](backend/README.md) for the API, the security model and the acceptance tests.
