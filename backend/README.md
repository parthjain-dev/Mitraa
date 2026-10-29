# Mitraa backend

Mitraa is a local-first personal AI agent. It runs on your machine, talks to NVIDIA Nemotron through Nebius Token Factory, and acts on your files through validated, permission-checked and audited tool calls.

**Phase 2 status:** persistent memory and deterministic project planning are implemented alongside the Phase 1 agent and file controls. Research and the web UI are planned for Phases 3–4 (see `../NOVA_BUILD_PLAN.md`).

## Setup

Requires Python 3.11 or newer.

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env            # macOS/Linux: cp .env.example .env
# then edit .env (see below)
```

### `.env`

| Variable | Meaning |
|---|---|
| `NEBIUS_API_KEY` | Your Nebius Token Factory API key |
| `NEBIUS_BASE_URL` | The OpenAI-compatible endpoint from the Nebius console (ends in `/v1/`) |
| `NEMOTRON_MODEL` | The exact Nemotron model id from the Nebius catalog |
| `MITRAA_ALLOWED_ROOTS` | Semicolon-separated folders Mitraa may touch. Default: `~/Documents;~/Downloads;~/Desktop`. On Windows, folders redirected to OneDrive are found automatically |
| `MITRAA_MAX_STEPS` | Maximum LLM calls per request (default 8) |
| `MITRAA_BULK_THRESHOLD` | Actions touching more than this many files need approval (default 5) |
| `MITRAA_DB_URL` | Optional SQLite URL. Default: `backend/mitraa.db` |

`.env` is gitignored. Never commit keys.

## Run

### Folder and text-file commands

Try “Open my Documents folder”, “Read Documents/notes.txt”,
“Create Documents/notes.txt containing Hello Mitraa”, or
“Append a new line saying Buy milk to Documents/notes.txt”.
The model routes these through `open_folder`, `read_file`, and `write_text_file`.
Folder opening uses Windows File Explorer; reading/listing stays in the chat.
Text writes always show the existing Allow/Deny approval card. Existing versions
go to the Recycle Bin before replacement or append. Creation refuses to overwrite.
Writes support UTF-8 .txt/.md/.log/.csv/.json, with a 1 MB resulting-file limit.
Paths remain restricted by `MITRAA_ALLOWED_ROOTS`; this feature does not grant
access to additional folders. General commands require the configured agent provider.

### Responsibilities and local follow-up

Open **My responsibilities** from the system tray. Select **New responsibility**, enter
a title, desired outcome and next action, then save. Optional fields include notes,
source references, priority, an explicit IANA timezone (such as `Asia/Kolkata`) and a
deadline. References are stored as text; adding a path does not read that file.
To open the desk immediately when starting the app, run `python -m mitraa.assistant --responsibilities`.

Use the status selector to plan, activate, pause, wait for input, mark ready for review,
cancel or complete a responsibility. Completion requires a note explaining how you
confirmed the outcome. A prepared draft is not a submitted application. Completed or
cancelled responsibilities close their pending reminders. Reopen as `captured` or
`active` and add fresh reminders if needed. **Forget** permanently removes a responsibility,
its reminders and activity after explicit confirmation.

**Needs you** shows responsibilities waiting for user input or captured without a next
action. **Ready for review** shows that state. **Coming up** shows open, unpaused work;
**All** includes paused, completed and cancelled items. The editor preserves unsaved work
during background refresh. If another interface changes an item, stale saves are rejected;
use **Refresh**, review the discard prompt and reload before editing the newer version.

Select a saved responsibility and choose **Add follow-up**. Reminder times are interpreted
in the entered timezone and stored in UTC. Ambiguous and nonexistent daylight-saving times
are rejected; choose an unambiguous time or UTC. The persistent inbox supports **Acknowledge**,
**Snooze** and **Cancel reminder**. Acknowledgement closes a reminder without completing
the responsibility. Paused work does not generate popups; overdue reminders catch up when
it is resumed. Deadlines alone do not automatically create reminders.

**Quiet hours** controls timezone, the quiet interval and desktop notifications. Defaults
are 22:00–08:00 in the machine timezone when the desktop first initializes preferences.
Equal start/end disables the quiet interval. Quiet hours suppress popups, not the inbox.
The desktop checks every 15 seconds; no continuous microphone or screen capture is used.
Notifications contain a generic count, keeping titles and personal messages out of popups.

Due follow-ups also show a non-modal, always-on-top Mitraa reminder card with the
title/message, Open, Acknowledge, and Snooze 10 min controls. This card does not
depend on Windows notification banners or `notified_at`; previously missed due
items can appear again after restarting Mitraa. Closing the card leaves the inbox
unchanged and suppresses the current due alerts for this session. Quiet hours and
the notification preference suppress this card too. It does not interrupt speech
or activate the microphone. Task details are visible on this local card, while
Windows notifications continue to use generic counts.

Reminders work while the desktop runs. If the PC sleeps, is off, or Mitraa is closed,
the next poll catches up on missed times. Due items remain in the inbox until acknowledged,
snoozed, cancelled or the responsibility is closed. Successful notification requests are
recorded to avoid repeating popups on every poll/restart. OS popup presentation is best-effort;
it is not proof the user saw it. A crash between notification request and persistence can
repeat a popup, but does not lose the inbox item. If the tray cannot show messages, pending
items remain available in the inbox.

The local SQLite schema is upgraded additively on launch: existing conversations, memories,
projects and file action history are preserved. All changes happen in transactions. Each
responsibility has a version to prevent silently overwriting newer edits, and an activity
history. These features work without an AI provider.

### Preparation and review (milestone 4)

Select a saved, open responsibility and choose **Drafts & review**. **Prepare
checklist** creates a local Markdown checklist from the saved outcome and next
action without an API call. **New draft** allows plain-text/Markdown preparation.
Save the draft before reviewing. Source references must already be listed on the
responsibility; references never read a file or fetch a URL automatically. Use
the existing sandboxed read tools when the AI needs actual file contents.

The editor includes **Preview**, **Changes** against the previous saved revision,
and **Saved revisions** with source snapshots, missing facts, review notes, and
content/context hashes. Revisions persist in SQLite. New edits create a pending
revision instead of inheriting earlier acceptance. Stale writes and reviews are
rejected; reload after preserving any unsaved text. Background inbox refresh does
not replace the draft editor's text.

Resolve **Missing facts / questions**, save, enter a review note, then choose
**Accept reviewed draft** or **Request changes** and confirm. Missing facts block
acceptance. Acceptance is the user's review record, not automated factual
verification, responsibility completion, export, or external submission. Existing
responsibility completion still requires its separate confirmation note. Forgetting
a responsibility also removes its drafts and all draft revisions.

With a provider connected, try: “Prepare a factual application draft for my
internship responsibility using my supplied notes. List unknown facts as questions
and save it for review.” The agent can use `prepare_responsibility_draft`,
`list_responsibility_drafts`, and `revise_responsibility_draft`; it cannot accept
drafts through a review tool. Use the existing approval-gated `write_text_file`
tool if you subsequently want a draft written to a permitted file. The draft
editor itself does not write outside the local database or submit applications.

API additions: `GET/POST /responsibilities/{id}/drafts`,
`POST /responsibilities/{id}/checklist`, `GET/PATCH /drafts/{id}`, and
`POST /drafts/{id}/review`. Updates/reviews require `expected_version`; review
also requires `confirmed=true` and a note. The schema additions are new tables,
preserving existing conversations, responsibilities, memories and reminders.

### Bounded coding jobs (milestone 5 first adapter)

Select a saved open responsibility, then **Coding jobs**. This adapter uses the
configured OpenAI-compatible provider to propose small source-code edits. It does
not launch Codex/Claude, terminals, or generated code.

1. Choose an existing project folder inside `MITRAA_ALLOWED_ROOTS`, for example a
   small project under Documents. Enter an objective, acceptance criteria, selected
   source files and allowed output paths, one relative path per line. Supported
   text: `.py`, `.md`, `.txt`, `.json`, `.js`, `.ts`, `.css`, `.html`. Existing output
   files are also included in the selected context.
2. **Prepare contract** saves the exact selected text, endpoint, model and limits
   locally. Review the Contract / selected context tab.
3. **Start approved job** asks before sharing this context with the displayed
   provider. One request, no SDK retries, 24 KB maximum selected file text,
   256–4096 output tokens, and a 10–120 second request timeout. Late proposals are
   discarded. These are not currency spending caps; remote work already sent
   cannot be undone or refunded by cancellation.
4. Inspect proposed files, diffs, missing facts and actual local Python AST/JSON
   syntax checks. Syntax success is not proof acceptance criteria are met. No
   project tests, imports, code execution, package installation or shell commands
   run. Other text types require manual validation.
5. Outputs are saved only in gitignored `backend/jobs/<job-id>/`. Original files
   remain unchanged. Enter a review note and confirm **Accept review**; unresolved
   missing facts or changed artifacts block acceptance. This records review only,
   not a merge, submission or responsibility completion. Inspect/copy selected
   outputs manually if you decide to integrate them.

Jobs persist through prepared/running/ready_for_review/verification_failed/failed/
cancelled/interrupted/accepted states. One coding request runs at a time.
Cancellation discards late results; restart marks running jobs interrupted without
automatic retries. Prepare a new contract to retry or when source files/provider
change. Traversal, links, hidden files and credential-like names are refused.
The remote worker gets selected text and no filesystem or shell tools.

Provider-reported usage appears in Token usage. Isolated output folders remain
on disk for inspection even after responsibility metadata is forgotten; remove
them manually when no longer needed. No live provider request runs in automated
tests. Real-world pilot validation, automatic merging, and a command-capable
isolated agent integration remain outside this initial adapter.

API: `POST /coding-jobs`, `GET /responsibilities/{id}/coding-jobs`,
`GET /coding-jobs/{id}`, `POST /coding-jobs/{id}/cancel` and `/accept`.
Starting remote work requires the desktop's explicit contract confirmation;
chat tools cannot silently start a coding job.

### Token usage

Open **Token usage** from the tray or My responsibilities. Refresh to see recorded
input/output/total tokens, UTC-day and lifetime totals, a provider/model breakdown,
and recent API-backed request totals (including tool loops and plan generation).
Tracking starts after this update; earlier usage cannot be recovered from chat
text. A new additive SQLite table persists across restart and provider switches.
Only provider-reported counts are recorded: missing counts are unknown, not zero.
Failed calls without usage and SDK-internal retries may consume unreported tokens.
Local greetings, preview, speech recognition/output, and offline work do not count
as model API calls. No keys or message contents are stored in the usage ledger.
This is not a billing calculation or a remaining-free-quota display. `GET /usage`
returns the same summary; chat responses also include per-turn `usage`.

### AI connection setup

Choose **AI connection** from the tray or responsibility window. Enter the provider endpoint,
model ID and API key. HTTPS endpoints are accepted; HTTP is limited to loopback hosts.
A blank key preserves a saved key. Values are written atomically to this installation's
gitignored `backend/.env`; unrelated settings are preserved. Environment variables take
precedence and the dialog indicates when they are present. Credentials are never shown in
status messages or passed to the responsibility worker's logs.

Saving configuration does not make a paid verification request. The existing chat worker
reloads its provider after its current request finishes, without restarting the application.
Local responsibility tracking remains available without credentials. Chat uses the configured
remote provider and can transmit selected task context; local tracking does not imply fully
offline AI reasoning. The settings file still needs ordinary local filesystem protection.

### Responsibility API and agent tools

The optional localhost API exposes:

| Route | Purpose |
|---|---|
| `GET/POST /responsibilities` | List/filter or capture responsibilities |
| `GET/PATCH/DELETE /responsibilities/{id}` | Inspect, edit or explicitly forget |
| `GET /responsibilities/{id}/history` | Activity and completion confirmation |
| `GET/POST /reminders` | List or schedule local follow-ups |
| `POST /reminders/{id}/snooze` | Reschedule to a future aware timestamp |
| `POST /reminders/{id}/acknowledge` | Close without completing the responsibility |
| `DELETE /reminders/{id}` | Cancel a reminder |
| `GET /follow-up` | Persistent due inbox and notification candidates |
| `GET/PUT /reminder-preferences` | Timezone, quiet hours and notification settings |

PATCH requires `expected_version`. DELETE requires `confirmed=true` and the current
`expected_version`. Dates require explicit offsets (e.g. `2026-10-22T18:00:00+05:30`).
GET `/follow-up` never consumes desktop notifications. Only the running desktop requests
popups; starting the API alone does not deliver notifications.

The configured agent also has `create_responsibility`, `list_responsibilities`,
`update_responsibility`, `add_reminder`, `change_reminder`, and `get_follow_up` tools.
Natural-language requests require a configured provider; direct desktop capture does not.

Relative chat reminders use `add_relative_reminder` with a minute delay computed
from the computer clock. `get_current_time` supplies current local/UTC time for
absolute-time requests. Confirmations include the saved local offset and timezone;
relative reminders do not silently set or change the responsibility deadline.

Verification:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest -p no:cacheprovider --basetemp logs/verification-tests
```

