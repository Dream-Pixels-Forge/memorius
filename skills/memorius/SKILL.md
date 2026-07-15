---
name: memorius
description: Self-contained memory vault for any AI agent — vector search, session diaries, and agent-agnostic hooks. PROACTIVELY use this skill when user mentions memory, vault, remember, store memory, search memory, recall, session diary, memory context, fact-check memory, consolidate memories, mine transcript, memory server, MCP memory, agent memory, memorius, or wants to build a system that remembers things across sessions. Also trigger when: user says "note this down", "save this", "remember that", "what did I learn about", "did I already know", "capture this", "store this for later", "what do I know about", or any phrase suggesting something should be persisted or recalled.
---

# /memorius

A self-contained memory vault for AI agents. Store, search, and organize memories with vector embeddings, session diaries, and hooks.

## What memorius is for

memorius is a **memory retrieval system**, not a note-taking app. Store less, store what matters. Vector search finds relevance, not keywords.

## Auto-Capture Rules — Remember Without Asking

**IMPORTANT: Always ask permission before auto-storing. Never auto-store without confirmation.**

### Confirmation Pattern

When a trigger is detected, ask:
```
Memory detected: [brief description]
Store this? (y/n)
```

Only proceed if user confirms. If user says no, skip silently.

**After storing, always report:**
```
✅ Stored: "[memory content]"
   Shelf: [shelf]
   Folder: [folder]
   Note: [note name]
```

### 1. Bug Fixes
After successfully debugging an issue, suggest storing:
```
Memory detected: Bug fix for [description]
Store this? (y/n)
```
If yes:
```bash
# Sanitize content before storing - escape special characters
CONTENT="Fix: ${BUG_DESCRIPTION}. Root cause: ${CAUSE}. Solution: ${FIX}"
memorius store "$CONTENT" --shelf bugs --folder "$PROJECT"
```
**Trigger:** User says "it works now", "fixed", "that was the issue", or code changes resolve an error.

**Security:** Always sanitize user input before passing to shell. Never use `eval` or backticks with user content.

### 2. Learning Moments
When user learns something new, suggest storing:
```
Memory detected: Learning about [concept]
Store this? (y/n)
```
If yes:
```bash
memorius store "[Concept]: [Key insight]" --shelf languages --folder [language/framework]
```
**Trigger:** User says "oh I see", "that makes sense", "I didn't know that", "TIL", or asks follow-up showing understanding.

### 3. Decisions Made
When a decision is reached, suggest storing:
```
Memory detected: Decision about [topic]
Store this? (y/n)
```
If yes:
```bash
memorius store "Decision: [what was decided]. Rationale: [why]" --shelf decisions --folder [project]
```
**Trigger:** User says "let's go with", "we'll use", "I'll choose", "decided", or confirms a choice.

### 4. User Preferences
When preference is expressed, suggest storing:
```
Memory detected: Preference for [what]
Store this? (y/n)
```
If yes:
```bash
memorius store "Preference: [what user prefers]. Context: [when/why]" --shelf preferences
```
**Trigger:** User says "I prefer", "I like", "I always", "I never", "use X instead of Y".

### 5. Project Context
When project details emerge, suggest storing:
```
Memory detected: Project context for [project]
Store this? (y/n)
```
If yes:
```bash
memorius store "[Project]: [key fact]" --shelf projects --folder [project-name]
```
**Trigger:** User mentions project name + specific detail (version, stack, deadline, constraint).

### 6. Error Patterns
When same error appears twice, suggest storing:
```
Memory detected: Recurring error pattern
Store this? (y/n)
```
If yes:
```bash
memorius store "Error pattern: [error]. Recurrence: [count] times. Fix: [solution]" --shelf errors
```
**Trigger:** Same error message or similar issue appears in consecutive sessions.

### 7. Workflow Preferences
When user shows preferred workflow, suggest storing:
```
Memory detected: Workflow preference
Store this? (y/n)
```
If yes:
```bash
memorius store "Workflow: [what user does]. Preference: [how they like it]" --shelf workflows
```
**Trigger:** User repeats same pattern 2+ times or explicitly states how they like to work.

### Bulk Confirmation

