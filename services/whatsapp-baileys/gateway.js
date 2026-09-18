'use strict';

/**
 * SK AI Agent — Baileys Headless WhatsApp Gateway  (v2 — full rewrite)
 * No browser tab. Pure Multi-Device WhatsApp Web protocol.
 *
 * Endpoints:
 *   GET  /health
 *   GET  /token                   (localhost only, no auth)
 *   GET  /status
 *   GET  /qr                      PNG image of current QR
 *   GET  /events                  SSE stream
 *   GET  /chats
 *   GET  /messages?jid=&limit=20
 *   POST /send-text               { to, text }
 *   POST /send-file               multipart: to + file
 *   POST /delete-message          { jid, msgId, forEveryone }
 *   POST /mark-read               { jid }
 *   POST /forward                 { fromJid, msgId, toJid }
 *   POST /react                   { jid, msgId, emoji }
 *   POST /logout
 */

const fs      = require('fs');
const path    = require('path');
const crypto  = require('crypto');
const express = require('express');
const multer  = require('multer');
const QRCode  = require('qrcode');
const pino    = require('pino');

const {
    default: makeWASocket,
    DisconnectReason,
    useMultiFileAuthState,
    fetchLatestWaWebVersion,
    isJidBroadcast,
    isJidGroup,
    jidDecode,
    getContentType,
} = require('@whiskeysockets/baileys');
const { Boom } = require('@hapi/boom');

// ── Paths ─────────────────────────────────────────────────────────────────────
const BASE_DIR   = path.resolve(__dirname, '..', '..');
const MEMORY_DIR = path.join(BASE_DIR, 'memory');
const AUTH_DIR   = path.join(MEMORY_DIR, 'baileys_auth');
const UPLOAD_DIR = path.join(MEMORY_DIR, 'baileys_uploads');
const EVENTS_LOG = path.join(MEMORY_DIR, 'baileys_events.jsonl');

for (const d of [MEMORY_DIR, AUTH_DIR, UPLOAD_DIR]) {
    fs.mkdirSync(d, { recursive: true });
}

// ── Logger ────────────────────────────────────────────────────────────────────
const logger = pino({ level: process.env.SK_LOG || 'silent' });

// ── HTTP ──────────────────────────────────────────────────────────────────────
const PORT  = parseInt(process.env.SK_WA_PORT  || '6482', 10);
const TOKEN = process.env.SK_WA_TOKEN || 'sk-wa-local-' + crypto.randomBytes(6).toString('hex');

const app = express();
app.use(express.json({ limit: '50mb' }));
app.use(express.urlencoded({ extended: true, limit: '50mb' }));

const upload = multer({
    storage: multer.diskStorage({
        destination: (_req, _file, cb) => cb(null, UPLOAD_DIR),
        filename:    (_req, file,  cb) => {
            const safe = (file.originalname || 'upload').replace(/[^a-zA-Z0-9._-]/g, '_');
            cb(null, Date.now() + '_' + safe);
        },
    }),
    limits: { fileSize: 100 * 1024 * 1024 },
});

function auth(req, res, next) {
    const hdr = req.headers.authorization || '';
    if (hdr.replace(/^Bearer\s+/i, '').trim() !== TOKEN) {
        return res.status(401).json({ error: 'Unauthorized' });
    }
    next();
}

