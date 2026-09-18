"""
core/whatsapp_manager.py
========================
SK AI Agent — full WhatsApp automation layer (Baileys headless gateway).

Capabilities
------------
• Send text messages
• Send files (image / video / audio / document)
• Read messages from any chat
• List all chats with unread counts
• Delete a message you sent (revoke)
• Edit a message you sent (delete + re-send replacement)
• Mark a chat as read
• Forward a message to another contact
• React to a message with an emoji
• Auto-reply engine (keyword patterns OR LLM-generated replies)
• SSE event stream for real-time incoming message notifications
• Background status poller for gateway health
"""

import asyncio
import json
import re
import sys
import time
import threading
import subprocess
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable


# ── HTTP helpers (requests preferred, urllib fallback) ────────────────────────

_REQUESTS_AVAILABLE = False
try:
    import requests
    _REQUESTS_AVAILABLE = True
except ImportError:
    try:
        import urllib.request as _ur
        _REQUESTS_AVAILABLE = "urllib"
    except Exception:
        _REQUESTS_AVAILABLE = False


from memory.whatsapp_config_manager import (
    load_whatsapp_config, save_whatsapp_config, update_whatsapp_config,
    get_auto_reply_enabled, set_auto_reply_enabled,
    resolve_contact_alias, add_contact_alias, remove_contact_alias,
    is_contact_allowed, add_allow_contact, add_block_contact,
    add_keyword_pattern, remove_keyword_pattern, match_keyword_pattern,
    check_rate_limit, record_rate_usage,
    log_whatsapp_event, get_whatsapp_history, get_recent_contacts,
    BROWSER_PROFILE_DIR,
)
from memory.memory_manager import load_memory, format_memory_for_prompt


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


_BAILEYS_DIR = _base_dir() / "services" / "whatsapp-baileys"
_DEFAULT_PORT = 6482


# ── HTTP utilities ────────────────────────────────────────────────────────────

def _http_get(url, token=None, timeout=30):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    if isinstance(_REQUESTS_AVAILABLE, bool) and _REQUESTS_AVAILABLE:
        try:
            r = requests.get(url, headers=headers, timeout=timeout)
            try:
                data = r.json() if r.content else {}
            except Exception:
                data = {}
            return r.status_code, data
        except Exception as e:
            return 0, {"error": str(e)}
    else:
        import urllib.request, urllib.error
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
                code = resp.getcode()
                data = {}
                if body:
                    try:
                        data = json.loads(body.decode("utf-8"))
                    except Exception:
                        data = {}
                return code, data
        except urllib.error.HTTPError as e:
            return e.code, {"error": str(e)}
        except Exception as e:
            return 0, {"error": str(e)}


def _http_post(url, token=None, data=None, files=None, timeout=60):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    if isinstance(_REQUESTS_AVAILABLE, bool) and _REQUESTS_AVAILABLE:
        try:
            if files is None:
                headers["Content-Type"] = "application/json"
                r = requests.post(url, headers=headers, json=data, timeout=timeout)
            else:
                import mimetypes
                normalized_files = {}
                for k, tup in (files or {}).items():
                    fname, fpath_or_bytes, mime = tup
                    if isinstance(fpath_or_bytes, (bytes, bytearray)):
                        content = bytes(fpath_or_bytes)
                    else:
                        with open(fpath_or_bytes, "rb") as f:
                            content = f.read()
                        fname = fname or Path(fpath_or_bytes).name
                    mime = mime or mimetypes.guess_type(fname)[0] or "application/octet-stream"
                    normalized_files[k] = (fname, content, mime)
                r = requests.post(url, headers=headers, data=data, files=normalized_files, timeout=timeout)
            try:
                resp_data = r.json() if r.content else {}
            except Exception:
                resp_data = {}
            return r.status_code, resp_data
        except Exception as e:
            return 0, {"error": str(e)}
    else:
        import urllib.request, urllib.error
        import mimetypes
        if files is None:
            body = json.dumps(data or {}).encode("utf-8")
            headers["Content-Type"] = "application/json"
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    resp_body = resp.read()
                    code = resp.getcode()
                    try:
                        resp_data = json.loads(resp_body.decode("utf-8"))
                    except Exception:
                        resp_data = {}
                    return code, resp_data
            except urllib.error.HTTPError as e:
                return e.code, {"error": str(e)}
            except Exception as e:
                return 0, {"error": str(e)}
        else:
            boundary = "----SKFormBoundary" + str(int(time.time() * 1000))
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
            lines = []
            for k, v in (data or {}).items():
                lines.append(f"--{boundary}\r\n".encode("utf-8"))
                lines.append(f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode("utf-8"))
                lines.append(str(v).encode("utf-8"))
                lines.append(b"\r\n")
            for k, tup in (files or {}).items():
                fname, fpath_or_bytes, mime = tup
                if isinstance(fpath_or_bytes, (bytes, bytearray)):
                    content = bytes(fpath_or_bytes)
                else:
                    with open(fpath_or_bytes, "rb") as f:
                        content = f.read()
                    fname = fname or Path(fpath_or_bytes).name
                mime = mime or mimetypes.guess_type(fname)[0] or "application/octet-stream"
                lines.append(f"--{boundary}\r\n".encode("utf-8"))
                lines.append(f'Content-Disposition: form-data; name="{k}"; filename="{fname}"\r\n'.encode("utf-8"))
                lines.append(f"Content-Type: {mime}\r\n\r\n".encode("utf-8"))
                lines.append(content)
                lines.append(b"\r\n")
            lines.append(f"--{boundary}--\r\n".encode("utf-8"))
            body = b"".join(lines)
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    rb = resp.read()
                    try:
                        resp_data = json.loads(rb.decode("utf-8"))
                    except Exception:
                        resp_data = {}
                    return resp.getcode(), resp_data
            except urllib.error.HTTPError as e:
                return e.code, {"error": str(e)}
            except Exception as e:
                return 0, {"error": str(e)}