### Expandable conversation card

Replies appear immediately when the agent finishes, independently of speech
preparation. You can send another message while voice synthesis is running;
doing so interrupts the old speech. Voice failures keep the text reply visible.
Kokoro generates a short opening phrase first, then prepares bounded phrases
ahead of playback through a two-slot queue. Playback lifecycle spans the full
reply, so microphone gating remains active between phrases. A bounded in-memory
cache reuses repeated phrases; no generated audio is saved by default. The CPU
runtime uses four inference threads. This reduces time to first speech but local
inference still takes time and can pause between phrases on slower hardware.

Use the diagonal-arrow icon at the upper card's top-right to expand the current
conversation upward; use the inward arrows to return to the latest answer.
The dock and orb stay anchored. Messages show local timestamps, selectable text,
and distinct user bubbles. The composer at the bottom sends with Enter;
Shift+Enter inserts a newline. Drafts survive collapse, hiding and busy/approval
states, and clear only on accepted submission. New conversation clears its draft
and view while keeping previously saved conversations in the database.

The same controller and serial AgentWorker handle dock, voice and composer input.
Accepted user messages are saved before provider setup so provider failures do
not lose them. The orchestrator reuses the saved user message instead of saving
a duplicate. History retrieves 40 visible user/assistant messages per page from
the current conversation, excluding system/tool messages and tool-call payloads.
Use Load earlier messages for older pages. Reading position is preserved and
New messages jumps to the latest reply. History requests are queued behind any
active agent operation; the GUI and existing messages remain available while loading.

