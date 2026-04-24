# Marneo Systematic Iteration Plan

> Created: 2026-04-24 — Post-audit stabilization roadmap

---

## Current State

- 132 tests passing, 12 tools registered, core engine functional
- Tool calling just fixed (tools were never passed to LLM before today)
- Feishu streaming card, @mention, sender name — all half-implemented
- 35 ad-hoc commits today, no regression tests for new features
- Employee renamed `老七` → `laoqi`, identity injection incomplete

---

## Phase A: Tool Calling — Verify & Fix (Priority 1)

**Goal:** Confirm LLM can actually call tools and get results back.

### A1. End-to-end tool call verification
- Send a test message via Feishu that should trigger a tool (e.g. "帮我看一下当前目录有哪些文件")
- Check gateway logs for: `tool_call` event → tool execution → `tool_result` event → final text response
- If MiniMax M2.7 doesn't return proper `delta.tool_calls` in streaming, implement fallback parser for XML-style tool calls
- **Success criteria:** User asks bot to run `ls`, bot calls `bash`, returns file list

### A2. Tool call integration test
- Write an integration test that mocks the LLM response with tool_call deltas
- Verify the full loop: `_send_with_tool_defs` → `tool_call` event → `registry.dispatch` → `tool_result` → next LLM call
- Cover: single tool call, multiple tool calls, max_iterations guard

### A3. Fix tool_defs format for MiniMax
- MiniMax may require different tool schema format than standard OpenAI
- If streaming tool_calls don't work, try non-streaming mode as fallback
- Or parse MiniMax's XML-style output: `<tool_call><tool name="...">` → extract and execute

---

## Phase B: Cleanup Sprint (Priority 2)

**Goal:** Stabilize what exists before adding more features.

### B1. Exception handling cleanup
- Replace all `except Exception: pass` with specific exceptions + logging
- Target: 15+ locations across codebase
- Pattern: `except (KeyError, FileNotFoundError) as exc: log.warning(...)`

### B2. Employee identity fix
- `profile.yaml` has `name: 老七` — use this as display_name in system prompt
- System prompt: `Your name is 老七 (employee_id: laoqi).`
- Verify SOUL.md loads correctly for `laoqi` directory

### B3. System prompt structure
- Verify the full prompt chain: capability directive → SOUL.md → Core Memory
- Test with `marneo memory stats -e laoqi`
- Ensure prompt stays within budget (≤4000 chars)

### B4. Tests for untested modules
- `tests/tools/test_feishu_tools.py` — mention formatting, doc creation, search
- `tests/tools/test_lark_cli.py` — credential loading, command building, safety
- At least 10 tests per module

### B5. Remove debug artifacts
- Remove `[Feishu] Group msg dropped` debug log or make it DEBUG level
- Clean up any leftover print statements or temporary code
- Verify all log levels are appropriate (INFO vs DEBUG)

---

## Phase C: Feishu Integration — Complete & Test (Priority 3)

**Goal:** All Feishu features work reliably, not just "sometimes works."

### C1. Streaming card reliability
- Test card create → update → close full lifecycle
- Handle Card Kit API permission missing → graceful fallback to text (with log)
- Decision: reply-thread vs new-message (make configurable)
- Test with actual Feishu conversation

### C2. @mention flow
- Test: user says "@Marneo at一下小A豪" → bot gets group members → finds person → sends @mention
- Requires: `lark_cli chat members` works → `feishu_send_mention` sends correctly
- If `lark_cli contact +search` doesn't exist, find the right command
- End-to-end test in real Feishu group

### C3. Sender name resolution
- Re-enable `_resolve_sender_name` with proper error handling
- Needs `contact:user.base:readonly` permission on Feishu App
- Cache results per session (already have `_sender_name_cache`)
- Fallback: use sender_id as display if API fails

### C4. Message context format
- Standardize the openclaw-style context injection:
  ```
  [2026-04-24 19:37:37] Feishu group | 张子豪 (ou_xxx) [msg:om_xxx] [chat:oc_xxx]
  ```
- Include: timestamp, platform, chat_type, sender_name, open_id, msg_id, chat_id
- Test that LLM can parse and use all fields

### C5. Session startup sequence
- When a new session starts, inject a "session startup" context (like openclaw does)
- Include: employee identity, current time, available tools summary, chat context
- This replaces ad-hoc tool descriptions in the system prompt

---

## Phase D: Memory System — Integration Test (Priority 4)

**Goal:** Memory system works in real conversations, not just unit tests.

### D1. Verify memory retrieval in gateway
- Send a message that should trigger memory retrieval
- Check if `retrieve_for_turn()` returns relevant results
- Verify they're injected into the conversation context

### D2. Episode extraction
- Send several messages, check if episodes are extracted after each turn
- Verify episodes appear in `marneo memory list -e laoqi`

### D3. Skill indexing
- Add a test skill to `~/.marneo/skills/`
- Send a message related to the skill topic
- Verify the skill is retrieved and its content injected

### D4. Core memory CLI
- Test `marneo memory add --core "API key 不能提交 git" -e laoqi`
- Verify it appears in `marneo memory list --core -e laoqi`
- Verify it's in the system prompt on next conversation

### D5. Context budget enforcement
- Set a small budget in config.yaml
- Verify system prompt stays within budget
- Verify working memory trim works (>20 turns → oldest removed)

---

## Phase E: Production Readiness (Priority 5)

**Goal:** Run 24 hours without manual intervention.

### E1. WS reconnect watchdog
- Monitor last message received time
- If no events for 5 minutes, auto-restart WS connection
- Log reconnect events

### E2. Session memory leak prevention
- Add background task to evict expired sessions every 5 minutes
- Log eviction counts

### E3. Structured logging
- Switch to structured JSON logs with correlation IDs
- Each message gets a UUID threaded through all log statements

### E4. Gateway health endpoint improvement
- `/health` returns: connected channels, session count, last message time, tool count
- Useful for monitoring

---

## Execution Order

```
Week 1: Phase A (tool calling) + Phase B (cleanup)
Week 2: Phase C (Feishu features)
Week 3: Phase D (memory integration) + Phase E (production)
```

Each phase: brainstorm if needed → write-plan → subagent-driven implementation → review

---

## Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Tests | 132 | 200+ |
| Tool calling | Broken (just fixed, untested) | Verified working |
| Feishu @mention | Not working | Working in group chat |
| Streaming card | Works sometimes | Reliable with fallback |
| Memory retrieval | Unit tested only | Verified in real chat |
| Gateway uptime | Needs manual restart | 24h+ unattended |
