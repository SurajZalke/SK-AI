import json
import sys
import re
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
from collections import defaultdict, deque


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()
WHATSAPP_CONFIG_PATH = BASE_DIR / "memory" / "whatsapp_config.json"
WHATSAPP_MESSAGES_PATH = BASE_DIR / "memory" / "whatsapp_messages.jsonl"
BROWSER_PROFILE_DIR = BASE_DIR / "memory" / "whatsapp_browser_profile"

_config_lock = Lock()
_messages_lock = Lock()

_DEFAULT_CONFIG = {
    "auto_reply_enabled": True,   # ON by default — SK replies on Suraj's behalf
    "auto_reply_allowlist": [],
    "auto_reply_blocklist": [],
    "keyword_patterns": [],
    "contact_aliases": {},
    "message_log_enabled": True,
    "max_replies_per_hour": 10,
    "speak_auto_reply_before_send": False,
    "poller_enabled": True,
    "poll_interval_seconds": 20,
}


def _ensure_dirs():
    WHATSAPP_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    WHATSAPP_MESSAGES_PATH.parent.mkdir(parents=True, exist_ok=True)
    BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)


def load_whatsapp_config() -> dict:
    _ensure_dirs()
    if not WHATSAPP_CONFIG_PATH.exists():
        return dict(_DEFAULT_CONFIG)
    with _config_lock:
        try:
            data = json.loads(WHATSAPP_CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                merged = dict(_DEFAULT_CONFIG)
                for k, v in data.items():
                    if k in merged:
                        merged[k] = v
                return merged
            return dict(_DEFAULT_CONFIG)
        except Exception as e:
            print(f"[WhatsAppConfig] Load error: {e}")
            return dict(_DEFAULT_CONFIG)


def save_whatsapp_config(config: dict) -> None:
    _ensure_dirs()
    if not isinstance(config, dict):
        return
    cleaned = {k: v for k, v in config.items() if k in _DEFAULT_CONFIG}
    with _config_lock:
        WHATSAPP_CONFIG_PATH.write_text(
            json.dumps(cleaned, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def update_whatsapp_config(updates: dict) -> dict:
    cfg = load_whatsapp_config()
    changed = False
    for k, v in (updates or {}).items():
        if k in _DEFAULT_CONFIG and cfg.get(k) != v:
            cfg[k] = v
            changed = True
    if changed:
        save_whatsapp_config(cfg)
    return cfg


def get_auto_reply_enabled() -> bool:
    return bool(load_whatsapp_config().get("auto_reply_enabled", False))


def set_auto_reply_enabled(enabled: bool) -> bool:
    cfg = update_whatsapp_config({"auto_reply_enabled": bool(enabled)})
    return bool(cfg.get("auto_reply_enabled"))


def resolve_contact_alias(spoken_name: str) -> str:
    if not spoken_name:
        return spoken_name
    aliases = load_whatsapp_config().get("contact_aliases", {}) or {}
    key = spoken_name.strip().lower()
    for alias, contact in aliases.items():
        if alias.strip().lower() == key:
            return contact
    return spoken_name


def add_contact_alias(alias: str, contact_name: str) -> bool:
    if not alias or not contact_name:
        return False
    cfg = load_whatsapp_config()
    aliases = dict(cfg.get("contact_aliases", {}) or {})
    aliases[alias.strip()] = contact_name.strip()
    update_whatsapp_config({"contact_aliases": aliases})
    return True


def remove_contact_alias(alias: str) -> bool:
    if not alias:
        return False
    cfg = load_whatsapp_config()
    aliases = dict(cfg.get("contact_aliases", {}) or {})
    removed = aliases.pop(alias.strip(), None) is not None
    if removed:
        update_whatsapp_config({"contact_aliases": aliases})
    return removed


def is_contact_allowed(contact: str) -> bool:
    """
    Returns True if this contact should receive an auto-reply.
    Blocklist always wins. Allowlist only restricts if non-empty.
    If allowlist is empty → everyone is allowed (reply to all).
    """
    if not contact:
        return False
    cfg = load_whatsapp_config()
    blocklist = [s.lower().strip() for s in (cfg.get("auto_reply_blocklist", []) or [])]
    allowlist = [s.lower().strip() for s in (cfg.get("auto_reply_allowlist", []) or [])]

    # Normalize contact for comparison — strip JID suffix, lowercase
    contact_clean = contact.lower().strip()
    contact_bare  = contact_clean.split("@")[0]   # e.g. "917304332469" from JID

    # Check blocklist (both full JID and bare number / name)
    for blocked in blocklist:
        if blocked in (contact_clean, contact_bare):
            return False
        # partial match for display names
        if blocked and (blocked in contact_clean or blocked in contact_bare):
            return False

    # If allowlist is empty → allow everyone
    if not allowlist:
        return True

    # If allowlist is set → must be in it
    for allowed in allowlist:
        if allowed in (contact_clean, contact_bare):
            return True
        if allowed and (allowed in contact_clean or allowed in contact_bare):
            return True
    return False


def add_allow_contact(contact: str) -> bool:
    if not contact:
        return False
    cfg = load_whatsapp_config()
    allowlist = list(cfg.get("auto_reply_allowlist", []) or [])
    contact = contact.strip()
    if contact not in allowlist:
        allowlist.append(contact)
        update_whatsapp_config({"auto_reply_allowlist": allowlist})
    return True


def add_block_contact(contact: str) -> bool:
    if not contact:
        return False
    cfg = load_whatsapp_config()
    blocklist = list(cfg.get("auto_reply_blocklist", []) or [])
    contact = contact.strip()
    if contact not in blocklist:
        blocklist.append(contact)
        update_whatsapp_config({"auto_reply_blocklist": blocklist})
    return True


def add_keyword_pattern(pattern: str, reply: str) -> bool:
    if not pattern or not reply:
        return False
    try:
        re.compile(pattern)
    except re.error:
        return False
    cfg = load_whatsapp_config()
    patterns = list(cfg.get("keyword_patterns", []) or [])
    patterns.append({"pattern": pattern.strip(), "reply": reply.strip()})
    update_whatsapp_config({"keyword_patterns": patterns})
    return True


def remove_keyword_pattern(index: int) -> bool:
    cfg = load_whatsapp_config()
    patterns = list(cfg.get("keyword_patterns", []) or [])
    if 0 <= index < len(patterns):
        del patterns[index]
        update_whatsapp_config({"keyword_patterns": patterns})
        return True
    return False


def match_keyword_pattern(message_text: str):
    if not message_text:
        return None
    patterns = load_whatsapp_config().get("keyword_patterns", []) or []
    text = message_text.strip()
    for entry in patterns:
        try:
            if re.match(entry.get("pattern", ""), text, re.IGNORECASE):
                return entry.get("reply")
        except re.error:
            continue
    return None


_rate_windows: dict = defaultdict(lambda: deque())
_rate_lock = Lock()


def check_rate_limit(contact: str) -> bool:
    cfg = load_whatsapp_config()
    max_per_hour = int(cfg.get("max_replies_per_hour", 10) or 10)
    if max_per_hour <= 0:
        return True
    cutoff = datetime.now() - timedelta(hours=1)
    with _rate_lock:
        window = _rate_windows[contact]
        while window and window[0] < cutoff:
            window.popleft()
        if len(window) >= max_per_hour:
            return False
        return True


def record_rate_usage(contact: str) -> None:
    with _rate_lock:
        _rate_windows[contact].append(datetime.now())


def log_whatsapp_event(direction: str, contact: str, message: str,
                       status: str = "sent") -> None:
    cfg = load_whatsapp_config()
    if not cfg.get("message_log_enabled", True):
        return
    _ensure_dirs()
    entry = {
        "ts": datetime.now().isoformat(),
        "direction": direction,
        "contact": contact or "",
        "message": (message or "")[:2000],
        "status": status or "sent",
    }
    with _messages_lock:
        try:
            with open(WHATSAPP_MESSAGES_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"[WhatsAppLog] Write error: {e}")


def get_whatsapp_history(contact=None, limit: int = 50) -> list:
    if not WHATSAPP_MESSAGES_PATH.exists():
        return []
    entries = []
    with _messages_lock:
        try:
            with open(WHATSAPP_MESSAGES_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except Exception:
                        continue
                    if contact:
                        if (entry.get("contact") or "").strip().lower() != contact.strip().lower():
                            continue
                    entries.append(entry)
        except Exception as e:
            print(f"[WhatsAppLog] Read error: {e}")
    entries.sort(key=lambda e: e.get("ts", ""), reverse=True)
    return entries[:max(1, int(limit))]


def get_recent_contacts(limit: int = 20) -> list:
    entries = get_whatsapp_history(limit=500)
    seen = {}
    for e in entries:
        c = e.get("contact") or ""
        if c and c not in seen:
            seen[c] = e
    return list(seen.keys())[:limit]
