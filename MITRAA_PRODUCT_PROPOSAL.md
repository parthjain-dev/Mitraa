# Mitraa — Personal Follow-Through Assistant

**Status:** Product direction. Milestones 1–3 have implementations; milestone 4 now
has local text preparation and revision review. Milestone 5 now has a bounded
coding-proposal adapter using selected text, an isolated output folder, review and
static checks. Command-capable agent isolation, automatic integration and the pilot
remain future work. Implemented features still require real workflow validation.

**Implementation update (31 October 2026):** Accepted coding proposals can now be
explicitly applied to their original workspace through the desktop UI. Application
checks for changed selected files and artifacts, rechecks workspace permission,
keeps sibling backups, and uses a durable journal for interrupted multi-file updates.
This does not execute generated code, automatically merge work, or complete the
responsibility. Restoring backups is manual.

Optional desktop-approved Python checks now run `unittest` or compare program
output in a temporary copy with Windows process/resource limits. Versioned evidence
records output, exit status, timestamps and artifact/context hashes. Failed or
interrupted checks block review until rerun successfully. This is local execution
under the user's account, not enforced filesystem/network isolation; it requires
explicit approval for trusted code. Full agent isolation remains future work.

**Implementation update (29 October 2026):** Milestone 4 includes local checklist
preparation, saved text/Markdown drafts, provenance snapshots, missing-fact questions,
revision diffs/history, and explicit review decisions. AI tools can prepare/revise
drafts; acceptance is recorded through the review UI/API. This does not provide
PDF/Word parsing, formatted export, automated factual verification, or submission.
**Date:** 20 October 2026
**Product promise:** Tell Mitraa what you need to handle. It remembers the responsibility, prepares the next steps, and helps you carry it through to completion.

## 1. Executive proposal

Evolve Mitraa from a request-response desktop assistant into a local-first personal assistant that manages ongoing responsibilities. A user can hand it an assignment, application, personal project, or administrative obligation. Mitraa keeps the context together, identifies the next action, prepares supported work, follows up at useful times, and records completion with evidence or user confirmation.

The product's primary outcome is less mental effort spent remembering and coordinating unfinished work. Agent orchestration is an internal capability that supports this outcome, rather than the interface users must learn.

Launch with students and early-career users. Initially support assignments, job/internship applications, and small software projects. Expansion to household, appointment, and other administrative workflows should follow demonstrated reliability in these initial workflows.

## 2. Problem and product hypothesis

People receive responsibilities in different places, repeatedly gather the same documents, postpone unclear tasks, and lose track of the next step. A reminder can surface a deadline but still leave all preparation and coordination to the user.

**Hypothesis:** Users will return to an assistant that keeps the context for a responsibility, prepares useful work, and asks for a small, specific contribution when needed.

This is a hypothesis to validate, not a claim of product-market fit or a world-first invention. Scheduling and habit management already have established alternatives; Mitraa should compete on follow-through, preparation, verifiable progress, and user control.

## 3. Core user experience

### Capture

The user speaks or types: "Help me apply for this internship before Friday. I have half an hour each evening." They paste the listing or select the relevant files. Mitraa extracts the goal, deadline, requirements, and available time. Ambiguous dates and material assumptions require clarification. Every extracted requirement retains its source.

### Prepare

Mitraa builds a short plan and gathers permitted context. It prepares a checklist, application draft, supporting documents, or a coding assignment. Personal claims must come from supplied facts; missing facts are questions, not invented content.

### Progress

Mitraa works within the assigned scope and presents actionable updates: "The draft is ready. I need your answer to one eligibility question." If time becomes insufficient, it offers explicit changes to scope or timing.

### Review and complete

The user reviews prepared outputs. Completion requires an appropriate check, an external receipt where supported, or explicit user confirmation. A prepared application is not a submitted application. A successful test run is not proof that every product requirement is met.

### Follow through

Mitraa retains the next follow-up date and supporting context. It can resume after restart and shows missed reminders when it next runs. Work requiring a response from another person stays in a waiting state.

## 4. Product interface

Keep the orb and dock as the quick-entry interface. Add a persistent responsibility view with three primary sections:

- **Needs you:** decisions, missing information, and requested approvals.
- **Ready for review:** drafts, changes, and completed checks.
- **Coming up:** deadlines, planned sessions, and follow-ups.

