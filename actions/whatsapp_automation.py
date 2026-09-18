"""
actions/whatsapp_automation.py
==============================
SK AI Agent — WhatsApp automation tools (auto-discovered by core/action_loader.py).

Tools exposed
─────────────
  whatsapp_send_message   — send a text message
  whatsapp_send_file      — send a file (image / video / audio / document)
  whatsapp_read_messages  — read recent messages from a chat
  whatsapp_list_chats     — list all chats with unread counts
  whatsapp_delete_message — delete / revoke a sent message
  whatsapp_edit_message   — edit a sent message (revoke + resend)
  whatsapp_mark_read      — mark a chat as read
  whatsapp_forward_message— forward a message to another contact
  whatsapp_react_message  — react to a message with an emoji
  whatsapp_auto_reply     — turn auto-reply ON / OFF / status
  whatsapp_summarize_chat — summarize a chat conversation
  whatsapp_configure      — manage aliases, allowlist, blocklist, keyword rules
  whatsapp_check_login    — check WhatsApp connection / QR status
"""

from core.whatsapp_manager import get_whatsapp_manager
from memory.whatsapp_config_manager import (
    set_auto_reply_enabled, get_auto_reply_enabled,
    add_contact_alias, remove_contact_alias,
    add_allow_contact, add_block_contact,
    add_keyword_pattern, remove_keyword_pattern,
    load_whatsapp_config, update_whatsapp_config,
    resolve_contact_alias,
)


# ── Shared helper ─────────────────────────────────────────────────────────────

def _mgr(player=None, speak=None):
    """Return the singleton WhatsAppManager, wiring logger + speak."""
    logger = None
    if player:
        def _log(m):
            try:
                player.write_log(f"[WhatsApp] {m}")
            except Exception:
                pass
        logger = _log
    return get_whatsapp_manager(logger=logger, speak_fn=speak)


# ── Tool handlers ─────────────────────────────────────────────────────────────

def whatsapp_send_message(parameters, player=None, speak=None, response=None, session_memory=None) -> str:
    params = parameters or {}
    receiver = (params.get("receiver") or "").strip()
    message_text = (params.get("message_text") or "").strip()
    if not receiver:
        return "Sir, please tell me who to send the WhatsApp message to."
    if not message_text:
        return "Sir, please tell me what message to send via WhatsApp."
    try:
        return _mgr(player, speak).send_message(receiver, message_text)
    except Exception as e:
        return f"Sir, WhatsApp send failed: {e}"


def whatsapp_send_file(parameters, player=None, speak=None, response=None, session_memory=None) -> str:
    params = parameters or {}
    receiver = (params.get("receiver") or "").strip()
    file_path = (params.get("file_path") or "").strip()
    if not receiver:
        return "Sir, please tell me who to send the file to on WhatsApp."
    if not file_path:
        return "Sir, please tell me which file to send via WhatsApp."
    try:
        return _mgr(player, speak).send_file(receiver, file_path)
    except Exception as e:
        return f"Sir, WhatsApp file send failed: {e}"


def whatsapp_read_messages(parameters, player=None, speak=None, response=None, session_memory=None) -> str:
    params = parameters or {}
    contact = (params.get("contact") or "").strip()
    limit = int(params.get("limit") or 10)
    if not contact:
        return "Sir, whose WhatsApp messages should I read?"
    try:
        return _mgr(player, speak).read_messages(contact, limit)
    except Exception as e:
        return f"Sir, reading WhatsApp messages failed: {e}"


def whatsapp_list_chats(parameters, player=None, speak=None, response=None, session_memory=None) -> str:
    try:
        return _mgr(player, speak).list_chats()
    except Exception as e:
        return f"Sir, listing WhatsApp chats failed: {e}"