# ── Main manager class ────────────────────────────────────────────────────────

class WhatsAppManager:
    """
    Central WhatsApp automation engine.

    Communicates with the local Baileys Node.js gateway over HTTP.
    The gateway handles all WhatsApp protocol work; this class provides
    a clean Python API for the rest of SK.
    """

    def __init__(
        self,
        logger: Optional[Callable[[str], None]] = None,
        speak_fn: Optional[Callable[[str], None]] = None,
        llm_generate_fn: Optional[Callable[[str], str]] = None,
        auto_start_gateway: bool = True,
    ):
        self._logger = logger or (lambda m: print(f"[WhatsApp] {m}"))
        self._speak = speak_fn or (lambda m: None)
        self._llm_generate = llm_generate_fn
        self._lock = threading.Lock()
        self._port = int(load_whatsapp_config().get("baileys_port", _DEFAULT_PORT))
        self._token: Optional[str] = None
        self._gateway_proc: Optional[subprocess.Popen] = None
        self._auto_start_gateway = auto_start_gateway
        self._logged_in: Optional[bool] = None
        self._qr_data_url: Optional[str] = None
        self._last_status: dict = {}
        self._poller_thread: Optional[threading.Thread] = None
        self._poller_stop = threading.Event()
        self._processed_message_ids: dict = {}
        self._auto_reply_engine = AutoReplyEngine(
            logger=self._logger,
            send_message_fn=self._send_text_internal,
            llm_generate_fn=self._llm_generate,
        )
        self._events_thread: Optional[threading.Thread] = None
        self._events_stop = threading.Event()

        if self._auto_start_gateway:
            try:
                self._ensure_gateway_running()
            except Exception as e:
                self._logger(f"Gateway auto-start skipped: {e}")

    # ── Gateway management ────────────────────────────────────────────────────

    @property
    def _base(self) -> str:
        return f"http://127.0.0.1:{self._port}"

    def _ensure_gateway_running(self) -> bool:
        with self._lock:
            if self._gateway_proc and self._gateway_proc.poll() is None:
                return True
            # Reuse an already-running instance
            code, data = _http_get(f"http://127.0.0.1:{self._port}/token", timeout=2)
            if code == 200 and isinstance(data, dict) and "token" in data:
                self._token = data["token"]
                self._port = int(data.get("port", self._port))
                self._logger("Baileys gateway already running (reused).")
                return True
            if not (_BAILEYS_DIR / "node_modules").exists():
                self._logger(
                    "Baileys deps not installed. "
                    f"Run: cd {_BAILEYS_DIR} && npm install"
                )
                return False
            node = shutil.which("node")
            if not node:
                self._logger("Node.js not in PATH. Cannot start Baileys gateway.")
                return False
            env = dict(**__import__("os").environ)
            env.setdefault("SK_WA_PORT", str(self._port))
            try:
                log_file = (_base_dir() / "memory" / "baileys_gateway.log").open("ab")
            except Exception:
                log_file = subprocess.DEVNULL
            self._gateway_proc = subprocess.Popen(
                [node, str((_BAILEYS_DIR / "gateway.js").resolve())],
                cwd=str(_BAILEYS_DIR.resolve()),
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                if sys.platform == "win32" else 0,
            )
            # Wait up to ~8 s for token endpoint
            for _ in range(16):
                time.sleep(0.5)
                if self._gateway_proc.poll() is not None:
                    self._logger(
                        "Baileys gateway exited immediately. "
                        "See memory/baileys_gateway.log"
                    )
                    self._gateway_proc = None
                    return False
                c2, d2 = _http_get(f"http://127.0.0.1:{self._port}/token", timeout=2)
                if c2 == 200 and isinstance(d2, dict) and "token" in d2:
                    self._token = d2["token"]
                    self._port = int(d2.get("port", self._port))
                    self._logger("Baileys gateway started (headless — no browser tab).")
                    return True
            return False

    def _gateway_status(self) -> dict:
        try:
            code, data = _http_get(
                f"{self._base}/status", token=self._token, timeout=15
            )
        except Exception:
            return {}
        if code != 200 or not isinstance(data, dict):
            return {}
        self._logged_in = bool(data.get("logged_in"))
        self._qr_data_url = data.get("qr") or None
        self._last_status = data
        return data

    def _gateway_alive(self) -> bool:
        if self._gateway_proc and self._gateway_proc.poll() is None:
            return True
        code, _ = _http_get(f"http://127.0.0.1:{self._port}/health", timeout=2)
        return code == 200

    # ── Status / lifecycle ────────────────────────────────────────────────────

    @property
    def status(self) -> dict:
        s = self._last_status if self._last_status else {}
        return {
            "baileys_available": bool(self._token and self._gateway_alive()),
            "browser_connected": bool(s.get("connected")),
            "logged_in": bool(self._logged_in or s.get("logged_in")),
            "auto_reply_enabled": get_auto_reply_enabled(),
            "poller_running": bool(
                self._poller_thread and self._poller_thread.is_alive()
            ),
            "events_running": bool(
                self._events_thread and self._events_thread.is_alive()
            ),
            "gateway_port": self._port,
            "qr_pending": bool(s.get("qrText") or self._qr_data_url),
        }

    def check_login(self) -> str:
        if not self._ensure_gateway_running():
            return (
                "Sir, Baileys WhatsApp gateway is not running. "
                f"Run: cd {_BAILEYS_DIR} && npm install && npm start"
            )
        status = self._gateway_status()
        if status.get("qrText"):
            return (
                "Sir, WhatsApp is not paired. Scan the QR code: "
                + (status.get("qrText")[:80] + "…")
            )
        if status.get("logged_in"):
            return "WhatsApp is connected and ready, sir (Baileys headless)."
        reason = status.get("reason") or "not ready yet"
        return f"Sir, WhatsApp is not ready: {reason}. Wait or re-pair."

    def close(self):
        self.stop_poller()
        self._events_stop.set()
        if self._gateway_proc:
            try:
                self._gateway_proc.terminate()
                try:
                    self._gateway_proc.wait(timeout=3)
                except Exception:
                    try:
                        self._gateway_proc.kill()
                    except Exception:
                        pass
            except Exception:
                pass
        self._gateway_proc = None

    # ── Send text ─────────────────────────────────────────────────────────────

    def send_message(self, receiver: str, message_text: str) -> str:
        if not receiver or not message_text:
            return "Please specify both receiver and message."
        resolved = resolve_contact_alias(receiver)
        result = self._send_text_internal(resolved, message_text)
        status = (
            "sent"
            if "sent" in result.lower()
            or ("ok" in result.lower() and self._logged_in)
            else "failed"
        )
        log_whatsapp_event("out", receiver, message_text, status)
        return result

    def _send_text_internal(self, receiver: str, message_text: str) -> str:
        if not self._ensure_gateway_running():
            return (
                "Sir, Baileys gateway not running. "
                "Run `npm install` in services/whatsapp-baileys then start the gateway."
            )
        resolved = resolve_contact_alias(receiver)
        try:
            code, data = _http_post(
                f"{self._base}/send-text",
                token=self._token,
                data={"to": resolved, "text": message_text},
                timeout=45,
            )
        except Exception as e:
            return f"Sir, send failed: {e}"
        if code == 200 and isinstance(data, dict) and data.get("ok"):
            return f"Message sent to {receiver} via WhatsApp."
        err = (data or {}).get("error") or f"HTTP {code}"
        return f"Sir, could not send to {receiver}: {err}"

    # ── Send file ─────────────────────────────────────────────────────────────

    def send_file(self, receiver: str, file_path: str) -> str:
        if not receiver or not file_path:
            return "Please specify both receiver and file path."
        p = Path(file_path)
        if not p.exists():
            return f"Sir, file not found: {file_path}"
        if not self._ensure_gateway_running():
            return "Sir, Baileys gateway not running. Cannot send file."
        resolved = resolve_contact_alias(receiver)
        import mimetypes
        mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        try:
            files = {"file": (p.name, str(p.resolve()), mime)}
            code, data = _http_post(
                f"{self._base}/send-file",
                token=self._token,
                data={"to": resolved},
                files=files,
                timeout=120,
            )
        except Exception as e:
            return f"Sir, file send failed: {e}"
        if code == 200 and isinstance(data, dict) and data.get("ok"):
            log_whatsapp_event("out", receiver, f"[FILE] {p.name}", "sent")
            return f"File '{p.name}' sent to {receiver} via WhatsApp."
        err = (data or {}).get("error") or f"HTTP {code}"
        return f"Sir, file send to {receiver} failed: {err}"

    # ── Read messages ─────────────────────────────────────────────────────────

    def read_messages(self, contact: str, limit: int = 10) -> str:
        if not contact:
            return "Please specify whose messages to read."
        limit = max(1, min(50, int(limit)))
        if not self._ensure_gateway_running():
            history = get_whatsapp_history(contact, limit=limit)
            if history:
                lines = []
                for h in reversed(history):
                    lines.append(
                        f"[{h.get('ts','')}] "
                        f"{h.get('direction','').upper()}: "
                        f"{h.get('message','')}"
                    )
                return f"Recent {contact} messages (from log):\n" + "\n".join(lines)
            return "Sir, Baileys not running and no cached history."
        resolved = resolve_contact_alias(contact)
        jid = self._find_jid_for_name(resolved) or resolved
        try:
            import urllib.parse
            code, data = _http_get(
                f"{self._base}/messages"
                f"?jid={urllib.parse.quote(jid)}&limit={limit}",
                token=self._token,
                timeout=20,
            )
        except Exception as e:
            return f"Sir, reading messages failed: {e}"
        if code != 200:
            return f"Sir, read messages failed: HTTP {code}"
        msgs = (data or {}).get("messages") or []
        if not msgs:
            return f"No recent messages with {contact}."
        lines = []
        for m in msgs:
            sender = "you" if m.get("fromMe") else contact
            text = m.get("text") or ("[" + (m.get("type") or "msg") + "]")
            msg_id = m.get("id", "")
            ts = m.get("time", "")
            ts_str = (
                datetime.fromtimestamp(ts / 1000).strftime("%H:%M")
                if isinstance(ts, (int, float)) and ts > 0
                else ""
            )
            id_hint = f" [id:{msg_id[:12]}]" if msg_id else ""
            lines.append(f"[{ts_str}] {sender}: {text}{id_hint}")
            if not m.get("fromMe"):
                log_whatsapp_event("in", contact, text, "read")
        return (
            f"Last {len(lines)} messages with {contact}:\n"
            + "\n".join(lines)
        )

    # ── List chats ────────────────────────────────────────────────────────────

    def list_chats(self) -> str:
        if not self._ensure_gateway_running():
            recent = get_recent_contacts(limit=10)
            if recent:
                return (
                    "Recent WhatsApp contacts (from history):\n"
                    + "\n".join(recent)
                )
            return "Sir, Baileys gateway not running and no history available."
        status = self._gateway_status()
        chats = status.get("chats") or []
        if not chats:
            try:
                code, data = _http_get(
                    f"{self._base}/chats", token=self._token, timeout=20
                )
                if code == 200:
                    chats = (data or {}).get("chats") or []
            except Exception:
                pass
        if not chats:
            return "No chats found."
        lines = []
        for c in chats[:25]:
            name = c.get("name") or c.get("jid") or "?"
            unread = int(c.get("unread") or 0)
            suffix = f" ({unread} unread)" if unread else ""
            lines.append(f"{name}{suffix}")
        return "Recent WhatsApp chats:\n" + "\n".join(lines)

    # ── Delete message ────────────────────────────────────────────────────────

    def delete_message(self, contact: str, message_id: str, for_everyone: bool = True) -> str:
        """
        Revoke (delete) a message you sent.
        for_everyone=True  → deletes for all parties (like WhatsApp "delete for everyone")
        for_everyone=False → deletes only from your own view
        """
        if not contact or not message_id:
            return "Sir, I need both the contact name and the message ID to delete."
        if not self._ensure_gateway_running():
            return "Sir, Baileys gateway not running. Cannot delete message."
        resolved = resolve_contact_alias(contact)
        jid = self._find_jid_for_name(resolved) or resolved
        try:
            code, data = _http_post(
                f"{self._base}/delete-message",
                token=self._token,
                data={
                    "jid": jid,
                    "msgId": message_id,
                    "forEveryone": bool(for_everyone),
                },
                timeout=30,
            )
        except Exception as e:
            return f"Sir, delete message failed: {e}"
        if code == 200 and isinstance(data, dict) and data.get("ok"):
            return f"Message deleted {'for everyone' if for_everyone else 'for you'} in chat with {contact}."
        err = (data or {}).get("error") or f"HTTP {code}"
        return f"Sir, could not delete message: {err}"

    # ── Edit message (delete + resend) ────────────────────────────────────────

    def edit_message(self, contact: str, message_id: str, new_text: str) -> str:
        """
        Edit a sent message: revoke the original then send the replacement.
        Returns a result string.
        """
        if not contact or not message_id or not new_text:
            return "Sir, I need the contact, original message ID, and the new text."
        # Step 1: delete original for everyone
        del_result = self.delete_message(contact, message_id, for_everyone=True)
        if "failed" in del_result.lower() or "could not" in del_result.lower():
            return f"Sir, edit failed — could not revoke original: {del_result}"
        # Step 2: send replacement
        send_result = self.send_message(contact, new_text)
        if "sent" in send_result.lower():
            return (
                f"Message edited in chat with {contact}: "
                f"original deleted and replacement sent."
            )
        return f"Sir, original deleted but re-send failed: {send_result}"

    # ── Mark as read ──────────────────────────────────────────────────────────

    def mark_read(self, contact: str) -> str:
        """Mark all messages in a chat as read."""
        if not contact:
            return "Sir, please specify the contact to mark as read."
        if not self._ensure_gateway_running():
            return "Sir, Baileys gateway not running."
        resolved = resolve_contact_alias(contact)
        jid = self._find_jid_for_name(resolved) or resolved
        try:
            code, data = _http_post(
                f"{self._base}/mark-read",
                token=self._token,
                data={"jid": jid},
                timeout=20,
            )
        except Exception as e:
            return f"Sir, mark-read failed: {e}"
        if code == 200 and isinstance(data, dict) and data.get("ok"):
            return f"Chat with {contact} marked as read."
        err = (data or {}).get("error") or f"HTTP {code}"
        return f"Sir, could not mark {contact} as read: {err}"

    # ── Forward message ───────────────────────────────────────────────────────

    def forward_message(self, from_contact: str, message_id: str, to_contact: str) -> str:
        """Forward a message from one chat to another contact."""
        if not from_contact or not message_id or not to_contact:
            return "Sir, I need source contact, message ID, and destination contact."
        if not self._ensure_gateway_running():
            return "Sir, Baileys gateway not running."
        from_resolved = resolve_contact_alias(from_contact)
        to_resolved = resolve_contact_alias(to_contact)
        from_jid = self._find_jid_for_name(from_resolved) or from_resolved
        to_jid = self._find_jid_for_name(to_resolved) or to_resolved
        try:
            code, data = _http_post(
                f"{self._base}/forward",
                token=self._token,
                data={
                    "fromJid": from_jid,
                    "msgId": message_id,
                    "toJid": to_jid,
                },
                timeout=30,
            )
        except Exception as e:
            return f"Sir, forward failed: {e}"
        if code == 200 and isinstance(data, dict) and data.get("ok"):
            return f"Message forwarded to {to_contact}."
        err = (data or {}).get("error") or f"HTTP {code}"
        return f"Sir, could not forward message: {err}"

    # ── React to message ──────────────────────────────────────────────────────

    def react_message(self, contact: str, message_id: str, emoji: str) -> str:
        """Send an emoji reaction to a specific message."""
        if not contact or not message_id or not emoji:
            return "Sir, I need the contact, message ID, and an emoji to react with."
        if not self._ensure_gateway_running():
            return "Sir, Baileys gateway not running."
        resolved = resolve_contact_alias(contact)
        jid = self._find_jid_for_name(resolved) or resolved
        try:
            code, data = _http_post(
                f"{self._base}/react",
                token=self._token,
                data={
                    "jid": jid,
                    "msgId": message_id,
                    "emoji": emoji.strip(),
                },
                timeout=20,
            )
        except Exception as e:
            return f"Sir, react failed: {e}"
        if code == 200 and isinstance(data, dict) and data.get("ok"):
            return f"Reacted with {emoji} to message in chat with {contact}."
        err = (data or {}).get("error") or f"HTTP {code}"
        return f"Sir, could not react to message: {err}"

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _find_jid_for_name(self, name: str) -> Optional[str]:
        try:
            status = (
                self._last_status if self._last_status else self._gateway_status()
            )
            chats = status.get("chats") or []
            if not chats:
                code, data = _http_get(
                    f"{self._base}/chats", token=self._token, timeout=15
                )
                if code == 200:
                    chats = (data or {}).get("chats") or []
            target = str(name).strip().lower()
            for c in chats:
                if str(c.get("name") or "").lower() == target:
                    return c.get("jid") or c.get("id")
            for c in chats:
                if target in str(c.get("name") or "").lower():
                    return c.get("jid") or c.get("id")
        except Exception:
            return None
        return None

    # ── Poller / SSE event stream ─────────────────────────────────────────────

    def start_poller(self, on_incoming: Optional[Callable[[str, str], None]] = None):
        """
        Start two background threads:
        1. SSE event stream — real-time incoming message notifications
        2. Status poll loop — refreshes gateway health every N seconds
        """
        cfg = load_whatsapp_config()
        if not cfg.get("poller_enabled", True):
            self._logger("Poller disabled in config.")
            return
        self._ensure_gateway_running()
        if (
            (self._poller_thread and self._poller_thread.is_alive())
            or (self._events_thread and self._events_thread.is_alive())
        ):
            return

        self._poller_stop.clear()
        self._events_stop.clear()

        # ── SSE thread ────────────────────────────────────────────────────────
        def _event_stream_loop():
            import urllib.request as _urllib_req

            backoff = 2
            while not self._events_stop.is_set():
                if not self._token:
                    self._ensure_gateway_running()
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 30)
                    continue
                try:
                    url = f"{self._base}/events"
                    req = _urllib_req.Request(
                        url,
                        headers={"Authorization": f"Bearer {self._token}"},
                    )
                    with _urllib_req.urlopen(req, timeout=300) as resp:
                        buf = b""
                        backoff = 2
                        while not self._events_stop.is_set():
                            chunk = resp.read(1024)
                            if not chunk:
                                break
                            buf += chunk
                            while b"\n\n" in buf:
                                msg, buf = buf.split(b"\n\n", 1)
                                for line in msg.split(b"\n"):
                                    line = line.strip()
                                    if not line:
                                        continue
                                    if line.startswith(b"data:"):
                                        line = line[5:].strip()
                                    if line.startswith(b":"):
                                        continue
                                    try:
                                        ev = json.loads(line.decode("utf-8"))
                                        self._handle_incoming_event(ev, on_incoming)
                                    except Exception:
                                        continue
                except Exception as e:
                    self._logger(f"Baileys SSE reconnect in {backoff}s: {e}")
                    for _ in range(int(backoff * 4)):
                        if self._events_stop.is_set():
                            break
                        time.sleep(0.25)
                    backoff = min(backoff * 2, 30)

        self._events_thread = threading.Thread(
            target=_event_stream_loop, daemon=True, name="WA_Baileys_SSE"
        )
        self._events_thread.start()

        # ── Status poll thread ────────────────────────────────────────────────
        def _status_loop():
            interval = max(
                10,
                int(
                    load_whatsapp_config().get("poll_interval_seconds", 20) or 20
                ),
            )
            while not self._poller_stop.is_set():
                try:
                    self._gateway_status()
                except Exception as e:
                    self._logger(f"Poll status error: {e}")
                for _ in range(interval * 4):
                    if self._poller_stop.is_set():
                        break
                    time.sleep(0.25)

        self._poller_thread = threading.Thread(
            target=_status_loop, daemon=True, name="WA_Baileys_Status"
        )
        self._poller_thread.start()
        self._logger("Baileys SSE + status poller started.")

    def stop_poller(self):
        self._poller_stop.set()
        self._events_stop.set()
        for t in (self._poller_thread, self._events_thread):
            if t:
                try:
                    t.join(timeout=2.0)
                except Exception:
                    pass
        self._poller_thread = None
        self._events_thread = None

    def _handle_incoming_event(
        self,
        ev: dict,
        on_incoming: Optional[Callable[[str, str], None]],
    ):
        if not isinstance(ev, dict):
            return
        t = ev.get("type")
        if t == "ready":
            self._logged_in = True
            self._qr_data_url = None
            self._logger("Baileys paired & ready.")
            return
        if t == "disconnect":
            self._logged_in = False
            return
        if t == "qr":
            self._qr_data_url = ev.get("qr")
            self._logger("QR code received (pairing pending).")
            return
        if t != "message":
            return

        # Use display name from event; fall back to stripping JID suffix
        raw_from = ev.get("from") or ev.get("jid") or "Unknown"
        jid       = ev.get("jid") or raw_from
        # Display name for speaking / logging (strip @s.whatsapp.net etc.)
        name = raw_from if "@" not in raw_from else jid.split("@")[0]
        # Prefer the gateway's resolved display name
        if ev.get("from") and "@" not in str(ev.get("from")):
            name = ev["from"]

        text = ev.get("text") or ""
        if not text:
            return

        # ── Filter non-personal / business JIDs ──────────────────────────
        # These cannot receive messages — sending to them causes
        # "Waiting for this message" errors on WhatsApp.
        if not self._is_personal_jid(jid):
            self._logger(f"Skipped auto-reply to business/non-personal JID: {jid}")
            log_whatsapp_event("in", name, text, "skipped-business")
            return

        msg_id = str(ev.get("id") or (jid + "|" + text[:80]))
        seen = self._processed_message_ids.setdefault(jid, set())
        if msg_id in seen:
            return
        seen.add(msg_id)
        # Keep the dedup set bounded
        if len(seen) > 2000:
            self._processed_message_ids[jid] = set(list(seen)[-500:])

        log_whatsapp_event("in", name, text, "new")

        notify = f"Sir, new WhatsApp message from {name}"
        if text:
            notify += f": {text[:80]}"
        self._speak(notify)
        self._logger(notify)

        if on_incoming:
            try:
                on_incoming(name, text)
            except Exception as e:
                self._logger(f"on_incoming handler error: {e}")

        # Pass JID as contact so auto-reply can send back to the right JID
        self._auto_reply_engine.process_incoming(jid, text, display_name=name)

    @staticmethod
    def _is_personal_jid(jid: str) -> bool:
        """
        Returns True only for genuine personal WhatsApp numbers safe to reply to.
        """
        if not jid:
            return False
        jid = str(jid).strip()
        # Must end with a personal suffix
        if not (jid.endswith("@s.whatsapp.net") or jid.endswith("@c.us")):
            return False
        bare   = jid.split("@")[0]
        digits = re.sub(r"\D", "", bare)
        # Short-code / alphanumeric sender (business SMS)
        if len(digits) <= 6:
            return False
        # Aggregator / gateway numbers — too long (real mobiles are 10-15 digits)
        if len(digits) > 15:
            return False
        # 15-digit numbers are almost always business aggregator IDs (e.g. Jio 770433…)
        if len(digits) == 15:
            return False
        # Toll-free & promo number prefixes (India)
        promo_prefixes = (
            "1600", "1800", "1860", "1400", "1406", "140",
            "700077", "91700077", "917000770007",
            # Jio service numbers
            "7700", "7000770007", "917000",
        )
        if any(digits.startswith(p) for p in promo_prefixes):
            return False
        return True