// ── Lightweight in-memory store (replaces removed makeInMemoryStore) ──────────
// Stores: chats map (jid → chat), contacts map (jid → contact),
//         messages map (jid → array of last 200 messages)
const store = {
    chats:    {},   // jid → { id, name, unreadCount, conversationTimestamp }
    contacts: {},   // jid → { id, name, notify }
    messages: {},   // jid → Message[]

    /** Bind to a Baileys socket event emitter */
    bind(ev) {
        ev.on('chats.set',    ({ chats })    => { for (const c of chats || [])    store._upsertChat(c);    });
        ev.on('chats.upsert', (chats)        => { for (const c of chats || [])    store._upsertChat(c);    });
        ev.on('chats.update', (updates)      => { for (const u of updates || [])  store._upsertChat(u);    });
        ev.on('contacts.set',    ({ contacts }) => { for (const c of contacts || []) store._upsertContact(c); });
        ev.on('contacts.upsert', (contacts)    => { for (const c of contacts || []) store._upsertContact(c); });
        ev.on('contacts.update', (updates)     => { for (const u of updates || []) store._upsertContact(u);  });
        ev.on('messages.upsert', ({ messages, type }) => {
            if (type !== 'notify' && type !== 'append') return;
            for (const m of messages || []) store._upsertMessage(m);
        });
        ev.on('messages.update', (updates) => {
            for (const u of updates || []) {
                const jid = u.key && u.key.remoteJid;
                if (!jid) continue;
                const arr = store.messages[jid] || [];
                const idx = arr.findIndex(m => m.key && m.key.id === u.key.id);
                if (idx >= 0) Object.assign(arr[idx], u.update || {});
            }
        });
    },

    _upsertChat(c) {
        if (!c || !c.id) return;
        store.chats[c.id] = Object.assign(store.chats[c.id] || {}, c);
    },
    _upsertContact(c) {
        if (!c || !c.id) return;
        store.contacts[c.id] = Object.assign(store.contacts[c.id] || {}, c);
    },
    _upsertMessage(m) {
        if (!m || !m.key || !m.key.remoteJid) return;
        const jid = m.key.remoteJid;
        if (!store.messages[jid]) store.messages[jid] = [];
        const arr = store.messages[jid];
        const idx = arr.findIndex(x => x.key && x.key.id === m.key.id);
        if (idx >= 0) arr[idx] = m;
        else {
            arr.push(m);
            if (arr.length > 200) arr.splice(0, arr.length - 200);
        }
    },

    readFromFile(fp) {
        const raw = JSON.parse(fs.readFileSync(fp, 'utf8'));
        store.chats    = raw.chats    || {};
        store.contacts = raw.contacts || {};
        store.messages = raw.messages || {};
    },
    writeToFile(fp) {
        fs.writeFileSync(fp, JSON.stringify({
            chats:    store.chats,
            contacts: store.contacts,
            messages: store.messages,
        }), 'utf8');
    },
};

// Persist store every 30 s
const STORE_FILE = path.join(MEMORY_DIR, 'baileys_store.json');
try { store.readFromFile(STORE_FILE); } catch (_) { /* first run, ignore */ }
setInterval(() => { try { store.writeToFile(STORE_FILE); } catch (_) {} }, 30_000);

// ── Gateway state ─────────────────────────────────────────────────────────────
let sock            = null;
let latestQR        = null;
let connectionOpen  = false;
let pairingDone     = false;
let lastDisconnect  = null;
let reconnecting    = false;

const eventSubscribers = new Set();
const eventBuffer      = [];          // last 100 events for late SSE joiners

function emitEvent(ev) {
    const row = { ts: Date.now(), ...ev };
    try { fs.appendFileSync(EVENTS_LOG, JSON.stringify(row) + '\n'); } catch (_) {}
    eventBuffer.push(row);
    if (eventBuffer.length > 100) eventBuffer.shift();
    for (const res of eventSubscribers) {
        try { res.write(`data: ${JSON.stringify(row)}\n\n`); } catch (_) {}
    }
}

// ── JID helpers ───────────────────────────────────────────────────────────────
function safeIsGroup(jid)     { try { return !!jid && isJidGroup(jid);     } catch (_) { return false; } }
function safeIsBroadcast(jid) { try { return !!jid && isJidBroadcast(jid); } catch (_) { return false; } }

function jidToName(jid, msg) {
    if (!jid) return 'Unknown';
    // 1. pushName from the message itself (most reliable)
    try { if (msg && msg.pushName) return msg.pushName; } catch (_) {}
    // 2. Store contacts cache
    try {
        if (store.contacts && store.contacts[jid]) {
            const c = store.contacts[jid];
            if (c.name)   return c.name;
            if (c.notify) return c.notify;
        }
    } catch (_) {}
    // 3. jidDecode — returns null for groups/broadcast; guard carefully
    try {
        const d = jidDecode(jid);
        if (d && d.user) return d.user;
    } catch (_) {}
    // 4. Raw strip
    try { return jid.split('@')[0] || jid; } catch (_) {}
    return jid;
}

