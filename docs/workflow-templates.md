# Voice Workflow Templates

Christopher ships three reusable workflow templates that are ready for immediate
field or team use. Each template defines a focused conversation pattern: a system
prompt, an input/output schema, a sample turn, and customization guidance.

Templates live in the [`workflows/`](../workflows/) directory as YAML files.
They are **not loaded automatically** — you activate one by passing its
`system_prompt` as the active context when starting a session.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Dispatch Template](#dispatch-template)
3. [Note Capture Template](#note-capture-template)
4. [Summary Generation Template](#summary-generation-template)
5. [Chaining Templates](#chaining-templates)
6. [Domain Adaptation Guide](#domain-adaptation-guide)

---

## Quick Start

### Load a template system prompt at runtime

```python
# In christopher.py — pass the template's system_prompt as the initial message
import yaml
from pathlib import Path

template = yaml.safe_load(Path("workflows/dispatch.yaml").read_text())
system_prompt = template["system_prompt"]

messages = [{"role": "system", "content": system_prompt}]
# then pass messages into run_turn() / voice loop
```

### Use from the command line (chat mode)

Start Christopher in chat mode, then paste the `system_prompt` block as the
first message when prompted:

```bash
python3 christopher.py --chat
# When the prompt appears, paste the system_prompt from the desired template.
```

---

## Dispatch Template

**File:** [`workflows/dispatch.yaml`](../workflows/dispatch.yaml)

Routes a spoken message to a team channel (Slack by default) or a ticketing
system (GitHub Issues). Christopher extracts the recipient and message body,
confirms what it is about to send, dispatches it, and speaks the confirmation.

### Input schema

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `recipient` | string | yes | Channel name, username, or team (`#ops-team`, `@alice`) |
| `message` | string | yes | Body of the message to send |

### Output schema

| Field | Type | Description |
|-------|------|-------------|
| `spoken_confirmation` | string | One-sentence verbal confirmation |
| `tool_result` | string | Delivery confirmation from the MCP tool |

### Sample turn

**User says:**
> "Tell ops-team: the staging database is down, please investigate."

**Christopher:**
> "Dispatching to ops-team: the staging database is down."
> *(sends message)*
> "Message dispatched to ops-team. They've been notified."

### Customization points

| Goal | What to change |
|------|---------------|
| Send to GitHub Issues instead of Slack | Swap `slack_send` for `github_create_issue` in the system prompt |
| Add a severity/priority field | Extend the prompt to extract a priority level and prepend it to the message |
| Use a custom webhook | Add a `webhook_dispatch` tool in `christopher.py → call_tool()` |

---

## Note Capture Template

**File:** [`workflows/notes.yaml`](../workflows/notes.yaml)

Transcribes a spoken note verbatim, auto-tags it with a category (meeting,
action, observation, issue, idea), echoes it back for confirmation, and
appends it to a local markdown file or a remote store.

### Input schema

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `note_text` | string | yes | — | Raw spoken note content |
| `category` | string | no | `auto` | Category override; Christopher infers one if omitted |

### Output schema

| Field | Type | Description |
|-------|------|-------------|
| `formatted_note` | string | `[CATEGORY] ISO-timestamp — note text` written to storage |
| `spoken_confirmation` | string | Verbal confirmation of what was saved |
| `destination` | string | Path or endpoint where the note was written (default: `~/christopher-notes.md`) |

### Sample turn

**User says:**
> "Observation: the east wing sensor is reading 3 degrees above baseline."

**Christopher:**
> "Got it — east wing sensor reading 3 degrees above baseline. Saving as observation."
> *(writes `[OBSERVATION] 2026-04-12T21:00:00Z — East wing sensor is reading 3 degrees above baseline.`)*
> "Saved."

### Customization points

| Goal | What to change |
|------|---------------|
| Post to a remote store | Add a `save_note` MCP tool and update the prompt to emit a `TOOL_CALL` |
| Add a project tag | Extend the format string in the prompt: `[CATEGORY][PROJECT] <text>` |
| Require explicit confirmation | Add a "wait for 'confirm' before saving" rule to the prompt |
| Use domain-specific categories | Replace the default list (`meeting, action, observation, issue, idea`) with your own |

---

## Summary Generation Template

**File:** [`workflows/summaries.yaml`](../workflows/summaries.yaml)

Condenses a block of spoken or transcribed text into a structured summary.
Supports three output styles — bullet points, prose paragraph, or TL;DR —
and can optionally dispatch the result via the dispatch template.

### Input schema

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `source_text` | string | yes | — | Content to summarize (notes, transcript, spoken description) |
| `summary_style` | string | no | `prose` | One of: `bullet`, `prose`, `tldr` |
| `dispatch_after` | boolean | no | `false` | If true, prompt for a destination and dispatch the summary |

### Output schema

| Field | Type | Description |
|-------|------|-------------|
| `summary_text` | string | Generated summary string |
| `summary_style` | string | Style used (`bullet` / `prose` / `tldr`) |
| `spoken_output` | string | Exactly what Christopher speaks aloud |
| `dispatched` | boolean | Whether the summary was sent via a dispatch tool |

### Sample outputs by style

**bullet:**
```
• East wing sensor reading 3 degrees above baseline.
• Maintenance ticket created for east wing HVAC unit.
• All other zones nominal.
```

**prose:**
```
East wing sensors recorded a 3-degree temperature anomaly; a maintenance
ticket has been raised for the HVAC unit. All other monitored zones
reported nominal readings.
```

**tldr:**
```
East wing HVAC anomaly flagged; ticket raised, all other zones normal.
```

### Sample turn

**User says:**
> "Summarize my shift notes as bullet points."

**Christopher:**
> "Here's your bullet-point summary:
> • East wing sensor reading 3 degrees above baseline.
> • Maintenance ticket created for east wing HVAC unit.
> • All other zones nominal.
> Want me to dispatch this summary somewhere?"

**User says:** "Yes, send it to ops-team."

**Christopher:**
> "Summary dispatched to ops-team."

### Customization points

| Goal | What to change |
|------|---------------|
| Default to TL;DR for voice-only use | Change `Default style: prose` to `Default style: tldr` in the prompt |
| Cap summary length for radio/intercom | Add a hard word limit rule to the prompt |
| Chain with the notes template | Feed captured `NOTE:` lines as `source_text` after a note session |
| Auto-dispatch without follow-up | Pre-configure a channel in the prompt and set `dispatch_after: true` |

---

## Chaining Templates

Templates can be composed into multi-step workflows. A common pattern is
**note → summarize → dispatch**:

```python
# Pseudocode — wire in christopher.py or a wrapper script

# 1. Run note-capture session
captured_notes = run_notes_session(messages, voice_mode=True)

# 2. Feed notes into the summary template
source_text = "\n".join(captured_notes)
summary = run_turn(
    messages,
    f"Summarize as bullet points:\n{source_text}",
    voice_mode=True,
)

# 3. Dispatch the summary
run_turn(messages, f"Send this to #shift-reports: {summary}", voice_mode=True)
```

---

## Domain Adaptation Guide

All three templates are designed to be forked for specific industries or team
structures. The key customization surface is the `system_prompt` field in each
YAML file.

### Common adaptations

**Field operations / security**
- Notes: replace default categories with `patrol, incident, handoff, equipment, welfare`
- Dispatch: route to a radio-bridge webhook instead of Slack
- Summaries: force `tldr` style; cap at 20 words for intercom clarity

**Healthcare / clinical**
- Notes: add `patient_id` extraction; gate saving behind an explicit "confirm" step
- Summaries: default to `prose`; preserve all numerical values verbatim
- Dispatch: route to `github_create_issue` or an internal ticket system

**Engineering / DevOps**
- Notes: add `severity` and `service_name` extraction
- Dispatch: default to `github_create_issue`; include priority label from severity
- Summaries: chain after incident notes; auto-dispatch to `#incident-channel`

### Testing a customized template

Use `--chat` mode to iterate on your `system_prompt` before deploying to voice:

```bash
python3 christopher.py --chat
# Paste your modified system_prompt, then test with representative utterances.
# Adjust until the output format matches your schema.
```

### Schema validation

Each template YAML includes an `input` and `output` block that describes the
expected fields. Use these to validate that your adapted prompt is extracting
and producing the correct data shapes before rolling out to field teams.

---

## Related Documentation

- [README.md](../README.md) — project overview, GPU tuning, model profiles
- [pilot-setup-guide.md](pilot-setup-guide.md) — installation and configuration
- [offline-runbook.md](offline-runbook.md) — offline startup and air-gapped deployment
- [`workflows/dispatch.yaml`](../workflows/dispatch.yaml) — dispatch template
- [`workflows/notes.yaml`](../workflows/notes.yaml) — note capture template
- [`workflows/summaries.yaml`](../workflows/summaries.yaml) — summary generation template