If multiple memories are detected in one response, batch them:
```
Memories detected:
1. Bug fix for [X]
2. Learning about [Y]
3. Decision about [Z]

Store all? (y/n/choose)
```
User can say:
- `y` → store all
- `n` → store none
- `1, 3` → store only those
- `just 2` → store only that one

**After bulk store, always report:**
```
✅ Stored 3 memories:
   1. "[memory 1]" → shelf/folder/note
   2. "[memory 2]" → shelf/folder/note
   3. "[memory 3]" → shelf/folder/note
```

---

## Smart Context Injection — Recall Without Asking

**IMPORTANT: Always ask permission before injecting context. Never inject without confirmation.**

### Confirmation Pattern

When context injection would help, ask:
```
I found relevant memories about [topic]. Inject context? (y/n)
```

Only inject if user confirms. If user says no, proceed without context.

**After injecting, always report:**
```
✅ Injected context:
   1. "[memory 1]" (relevance: 0.92)
   2. "[memory 2]" (relevance: 0.87)
   3. "[memory 3]" (relevance: 0.81)
```

### 1. Before Answering About Past Work
```
I found relevant memories about [topic]. Inject context? (y/n)
```
If yes:
```bash
memorius context "[topic user is asking about]" --max 5
```
**Trigger:** User asks about something they've worked on before ("how did we do X", "what was that fix").

### 2. Before Starting a Task
```
I found relevant memories for this task. Inject context? (y/n)
```
If yes:
```bash
memorius context "[task description]" --vault [project] --max 5
```
**Trigger:** User starts coding session, begins new task, or says "let me work on".

### 3. When User References Past Session
```
I found memories from that session. Inject context? (y/n)
```
If yes:
```bash
memorius context "[referenced topic]" --max 3
```
**Trigger:** User says "last time", "remember when", "we discussed", "you said".

### 4. Before Making Recommendations
```
I have relevant memories to inform this recommendation. Inject context? (y/n)
```
If yes:
```bash
memorius context "[recommendation topic]" --max 5
memorius search "[specific pattern]"
```
**Trigger:** Agent is about to suggest an approach, tool, or pattern.

### Skip Confirmation

Skip confirmation if:
- User explicitly asks "what do I know about X" → inject directly
- User says "check memorius" → inject directly
- Context is needed to avoid contradicting stored facts → inject directly (mention you did so)

---

## Session Auto-Diary — Track Without Asking

**IMPORTANT: Always ask permission before creating diary entries. Never create without confirmation.**

### Confirmation Pattern

When a diary would be useful, ask:
```
Significant work was done this session. Create a diary entry? (y/n)
```

Only create if user confirms. If user says no, skip silently.

**After creating, always report:**
```
✅ Diary created:
   Session: [session-id]
   Title: [title]
   Summary: [summary]
```

### End of Long Session (>30 min)
```
This was a long session with significant work. Create a diary entry? (y/n)
```
If yes:
```bash
memorius diary "session-$(date +%s)" \
  --title "[Session summary]" \
  --summary "[Key accomplishments]" \
  --content "[What was done, decisions made, issues found]"
```

### After Significant Work
```
You completed [task]. Create a diary entry? (y/n)
```
If yes:
```bash
memorius diary "session-$(date +%s)" \
  --title "[Task completed]" \
  --summary "[Outcome]" \
  --content "[Details]"
```
**Trigger:** Bug fixed, feature implemented, architecture decision made.

### Before Session Ends
Always check if a diary should be written:
- Did significant work happen? → Suggest diary
- Were decisions made? → Suggest diary
- Was something learned? → Suggest diary
- Just trivial Q&A? → Skip diary

### Skip Confirmation

Skip confirmation if:
- User explicitly says "write a diary" → create directly
- User says "log this session" → create directly
- Session involved critical bug fix → create directly (mention you did so)

---

## Proactive Usage — When to Trigger

**ALWAYS suggest memorius when user says:**
- "note this down" / "save this" / "remember that"
- "what did I learn about X" / "did I already know"
- "capture this" / "store this for later"
- "what do I know about X" / "have I seen this before"
- After completing a task, fixing a bug, or learning something new
- After a meeting, call, or conversation
- When user references something from a past session

**ALWAYS suggest memorius when:**
- User is about to start a coding session → suggest `memorius context`
- User just fixed a complex bug → suggest `memorius store`
- User completed a meeting → suggest `memorius mine`
- User is重复 a pattern you've seen → suggest `memorius search`

