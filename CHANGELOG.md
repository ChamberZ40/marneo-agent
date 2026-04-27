# Changelog

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
