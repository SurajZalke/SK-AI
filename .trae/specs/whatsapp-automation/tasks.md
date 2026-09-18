# WhatsApp Automation for SK AI Agent - Implementation Plan

## Task 1: Create WhatsApp Core Manager Module
- **Status**: `pending`
- **Priority**: high
- **Depends On**: None
- **Description**:
  - Create `core/whatsapp_manager.py` — the central abstraction layer for all WhatsApp operations
  - Implement Playwright-based WhatsApp Web controller:
    - Connect/launch browser with persistent user data directory (avoids re-scanning QR)
    - Navigate to WhatsApp Web, detect login state (QR vs logged in)
    - Search for contact/group by name
    - Open chat, send text message
    - Send file attachment (by path)
    - Read messages from current chat (last N messages, with sender/timestamp)
    - List recent chats with unread count
    - Periodic new message poller (background thread) with callback hook
  - Implement contact alias mapping layer (e.g., "Aai" → actual WhatsApp name)
  - Implement fallback to existing PyAutoGUI method if Playwright fails or is unavailable
  - All methods must never raise raw exceptions — return user-friendly error strings
- **Acceptance Criteria Addressed**: AC-1, AC-2, AC-3, AC-9, NFR-4, NFR-5
- **Test Requirements**:
  - `rule` TR-1.1: Importing `core.whatsapp_manager` does not raise even if Playwright browsers not installed; returns a clear status on `WhatsAppManager.status`
  - `rule` TR-1.2: `WhatsAppManager._resolve_alias("Aai")` returns the mapped contact name when alias configured, else returns input unchanged
  - `rubric` TR-1.3: Code architecture quality; scale 1-5; anchors 1 = monolithic blob / no separation, 3 = works but mixed concerns, 5 = clean separation of browser control, alias layer, polling; threshold >= 4; evidence = code review of whatsapp_manager.py
- **Notes**: Persist browser user data in `memory/whatsapp_browser_profile/` subdirectory so session survives SK restarts