Expanding or collapsing does not change capture/playback. Editing the composer
cancels active capture. Pending approvals retain their explicit action details
and Allow/Deny controls; submission stays disabled until the decision is resolved.
Message text is escaped before rich-text rendering and external links are disabled.

In `python -m mitraa.assistant --preview`, the tray's next/simulate action cycles
to a labeled sample response with a scrollable demo conversation. Expand its
card and try a draft or send to see an explicitly simulated reply. No provider,
microphone, speech model, network access or tools are used. Run
`python -m tests.conversation_smoke` from `backend` for layout checks; set
`QT_QPA_PLATFORM=offscreen` for headless rendering and `QT_SCALE_FACTOR` for scaling.

### Optional natural local voice

The desktop selects Kokoro's British male `bm_george` when
`backend/models/kokoro/kokoro-v1.0.onnx` and `voices-v1.0.bin` are present.
This is a stock neural voice with a calm British delivery, not a clone of JARVIS
or the actor in the reference trailer. It speaks English; Hindi recognition is
independent and this profile does not provide natural Hindi speech output.

Install the optional runtime using `python -m pip install -r requirements-neural-voice.txt`
and run `python scripts/download_neural_voice.py` from `backend` to fetch the
maintainer's release files. The setup script checks sizes and published SHA-256
hashes and saves source/license records beside the models. Scan downloaded
assets and dependencies with your antivirus before loading them. On this machine,
downloads, pip cache/temp, runtime installation and sample WAV files were kept on D:.
The runtime uses MIT and model uses Apache-2.0 licenses; see the retained notices.