# ── Auto-reply engine ─────────────────────────────────────────────────────────

class AutoReplyEngine:
    """
    Processes incoming messages and optionally sends an automatic reply.

    Priority:
    1. Check auto-reply is enabled
    2. Check contact is not blocked / is allowed
    3. Check rate limit
    4. Match keyword pattern → deterministic reply
    5. Generate LLM reply (if LLM function available)
    """

    def __init__(
        self,
        logger: Callable[[str], None],
        send_message_fn: Callable[[str, str], str],
        llm_generate_fn: Optional[Callable[[str], str]] = None,
    ):
        self._logger = logger
        self._send = send_message_fn
        self._llm_generate = llm_generate_fn

    def process_incoming(self, contact: str, message_text: str, display_name: str = "") -> Optional[str]:
        if not get_auto_reply_enabled():
            return None
        # Use display_name for human-readable logging; contact (JID) for sending
        label = display_name or contact
        if not is_contact_allowed(contact):
            log_whatsapp_event("in", label, message_text, "skipped-blocked")
            self._logger(f"Blocked auto-reply to {label}")
            return None
        if not check_rate_limit(contact):
            log_whatsapp_event("in", label, message_text, "skipped-rate")
            self._logger(f"Rate-limited auto-reply to {label}")
            return None

        # Keyword / pattern match (deterministic, no LLM cost)
        pattern_reply = match_keyword_pattern(message_text)
        if pattern_reply:
            self._logger(f"Keyword pattern matched for {label}")
            self._send(contact, pattern_reply)
            record_rate_usage(contact)
            log_whatsapp_event("out", label, pattern_reply, "auto-replied")
            return pattern_reply

        # LLM-generated reply
        if self._llm_generate:
            try:
                reply = self._generate_llm_reply(label, message_text)
                if reply:
                    self._send(contact, reply)
                    record_rate_usage(contact)
                    log_whatsapp_event("out", label, reply, "auto-replied")
                    return reply
            except Exception as e:
                self._logger(f"LLM reply error: {e}")
        return None

    def _generate_llm_reply(self, contact: str, message_text: str) -> str:
        memory = load_memory()
        mem_block = format_memory_for_prompt(memory)
        history = get_whatsapp_history(contact, limit=8)
        hist_lines = []
        for h in reversed(history):
            d = "Them" if h.get("direction") == "in" else "You"
            hist_lines.append(f"{d}: {h.get('message','')}")
        hist_block = (
            "\n".join(hist_lines) if hist_lines else "(no prior messages)"
        )
        now = datetime.now().strftime("%A, %B %d, %Y — %I:%M %p")
        prompt = f"""[CURRENT DATE & TIME]
{now}

[WHAT YOU KNOW ABOUT SURAJ]
{mem_block}

[YOUR ROLE]
You are SK, Suraj's personal AI assistant. You are replying to a WHATSAPP message
FROM "{contact}" SENT TO SURAJ. Write a reply ON SURAJ'S BEHALF, as if Suraj wrote
it himself. Do NOT reveal you are an AI. Do NOT sign "SK" or "assistant".

[RECENT CONVERSATION WITH {contact}]
{hist_block}

[INCOMING MESSAGE FROM {contact}]
{message_text}

[RULES]
1. Reply in the SAME LANGUAGE as the incoming message.
2. If {contact} is family (Aai = mother, Baba = father, sister, brother, etc.),
   use the appropriate respectful form in Marathi or the language being used.
3. Keep replies CONCISE and natural — 1-3 sentences usually.
4. Never write a long essay unless the message specifically asks for one.
5. If you don't know enough to answer, say "Let me check and get back to you."

Write only the reply text. Nothing else."""
        reply = self._llm_generate(prompt) if self._llm_generate else None
        if not reply:
            return ""
        reply = reply.strip()
        reply = re.sub(r'^["\']|["\']$', "", reply).strip()
        return reply[:1000]


# ── Singleton ─────────────────────────────────────────────────────────────────

_instance: Optional[WhatsAppManager] = None
_instance_lock = threading.Lock()


def get_whatsapp_manager(
    logger=None,
    speak_fn=None,
    llm_generate_fn=None,
) -> WhatsAppManager:
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = WhatsAppManager(
                logger=logger,
                speak_fn=speak_fn,
                llm_generate_fn=llm_generate_fn,
            )
        else:
            if logger is not None:
                _instance._logger = logger
            if speak_fn is not None:
                _instance._speak = speak_fn
            if llm_generate_fn is not None:
                _instance._llm_generate = llm_generate_fn
                _instance._auto_reply_engine._llm_generate = llm_generate_fn
        return _instance


def reset_whatsapp_manager():
    global _instance
    with _instance_lock:
        if _instance is not None:
            try:
                _instance.close()
            except Exception:
                pass
        _instance = None