def whatsapp_delete_message(parameters, player=None, speak=None, response=None, session_memory=None) -> str:
    params = parameters or {}
    contact = (params.get("contact") or "").strip()
    message_id = (params.get("message_id") or "").strip()
    for_everyone_raw = str(params.get("for_everyone", "true")).lower().strip()
    for_everyone = for_everyone_raw not in ("false", "0", "no")
    if not contact:
        return "Sir, which contact's chat contains the message to delete?"
    if not message_id:
        return "Sir, I need the message ID to delete. Read the messages first to get IDs."
    try:
        return _mgr(player, speak).delete_message(contact, message_id, for_everyone)
    except Exception as e:
        return f"Sir, WhatsApp delete message failed: {e}"


def whatsapp_edit_message(parameters, player=None, speak=None, response=None, session_memory=None) -> str:
    params = parameters or {}
    contact = (params.get("contact") or "").strip()
    message_id = (params.get("message_id") or "").strip()
    new_text = (params.get("new_text") or "").strip()
    if not contact:
        return "Sir, which contact's chat has the message to edit?"
    if not message_id:
        return "Sir, I need the message ID to edit. Read the messages first to get IDs."
    if not new_text:
        return "Sir, what should the edited message say?"
    try:
        return _mgr(player, speak).edit_message(contact, message_id, new_text)
    except Exception as e:
        return f"Sir, WhatsApp edit message failed: {e}"


def whatsapp_mark_read(parameters, player=None, speak=None, response=None, session_memory=None) -> str:
    params = parameters or {}
    contact = (params.get("contact") or "").strip()
    if not contact:
        return "Sir, which chat should I mark as read?"
    try:
        return _mgr(player, speak).mark_read(contact)
    except Exception as e:
        return f"Sir, WhatsApp mark-read failed: {e}"


def whatsapp_forward_message(parameters, player=None, speak=None, response=None, session_memory=None) -> str:
    params = parameters or {}
    from_contact = (params.get("from_contact") or "").strip()
    message_id = (params.get("message_id") or "").strip()
    to_contact = (params.get("to_contact") or "").strip()
    if not from_contact:
        return "Sir, which contact sent the original message?"
    if not message_id:
        return "Sir, I need the message ID to forward. Read messages first to get IDs."
    if not to_contact:
        return "Sir, who should I forward the message to?"
    try:
        return _mgr(player, speak).forward_message(from_contact, message_id, to_contact)
    except Exception as e:
        return f"Sir, WhatsApp forward failed: {e}"


def whatsapp_react_message(parameters, player=None, speak=None, response=None, session_memory=None) -> str:
    params = parameters or {}
    contact = (params.get("contact") or "").strip()
    message_id = (params.get("message_id") or "").strip()
    emoji = (params.get("emoji") or "").strip()
    if not contact:
        return "Sir, which contact's chat has the message to react to?"
    if not message_id:
        return "Sir, I need the message ID. Read messages first to get IDs."
    if not emoji:
        return "Sir, which emoji should I react with? (e.g. 👍, ❤️, 😂)"
    try:
        return _mgr(player, speak).react_message(contact, message_id, emoji)
    except Exception as e:
        return f"Sir, WhatsApp react failed: {e}"


def whatsapp_auto_reply(parameters, player=None, speak=None, response=None, session_memory=None) -> str:
    params = parameters or {}
    mode = (params.get("mode") or "status").strip().lower()

    if mode in ("on", "enable", "start", "true", "1"):
        set_auto_reply_enabled(True)
        # Start the poller if not already running
        try:
            mgr = _mgr(player, speak)
            if not (mgr._poller_thread and mgr._poller_thread.is_alive()):
                mgr.start_poller()
        except Exception:
            pass
        msg = "WhatsApp auto-reply is now ON, sir. I'll reply to incoming messages on your behalf."
        if player:
            try:
                player.write_log("[WhatsApp] Auto-reply ON")
            except Exception:
                pass
        return msg

    if mode in ("off", "disable", "stop", "false", "0"):
        set_auto_reply_enabled(False)
        msg = "WhatsApp auto-reply is now OFF, sir."
        if player:
            try:
                player.write_log("[WhatsApp] Auto-reply OFF")
            except Exception:
                pass
        return msg

    status = "ON" if get_auto_reply_enabled() else "OFF"
    return f"Sir, WhatsApp auto-reply is currently {status}."


