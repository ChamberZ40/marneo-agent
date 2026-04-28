# Changelog

## [0.2.0] - 2026-04-28

### Changed (BREAKING)
- **ask_user complete rewrite — faithful port of openclaw-lark ask-user-question.js (860 LOC)**
  - **Non-blocking**: tool returns `{status: 'pending', questionId}` immediately, does NOT block agentic loop
  - **Synthetic message injection**: user answers arrive as a new ChannelMessage in a NEW conversation turn (not via Future)
  - **4 card states**: 待回答 (blue) → 处理中 (turquoise) → 已完成 (green) → 已过期 (grey), updated via Card Kit PATCH API
  - **Form container**: all questions in `<form>` tag, submit button with `form_action_type: "submit"`, form_value one-shot callback
  - **Multi-strategy submit detection**: button name prefix, tag+formValue, form_submit tag (matches all SDK versions)
  - **Sender verification**: only the original user can answer
  - **TTL expiry**: auto-expire after 5 min, card updates to expired state
  - **Retry logic**: synthetic message injection retries up to 2x with 2s delay, reverts card to submittable on failure
  - **Chat-scoped fallback**: when operationId missing, lookup by account:chat secondary index
  - **Full i18n**: zh_cn + en_us on all card elements
- **PendingQuestionStore replaced** with openclaw registry pattern: store/consume/findByChat, TTL timer, submitted flag, cardSequence tracking

## [0.1.9] - 2026-04-28

### Changed
- **ask_user rewrite (openclaw pattern)**: form container with select_static dropdowns, left-right column_set layout, option descriptions, blue card header with "需要你的确认" + "待回答" tag, supports 1-6 questions per card, single "📮 提交" submit button. Card Kit v2 entity creation. Backward compatible with single question+choices format.
- **Card action handler**: now handles form_value submit (form_action_type: "submit") in addition to legacy button clicks. Parses selection/answer fields per question index.
- **PendingQuestionStore**: added `set_questions`/`get_questions` for storing full question objects needed for form answer parsing

## [0.1.8] - 2026-04-28

### Added
- **tool-use-display**: streaming card now shows tool execution progress with name and status (🔧 执行中 / ✅ 完成), replaced by final text when LLM responds
- **feishu_send_file tool**: bot can now upload and send images (jpg/png/gif/webp via /im/v1/images) and files (pdf/docx/xlsx via /im/v1/files) to Feishu chats. Size limits: 10MB images, 20MB files
- **lark-cli skills**: 19 skill files symlinked to ~/.marneo/skills/ (lark-im, lark-calendar, lark-doc, lark-base, lark-sheets, lark-task, lark-mail, lark-drive, lark-wiki, etc.)
- **Feishu integration decision doc**: docs/feishu-integration-decision.md — lark_cli.py stays as primary (1 tool = 190+ commands, 95% fewer tokens than MCP), MCP bridge reserved for non-Feishu ecosystems
- 17 new tests (278 total)

## [0.1.7] - 2026-04-28

### Added
- **MCP protocol bridge** (hermes pattern): standalone module for connecting to any MCP server (Node.js, Go, Rust, Python) via subprocess + stdin/stdout JSON-RPC. Supports tool discovery, tool calling, env var expansion, reconnect with backoff. NOT wired into gateway yet — designed as a capability for future integration.
  - `McpBridge`: single server connection lifecycle (connect/discover/call/disconnect)
  - `McpManager`: multi-server management
  - Graceful degradation when `mcp` package not installed

## [0.1.6] - 2026-04-27

### Added
- **`ask_user` tool** (hermes clarify pattern): LLM sends interactive Feishu card with buttons, waits for user response via `card.action.trigger` callback. Supports button choices (max 4) and free-text reply mode. 300s timeout.
- **`PendingQuestionStore`**: thread-safe async Future coordination between card callback and agentic loop
- **Feishu one-click app creation**: `marneo employee add-feishu` now supports QR code scan to auto-create Feishu app via `lark.register_app()` (lark-oapi 1.5.5), no need to manually visit developer console
- **`async_dispatch`** in ToolRegistry for async tool handlers (ask_user is async)
- 16 new tests (261 total)

## [0.1.5] - 2026-04-27

### Added
- **AutoDream memory consolidation** (openclaw Dreaming pattern):
  - `RecallTracker`: records every memory retrieval hit with scores, query hashes, concept tags, recall days
  - `DreamingSweep`: three-phase sweep — Light Sleep (ingest episodes as synthetic recalls), REM Sleep (pattern analysis), Deep Sleep (6-signal scoring + promotion)
  - Scoring formula: frequency 24% / relevance 30% / diversity 15% / recency 15% (14-day half-life) / consolidation 10% / conceptual 6%
  - Threshold gates: score >= 0.75, recall_count >= 3, unique_queries >= 2
  - Wired into HybridRetriever — recalls tracked automatically during retrieval
