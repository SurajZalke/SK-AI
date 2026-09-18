# WhatsApp Automation for SK AI Agent - Product Requirements Document

## Overview
- **Summary**: A dedicated WhatsApp automation module integrated into the SK AI Agent that enables sending messages, sending files, reading incoming messages, and providing intelligent auto-replies using the SK Agent's LLM capabilities.
- **Purpose**: To allow Suraj to manage WhatsApp conversations directly through SK Agent, automate responses, share files, and leverage the agent's existing memory and LLM for context-aware replies.
- **Target Users**: Suraj Zalke (primary user of SK AI Agent)

## Goals
- Send text messages to WhatsApp contacts/groups via SK Agent voice or text commands
- Send files (images, documents, PDFs) to WhatsApp contacts
- Read and monitor incoming WhatsApp messages
- Provide AI-powered auto-replies to incoming messages using SK Agent's LLM and memory context
- Maintain WhatsApp conversation history and integrate with SK's memory system
- Support both manual (user-initiated) and automated (rule/LLM-triggered) messaging
- Expose WhatsApp controls through the SK Agent dashboard (remote control UI)

## Non-Goals
- WhatsApp voice/video call automation
- End-to-end encryption key management
- WhatsApp Business API integration (uses WhatsApp Web/Desktop automation approach)
- Bulk marketing spam messaging
- Multi-account support (single WhatsApp account only)