def whatsapp_summarize_chat(parameters, player=None, speak=None, response=None, session_memory=None) -> str:
    from memory.whatsapp_config_manager import get_whatsapp_history
    params = parameters or {}
    contact = (params.get("contact") or "").strip()
    if not contact:
        return "Sir, which WhatsApp chat should I summarize?"
    history = get_whatsapp_history(contact, limit=30)
    if not history:
        return f"Sir, no message history found for {contact}."
    lines = []
    for h in reversed(history):
        who = "Them" if h.get("direction") == "in" else "Suraj"
        lines.append(f"[{h.get('ts','')}] {who}: {h.get('message','')}")
    transcript = "\n".join(lines)
    # Use LLM if available via mgr
    try:
        mgr = _mgr(player, speak)
        if mgr._llm_generate:
            prompt = (
                f"Summarize this WhatsApp chat between Suraj and {contact} "
                f"in 2-3 natural sentences. Mention who said what key things.\n"
                f"Chat:\n{transcript[:4000]}"
            )
            summary = mgr._llm_generate(prompt)
            if summary and summary.strip():
                return summary.strip()
    except Exception:
        pass
    return (
        f"Recent chat with {contact} ({len(history)} messages). "
        f"Last message: {history[0].get('message','')[:120]}"
    )


def whatsapp_configure(parameters, player=None, speak=None, response=None, session_memory=None) -> str:
    params = parameters or {}
    action = (params.get("action") or "").strip().lower()

    if action in ("add_alias", "alias"):
        alias = (params.get("alias") or "").strip()
        contact_name = (params.get("contact_name") or "").strip()
        if not alias or not contact_name:
            return "Sir, I need both the alias (spoken name) and the actual WhatsApp contact name."
        ok = add_contact_alias(alias, contact_name)
        return f"Done, sir. Added alias: '{alias}' → '{contact_name}'." if ok else "Sir, could not add that alias."

    if action in ("remove_alias", "unalias"):
        alias = (params.get("alias") or "").strip()
        if not alias:
            return "Sir, which alias should I remove?"
        ok = remove_contact_alias(alias)
        return f"Done, sir. Removed alias '{alias}'." if ok else f"Sir, alias '{alias}' was not found."

    if action in ("allow", "allowlist", "add_allow"):
        contact = (params.get("contact") or "").strip()
        if not contact:
            return "Sir, which contact should I allow for auto-replies?"
        add_allow_contact(contact)
        return f"Done, sir. Added '{contact}' to the auto-reply allowlist."

    if action in ("block", "blocklist", "add_block"):
        contact = (params.get("contact") or "").strip()
        if not contact:
            return "Sir, which contact should I block from auto-replies?"
        add_block_contact(contact)
        return f"Done, sir. Added '{contact}' to the auto-reply blocklist."

    if action in ("add_pattern", "pattern", "keyword"):
        pattern = (params.get("pattern") or "").strip()
        reply = (params.get("reply") or "").strip()
        if not pattern or not reply:
            return (
                "Sir, I need a regex pattern (e.g. '^hi$') and the reply text "
                "for the keyword rule."
            )
        ok = add_keyword_pattern(pattern, reply)
        return "Done, sir. Added keyword pattern rule." if ok else "Sir, that pattern is invalid or could not be added."

    if action in ("remove_pattern", "delete_pattern"):
        try:
            index = int(params.get("index") or 0)
        except ValueError:
            return "Sir, please give me the index number of the pattern to remove."
        ok = remove_keyword_pattern(index)
        return f"Done, sir. Removed pattern at index {index}." if ok else f"Sir, no pattern found at index {index}."

    if action in ("set_rate_limit", "rate_limit"):
        try:
            limit = int(params.get("limit") or 10)
        except ValueError:
            return "Sir, please give me a number for the rate limit (replies per hour)."
        update_whatsapp_config({"max_replies_per_hour": limit})
        return f"Done, sir. Auto-reply rate limit set to {limit} per hour."

    if action in ("set_poll_interval", "poll_interval"):
        try:
            interval = max(10, int(params.get("interval") or 20))
        except ValueError:
            return "Sir, please give me a number in seconds for the poll interval."
        update_whatsapp_config({"poll_interval_seconds": interval})
        return f"Done, sir. Poll interval set to {interval} seconds."

    if action == "list":
        cfg = load_whatsapp_config()
        parts = [
            f"Auto-reply: {'ON' if cfg.get('auto_reply_enabled') else 'OFF'}",
            f"Rate limit: {cfg.get('max_replies_per_hour', 10)} replies/hour",
            f"Poll interval: {cfg.get('poll_interval_seconds', 20)}s",
        ]
        aliases = cfg.get("contact_aliases") or {}
        if aliases:
            parts.append("Aliases:\n" + "\n".join(f"  {a} → {c}" for a, c in aliases.items()))
        patterns = cfg.get("keyword_patterns") or []
        if patterns:
            parts.append(
                "Keyword patterns:\n"
                + "\n".join(
                    f"  [{i}] /{p.get('pattern','')}/ → {p.get('reply','')}"
                    for i, p in enumerate(patterns)
                )
            )
        allow = cfg.get("auto_reply_allowlist") or []
        if allow:
            parts.append("Allowlist: " + ", ".join(allow))
        block = cfg.get("auto_reply_blocklist") or []
        if block:
            parts.append("Blocklist: " + ", ".join(block))
        return "\n".join(parts)

    return (
        "Sir, specify one of: add_alias, remove_alias, allow, block, "
        "add_pattern, remove_pattern, set_rate_limit, set_poll_interval, list."
    )