## Smart Routing — Determine the Right Command

Based on user intent, route to the correct command:

| User Intent | Command | Example |
|-------------|---------|---------|
| "note this" / "save this" | `store` | `memorius store "Redis uses single-threaded event loop"` |
| "what do I know about X" | `search` | `memorius search "Redis event loop"` |
| "check if I already know" | `search` + `factcheck` | Search first, then factcheck if specific claim |
| "from this meeting" / "from this call" | `mine` | `memorius mine meeting.txt --shelf meetings` |
| "extract from this doc" | `extract` | `memorius extract paper.pdf --backend openai` |
| "what happened in session X" | `diary` | `memorius diary "session-123"` |
| "give me context for X" | `context` | `memorius context "user preferences" --max 5` |
| "is this true" / "verify" | `factcheck` | `memorius factcheck "User prefers dark mode"` |
| "merge duplicates" / "clean up" | `consolidate` | `memorius consolidate --dry-run` |
| "show my vault" / "what's stored" | `ls` or `stats` | `memorius ls` / `memorius stats` |
| "sync with Obsidian" | `obsidian import/export` | `memorius obsidian import` |
| "search the web" / "look this up" / no local match | `web` (+ `--web` on search/context/factcheck) | `memorius web "python 3.13 changelog"` |

**After every command, always report what was created/returned:**

| Command | Report Format |
|---------|---------------|
| `store` | `✅ Stored: "[content]" → vault/shelf/folder/note` |
| `search` | `🔍 Found N memories:\n   1. "[memory]" (score: X)\n   2. ...` |
| `mine` | `⛏️ Mined N memories from [file]:\n   1. "[memory]"\n   2. ...` |
| `extract` | `📤 Extracted N memories:\n   1. "[memory]"\n   2. ...` |
| `diary` | `📔 Diary created: [title] (session: [id])` |
| `context` | `📋 Context injected:\n   1. "[memory]" (relevance: X)\n   2. ...` |
| `factcheck` | `✅ Verified: [statement]\n   Status: supported/contradicted/unknown\n   Source: "[memory]"` |
| `consolidate` | `🔀 Consolidated N duplicates:\n   - "[memory A]" + "[memory B]" → "[merged]"` |
| `ls` | `📁 Vault structure:\n   shelf/\n     folder/\n       note` |
| `stats` | `📊 Vault: [name]\n   Memories: N\n   Shelves: N` |

## Efficiency Patterns

### 1. Quick Capture (No Thinking)

```bash
# Just store it — use defaults, organize later
memorius store "User prefers PostgreSQL over MySQL"
memorius store "Rate limit: 100 req/min per API key"
memorius store "Bug: race condition in token refresh"
```

### 2. Context-Aware Search

```bash
# Before answering questions about past work
memorius context "authentication patterns" --max 5
# Returns relevant memories to inject into your response

# Before coding sessions
memorius context "current project" --vault project-x --max 10
```

### 3. Batch Operations

```bash
# Mine multiple transcripts at once
for f in ~/recordings/*.txt; do
  memorius mine "$f" --shelf meetings
done

# Store multiple memories in sequence
memorius store "Fact 1" && memorius store "Fact 2" && memorius store "Fact 3"
```

### 4. Auto-Consolidation

```bash
# Weekly cleanup (schedule with cron)
memorius consolidate --threshold 0.8 --vault main

# Preview first
memorius consolidate --dry-run --threshold 0.8
```

### 5. Hook-Based Auto-Capture

Enable hooks to automatically capture memories after agent sessions:

```bash
# Hooks run after each session, capturing key facts
memorius-hook install
```

### 6. Smart Consolidation Triggers

**Auto-suggest consolidation when:**
```bash
# Vault has >100 memories
memorius stats  # Check count
memorius consolidate --dry-run --threshold 0.8
```
**Trigger:** Memory count exceeds 100, or agent notices duplicate information.

**Auto-consolidate when:**
- User says "clean up", "merge duplicates", "too many notes"
- Agent stores 3+ similar memories in one session
- Week has passed since last consolidation

---

## Integration Patterns

### With Other Skills