Each responsibility opens a detail card showing the desired outcome, deadline, source material, next action, progress, prepared artifacts, and activity history. Provide pause, edit, cancel, and forget controls. An optional daily briefing should be short and respect quiet hours.

An "I have less time today" action proposes a reduced plan. The assistant must preserve fixed commitments unless the user changes them and explain what will be deferred.

## 5. First-release scope

| Capability | First-release behavior |
|---|---|
| Responsibility capture | Voice/text input and selected source material; review extracted dates and requirements |
| Durable tracking | Local records, explicit states, next actions, dependencies, follow-up dates |
| Preparation | Checklists, plain-text/Markdown drafts, organized supporting files |
| Planning | Use the existing deterministic planner for estimates and dependencies |
| Follow-up | Local reminders, quiet hours, snooze, missed-reminder catch-up |
| Verification | File checks, checklist evidence, user confirmation, bounded project checks |
| Agent delegation | One coding-agent adapter for selected software-project tasks |
| Review | Artifact previews/diffs, evidence, failed checks, explicit unresolved items |
| Privacy controls | Selected workspace access, visible provider use, local history and export/delete controls |

Begin with user-supplied text and supported text files. PDF/Word parsing, screenshots, and formatted document export are separate capabilities and must not be implied by a file picker.

Applications are drafted and tracked in version one; the user submits them. Assignment support should prioritize learning, planning, feedback, and permitted assistance rather than misrepresenting authorship.

## 6. Explicit exclusions

- No promise to perform arbitrary work or manage every aspect of life.
- No unrestricted desktop control or arbitrary background shell execution.
- No automatic purchases, financial transfers, public publishing, or application submission.
- No always-on microphone, covert screen recording, or whole-disk indexing.
- No medical, legal, or financial decision-making on the user's behalf.
- No mobile companion, always-available notifications, or broad email/calendar synchronization in the first release.
- No claim that a local interface alone makes cloud-agent processing private or offline.

## 7. Proposed architecture

1. **Desktop interface:** extend the current Qt app with the responsibility view and review controls.
2. **Responsibility service:** own requirements, source references, next actions, deadlines, and lifecycle transitions.
3. **Planning service:** reuse CPM/CP-SAT where appropriate; keep dates and constraint calculations outside model-generated prose.
4. **Durable job service:** persist queued/running jobs, attempts, checkpoints, cancellation requests, and recovery state in SQLite.
5. **Capability registry:** describe supported operations, inputs, permissions, verification methods, and external data use.
6. **Agent adapters:** start with one supported integration; add others behind the same job contract after validating their interfaces and authentication requirements.
7. **Permission and execution broker:** enforce filesystem, command, network, and spending boundaries at the actual execution layer.
8. **Verification service:** store check results with timestamps and artifact versions; invalidate affected checks after changes.
9. **Local scheduler:** deliver reminders while the app runs and recover missed events on restart.

Suggested records: Responsibility, Requirement, SourceReference, WorkItem, Job, Artifact, Verification, Approval, Reminder, ActivityEvent. Extend existing models where appropriate instead of duplicating equivalent state.

Suggested responsibility states: captured, planned, active, waiting_for_user, waiting_external, ready_for_review, completed, paused, cancelled. Job states and responsibility states should remain separate.

## 8. Delegation contract

Every delegated job contains a bounded objective, acceptance criteria, selected context, permitted workspace, permitted tools/network destinations, time and spending limits, and expected outputs.

Workers return structured status, artifact locations, verification evidence, unresolved questions, and approval requests. Agent self-reports are evidence to inspect, not final completion authority.

Coding workers use isolated worktrees or workspace copies. Integrate their changes only after inspection and checks. Begin with one worker at a time; add concurrent workers only with clear ownership and conflict handling.

The current permission engine protects Mitraa's own tools. It does not automatically constrain external agents. OS/process isolation and integration-specific permission handling are required before exposing delegated execution to personal workspaces.

## 9. Privacy and trust model

**Local mode:** local storage, local models, local tools, and enforced outbound-network restrictions. Availability depends on compatible hardware and installed models. The manager itself must use a local model or deterministic logic; the existing Nebius model path is cloud-connected.

**Connected mode:** orchestration and records stay on the PC, while explicitly selected providers receive task context. Show the provider and intended data before delegation. Limit transmitted context and exclude credentials. Existing provider credentials stay in appropriate local secret storage, not shared agent prompts or job logs.