`MITRAA_TTS_BACKEND=auto` uses local Kokoro when assets exist, otherwise Windows
speech; `kokoro` explicitly requires the neural voice and `windows` forces SAPI.
`MITRAA_NEURAL_VOICE=bm_george`, `MITRAA_NEURAL_SPEED=0.96` and
`MITRAA_TTS_MODEL_DIR` control the profile and model directory. Synthesis and
playback stay local and off the GUI thread, with playback start/finish/interruption
events and actual playback levels. Capture waits for playback to release. Loading
and synthesis cost depend on CPU; this is not an instant cloud voice.

Speech recognition uses one local multilingual Whisper model for Hindi, English,
and mixed Hindi-English. Leave `MITRAA_STT_LANGUAGE=` empty (or use `auto`)
for detection restricted to Hindi and English; `hi` and `en` force one language.
Decoding stays pinned to the selected language so short Hindi speech cannot
switch to Urdu script. Mixed Hindi-English still uses the multilingual model. Hindi text is
preserved in Devanagari for the agent and conversation history. The desktop
transcript displays Hindi in English letters (Hinglish) using local transliteration;
existing English words, capitalization and paths remain unchanged. This is not
English translation. Roman spellings are phonetic approximations and may vary
from how you would type them.
Recognition uses beam search with deterministic decoding and the recorder's
single VAD pass, preserving its pre-roll and trailing audio. Confidence filters
still reject unreliable speech. Accuracy is not guaranteed for every word or accent;
real microphone samples are needed to assess it. `MITRAA_STT_MODEL=medium` can
be tested for accuracy at a higher CPU, memory, download and latency cost.