## Task 2: WhatsApp Configuration Manager
- **Status**: `pending`
- **Priority**: high
- **Depends On**: None
- **Description**:
  - Create `memory/whatsapp_config.json` schema and persistence layer (append to memory_manager or standalone)
  - Config fields:
    - `auto_reply_enabled: bool` (default false)
    - `auto_reply_allowlist: list[str]` (contact names; empty = all allowed)
    - `auto_reply_blocklist: list[str]` (contact names to skip; overrides allowlist)
    - `keyword_patterns: list[{pattern: str, reply: str}]` (regex patterns for deterministic replies)
    - `contact_aliases: dict[str, str]` (spoken name → WhatsApp display name)
    - `message_log_enabled: bool` (default true)
    - `max_replies_per_hour: int` (default 10)
  - Implement thread-safe load/save (copy memory_manager's Lock pattern)
  - Implement runtime get/set methods for each field
- **Acceptance Criteria Addressed**: AC-4, AC-6, AC-7, AC-8, FR-8, FR-9, FR-13, FR-15
- **Test Requirements**:
  - `rule` TR-2.1: Writing a config with `save_whatsapp_config(...)` and re-reading with `load_whatsapp_config()` returns identical dict (JSON round-trip)
  - `rule` TR-2.2: Config file created at `memory/whatsapp_config.json` on first save; file survives SK process restart
  - `rule` TR-2.3: `is_contact_allowed(contact)` correctly implements allowlist → blocklist → default-allow logic
- **Notes**: Put this in `memory/config_manager.py` as new functions, or create `memory/whatsapp_config_manager.py`. Use existing memory_manager patterns (threading.Lock, BASE_DIR resolution, Path usage).

## Task 3: WhatsApp Message Activity Logger
- **Status**: `pending`
- **Priority**: medium
- **Depends On**: Task 2
- **Description**:
  - Implement `log_whatsapp_event(direction, contact, message, timestamp, status)` function
  - Store in `memory/whatsapp_messages.jsonl` (append-only JSON lines format)
  - Fields per line: `{ts, direction: "in"|"out", contact, message, status: "sent"|"failed"|"auto-replied"|"skipped-blocked"}`
  - Implement `get_whatsapp_history(contact=None, limit=50)` for retrieval
  - Integrate logger into WhatsAppManager send/read paths (called on every in/out event)
  - Implement `summarize_chat(contact)` helper that feeds recent messages to SK LLM for a natural-language summary
- **Acceptance Criteria Addressed**: AC-7, FR-10, FR-11, FR-12
- **Test Requirements**:
  - `rule` TR-3.1: After one `log_whatsapp_event("out", "Alice", "Hi", ...)` call, `get_whatsapp_history("Alice", 1)` returns exactly that event
  - `rule` TR-3.2: JSONL file `memory/whatsapp_messages.jsonl` is valid line-delimited JSON; file append is thread-safe (no interleaved writes)
- **Notes**: Use JSONL instead of a single JSON array to keep writes O(1) append — avoids rewriting a large array on every message.

## Task 4: Auto-Reply Engine with LLM and Keyword Patterns
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 1, Task 2, Task 3
- **Description**:
  - Implement `AutoReplyEngine` class in `core/whatsapp_manager.py` or a new module
  - Pipeline for each incoming message:
    1. Check `auto_reply_enabled` flag
    2. Check allowlist/blocklist (if skipped → log as "skipped-blocked")
    3. Check rate limit (max_replies_per_hour, per-contact)
    4. Check keyword patterns FIRST (regex match → use configured reply, skip LLM; per user preference for deterministic responses)
    5. If no keyword match, build LLM prompt:
       - Inject SK's long-term memory (use existing `format_memory_for_prompt` + user's relationship context)
       - Inject recent 5-10 message history with this contact for context
       - Inject system identity: "You are SK, Suraj's AI assistant. You are replying to a WhatsApp message FROM {contact} TO Suraj. Reply on Suraj's behalf in the same language as the incoming message. Use Marathi for family when appropriate. Keep replies natural and concise — never reveal you are an AI unless asked directly."
       - Call existing Gemini LLM client (reuse `core/llm_client.py` or main's session.send pattern)
    6. Send generated reply via WhatsAppManager
    7. Log event as "auto-replied" with both incoming message and outgoing reply
  - Implement rate limiter with sliding window (per-contact and global)
- **Acceptance Criteria Addressed**: AC-5, AC-6, AC-7, FR-5, FR-6, FR-7, FR-8, FR-9
- **Test Requirements**:
  - `rule` TR-4.1: Given pattern `{"pattern": "^hi$", "reply": "Namaskar!"}`, incoming "hi" → output reply is exactly "Namaskar!" (no LLM call made)
  - `rule` TR-4.2: Given blocklist=["Spammer"], incoming from Spammer → no reply sent; log entry has status="skipped-blocked"
  - `rubric` TR-4.3: LLM reply personalization quality; scale 1-5; anchors 1 = generic robotic reply, 3 = correct language but no memory reference, 5 = references stored memory (e.g., greets "Aai" with correct respectful form in Marathi); threshold >= 4; evidence = 3 hand-checked test replies
  - `rule` TR-4.4: Rate limiter: 11 rapid messages from same contact in <1 hour → only first 10 get replies; 11th is skipped
- **Notes**: Critical: Keyword patterns run BEFORE LLM — this is the user's explicit deterministic preference from their memory profile. Regex matching must be case-insensitive and trim whitespace.

## Task 5: WhatsApp Actions Suite (TOOL declarations for SK Agent)
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 1, Task 2, Task 3, Task 4
- **Description**:
  - Create `actions/whatsapp_automation.py` with a TOOL dict per action (follow action_loader pattern):
    1. `whatsapp_send_message(receiver, message_text)` → AC-1
    2. `whatsapp_send_file(receiver, file_path)` → AC-2
    3. `whatsapp_read_messages(contact, limit)` → AC-3
    4. `whatsapp_list_chats()` → FR-3
    5. `whatsapp_auto_reply(mode: "on"|"off"|"status")` → AC-4
    6. `whatsapp_summarize_chat(contact)` → FR-11
    7. `whatsapp_configure(action: "add_alias"|"remove_alias"|"allow"|"block"|"add_pattern"|"remove_pattern", ...)` → FR-8, FR-9, FR-15
    8. `whatsapp_check_login()` → AC-9
  - Each TOOL handler calls WhatsAppManager methods
  - Each handler signature receives `player` (SKUI) and `speak` via ctx injection
  - Write detailed TOOL descriptions so Gemini correctly routes user queries (e.g., "Send WhatsApp to John saying hello" → whatsapp_send_message)
  - Ensure every TOOL description explicitly says to use this instead of generic `send_message` for WhatsApp
- **Acceptance Criteria Addressed**: AC-1, AC-2, AC-3, AC-4, AC-9, FR-1 through FR-12
- **Test Requirements**:
  - `rule` TR-5.1: `discover_actions()` loads `whatsapp_automation.py` with no errors; all 8 TOOLs appear in ActionRegistry with valid=True
  - `rule` TR-5.2: Calling `whatsapp_check_login` handler returns a user-friendly status string even when Playwright is unavailable (never raises)
  - `rule` TR-5.3: TOOL parameter schemas are valid JSON Schema OBJECT type with correct required fields
- **Notes**: Follow the exact TOOL dict pattern in [send_message.py](file:///c:/Users/suraj/OneDrive/Desktop/SK%20AI%20AGEENT/actions/send_message.py#L270-L296). Handler signatures use `(parameters, player, speak, response, session_memory)` as needed.

## Task 6: Dashboard Integration — WhatsApp UI and API Endpoints
- **Status**: `pending`
- **Priority**: medium
- **Depends On**: Task 1, Task 2, Task 3
- **Description**:
  - Extend `dashboard/server.py`:
    - Add `GET /whatsapp` page (HTML) showing:
      - Auto-reply toggle switch (on/off)
      - Recent message log table (last 20 entries, in/out, contact, message, time, status)
      - Send message form (receiver + message text fields + submit)
      - Send file upload form (receiver + file picker)
      - Alias management table (add/remove spoken name → WhatsApp name)
    - Add API routes:
      - `POST /api/whatsapp/send` → body `{receiver, message}` → calls whatsapp_send_message
      - `POST /api/whatsapp/send-file` → multipart `{receiver, file}` → calls whatsapp_send_file
      - `POST /api/whatsapp/auto-reply` → body `{enabled: bool}` → toggles + persists
      - `GET  /api/whatsapp/history?limit=20` → returns JSON array of logged events
      - `GET  /api/whatsapp/chats` → returns recent chats list
      - `POST /api/whatsapp/alias` → body `{alias, contact_name}`
      - `DELETE /api/whatsapp/alias/{alias}`
  - Reuse existing dashboard auth (cryptography key-based auto-login)
  - Add WhatsApp link/nav entry to main dashboard page
- **Acceptance Criteria Addressed**: AC-10, FR-14
- **Test Requirements**:
  - `rule` TR-6.1: Unauthenticated GET /whatsapp redirects to login (respects existing dashboard auth)
  - `rule` TR-6.2: POST /api/whatsapp/auto-reply with `{enabled: true}` returns 200 and updates whatsapp_config.json on disk
  - `rule` TR-6.3: GET /api/whatsapp/history returns valid JSON array with correct schema fields
- **Notes**: Keep HTML templates in `dashboard/static/whatsapp.html` or inline within server.py (follow existing app.html pattern). Keep Python 3.10 compatible (no match/case).

## Task 7: Background Message Poller & Notification Integration
- **Status**: `pending`
- **Priority**: medium
- **Depends On**: Task 1, Task 4
- **Description**:
  - Implement `WhatsAppPoller` background thread:
    - Wakes every 15-30 seconds
    - Checks for new unread messages across all chats (via Playwright WhatsApp DOM scan)
    - For each new message:
      - Calls AutoReplyEngine.process_incoming() if auto-reply enabled
      - Triggers SK spoken notification: "Sir, new WhatsApp message from {contact}: {first 50 chars}" (respects mute/wake state)
      - Writes UI log entry in SK UI: `[WhatsApp] {contact}: ...`
    - Deduplicates already-processed messages by tracking last-seen message ID per chat
  - Integrate poller lifecycle: start in SKLive.__init__() (lazy start when WhatsApp first used), stop on shutdown
  - Expose poller pause/resume via whatsapp_configure action and dashboard toggle
- **Acceptance Criteria Addressed**: FR-3, FR-12, NFR-3
- **Test Requirements**:
  - `rule` TR-7.1: Poller process_incoming() is idempotent: feeding the same message ID twice → only ONE reply/notification/log entry on second call (dedup works)
  - `rule` TR-7.2: With auto-reply OFF, incoming message triggers spoken notification only (no reply sent)
- **Notes**: Use existing `ui.write_log()` and `speak()` methods for notifications. Poll interval must not be < 10 seconds to avoid WhatsApp rate limiting / detection.

## Task 8: Requirements & Import Safety Updates
- **Status**: `pending`
- **Priority**: medium
- **Depends On**: None
- **Description**:
  - Verify `requirements.txt` already has `playwright` (yes, present) — no new core dependencies needed
  - Add optional note comment about running `playwright install chromium` if not yet done
  - Add robust try/except imports in whatsapp_manager for playwright: if import fails, module exposes WhatsAppManager that gracefully returns "Playwright not installed" errors without crashing SK
  - Add whatsapp_messages.jsonl, whatsapp_browser_profile/ to .gitignore if not already ignored
  - Add whatsapp_config.json to .gitignore (contains user contact data)
- **Acceptance Criteria Addressed**: AC-9, NFR-1, NFR-2, NFR-5
- **Test Requirements**:
  - `rule` TR-8.1: With `playwright` package uninstalled, SK Agent main process still starts successfully; only WhatsApp-related commands return "not installed" friendly errors
  - `rule` TR-8.2: .gitignore entries prevent WhatsApp config/history/profile from being committed
- **Notes**: Test this by temporarily removing playwright from sys.modules and doing an import test. Guard every Playwright usage behind the `_PLAYWRIGHT_AVAILABLE` boolean flag pattern used in send_message.py for pyautogui.

## Task 9: Integration Verification & End-to-End Smoke Test
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 1-8 (all)
- **Description**:
  - Write and run manual smoke test script or inline Python verification:
    1. Verify action_loader discovers all 8 WhatsApp TOOLs
    2. Round-trip write/read whatsapp_config.json
    3. Verify keyword regex pattern matching
    4. Verify allowlist/blocklist logic
    5. Verify rate limiter
    6. Verify message logger JSONL append and retrieval
    7. Import core.whatsapp_manager in isolation with mocked Playwright unavailable → no crash
    8. Dashboard routes return 200 after auth (use requests.get against local server)
  - Run existing project lint/type checks (GetDiagnostics)
  - Document any known limitations inline in code comments
- **Acceptance Criteria Addressed**: All ACs (final coverage)
- **Test Requirements**:
  - `rule` TR-9.1: All 8 acceptance criteria have at least one passing TR result recorded in task completion evidence
  - `rule` TR-9.2: `python -c "from actions import whatsapp_automation"` succeeds with exit code 0
  - `rule` TR-9.3: GetDiagnostics reports zero errors in all created/modified files
  - `rubric` TR-9.4: Overall developer experience; scale 1-5; anchors 1 = crashes often / unclear errors, 3 = works but setup steps unclear, 5 = works out of box with friendly status messages; threshold >= 4; evidence = first-run smoke test log
- **Notes**: If Playwright browser is not actually installed in this environment, use dependency-injection mocks (inject a FakeBrowser class) that exercise all non-DOM logic paths. DOM selectors for WhatsApp Web are best-effort and documented as "may need updating if WhatsApp changes their UI".