function normalizeJid(target) {
    if (!target) return '';
    target = String(target).trim();

    // Already a valid WhatsApp JID — return as-is
    if (/@(s\.whatsapp\.net|g\.us|c\.us|broadcast)$/.test(target)) return target;

    // Strip common phone formatting: +, spaces, dashes, parentheses
    const stripped = target.replace(/[\s\-().+]/g, '');
    const digits   = stripped.replace(/\D/g, '');

    // Pure number — build JID
    if (digits.length >= 7) {
        // WhatsApp uses full international format without leading zeros
        // e.g. 07304... (India local) → 917304...
        // e.g. 7304... (10-digit India) → 917304...
        // e.g. 917304... (already has country code) → 917304...
        let normalized = digits;

        // 10-digit Indian mobile (starts 6-9, no country code)
        if (digits.length === 10 && /^[6-9]/.test(digits)) {
            normalized = '91' + digits;
        }
        // 11-digit starting with 0 (local format like 07304...)
        else if (digits.length === 11 && digits.startsWith('0')) {
            normalized = '91' + digits.slice(1);
        }

        return normalized + '@s.whatsapp.net';
    }

    // Name / alias — look up in store (chats first, then contacts)
    const lc = target.toLowerCase();

    const chatList = Object.values(store.chats);
    // Exact name match
    for (const c of chatList) {
        if ((c.name || '').toLowerCase() === lc) return c.id;
    }
    // Partial match
    for (const c of chatList) {
        if ((c.name || '').toLowerCase().includes(lc)) return c.id;
    }

    const contactList = Object.values(store.contacts);
    for (const c of contactList) {
        const cname = (c.name || c.notify || '').toLowerCase();
        if (cname === lc) return c.id;
    }
    for (const c of contactList) {
        const cname = (c.name || c.notify || '').toLowerCase();
        if (cname && cname.includes(lc)) return c.id;
    }

    // Nothing matched — return raw; sendText will surface a clear error
    return target;
}

// ── Message text extractor ────────────────────────────────────────────────────
function msgText(msg) {
    if (!msg || !msg.message) return '';
    try {
        const m = msg.message;
        if (m.conversation)           return m.conversation;
        if (m.extendedTextMessage)    return m.extendedTextMessage.text || '';
        if (m.imageMessage)           return m.imageMessage.caption     || '[image]';
        if (m.videoMessage)           return m.videoMessage.caption     || '[video]';
        if (m.documentMessage)        return m.documentMessage.fileName || '[document]';
        if (m.audioMessage)           return '[audio]';
        if (m.stickerMessage)         return '[sticker]';
        if (m.reactionMessage)        return '[reaction]';
        const type = getContentType(m);
        if (type && m[type]) {
            const inner = m[type];
            if (typeof inner === 'string')  return inner;
            if (inner.text)                 return inner.text;
            if (inner.caption)              return `[${type.replace('Message','')}] ${inner.caption}`;
            return `[${type.replace('Message','')}]`;
        }
    } catch (_) {}
    return '';
}

// ── MIME guesser ──────────────────────────────────────────────────────────────
function guessMime(ext, buf) {
    const h = (buf || Buffer.alloc(0)).slice(0, 12).toString('hex');
    if (h.startsWith('ffd8ff'))   return 'image/jpeg';
    if (h.startsWith('89504e47')) return 'image/png';
    if (h.startsWith('47494638')) return 'image/gif';
    if (h.startsWith('25504446')) return 'application/pdf';
    if (h.startsWith('504b0304')) return 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
    const m = { jpg:'image/jpeg', jpeg:'image/jpeg', png:'image/png', gif:'image/gif',
                webp:'image/webp', mp4:'video/mp4', mov:'video/quicktime',
                mp3:'audio/mpeg', ogg:'audio/ogg', pdf:'application/pdf',
                doc:'application/msword',
                docx:'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                xls:'application/vnd.ms-excel',
                xlsx:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                txt:'text/plain' };
    return m[ext] || 'application/octet-stream';
}

// ── Send helpers ──────────────────────────────────────────────────────────────

// Cache of JIDs we've already subscribed presence for (avoids repeat calls)
const _presenceSubscribed = new Set();

async function ensureKeysForJid(jid) {
    // Subscribing to presence forces Baileys to fetch the contact's identity
    // key from WhatsApp servers. Without this, the first message to a contact
    // the socket has never seen causes a "Waiting for this message" error
    // because the Signal session doesn't exist yet.
    if (_presenceSubscribed.has(jid)) return;
    try {
        await sock.presenceSubscribe(jid);
        _presenceSubscribed.add(jid);
        // Give WhatsApp ~800ms to acknowledge and cache the key material
        await new Promise(r => setTimeout(r, 800));
    } catch (_) {
        // Non-fatal — send anyway
    }
}