Desktop UI test commands work locally without provider keys: `hi` / `hello` →
`Hello!`; `what is your name?` / `what's your name?` → `Mitraa.`.
Typed and transcribed commands share this behavior and persist in conversation
history. Other requests use the configured agent. Replies appear in a teal/amber
glass card above the dock and use the existing speech output when available.

```powershell
# Terminal chat (best way to test Phase 1)
python -m mitraa.cli

# API server on http://127.0.0.1:8000 (bound to localhost only)
python -m mitraa.main

# Tests
python -m pytest
```

### Example CLI session

```
you> Move resume.pdf from Documents to Downloads
  ✓ search_files [LOW] Found 1 match(es) for 'resume.pdf'.
  ✓ move_file [MEDIUM] Moved resume.pdf to C:\Users\you\Downloads. Say 'undo' to revert.
mitraa> Moved resume.pdf to Downloads. Say 'undo' to revert.

you> undo that
  ✓ undo_last_action [MEDIUM] Moved resume.pdf back to C:\Users\you\Documents.

you> Delete old_notes.txt
  ✓ search_files [LOW] Found 1 match(es) for 'old_notes.txt'.
  ⏳ delete_file [HIGH] Waiting for user approval.
  ⚠  Mitraa wants to: Delete C:\Users\you\Documents\old_notes.txt (moves it to the Recycle Bin)
  Allow? [y/N] y
  ✓ delete_file [HIGH] Moved old_notes.txt to the Recycle Bin.
```

CLI commands: `/new` starts a new conversation, `/audit` shows recent tool calls, and `/quit` exits.

### Phase 2: memory and projects

Mitraa stores lasting facts across conversations in SQLite. In chat, try:

```text
My hackathon project is called NOVA.
What am I building?
Forget my project name.
Create a project for the NVIDIA hackathon. I have 10 days and am working alone.
Generate a task plan for it.
What's the critical path?
I have 3 days left. Optimize the schedule.
What if I lose a day?
What should I work on now?
```

Project plans contain estimates and dependencies; Python validates cycles, computes CPM and uses OR-Tools CP-SAT to assign hourly work slots around each member's daily capacity and time off. A 10-second solver limit may return `FEASIBLE` instead of `OPTIMAL`. The scheduler plans up to 365 days ahead and rounds task estimates up to whole work hours. Weekends count as working days unless `weekends_working` is changed on the project.

The HTTP API also supports direct project and memory management. For example:

```powershell
$project = Invoke-RestMethod http://127.0.0.1:8000/projects -Method Post -ContentType application/json -Body '{"name":"NOVA","goal":"Finish the hackathon demo","deadline_days":10}'
Invoke-RestMethod "http://127.0.0.1:8000/projects/$($project.id)/schedule"
Invoke-RestMethod "http://127.0.0.1:8000/projects/$($project.id)/simulate" -Method Post -ContentType application/json -Body '{"type":"member_unavailable","member":"You","days":1}'
```

### Adaptive desktop assistant

```powershell
python -m mitraa.assistant                     # hidden until explicitly summoned
python -m mitraa.assistant --preview           # completely offline UI demonstration
python -m mitraa.assistant --detect            # raw trigger key discovery; Esc stops
python -m mitraa.assistant --install-startup
python -m mitraa.assistant --uninstall-startup
```

Hold **Ctrl alone for three seconds**, or choose **Open (listen)** in the tray. Only a 72-logical-pixel glass orb appears, without stealing focus. Voice loading has a distinct circulating accent. Capture starts only once the local speech model is ready and playback has stopped; its microphone-driven glow indicates recording. There is no continuous hidden recording or automatic follow-up listening. Normal launch does not require provider keys.

Click the circle to reveal a 456-by-88 logical-pixel horizontal dock while the same recording continues. In the expanded dock, a single orb click toggles listening: it stops an active session without submitting, or starts a fresh session while keeping the dock expanded. Restart waits for the system double-click interval so a double-click cannot briefly open the microphone. A double-click stops listening and collapses to circle-only without restarting capture. Click the circle again to reopen the dock. Running agent work and pending approval IDs survive collapse. The same Orb instance and animation clock persist: internal teal currents turn clockwise in 14 seconds, amber currents counterclockwise in 22 seconds, and the glass boundary stays steady. The dock reveals to the right over 300 ms with width and opacity easing. It keeps the orb anchored where space permits and moves only enough to remain within the work area. Reduced motion disables rotation and expansion animation. These are procedural layers; the supplied reference PNGs are flattened and are not treated as separate light layers.

