# Changelog

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