// Clears corrupt Signal session keys for a JID so Baileys re-negotiates.
// Fixes "Bad MAC" / "Waiting for this message" on specific contacts.
async function resetSessionForJid(jid) {
    try {
        if (sock && sock.authState && sock.authState.keys) {
            // Baileys stores per-JID session keys — remove them so it re-fetches
            const keys = sock.authState.keys;
            const bare = jid.split('@')[0];
            if (keys.get) {
                // Try both address formats WhatsApp uses
                for (const addr of [`${bare}.0`, `${bare}.1`, bare]) {
                    try { await keys.set({ 'session': { [addr]: null } }); } catch (_) {}
                }
            }
        }
        _presenceSubscribed.delete(jid);  // force re-subscribe next send
        process.stdout.write(`[Baileys] Session reset for ${jid} — will re-negotiate keys.\n`);
    } catch (e) {
        process.stdout.write(`[Baileys] Session reset warning: ${e.message}\n`);
    }
}

async function sendText(to, text) {
    if (!sock) throw new Error('WhatsApp socket not ready');
    if (!pairingDone) throw new Error('WhatsApp not paired yet — scan QR first');
    const jid = normalizeJid(to);
    if (!jid || !jid.includes('@')) {
        throw new Error(
            `Cannot resolve "${to}" to a WhatsApp JID. ` +
            `Use their exact display name as it appears in WhatsApp, ` +
            `or their phone number with country code (e.g. 917304332469).`
        );
    }
    // Pre-fetch keys so the message encrypts cleanly on first send
    await ensureKeysForJid(jid);
    try {
        const sent = await sock.sendMessage(jid, { text: String(text || '') });
        return (sent && sent.key && sent.key.id) || ('msg_' + Date.now());
    } catch (e) {
        // "Bad MAC" / corrupt session — reset keys and retry once
        if (/bad mac|mac error|session|decrypt/i.test(String(e.message || e))) {
            process.stdout.write(`[Baileys] Key error for ${jid} — resetting session and retrying.\n`);
            await resetSessionForJid(jid);
            await ensureKeysForJid(jid);
            await new Promise(r => setTimeout(r, 1000));
            const sent = await sock.sendMessage(jid, { text: String(text || '') });
            return (sent && sent.key && sent.key.id) || ('msg_' + Date.now());
        }
        throw e;
    }
}

async function sendFile(to, filePath, originalName) {
    if (!sock) throw new Error('WhatsApp socket not ready');
    if (!pairingDone) throw new Error('WhatsApp not paired yet — scan QR first');
    const jid  = normalizeJid(to);
    if (!jid || !jid.includes('@')) {
        throw new Error(`Cannot resolve "${to}" to a WhatsApp JID.`);
    }
    await ensureKeysForJid(jid);
    const ext   = path.extname(originalName || filePath || '').toLowerCase().slice(1);
    const buf   = fs.readFileSync(filePath);
    const mime  = guessMime(ext, buf);
    const fname = originalName || path.basename(filePath);

    if (!buf || buf.length === 0) {
        throw new Error(`Uploaded file "${fname}" is empty (0 bytes). Upload may have failed.`);
    }
    if (buf.length < 200 && !mime.startsWith('text/') && ext !== 'txt') {
        throw new Error(
            `Uploaded file "${fname}" is only ${buf.length} bytes ` +
            `(claimed type: ${mime}). This is almost certainly a corrupt upload — ` +
            `please verify the original file exists and is readable.`
        );
    }
    process.stdout.write(
        `[Baileys] Sending file to ${jid}: "${fname}" | ${buf.length} bytes | mime=${mime}\n`
    );

    let sent;
    const sendOnce = async () => {
        if (mime.startsWith('image/')) {
            return await sock.sendMessage(jid, {
                image: buf, caption: fname, mimetype: mime,
            });
        }
        if (mime.startsWith('video/')) {
            const gif = ext === 'gif' || mime === 'image/gif';
            return await sock.sendMessage(jid, {
                video: buf, caption: fname, mimetype: mime, gifPlayback: gif,
            });
        }
        if (mime.startsWith('audio/')) {
            return await sock.sendMessage(jid, {
                audio: buf, mimetype: mime, ptt: false,
            });
        }
        return await sock.sendMessage(jid, {
            document: buf, mimetype: mime, fileName: fname,
        });
    };
    try {
        sent = await sendOnce();
    } catch (e) {
        if (/bad mac|mac error|session|decrypt/i.test(String(e.message || e))) {
            process.stdout.write(`[Baileys] Key error for ${jid} (file) — resetting session and retrying.\n`);
            await resetSessionForJid(jid);
            await ensureKeysForJid(jid);
            await new Promise(r => setTimeout(r, 1500));
            sent = await sendOnce();
        } else if (/upload|media|server|timeout|socket hang up|ECONNRESET/i.test(String(e.message || e))) {
            process.stdout.write(`[Baileys] Media upload issue for ${jid} (${e.message || e}) — retrying once with longer wait.\n`);
            await new Promise(r => setTimeout(r, 2000));
            sent = await sendOnce();
        } else {
            throw e;
        }
    }
    return (sent && sent.key && sent.key.id) || ('msg_' + Date.now());
}