def whatsapp_check_login(parameters, player=None, speak=None, response=None, session_memory=None) -> str:
    try:
        return _mgr(player, speak).check_login()
    except Exception as e:
        return f"Sir, WhatsApp status check failed: {e}"


# ── Tool declarations ─────────────────────────────────────────────────────────
# Auto-discovered by core/action_loader.py via TOOL / TOOL_2 / … or TOOL_LIST.

TOOL = {
    "name": "whatsapp_send_message",
    "description": (
        "Sends a TEXT MESSAGE to a WhatsApp contact or group. "
        "ALWAYS use this tool (NOT a generic send tool) whenever the user says "
        "'WhatsApp', 'WP', 'send on WhatsApp', 'message on WhatsApp', etc. "
        "Receiver can be a saved contact name or a nickname alias (e.g. 'Aai' for mother)."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "receiver": {
                "type": "STRING",
                "description": "Contact name, group name, or alias (e.g. 'Mom', 'Aai', 'John')",
            },
            "message_text": {
                "type": "STRING",
                "description": "The text message to send",
            },
        },
        "required": ["receiver", "message_text"],
    },
    "handler": whatsapp_send_message,
}

TOOL_2 = {
    "name": "whatsapp_send_file",
    "description": (
        "Sends a FILE (image, PDF, document, photo, video, audio) to a WhatsApp contact. "
        "Use when user says 'send this file', 'send the photo', 'share the PDF', "
        "'send document' via WhatsApp. Requires the full file path."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "receiver": {
                "type": "STRING",
                "description": "Contact or group name on WhatsApp",
            },
            "file_path": {
                "type": "STRING",
                "description": "Full absolute path to the file (e.g. C:\\Users\\suraj\\Pictures\\pic.jpg)",
            },
        },
        "required": ["receiver", "file_path"],
    },
    "handler": whatsapp_send_file,
}

TOOL_3 = {
    "name": "whatsapp_read_messages",
    "description": (
        "READS the most recent messages from a specific WhatsApp chat. "
        "Use when the user says 'read my WhatsApp messages', 'what did X say on WhatsApp', "
        "'show messages from Mom', etc. Returns sender, text, timestamp, and message ID "
        "(needed for delete/edit/react/forward)."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "contact": {
                "type": "STRING",
                "description": "The contact or group name whose messages to read",
            },
            "limit": {
                "type": "STRING",
                "description": "Max number of recent messages to return (default 10, max 50)",
            },
        },
        "required": ["contact"],
    },
    "handler": whatsapp_read_messages,
}