Local storage still requires access controls, retention choices, and careful logging. Locality is a useful control, not a security guarantee.

Require explicit approval for externally consequential actions if these are added later. Design retries to avoid duplicate sends, submissions, or purchases. Cancellation must report which work stopped and which external effects already occurred. Rollback is available only for operations with a tested reversal path.

The first release cannot reliably notify a user when the PC is off or the app is not running. It must disclose this and catch up on the next launch. A future mobile or remote notification component would be a separate, opt-in architecture decision.

## 10. Existing foundation and immediate gaps

Reuse the voice interface, Qt dock, SQLite persistence, file tools, memory retrieval, project planner, approval flow, and audit records.

New work includes durable responsibilities, reminder scheduling, job recovery, preparation/editing tools, agent adapters, execution isolation, artifact review, and evidence-based completion.

Before expansion, resolve provider onboarding, the observed Whisper GPU initialization error, and the outdated worker test fixture identified during the system review. No live cloud-agent workflow has yet been verified on this checkout because provider configuration is missing.

## 11. Delivery milestones

| Milestone | Deliverable | Exit condition |
|---|---|---|
| 1. Reliable foundation | Configuration onboarding, baseline issues resolved | Desktop and core test suite pass; provider/local mode status is clear |
| 2. Responsibilities | Capture, edit, persist, next actions, states | A responsibility survives restart without losing context |
| 3. Follow-up | Reminders, quiet hours, snooze, catch-up | Missed and repeated reminders are handled deterministically |
| 4. Preparation and review | Drafts, source references, artifact previews | A user can review useful prepared work and identify missing facts |
| 5. Delegated execution | One adapter, isolated coding workspace, bounded jobs | A small task completes with inspected changes and verification evidence |
| 6. Pilot | Complete workflows and usability feedback | Participants can finish real responsibilities with measured assistance |

Preliminary planning estimate: 6–8 weeks for one experienced developer to build a limited pilot, excluding broad integrations and extensive security hardening. This is a planning assumption, not a delivery commitment; re-estimate after testing the first adapter and local execution constraints.

## 12. Validation and success criteria

Run a two-week pilot with roughly 10–15 consenting users from the initial audience. Compare assisted responsibilities with each user's baseline where practical. These are proposed evaluation targets, not established outcomes:

- At least 70% complete a first useful workflow without developer help.
- At least half use Mitraa in both pilot weeks.
- At least 60% report lower coordination effort, supported by specific examples.
- Track preparation time, missed deadlines, accepted versus discarded drafts, and notification dismissals.
- Every completed responsibility has recorded user confirmation or relevant verification evidence.
- No unauthorized external actions; test access boundaries rather than inferring safety from the absence of incidents.
- Responsibility and job state recover after forced restart without silently duplicating actions.

Continue development based on demonstrated repeat use and completed responsibilities. Do not optimize for chat volume, agent count, or time spent in the interface.

## 13. Proposed pilot demonstration

User: "Help me prepare this internship application by Friday. Here are the requirements and my resume."

Mitraa captures the responsibility, extracts requirements with sources, identifies missing information, prepares a factual draft, schedules a review session, and presents the draft for approval. The user submits outside Mitraa and records confirmation. Mitraa stores the confirmation and prepares a follow-up reminder. Repeat with a changed deadline and an application restart to demonstrate adaptation and recovery.

This demonstration proves a coherent responsibility lifecycle without depending on unrestricted browser automation or unsupported integrations.

## 14. Decision proposed

Adopt personal follow-through as the product direction. Start with a reliable, local-first lifecycle for a small set of responsibilities. Introduce agent delegation as a bounded execution capability within that lifecycle. Expand only after users repeatedly benefit from the initial workflows.

## References

- Existing repository implementation: `backend/mitraa/assistant/`, `backend/mitraa/agent/`, `backend/mitraa/planning/`, `backend/mitraa/tools/`, and `backend/mitraa/db/`.
- Codex integration surfaces: https://developers.openai.com/blog/codex-as-a-platform
- Adjacent scheduling capability: https://reclaim.ai/features/habits
- Adjacent project planning capability: https://www.usemotion.com/features/ai-project-manager

Competitive references establish adjacent capabilities; they do not establish that this proposal is unique across the market.