// ── Socket boot ───────────────────────────────────────────────────────────────
async function startSocket() {
    if (reconnecting) return;
    reconnecting = true;

    let saveCreds;
    try {
        const authState = await useMultiFileAuthState(AUTH_DIR);
        saveCreds = authState.saveCreds;
        const { version } = await fetchLatestWaWebVersion().catch(() => ({
            version: [2, 3000, 1017531287],
        }));

        sock = makeWASocket({
            auth:                       authState.state,
            version,
            logger,
            browser:                    ['SK AI Agent', 'Chrome', '128.0'],
            printQRInTerminal:          false,
            generateHighQualityLinkPreview: false,
            syncFullHistory:            false,
            markOnlineOnConnect:        false,
        });

        // Bind the in-memory store to this socket
        store.bind(sock.ev);

        sock.ev.on('creds.update', async () => {
            try { await saveCreds(); } catch (_) {}
        });

        sock.ev.on('connection.update', (update) => {
            const { connection, lastDisconnect: ld, qr } = update;

            if (qr) {
                latestQR = qr;
                emitEvent({ type: 'qr', qr });
                // Print ASCII QR to stdout so it shows in the terminal / log
                QRCode.toString(qr, { type: 'terminal', small: true }, (_err, str) => {
                    process.stdout.write('\n[Baileys] Scan QR with WhatsApp → Settings → Linked Devices\n\n' + (str || qr) + '\n');
                });
            }

            if (connection === 'open') {
                connectionOpen = true;
                pairingDone    = true;
                latestQR       = null;
                reconnecting   = false;
                _presenceSubscribed.clear();   // flush key cache on fresh session
                emitEvent({ type: 'ready', me: sock.user ? sock.user.id : null });
                process.stdout.write('[Baileys] ✅ Connected & ready.\n');
                return;
            }

            if (connection === 'close') {
                connectionOpen = false;
                reconnecting   = false;

                const boom       = ld && ld.error instanceof Boom ? ld.error : null;
                const statusCode = boom ? boom.output.statusCode
                                        : (ld && ld.output ? ld.output.statusCode : 0);
                const reason     = DisconnectReason[statusCode] || String(statusCode);

                lastDisconnect = { reason, code: statusCode, ts: Date.now() };
                emitEvent({ type: 'disconnect', reason, code: statusCode });
                process.stdout.write(`[Baileys] Connection closed: ${reason} (${statusCode})\n`);

                if (statusCode === DisconnectReason.loggedOut) {
                    // Wipe creds so the next start shows a fresh QR
                    process.stdout.write('[Baileys] Logged out — clearing auth for fresh pair.\n');
                    pairingDone = false;
                    try {
                        for (const f of fs.readdirSync(AUTH_DIR)) {
                            fs.unlinkSync(path.join(AUTH_DIR, f));
                        }
                    } catch (_) {}
                    // Restart to show fresh QR
                    setTimeout(startSocket, 3000);
                } else {
                    // All other disconnects: reconnect with backoff
                    const delay = [restartRequired, badSession, timedOut].includes(statusCode)
                        ? 5000 : 3000;
                    process.stdout.write(`[Baileys] Reconnecting in ${delay}ms…\n`);
                    setTimeout(startSocket, delay);
                }
            }
        });

        // Incoming messages
        sock.ev.on('messages.upsert', ({ messages, type }) => {
            if (type !== 'notify') return;
            for (const msg of messages) {
                try {
                    if (!msg || !msg.key) continue;
                    if (msg.key.fromMe) continue;
                    const jid = msg.key.remoteJid || '';

                    // ── Skip non-personal JIDs ────────────────────────────
                    if (safeIsBroadcast(jid)) continue;        // broadcast lists
                    if (safeIsGroup(jid)) continue;             // group chats — skip for auto-reply (can enable later)
                    if (jid.endsWith('@newsletter')) continue;  // WhatsApp channels
                    if (jid.endsWith('@lid'))        continue;  // linked-device ghost JIDs
                    if (jid.endsWith('@g.us'))       continue;  // groups (belt+braces)

                    const text = msgText(msg);
                    if (!text) continue;

                    // ── Skip obvious promo / business senders ─────────────
                    // Business JIDs that send one-way promotions can't receive replies.
                    // Detect by: short numbers (≤6 digits), known promo prefixes,
                    // or numbers that are clearly not a personal Indian/intl mobile.
                    const bareNum = jid.split('@')[0];

                    // Short-code or alphanumeric sender (business SMS-style)
                    if (/^\d{1,6}$/.test(bareNum)) continue;

                    // WhatsApp business pattern: country-long numbers starting
                    // with known promo prefixes (Jio=7000, 1600, 1800 toll-free, etc.)
                    if (/^(1600|1800|1860|140|700077|91700077)/.test(bareNum)) continue;

                    // Numbers with 15+ digits are typically aggregator/gateway IDs
                    if (bareNum.replace(/\D/g,'').length > 15) continue;

                    emitEvent({
                        type:    'message',
                        id:      msg.key.id || ('in_' + Date.now()),
                        jid,
                        from:    jidToName(jid, msg),
                        text,
                        time:    msg.messageTimestamp ? Number(msg.messageTimestamp) * 1000 : Date.now(),
                        isGroup: false,
                    });
                } catch (_) {}
            }
        });

    } catch (err) {
        reconnecting = false;
        process.stderr.write('[Baileys] startSocket error: ' + String(err) + '\n');
        setTimeout(startSocket, 5000);
    }
}