TOOL_4 = {
    "name": "whatsapp_list_chats",
    "description": (
        "LISTS all recent WhatsApp chats with their unread message counts. "
        "Use when user says 'show my WhatsApp chats', 'who messaged me on WhatsApp', "
        "'list conversations', 'any unread messages?'."
    ),
    "parameters": {"type": "OBJECT", "properties": {}, "required": []},
    "handler": whatsapp_list_chats,
}

TOOL_5 = {
    "name": "whatsapp_delete_message",
    "description": (
        "DELETES / REVOKES a WhatsApp message you sent. "
        "Use when user says 'delete that message', 'unsend that', "
        "'remove the message I sent to X'. "
        "Requires message_id — call whatsapp_read_messages first if you don't have it. "
        "for_everyone=true (default) deletes for all parties; false removes only from your view."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "contact": {
                "type": "STRING",
                "description": "Contact or group name the message was sent to",
            },
            "message_id": {
                "type": "STRING",
                "description": "Message ID (from whatsapp_read_messages output — shown as [id:…])",
            },
            "for_everyone": {
                "type": "STRING",
                "description": "'true' to delete for all parties (default), 'false' for self only",
            },
        },
        "required": ["contact", "message_id"],
    },
    "handler": whatsapp_delete_message,
}

TOOL_6 = {
    "name": "whatsapp_edit_message",
    "description": (
        "EDITS a WhatsApp message you already sent by revoking the original and "
        "sending a corrected replacement. "
        "Use when user says 'edit that message', 'fix what I sent to X', "
        "'change the message I sent to Y'. "
        "Requires message_id — call whatsapp_read_messages first if you don't have it."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "contact": {
                "type": "STRING",
                "description": "Contact or group name the original message was sent to",
            },
            "message_id": {
                "type": "STRING",
                "description": "ID of the message to replace (from whatsapp_read_messages output)",
            },
            "new_text": {
                "type": "STRING",
                "description": "The corrected / replacement message text to send",
            },
        },
        "required": ["contact", "message_id", "new_text"],
    },
    "handler": whatsapp_edit_message,
}

TOOL_7 = {
    "name": "whatsapp_mark_read",
    "description": (
        "MARKS a WhatsApp chat as read, clearing the unread count. "
        "Use when user says 'mark X as read', 'clear unread for Y', "
        "'I've read those messages from Z'."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "contact": {
                "type": "STRING",
                "description": "Contact or group name to mark as read",
            },
        },
        "required": ["contact"],
    },
    "handler": whatsapp_mark_read,
}

TOOL_8 = {
    "name": "whatsapp_forward_message",
    "description": (
        "FORWARDS a WhatsApp message from one chat to another contact. "
        "Use when user says 'forward that message to X', 'send Y's message to Z'. "
        "Requires message_id — call whatsapp_read_messages first if you don't have it."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "from_contact": {
                "type": "STRING",
                "description": "Contact who sent the original message (source chat)",
            },
            "message_id": {
                "type": "STRING",
                "description": "ID of the message to forward",
            },
            "to_contact": {
                "type": "STRING",
                "description": "Contact or group to forward the message to (destination)",
            },
        },
        "required": ["from_contact", "message_id", "to_contact"],
    },
    "handler": whatsapp_forward_message,
}

TOOL_9 = {
    "name": "whatsapp_react_message",
    "description": (
        "SENDS AN EMOJI REACTION to a specific WhatsApp message. "
        "Use when user says 'react to X's message with a heart', 'thumbs up that message', "
        "'send 👍 to that'. "
        "Requires message_id — call whatsapp_read_messages first if you don't have it."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "contact": {
                "type": "STRING",
                "description": "Contact or group name whose message to react to",
            },
            "message_id": {
                "type": "STRING",
                "description": "ID of the message to react to",
            },
            "emoji": {
                "type": "STRING",
                "description": "Emoji to react with (e.g. '👍', '❤️', '😂', '🔥')",
            },
        },
        "required": ["contact", "message_id", "emoji"],
    },
    "handler": whatsapp_react_message,
}