## Background & Context
- The SK AI Agent already has a `send_message` action in [send_message.py](file:///c:/Users/suraj/OneDrive/Desktop/SK%20AI%20AGEENT/actions/send_message.py) that uses PyAutoGUI for basic WhatsApp desktop automation. This is unreliable for complex operations.
- The project uses an action/plugin discovery system via [action_loader.py](file:///c:/Users/suraj/OneDrive/Desktop/SK%20AI%20AGEENT/core/action_loader.py) and [plugin_loader.py](file:///c:/Users/suraj/OneDrive/Desktop/SK%20AI%20AGEENT/core/plugin_loader.py).
- Memory persistence via [memory_manager.py](file:///c:/Users/suraj/OneDrive/Desktop/SK%20AI%20AGEENT/memory/memory_manager.py) stores user preferences and facts.
- A remote dashboard exists at [dashboard/server.py](file:///c:/Users/suraj/OneDrive/Desktop/SK%20AI%20AGEENT/dashboard/server.py) for phone control.
- User prefers deterministic pattern-based responses for routine interactions (per user profile preferences).

## Functional Requirements

### Core Messaging
- **FR-1**: SK Agent can send a text message to a specified WhatsApp contact or group by name
- **FR-2**: SK Agent can send files (images, PDFs, documents) to a specified WhatsApp contact
- **FR-3**: SK Agent can list recent WhatsApp chats and unread message counts
- **FR-4**: SK Agent can read the last N messages from a specific chat conversation

### Auto-Reply System
- **FR-5**: Auto-reply mode can be toggled ON/OFF by the user
- **FR-6**: When auto-reply is ON, incoming WhatsApp messages trigger SK Agent to generate a context-aware reply using the LLM
- **FR-7**: Auto-replies incorporate SK Agent's long-term memory (user preferences, relationships, etc.) for personalization
- **FR-8**: User can configure specific contacts/groups that should receive auto-replies (allowlist) or be excluded (blocklist)
- **FR-9**: User can define keyword-based auto-reply patterns (regex) for deterministic responses, per user preference

### Monitoring & History
- **FR-10**: WhatsApp message activity (sent/received) is logged with timestamps and contact info
- **FR-11**: SK Agent can summarize a WhatsApp chat conversation when requested
- **FR-12**: Unread messages trigger a notification through SK Agent (spoken alert + UI log)

### Configuration & Integration
- **FR-13**: WhatsApp settings (auto-reply toggle, allowlist, blocklist, keyword patterns) are persisted across sessions
- **FR-14**: WhatsApp controls are exposed via the remote dashboard for phone access
- **FR-15**: Contacts can be aliased/nicknamed (e.g., "Aai" → actual WhatsApp contact name)

## Non-Functional Requirements
- **NFR-1**: WhatsApp module auto-discovers at startup via the action_loader system (no manual main.py edits)
- **NFR-2**: All user-facing errors are caught and reported as natural-language spoken messages, never raw stack traces
- **NFR-3**: Auto-reply response time < 15 seconds from message receipt (excluding LLM latency variance)
- **NFR-4**: WhatsApp Web/Desktop session persistence — does not require re-scanning QR code on every SK Agent restart
- **NFR-5**: Module gracefully degrades if WhatsApp is not installed/logged in — reports status instead of crashing
- **NFR-6**: All file operations and message logs respect Windows file path conventions

## Constraints
- **Technical**:
  - Must use WhatsApp Web automation via Playwright (already in requirements.txt) rather than unofficial APIs, to avoid TOS violations and account bans
  - Must integrate with existing action_loader pattern (TOOL dict in actions/*.py)
  - Must work on Windows (primary OS per config)
  - Must use existing memory_manager for persistence — no new database
- **Business**:
  - Must not violate WhatsApp Terms of Service (no spam, reasonable message rates)
- **Dependencies**:
  - Playwright browser automation (already installed)
  - Existing PyAutoGUI/Pyperclip as fallback mechanism
  - Gemini LLM for AI replies (already configured)

## Assumptions
- User has WhatsApp Desktop installed and logged in on the SK Agent machine, or WhatsApp Web accessible via browser
- User understands that WhatsApp automation via browser control may be rate-limited if abused
- A single WhatsApp account will be used with the agent
- User will provide contact name mappings where WhatsApp display names differ from spoken names

## Acceptance Criteria

### AC-1: Send Text Message
- **Type**: `rule`
- **Given**: WhatsApp is logged in and contact name "John" exists
- **When**: User says "WhatsApp John hey how are you" or types equivalent command
- **Then**: The message "hey how are you" appears in the WhatsApp chat with John within 30 seconds
- **Pass Condition**: Playwright browser confirms message element present in chat DOM with correct text content
- **Evidence**: Playwright DOM snapshot + SK log line showing "message sent" status

### AC-2: Send File
- **Type**: `rule`
- **Given**: WhatsApp is logged in, contact "Mom" exists, file `C:\Users\suraj\Pictures\photo.jpg` exists
- **When**: User commands SK Agent to send photo.jpg to Mom via WhatsApp
- **Then**: The file is attached and sent to Mom's WhatsApp chat within 60 seconds
- **Pass Condition**: Playwright detects file attachment success confirmation in WhatsApp UI
- **Evidence**: Playwright screenshot of sent file + tool return value = "file sent"

### AC-3: Read Incoming Messages
- **Type**: `rule`
- **Given**: WhatsApp chat with "Alice" has 3 unread messages
- **When**: User asks "read my WhatsApp messages from Alice"
- **Then**: SK Agent speaks the content of Alice's messages with sender and timestamp
- **Pass Condition**: SK agent output (spoken/log) contains the exact text of Alice's 3 messages
- **Evidence**: SK UI log entries + captured Playwright message text

### AC-4: Auto-Reply Toggle
- **Type**: `rule`
- **Given**: WhatsApp automation is loaded
- **When**: User says "turn on WhatsApp auto reply"
- **Then**: Auto-reply mode is activated and setting is persisted to disk
- **Pass Condition**: `whatsapp_config.json` contains `"auto_reply_enabled": true` after command
- **Evidence**: File content inspection + SK log line confirming state change

### AC-5: AI Auto-Reply with Memory
- **Type**: `rubric`
- **Dimension**: Quality of context-aware auto-replies using memory
- **Scale**: 1-5
- **Anchors**: 1 = generic/unrelated reply with no context; 3 = correct response but ignores user memory/preferences; 5 = reply incorporates known facts (e.g., remembers relationship "Aai" = Mother, uses correct respectful form, references stored preferences)
- **Pass Threshold**: >= 4
- **Evidence**: Compare auto-reply output against stored memory entries. Verify reply content references at least one stored fact when relevant. Human review of 3 test conversations.

### AC-6: Keyword Pattern Matching
- **Type**: `rule`
- **Given**: Keyword pattern configured: `^\s*(hi|hello|hey)\s*$` → reply "Namaskar! Kase ahat?" (Marathi greeting)
- **When**: Incoming message is exactly "hi"
- **Then**: The deterministic pattern reply is sent instead of LLM generation
- **Pass Condition**: Sent message text exactly matches configured pattern reply
- **Evidence**: SK log + WhatsApp DOM showing the configured reply text (not LLM-generated variant)

### AC-7: Allowlist/Blocklist Filtering
- **Type**: `rule`
- **Given**: Auto-reply ON, allowlist = ["Alice", "Bob"], contact "UnknownSpammer" sends message
- **When**: UnknownSpammer sends "Buy cheap pills"
- **Then**: No auto-reply is sent to UnknownSpammer; message is logged as skipped
- **Pass Condition**: No outgoing message detected in WhatsApp DOM for UnknownSpammer; SK log contains "blocked/skipped" entry
- **Evidence**: Playwright DOM check + SK activity log

### AC-8: Configuration Persistence
- **Type**: `rule`
- **Given**: Auto-reply enabled, allowlist = ["Mom"], keyword pattern configured
- **When**: SK Agent process is fully restarted
- **Then**: All WhatsApp settings are restored exactly as configured before restart
- **Pass Condition**: After restart, in-memory config matches pre-restart JSON file content byte-for-byte
- **Evidence**: Diff of pre-restart and post-restart config dumps = zero differences

### AC-9: Graceful Degradation (No WhatsApp)
- **Type**: `rule`
- **Given**: WhatsApp Web is not logged in / QR code not scanned
- **When**: User requests any WhatsApp action
- **Then**: SK Agent says a clear error message ("Sir, WhatsApp is not logged in. Please scan the QR code.") without raising uncaught exceptions
- **Pass Condition**: No Python exception traceback in console; spoken error message matches expected format
- **Evidence**: Console output scan for "Traceback" = 0 matches; UI log contains user-friendly error

### AC-10: Dashboard Integration
- **Type**: `rule`
- **Given**: Dashboard server is running and user is authenticated
- **When**: Dashboard /whatsapp page is requested
- **Then**: Page shows auto-reply toggle, recent message log, and a "Send Message" form — all functional
- **Pass Condition**: HTTP GET /whatsapp returns 200 with HTML containing expected UI elements; toggle changes server-side state
- **Evidence**: curl command output + server log of successful form POST

## Open Questions
- [ ] Should auto-replies default to OFF on first run (safer) or ON? → Recommend OFF, user must explicitly enable.
- [ ] Should message logs store message bodies or just metadata (sender/timestamp/status)? → Recommend storing bodies for chat summary feature, but with clear opt-in.
- [ ] Maximum auto-reply rate limit per contact per hour? → Recommend 10/hour soft cap to avoid rate limiting.
- [ ] Should auto-replies use the same configured assistant voice/TTS to speak the reply before sending? → Recommend optional, default OFF (silent auto-reply).