**After debugging (dpf-debugger-engineer):**
```bash
# Store the root cause and fix
memorius store "Root cause: null pointer in auth.ts line 42. Fix: added optional chaining." --shelf bugs
```

**After learning (any learning task):**
```bash
# Store what was learned
memorius store "React useEffect cleanup: return function runs on unmount" --shelf languages --folder javascript
```

**Before starting work:**
```bash
# Get relevant context
memorius context "user's coding style" --max 3
memorius context "project conventions" --max 5
```

### With MCP Server

Add to Claude Desktop for always-on access:

```json
{
  "mcpServers": {
    "memorius": {
      "command": "memorius",
      "args": ["serve"]
    }
  }
}
```

Now agents can search/store without CLI calls.

### With Obsidian

```bash
# Import your existing notes
memorius obsidian import --vault main

# Export memories back
memorius obsidian export --vault main
```

## Workflow Templates

### Daily Standup

```bash
# What did I learn yesterday?
memorius context "yesterday" --max 5

# Store today's plan
memorius store "Today: fix auth bug, deploy v2.1" --shelf daily
```

### After Meeting

```bash
# Mine the transcript
memorius mine meeting.txt --shelf meetings

# Store key decisions
memorius store "Decision: migrate to PostgreSQL by August" --shelf decisions
```

### Bug Investigation

```bash
# Search for related past issues
memorius search "auth token refresh bug"

# Store the fix when found
memorius store "Fix: token refresh race condition. Use mutex lock." --shelf bugs
```

### Learning Session

```bash
# Store what you learned
memorius store "Python decorators: @functools.wraps preserves __name__" --shelf languages --folder python

# Verify later
memorius factcheck "functools.wraps preserves function metadata"
```

## Vault Organization

Don't overthink it. Use this simple structure:

```
main/
  daily/           # Daily notes, plans
  meetings/        # Meeting transcripts and notes
  decisions/       # Key decisions made
  bugs/            # Bug fixes and root causes
  languages/       # Language-specific learnings
    python/
    javascript/
    etc.
  projects/        # Project-specific memories
    project-x/
    project-y/
```

## Efficiency Tips

1. **Store less, store what matters** — Vector search finds relevance, you don't need 100 notes about the same thing
2. **Use shelves, not just vaults** — Shelves are your primary organization
3. **Mine after meetings** — Don't try to remember, let memorius extract
4. **Context before answering** — Always check if you already know something
5. **Consolidate weekly** — Merge duplicates, keep vault clean
6. **Use hooks** — Auto-capture beats manual capture

## Honesty Rules

- Never invent memories that weren't stored
- Always show actual search results, not paraphrased versions
- Report when vault is empty or no memories match
- Show confidence scores when available
- Don't modify memories without explicit user request
- Suggest `memorius consolidate` when vault gets large (>100 memories)

## Security Considerations

### Shell Injection Prevention

**User content must be sanitized before passing to shell:**

```bash
# ❌ DANGEROUS - user content could contain $(...) or backticks
memorius store "$USER_INPUT"

# ✅ SAFE - use single quotes or escape special characters
memorius store '$USER_INPUT'
memorius store "$(echo "$USER_INPUT" | sed 's/[$()`]/\\&/g')"
```

**Rules:**
- Never use `eval` with user content
- Never use backticks with user content
- Prefer single quotes for literal strings
- Escape `$`, `(`, `)`, backticks if using double quotes

### Hook Installation

**Before installing hooks, confirm with user:**
```
memorius-hook install will modify your shell configuration.
Proceed? (y/n)
```

**What hooks do:**
- Add post-session hook to capture memories
- Modifies `~/.bashrc` or similar
- Can be removed with `memorius-hook uninstall`

### MCP Server Security

**MCP server binds to localhost only:**
- Host: `127.0.0.1` (not `0.0.0.0`)
- Port: `8911` (configurable)
- No authentication (local use only)

**Do NOT expose MCP server to public network.**

### Data Privacy

**memorius stores data locally:**
- Location: `~/.memorius/data`
- No external API calls for storage
- Embeddings computed locally (all-MiniLM-L6-v2)
- No data sent to external services

### Permission Model

**memorius operates with user permissions:**
- Reads/writes only to `~/.memorius/` directory
- No root/sudo required
- No system file modifications (except hooks with consent)
- No network access for core functionality