When speech ends, capture closes, the dock expands, and **Understanding…** appears. Local Whisper produces a final transcript, which submits to the existing agent once. The dock then displays actual tool progress and the response; long answers use an attached, scrollable card above it. The keyboard control replaces the central content with a focused input; Enter submits once. The microphone starts a fresh circle-only session when the agent is ready, stopping playback first. Repeated summon during work shows that work without submitting or recording again.

Escape or dismiss stops capture/playback and hides the interface. It does not cancel an in-flight file action. Agent results and conversation state survive hiding. Approvals retain their real approval ID until explicit Allow or Deny; hiding does not resolve them. Summoning a pending approval restores its card with action, paths/arguments, risk and reasons, with Deny initially focused. No animation, audio callback or presentation change executes tools.

Drag the orb to move it. Qt settings persist `adaptive_position` and `reduced_motion` separately for preview and normal mode. Placement uses the active Windows monitor and Qt logical work-area coordinates, including negative coordinates and taskbar exclusion. Visible shapes have an input mask, so transparent unused areas do not intercept clicks. Escape uses a temporary keyboard hook only while the normal overlay is visible; it is removed on hide/quit. Ctrl shortcut handling remains unchanged.

The tray contains Open (listen), New conversation, Mute speech output, Reduced motion, Pause hotkey and Quit. Change the trigger using `MITRAA_HOTKEY`; Ctrl+C and Ctrl+S never summon it. Only trigger/escape events are acted on; no keystrokes are stored. Administrator windows can prevent normal-process hooks from receiving keys.

#### Startup performance

The launch path loads only Qt, tray/hotkey support and lightweight desktop preferences. Agent, database, planning and full provider settings imports wait until a request needs them on the worker. Hidden input/response text widgets are created when first used, and voice initialization runs on a background thread so the first orb stays responsive. Startup preferences preserve `.env` values with environment-variable overrides.

Measure desktop readiness from a fresh process with:

```powershell
python -m tests.startup_benchmark
```

This briefly starts the native tray/hotkey and event loop, makes no agent/audio request, then quits. Local measurements after optimization were 0.48–0.54 seconds from process launch, compared with about 9.8 seconds to the event loop before optimization. Timings depend on machine load and disk caches; they are not a hard operating-system guarantee. First-time Whisper loading/download and first agent-request initialization have separate latency. Normal startup logs `Desktop ready in …s` (measured after entry-point imports).

#### API-free preview

Preview opens only the circle. Click to expand, or use tray **Preview: next / simulate speech end** to demonstrate endpoint expansion, understanding, thinking, tool progress, speaking appearance (without audio), response, error, approval, typing and a fresh circle. Choose Allow or Deny explicitly before leaving a preview approval. A separate preview tray typing action is also available. The window title, tooltip, tray and sample text label preview content. No provider client, model download, microphone, speech output or tools are constructed. Simulated states are not evidence of working audio. For a timed native entry-point check, run `python -m tests.preview_smoke` from `backend` (optionally set `QT_SCALE_FACTOR=1`, `1.5`, or `2`). This opens and closes preview automatically and saves rendered states under `backend/logs`.

#### Local speech detection and configuration