// Helper constants used in disconnect handler
const { restartRequired, badSession, timedOut } = DisconnectReason;

// ── Routes ────────────────────────────────────────────────────────────────────

app.get('/health', (_req, res) => res.json({ ok: true, ts: Date.now(), pid: process.pid }));

app.get('/token', (req, res) => {
    const addr = req.socket.remoteAddress || '';
    if (!['127.0.0.1', '::ffff:127.0.0.1', '::1'].includes(addr)) {
        return res.status(401).json({ error: 'localhost only' });
    }
    res.json({ token: TOKEN, port: PORT });
});

// SSE stream
app.get('/events', auth, (req, res) => {
    res.writeHead(200, {
        'Content-Type':  'text/event-stream',
        'Cache-Control': 'no-cache',
        'Connection':    'keep-alive',
        'X-Accel-Buffering': 'no',
    });
    // Replay buffer for late joiners
    for (const ev of eventBuffer) {
        try { res.write(`data: ${JSON.stringify(ev)}\n\n`); } catch (_) {}
    }
    const ping = setInterval(() => { try { res.write(': ping\n\n'); } catch (_) {} }, 20_000);
    eventSubscribers.add(res);
    const cleanup = () => { clearInterval(ping); eventSubscribers.delete(res); };
    req.on('close',   cleanup);
    req.on('aborted', cleanup);
    req.on('end',     cleanup);
});

// Status
app.get('/status', auth, async (_req, res) => {
    const qrDataUrl = latestQR ? await QRCode.toDataURL(latestQR).catch(() => null) : null;

    // Build chats from the in-memory store
    let chats = [];
    try {
        const raw = Object.values(store.chats.all ? store.chats.all() : (store.chats || {}));
        chats = raw.slice(0, 50).map(c => ({
            id:      c.id,
            jid:     c.id,
            name:    c.name || jidToName(c.id, null),
            unread:  c.unreadCount || 0,
            isGroup: safeIsGroup(c.id),
            lastMessageTime: c.conversationTimestamp
                ? Number(c.conversationTimestamp) * 1000 : null,
        })).sort((a, b) => (b.lastMessageTime || 0) - (a.lastMessageTime || 0));
    } catch (_) {}

    res.json({
        connected:  connectionOpen,
        logged_in:  pairingDone || connectionOpen,
        qr:         qrDataUrl,
        qrText:     latestQR,
        reason:     lastDisconnect ? lastDisconnect.reason : null,
        me:         sock && sock.user ? sock.user.id : null,
        chats,
    });
});

// QR PNG
app.get('/qr', auth, async (_req, res) => {
    if (!latestQR) {
        return res.status(404).json({
            error: pairingDone ? 'Already paired — no QR needed' : 'QR not ready yet',
        });
    }
    const png = await QRCode.toBuffer(latestQR).catch(() => null);
    if (!png) return res.status(500).json({ error: 'QR encode failed' });
    res.type('image/png').send(png);
});