TOOL_10 = {
    "name": "whatsapp_auto_reply",
    "description": (
        "TURNS WhatsApp auto-reply ON or OFF, or shows current status. "
        "When ON, SK automatically replies to incoming messages using Suraj's memory "
        "and LLM context (or keyword patterns if matched). "
        "Use when user says 'enable WhatsApp auto reply', 'turn off auto replies', "
        "'is auto reply on?'. Defaults to OFF for safety."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "mode": {
                "type": "STRING",
                "description": "'on' to enable, 'off' to disable, 'status' to check (default: status)",
            },
        },
        "required": [],
    },
    "handler": whatsapp_auto_reply,
}

TOOL_11 = {
    "name": "whatsapp_summarize_chat",
    "description": (
        "SUMMARIZES a WhatsApp conversation with a specific contact. "
        "Use when user says 'summarize my chat with X', 'what did we talk about with Y', "
        "'give me a summary of my WhatsApp conversation with Z'."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "contact": {
                "type": "STRING",
                "description": "Contact or group name whose chat to summarize",
            },
        },
        "required": ["contact"],
    },
    "handler": whatsapp_summarize_chat,
}

TOOL_12 = {
    "name": "whatsapp_configure",
    "description": (
        "CONFIGURE WhatsApp automation settings: contact aliases, allowlist/blocklist, "
        "keyword pattern rules, rate limit, and poll interval. "
        "Use when user says: 'add alias Aai for Mom', 'block Spammer from auto replies', "
        "'add keyword hi → Namaskar', 'list WhatsApp settings', "
        "'set rate limit to 5 per hour'."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": (
                    "'add_alias' | 'remove_alias' | 'allow' | 'block' | "
                    "'add_pattern' | 'remove_pattern' | "
                    "'set_rate_limit' | 'set_poll_interval' | 'list'"
                ),
            },
            "alias": {
                "type": "STRING",
                "description": "For add_alias / remove_alias: the spoken nickname (e.g. 'Aai')",
            },
            "contact_name": {
                "type": "STRING",
                "description": "For add_alias: the actual WhatsApp display name (e.g. 'Mom')",
            },
            "contact": {
                "type": "STRING",
                "description": "For allow / block: contact name",
            },
            "pattern": {
                "type": "STRING",
                "description": "For add_pattern: regex pattern (e.g. '^hi$' or '.*price.*')",
            },
            "reply": {
                "type": "STRING",
                "description": "For add_pattern: exact reply text when pattern matches",
            },
            "index": {
                "type": "STRING",
                "description": "For remove_pattern: integer index of pattern to delete",
            },
            "limit": {
                "type": "STRING",
                "description": "For set_rate_limit: max auto-replies per hour (integer)",
            },
            "interval": {
                "type": "STRING",
                "description": "For set_poll_interval: seconds between status polls (integer, min 10)",
            },
        },
        "required": ["action"],
    },
    "handler": whatsapp_configure,
}

TOOL_13 = {
    "name": "whatsapp_check_login",
    "description": (
        "CHECKS whether WhatsApp is logged in and the Baileys gateway is running. "
        "Use when user says 'is WhatsApp working', 'check WhatsApp login', "
        "'scan QR code for WhatsApp', 'why is WhatsApp not responding'."
    ),
    "parameters": {"type": "OBJECT", "properties": {}, "required": []},
    "handler": whatsapp_check_login,
}


TOOL_LIST = [
    TOOL, TOOL_2, TOOL_3, TOOL_4, TOOL_5, TOOL_6,
    TOOL_7, TOOL_8, TOOL_9, TOOL_10, TOOL_11, TOOL_12, TOOL_13,
]