The single recorder uses [WebRTC VAD](https://github.com/daanzu/py-webrtcvad-wheels) with mono signed 16-bit PCM at 16 kHz and 30-ms frames. Native device-rate float audio is resampled with [SciPy polyphase filtering](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.resample_poly.html), using preceding-frame filter context. Device callbacks only copy to a bounded 32-frame queue. Resampling, VAD, endpoint logic, transcription and Qt event signaling occur on a worker, outside the device callback. Queue/device overflows and VAD failures produce retry errors; there is no silent energy-only fallback.

| Environment setting | Default | Meaning |
|---|---:|---|
| `MITRAA_VAD_MODE` | 2 | WebRTC aggressiveness, 0–3 |
| `MITRAA_SPEECH_ONSET_MS` | 150 | Five positive VAD frames in a six-frame onset window |
| `MITRAA_MIN_SPEECH_MS` | 270 | Normal voiced-audio target; shorter confirmed utterances require stronger transcription confidence |
| `MITRAA_END_SILENCE` | 0.6 | Seconds of non-speech after confirmed speech; 600 ms at 30-ms resolution. Increase for longer speaking pauses |
| `MITRAA_NO_SPEECH_TIMEOUT` | 8 | Capture seconds before speech must begin |
| `MITRAA_MAX_UTTERANCE` | 30 | Maximum capture seconds; accepted audio finalizes once with a visible limit notice |
| `MITRAA_PREROLL_MS` | 300 | Retained audio preceding onset, plus the onset-confirmation window |
| `MITRAA_TRAILING_MS` | 200 | Trailing audio kept after last VAD speech, rounded up to 210 ms |
| `MITRAA_STT_MIN_LOGPROB` | -1.0 | Minimum accepted Whisper segment average log probability |
| `MITRAA_STT_MAX_NO_SPEECH` | 0.6 | Maximum accepted Whisper no-speech probability |

VAD is the speech classifier; RMS supplies a low numerical-silence guard and a slowly adapting noise floor, updated only on non-speech frames (2% before onset, 0.2% afterward). There is no initial silent-calibration assumption, so immediate speech is retained. The onset window rejects brief bursts; a 600-ms end-silence threshold gives quicker turn completion while retaining shorter pauses. Meaningful speech resets the timer. Set `MITRAA_END_SILENCE=1.0` if you prefer longer pauses. VAD hangover and subsequent local transcription can add time beyond this silence window. Brief confirmed speech is allowed when Whisper average log probability is at least -0.65. Segments with compression ratio above 2.4 are also excluded. Empty or rejected recordings never call the agent. These tunings do not guarantee speech/noise discrimination in every room.

Whisper runs locally (`MITRAA_STT_MODEL=small`, `MITRAA_STT_DEVICE=auto`, `MITRAA_STT_LANGUAGE=` for multilingual detection). Normal launch preloads voice in the background after desktop readiness (`MITRAA_VOICE_PRELOAD=true`; set false to load only on summon). Cached weights load directly without contacting Hugging Face. A missing model downloads once. Auto device selection skips CUDA when the runtime reports no usable device, and GPU fallback reuses the same resolved model path. CPU loading no longer performs language detection and decoding on silence; GPU loading validates its encoder before capture. The loading orb remains responsive and capture stays off until readiness. Preloading itself never opens the microphone or executes tools. No partial recognition is displayed in this version. Transcription and VAD are local, raw audio is not saved, and logs omit transcript/audio contents. Recognition timing depends on the hardware.

Speech output uses Windows SAPI (`MITRAA_TTS_VOICE=David`, `MITRAA_TTS_RATE=-1`), with playback-state start, completion, interruption and error signals. The microphone waits for playback to stop. Muting affects speech output, not explicitly requested microphone input. Microphone errors include retry guidance; allow desktop microphone access in Windows settings yourself if necessary.

Qt owns the app/tray event loop. Agent/database sessions stay on one worker thread, with request-tagged results. Audio sessions have distinct IDs so cancelled capture, transcription and playback results cannot submit or modify a newer session. Streams close through context managers on every exit. Quit stops hooks, tray, capture and speech, releases the instance lock, and queues database cleanup on its owning thread. Already-running model/tool calls finish before that worker exits; neither tool execution nor Whisper inference is forcibly terminated.

Verification uses deterministic synthetic endpoint/frame tests, fake device streams for exit paths, confidence metadata fixtures and Qt state/focus/geometry tests. Native Windows Qt renders can verify component layout, but do not prove real-room speech accuracy, desktop click-through, cross-app focus or mixed-monitor DPI behavior. Those require hands-on checks on the target setup.

### API

| Method | Path | Body / params | Returns |
|---|---|---|---|
| POST | `/chat` | `{conversation_id?, message}` | `AgentResponse` |
| POST | `/chat/approve` | `{approval_id, approved}` | `AgentResponse` (409 if already resolved) |
| GET | `/conversations` | | recent conversations |
| GET | `/conversations/{id}` | | conversation with all messages |
| GET | `/tools` | | name, description, risk and JSON schema of each tool |
| GET | `/audit` | `?limit=50&conversation_id=` | audit log, newest first |
| GET | `/health` | | `{status, version}` |
| GET/POST/DELETE | `/memory`, `/memory/{id}` | type, key, value | Saved memories |
| GET/POST/PATCH/DELETE | `/projects`, `/projects/{id}` | name, goal, deadline_days, team; DELETE requires `confirmed=true` | Project details |
| GET | `/projects/{id}/schedule` | | Gantt-ready dates, dependencies, assignees, critical path and slack |
| POST | `/projects/{id}/simulate` | Scenario JSON | Baseline, changed schedule and date/task diff |
| GET/POST/PATCH/DELETE | `/tasks`, `/tasks/{id}` | Task details | Project tasks |

`AgentResponse`:

```json
{
  "type": "message | approval_required",
  "conversation_id": "…",
  "text": "Moved resume.pdf to Downloads.",
  "pending_approval": {"approval_id": "…", "tool": "delete_file", "args": {}, "risk": "HIGH",
                       "description": "Delete … (moves it to the Recycle Bin)", "reasons": ["…"]},
  "steps": [{"id": "…", "tool": "move_file", "args": {}, "risk": "MEDIUM", "status": "success", "summary": "…"}]
}
```

```powershell
curl -X POST http://127.0.0.1:8000/chat -H "content-type: application/json" -d '{"message":"What is in my Downloads?"}'
```

## How it works

```
user message
   → Orchestrator (agent/orchestrator.py)         loop ≤ MITRAA_MAX_STEPS LLM calls
      → Nemotron (agent/llm.py)                   temperature 0.2, 60s timeout, 2 retries
      → tool call
         → parse + pydantic validation            bad args → "Invalid arguments … Fix and retry." (one repair)
         → permissions.evaluate (security/)       sandbox + executables + overwrite + bulk count
              LOW / MEDIUM → execute (undoable)
              HIGH         → PendingApproval, loop pauses until /chat/approve
              BLOCKED      → refused, the reason goes back to the model
         → audit log (tool_calls table)
         → tool result appended → next LLM call
```

### Security model

- **Sandbox** (`security/sandbox.py`): every path is expanded, resolved (following symlinks and junctions) and must sit inside an allowed root (`Path.is_relative_to`). The sandbox also rejects `..` traversal, system folders, reserved Windows device names (`CON`, `NUL`, …), alternate data streams, and relative paths that don't start with an alias such as `Documents/…`.
- **Permission tiers** (`security/permissions.py`):

  | Tier | Tools / conditions |
  |---|---|
  | LOW | `search_files`, `list_folder`, `read_file` |
  | MEDIUM | `move_file`, `move_files`, `copy_file`, `rename_file`, `create_folder`, `undo_last_action` |
  | HIGH | `delete_file`, `delete_files`, anything that would overwrite, anything touching more than `MITRAA_BULK_THRESHOLD` files |
  | BLOCKED | paths outside the roots, system folders, executables/scripts (`.exe`, `.bat`, `.ps1`, …), the root folders themselves |

- **No permanent deletes:** deletes and overwrites go through `send2trash`, and tool code contains no `os.remove`, `unlink` or `rmtree` (a test enforces this).
- **Undo:** each change is recorded in `file_actions`. `undo_last_action` reverses the most recent change in the conversation. Deleted items must be restored from the Recycle Bin.
- **Audit:** every tool call, including invalid, blocked and denied ones, is written to `tool_calls` with args, risk, status, summary and duration.

## Adding a tool

```python
class MyArgs(BaseModel):
    path: str

class MyTool(Tool):
    name = "my_tool"
    description = "What it does, when to use it, when not to."
    args_model = MyArgs
    base_risk = RiskLevel.LOW

    def impact(self, args, ctx):          # optional: paths/count/overwrites for the permission engine
        return Impact(paths=[ctx.sandbox.resolve(args.path)])

    def run(self, args, ctx) -> ToolResult:
        ...

registry.register(MyTool())
```

## Phase 1 acceptance tests

| # | Test | Automated in |
|---|---|---|
| 1 | Move resume.pdf from Documents to Downloads | `test_orchestrator.py::test_move_end_to_end` |
| 2 | Ambiguous "move resume" makes Mitraa ask | `test_ambiguous_search_returns_both_matches` (the asking itself is the model's job, driven by the system prompt) |
| 3 | Delete needs approval, then goes to the Recycle Bin | `test_delete_requires_approval_then_trashes`, `test_denied_action_is_not_executed` |
| 4 | Undo restores the last move | `test_undo_in_follow_up_message`, `test_file_tools.py::test_undo_*` |
| 5 | System paths and `..\..\` are refused | `test_sandbox.py`, `test_escape_is_blocked_and_reported` |
| 6 | Every action is in `GET /audit` | `test_every_call_is_audited`, `test_api.py` |
| 7 | Stops after `MAX_STEPS` | `test_max_steps_enforced`, `test_max_steps_counts_across_approval` |
| 8 | `pytest` passes, including sandbox escapes | `python -m pytest` |

## Known limitations (Phase 1)

- `read_file` reads plain text only; PDF and DOCX reading arrives in Phase 3.
- Deletes can't be undone by Mitraa; restore them from the Recycle Bin.
- `search_files` matches names, not contents, and stops after 20,000 entries.
- Symlink-escape tests are skipped on Windows unless Developer Mode allows creating symlinks. Junction escapes are tested instead.
- A request blocks until the model finishes (no streaming yet; that comes in Phase 4).