// Chats list
app.get('/chats', auth, (_req, res) => {
    try {
        const raw = Object.values(store.chats.all ? store.chats.all() : (store.chats || {}));
        const list = raw.map(c => ({
            id:      c.id,
            jid:     c.id,
            name:    c.name || jidToName(c.id, null),
            unread:  c.unreadCount || 0,
            isGroup: safeIsGroup(c.id),
            lastMessageTime: c.conversationTimestamp
                ? Number(c.conversationTimestamp) * 1000 : null,
        })).sort((a, b) => (b.lastMessageTime || 0) - (a.lastMessageTime || 0));
        res.json({ chats: list });
    } catch (e) {
        res.status(500).json({ error: String(e.message || e) });
    }
});

// Messages in a chat
app.get('/messages', auth, (req, res) => {
    try {
        const jid   = String(req.query.jid   || '').trim();
        const limit = Math.max(1, Math.min(100, parseInt(req.query.limit || '20', 10)));
        if (!jid) return res.status(400).json({ error: 'jid required' });

        const chatMsgs = store.messages[jid];
        const raw = chatMsgs
            ? (chatMsgs.array || Object.values(chatMsgs)).slice(-limit)
            : [];

        const msgs = raw.map(m => ({
            id:     m.key && m.key.id,
            fromMe: !!(m.key && m.key.fromMe),
            jid:    m.key && m.key.remoteJid,
            text:   msgText(m),
            time:   m.messageTimestamp ? Number(m.messageTimestamp) * 1000 : null,
            type:   m.message ? getContentType(m.message) : null,
        })).filter(m => m.text || m.type);

        res.json({ messages: msgs });
    } catch (e) {
        res.status(500).json({ error: String(e.message || e) });
    }
});

// Send text
app.post('/send-text', auth, async (req, res) => {
    try {
        const { to, text } = req.body || {};
        if (!to || !text) return res.status(400).json({ error: 'to and text required' });
        const id = await sendText(to, text);
        res.json({ ok: true, msgId: id });
    } catch (e) {
        res.status(500).json({ error: String(e.message || e) });
    }
});

// Send file
app.post('/send-file', auth, upload.single('file'), async (req, res) => {
    try {
        const to = (req.body && req.body.to) || '';
        if (!to)       return res.status(400).json({ error: 'to required' });
        if (!req.file) return res.status(400).json({ error: 'file required' });
        process.stdout.write(
            `[Baileys] /send-file upload received: ` +
            `"${req.file.originalname}" -> saved as "${req.file.filename}" ` +
            `(${req.file.size} bytes, mime=${req.file.mimetype})\n`
        );
        const id = await sendFile(to, req.file.path, req.file.originalname);
        try { fs.unlinkSync(req.file.path); } catch (_) {}
        res.json({ ok: true, msgId: id });
    } catch (e) {
        process.stdout.write(`[Baileys] /send-file FAILED: ${String(e.message || e)}\n`);
        try { if (req.file) fs.unlinkSync(req.file.path); } catch (_) {}
        res.status(500).json({ error: String(e.message || e) });
    }
});

// Delete / revoke a message
app.post('/delete-message', auth, async (req, res) => {
    try {
        const { jid, msgId, forEveryone } = req.body || {};
        if (!jid || !msgId) return res.status(400).json({ error: 'jid and msgId required' });
        if (!sock || !pairingDone) return res.status(503).json({ error: 'Not connected' });

        const targetJid  = normalizeJid(jid);
        const deleteAll  = forEveryone !== false && forEveryone !== 'false';
        const messageKey = { remoteJid: targetJid, id: msgId, fromMe: true };

        if (deleteAll) {
            await sock.sendMessage(targetJid, { delete: messageKey });
        } else {
            await sock.chatModify(
                { clear: { messages: [{ id: msgId, fromMe: true, timestamp: Math.floor(Date.now() / 1000) }] } },
                targetJid,
            );
        }
        res.json({ ok: true });
    } catch (e) {
        res.status(500).json({ error: String(e.message || e) });
    }
});