- **Manifest-First plugin system** (openclaw pattern):
  - `PluginManifest`: frozen dataclass parsed from `manifest.json` (no code execution at discovery)
  - `PluginRegistry`: discover → activate (lazy import) → deactivate lifecycle
  - `load_plugin_module`: handles dotted module paths and file paths
  - Auto-activates `enabled_by_default` plugins during startup
  - Thread-safe, bad plugins can't crash the system
- 33 new tests (245 total)

## [0.1.4] - 2026-04-27

### Fixed
- **WS ping_timeout (3003)**: create lark-oapi Client inside executor thread so asyncio.Lock() binds to the correct event loop — eliminates "different loop" errors that killed ping/pong
- **NoneType crash in token tracking**: `prompt_tokens_details` can be None from MiniMax relay; added robust null checks
- **stream_options incompatibility**: removed `stream_options={"include_usage": True}` that broke MiniMax; capture usage opportunistically instead
- **Duplicate reply via feishu_send_mention**: platform hint now tells LLM not to use mention tool for replying to sender (card IS the reply)

### Changed
- **Group chat replies**: streaming card now replies to original message (shows "回复 张子豪: ..." header) — consistent with DM behavior
- Upgraded lark-oapi from 1.4.24 to 1.5.5

## [0.1.3] - 2026-04-27

### Added
- **FTS5 full-text search** (hermes pattern): cross-session keyword search across episode content, type, tags, project via SQLite FTS5 virtual table with auto-sync triggers
- **Model failover + credential pool**: ProviderPool with primary + fallback providers, auto-switch on auth errors, exponential backoff on rate limits, 5min cooldown after 3 failures
- **Token usage tracking**: TokenTracker captures input/output/cache tokens from OpenAI and Anthropic responses, per-model breakdown, session summary
- **Episode → Core auto-promotion** (openclaw scoring): 6-factor scoring formula (relevance 30% / frequency 24% / freshness 15% / diversity 15% / size 10% / promoted 6%), threshold-based promotion
- **Platform-specific hints**: system prompt adapts to channel capabilities (Feishu markdown+cards, Telegram markdown, WeChat plain text, Discord embeds, CLI)
- **last_accessed_at** timestamp on episodes (with migration for pre-v0.1.2 DBs)
- 22 new tests (212 total)

## [0.1.2] - 2026-04-27

### Added
- **JSON argument auto-repair** (hermes pattern): handles trailing commas, unclosed brackets, Python None/True/False, markdown fences, single quotes
- **Tool loop detection** (openclaw pattern): consecutive identical tool calls (same name + args) auto-break at threshold 3
- **Hermetic test isolation**: strips credential env vars, redirects MARNEO_HOME, sets deterministic TZ/LANG/PYTHONHASHSEED
- 13 new tests (190 total)

## [0.1.1] - 2026-04-27

### Fixed
- **Duplicate replies**: dedup check moved before async operations (`_resolve_sender_name`) to prevent race condition when Feishu WS re-delivers events during await
- **WS disconnect crash**: `disconnect()` now closes underlying websocket connection directly instead of calling non-existent `stop()` method on lark-oapi Client
- **Streaming card narration leak**: tool-calling iterations no longer leak intermediate narration text to the card; only final response is displayed
- **Fake @mention in cards**: removed `<at>` prefix from Card Kit markdown (not supported as real mention)
- **`publish_apply_v6` ERROR noise**: registered no-op handlers for app version publish/revoke events

## [0.1.0] - 2026-04-27

### Added
- Feishu adapter (WebSocket + streaming cards via Card Kit API)
- Tool system with 12 tools (bash, files, web, lark_cli, feishu_tools)
- 3-tier memory system (Core/Episodic/Working) with BM25+fastembed hybrid retrieval
- Agentic tool-calling loop (send_with_tools)
- Multimodal support (image/PDF/file download)
- Per-chat serial locks (openclaw createChatQueue pattern)
- Reaction lifecycle (SaluteFace on processing, remove on success, CrossMark on failure)
- WS watchdog (auto-restart after 5min inactivity)
- Session cleanup (evict expired sessions every 5min)
- Health endpoint (`/health` with tools count, uptime, last event time)
- Correlation IDs (`[msg:xxx]`) across adapter → manager → streaming
- 177 tests passing