// Mark chat as read
app.post('/mark-read', auth, async (req, res) => {
    try {
        const { jid } = req.body || {};
        if (!jid) return res.status(400).json({ error: 'jid required' });
        if (!sock || !pairingDone) return res.status(503).json({ error: 'Not connected' });

        const targetJid = normalizeJid(jid);
        // Baileys readMessages marks specific keys; to clear all unread we use chatModify
        await sock.chatModify({ markRead: true, lastMessages: [] }, targetJid);
        res.json({ ok: true });
    } catch (e) {
        res.status(500).json({ error: String(e.message || e) });
    }
});

// Forward a message
app.post('/forward', auth, async (req, res) => {
    try {
        const { fromJid, msgId, toJid } = req.body || {};
        if (!fromJid || !msgId || !toJid) {
            return res.status(400).json({ error: 'fromJid, msgId and toJid required' });
        }
        if (!sock || !pairingDone) return res.status(503).json({ error: 'Not connected' });

        const srcJid = normalizeJid(fromJid);
        const dstJid = normalizeJid(toJid);

        // Look up original message in the store
        const chatMsgs = store.messages[srcJid];
        const raw      = chatMsgs ? (chatMsgs.array || Object.values(chatMsgs)) : [];
        const original = raw.find(m => m.key && m.key.id === msgId);

        if (!original || !original.message) {
            return res.status(404).json({ error: 'Message not found in store' });
        }

        await sock.sendMessage(dstJid, { forward: original, force: true });
        res.json({ ok: true });
    } catch (e) {
        res.status(500).json({ error: String(e.message || e) });
    }
});

// React to a message
app.post('/react', auth, async (req, res) => {
    try {
        const { jid, msgId, emoji } = req.body || {};
        if (!jid || !msgId || !emoji) {
            return res.status(400).json({ error: 'jid, msgId and emoji required' });
        }
        if (!sock || !pairingDone) return res.status(503).json({ error: 'Not connected' });

        const targetJid = normalizeJid(jid);
        await sock.sendMessage(targetJid, {
            react: {
                text: String(emoji).trim(),
                key:  { remoteJid: targetJid, id: msgId, fromMe: false },
            },
        });
        res.json({ ok: true });
    } catch (e) {
        res.status(500).json({ error: String(e.message || e) });
    }
});

// Logout — clears creds and restarts for fresh QR
// Reset corrupted Signal session for a contact (fixes "Waiting for this message")
app.post('/reset-session', auth, async (req, res) => {
    try {
        const { jid } = req.body || {};
        if (!jid) return res.status(400).json({ error: 'jid required' });
        const targetJid = normalizeJid(jid);
        await resetSessionForJid(targetJid);
        res.json({ ok: true, jid: targetJid });
    } catch (e) {
        res.status(500).json({ error: String(e.message || e) });
    }
});

app.post('/logout', auth, async (_req, res) => {
    try {
        if (sock) {
            try { await sock.logout(); } catch (_) {}
            try { sock.end(new Error('logout')); } catch (_) {}
        }
        sock           = null;
        pairingDone    = false;
        connectionOpen = false;
        latestQR       = null;
        try {
            for (const f of fs.readdirSync(AUTH_DIR)) {
                fs.unlinkSync(path.join(AUTH_DIR, f));
            }
        } catch (_) {}
        res.json({ ok: true });
        // Restart socket so a fresh QR appears immediately
        setTimeout(startSocket, 1500);
    } catch (e) {
        res.status(500).json({ error: String(e.message || e) });
    }
});

// ── Start server ──────────────────────────────────────────────────────────────
const server = app.listen(PORT, '127.0.0.1', async () => {
    process.stdout.write(
        '╔══════════════════════════════════════════════════════════════╗\n' +
        '║  SK AI Agent — Baileys WhatsApp Gateway  (headless v2)      ║\n' +
        '╚══════════════════════════════════════════════════════════════╝\n' +
        `   HTTP :  http://127.0.0.1:${PORT}\n` +
        `   Token:  ${TOKEN}\n\n`
    );
    await startSocket();
});

server.on('error', err => {
    process.stderr.write('[Gateway] Server error: ' + String(err) + '\n');
    process.exit(1);
});

// Graceful shutdown
let stopping = false;
for (const sig of ['SIGINT', 'SIGTERM']) {
    process.on(sig, () => {
        if (stopping) return;
        stopping = true;
        process.stdout.write('[Baileys] Shutting down…\n');
        try { store.writeToFile(STORE_FILE); } catch (_) {}
        try { if (sock) sock.end(); } catch (_) {}
        server.close(() => process.exit(0));
        setTimeout(() => process.exit(0), 2000);
    });
}
