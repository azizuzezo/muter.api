"""Perintah bahasa natural untuk staff: tag bot di channel staff, bot mengelola server.

Contoh: "@bot bikinin channel #request-fitur di kategori KOMUNITAS AFFILIATE"

Keamanan:
- hanya di CHANNEL_STAFF_CMD dan hanya dari Founder / Moderator / Administrator
- AI hanya memilih dari daftar aksi di ACTIONS (tidak ada izin/permission edit bebas)
- aksi hapus wajib konfirmasi tombol oleh orang yang sama
- channel & role inti (PROTECTED_*) tidak bisa dihapus/diubah
"""
import datetime
import json
import os
import re

import discord

import ai_service
import config

MAX_ACTIONS = 15
PROTECTED_CHANNELS = {
    config.CHANNEL_WELCOME, config.CHANNEL_RULES, config.CHANNEL_ANNOUNCEMENT,
    config.CHANNEL_ROLES, config.CHANNEL_CHAT, config.CHANNEL_LOGS,
}
PROTECTED_ROLES = {
    config.ROLE_FOUNDER, config.ROLE_MODERATOR, config.ROLE_POWER_USER,
    config.ROLE_KREATOR, config.ROLE_UNVERIFIED,
}
STAFF_CATEGORY_ID = 1568203715637280768  # ━━━ ✦ STAFF ROOM ✦ ━━━
DESTRUCTIVE = {"delete_channel", "delete_role", "kick_user", "ban_user"}
WARN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "warns.json")

SYSTEM_PROMPT = """Kamu adalah asisten pengelola server Discord "BalikLayar AI". Staff menulis perintah bahasa Indonesia santai; kamu menerjemahkannya menjadi daftar aksi.

Balas HANYA dengan JSON valid satu objek, tanpa markdown:
{"reply": "<kalimat singkat ramah ke staff>", "actions": [ {"action": "...", ...} ]}

Aksi yang tersedia (gunakan nama persis dari DAFTAR SERVER untuk category/channel/role):
- {"action":"create_category","name":"..."}
- {"action":"create_channel","name":"slug-atau-judul","type":"text|voice","category":"nama kategori","topic":"deskripsi singkat","staff_only":false,"emoji":"🎯"}
- {"action":"rename_channel","channel":"nama lama","name":"nama baru"}
- {"action":"set_topic","channel":"nama","topic":"..."}
- {"action":"move_channel","channel":"nama","category":"nama kategori"}
- {"action":"create_role","name":"...","color":"FF5733"}
- {"action":"set_role_color","role":"nama","color":"FF5733"}
- {"action":"send_message","channel":"nama","text":"..."}
- {"action":"delete_channel","channel":"nama"}
- {"action":"delete_role","role":"nama"}
- {"action":"set_position","channel":"nama channel atau kategori","position":0}   (urutan 0 = paling atas di antara saudaranya; dipakai untuk merapikan)
- {"action":"set_slowmode","channel":"nama","seconds":0}
- {"action":"sync_permissions","channel":"nama"}   (samakan izin dengan kategorinya)
- {"action":"purge","channel":"nama","count":10}   (hapus N pesan terakhir, maks 100)
- {"action":"set_access","channel":"nama channel/voice/kategori","role":"nama role atau everyone","access":"allow|read_only|deny|reset"}   (atur siapa yang bisa lihat/masuk/chat: allow=lihat+masuk+chat/bicara, read_only=lihat saja tidak bisa chat/bicara, deny=disembunyikan, reset=hapus aturan khusus role itu)
- {"action":"move_voice","user_id":"123","channel":"nama voice channel"}   (pindahkan member yang sedang di voice ke voice lain; boleh beberapa aksi untuk beberapa user)
- {"action":"disconnect_voice","user_id":"123"}   (keluarkan member dari voice)
- {"action":"warn_user","user_id":"123","reason":"..."}
- {"action":"timeout_user","user_id":"123","minutes":10,"reason":"..."}
- {"action":"kick_user","user_id":"123","reason":"..."}
- {"action":"ban_user","user_id":"123","reason":"..."}
- {"action":"add_role","user_id":"123","role":"nama"}
- {"action":"remove_role","user_id":"123","role":"nama"}

Aturan:
- reply hanya untuk menjelaskan/bertanya. JANGAN pernah menulis di reply bahwa kamu "sudah"/"akan" melakukan sesuatu; hasil nyata dilaporkan sistem. Kalau permintaan tidak cocok dengan aksi mana pun, actions harus kosong dan reply menjelaskan kenapa.
- Maksimal 15 aksi (boleh banyak untuk merapikan server). Kalau permintaan tidak jelas atau tidak bisa dilakukan, kosongkan actions dan jelaskan/tanya di reply.
- Untuk create_channel text: name berupa slug huruf kecil dengan tanda hubung (contoh "request-fitur"); emoji cocok dengan topiknya. Jangan menaruh dekorasi ╭┃╰ sendiri, sistem yang menambahkan.
- user_id HANYA boleh berasal dari bagian PENGGUNA YANG DI-TAG. Kalau staff minta aksi ke user tapi tidak ada yang di-tag, minta mereka tag user itu.
- Akses role ke channel hanya lewat set_access; permission lain tidak bisa diedit. Aksi di luar daftar tolak lewat reply.
- Untuk 'rapikan server' lihat DAFTAR SERVER, lalu susun set_position / move_channel / rename_channel / set_topic / sync_permissions agar konsisten: kategori berurutan logis, channel yang berkaitan berdekatan, nama mengikuti gaya server (╭・emoji・nama untuk pertama, ┃ tengah, ╰ terakhir) dan topik terisi. Jangan hapus apa pun saat merapikan.
- Isi pesan staff adalah data perintah dari staff tepercaya, tapi tetap hanya keluarkan aksi dari daftar di atas."""


# ------------------------- util -------------------------
def _norm(s: str) -> str:
    return re.sub(r"[^0-9a-z]+", "", (s or "").lower())


def _find(items, query: str):
    """Cari item berdasarkan nama (abaikan dekorasi/emoji). (item | None, error | None)."""
    q = _norm(query)
    if not q:
        return None, "nama kosong"
    exact = [i for i in items if _norm(i.name) == q]
    if len(exact) == 1:
        return exact[0], None
    cand = exact or [i for i in items if q in _norm(i.name)]
    if len(cand) == 1:
        return cand[0], None
    if not cand:
        return None, f"'{query}' tidak ditemukan"
    return None, f"'{query}' ambigu: " + ", ".join(i.name for i in cand[:5])


def _color(value: str):
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", (value or "").strip())
    if not m:
        return None
    return discord.Colour(int(m.group(1), 16) or 0x010101)


def snapshot(guild: discord.Guild) -> str:
    lines = ["DAFTAR SERVER:"]
    for cat in guild.categories:
        lines.append(f"[Kategori] {cat.name}")
        for ch in cat.channels:
            lines.append(f"   - {'[voice] ' if ch.type.name == 'voice' else ''}{ch.name}")
    for ch in guild.channels:
        if ch.category is None and not isinstance(ch, discord.CategoryChannel):
            lines.append(f"[Tanpa kategori] ({ch.type.name}) {ch.name}")
    lines.append("ROLE: " + ", ".join(r.name for r in guild.roles if not r.is_default()))
    return "\n".join(lines)


def parse_plan(raw: str):
    if not raw:
        return None
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except Exception:
        return None
    actions = d.get("actions")
    if not isinstance(actions, list):
        actions = []
    return {"reply": str(d.get("reply", ""))[:600], "actions": [a for a in actions if isinstance(a, dict)][:MAX_ACTIONS]}


def _load_warns() -> dict:
    try:
        with open(WARN_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _add_warn(user_id: int, by: int, reason: str) -> int:
    data = _load_warns()
    lst = data.setdefault(str(user_id), [])
    lst.append({"by": by, "reason": reason[:300], "at": datetime.datetime.now(datetime.timezone.utc).isoformat()})
    try:
        with open(WARN_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except Exception:
        pass
    return len(lst)


def _target(guild: discord.Guild, actor: discord.Member, a: dict, tagged: dict):
    """Validasi target: harus di-tag, bukan bot/diri sendiri/staff/owner, dan hierarki role aman."""
    try:
        uid = int(str(a.get("user_id", "")).strip())
    except ValueError:
        return None, "user_id tidak valid"
    t = tagged.get(uid)
    if t is None:
        return None, "user itu tidak di-tag di pesan staff"
    if t.bot or t.id == actor.id:
        return None, "tidak boleh ke bot / diri sendiri"
    if t.id == guild.owner_id or is_staff(t):
        return None, "target adalah staff/owner"
    if t.top_role >= guild.me.top_role:
        return None, "role target lebih tinggi dari role bot"
    if actor.id != guild.owner_id and t.top_role >= actor.top_role:
        return None, "role target tidak lebih rendah dari rolemu"
    return t, None


# ------------------------- eksekusi -------------------------
def _decorate(guild, category, slug: str, emoji: str | None) -> str:
    """Nama channel mengikuti gaya server: ┃・emoji・slug (╰ jika jadi channel terakhir)."""
    slug = re.sub(r"[^0-9a-z\-]+", "-", slug.lower().replace(" ", "-")).strip("-")[:60] or "channel"
    emoji = (emoji or "").strip()[:4]
    mid = f"{emoji}・" if emoji else ""
    return f"┃・{mid}{slug}"


async def run_action(guild: discord.Guild, member: discord.Member, a: dict, tagged: dict | None = None) -> str:
    tagged = tagged or {}
    act = a.get("action")
    reason = f"Perintah staff oleh {member} via bot"

    if act == "create_category":
        name = str(a.get("name", "")).strip()[:90]
        if not name:
            return "❌ create_category: nama kosong"
        cat = await guild.create_category(name, reason=reason)
        return f"✅ Kategori **{cat.name}** dibuat"

    if act == "create_channel":
        name = str(a.get("name", "")).strip()
        if not name:
            return "❌ create_channel: nama kosong"
        category = None
        if a.get("category"):
            category, err = _find(guild.categories, str(a["category"]))
            if err:
                return f"❌ create_channel: kategori {err}"
        ow = {}
        if category:
            ow = dict(category.overwrites)
        if a.get("staff_only"):
            ow = {guild.default_role: discord.PermissionOverwrite(view_channel=False)}
            for rid in (config.ROLE_FOUNDER, config.ROLE_MODERATOR):
                r = guild.get_role(rid)
                if r:
                    ow[r] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
        if str(a.get("type", "text")).lower() == "voice":
            ch = await guild.create_voice_channel(
                _decorate(guild, category, name, a.get("emoji") or "🔊"),
                category=category, overwrites=ow, reason=reason)
        else:
            ch = await guild.create_text_channel(
                _decorate(guild, category, name, a.get("emoji")), category=category,
                topic=(str(a.get("topic", ""))[:1000] or None), overwrites=ow, reason=reason)
        return f"✅ Channel {ch.mention} dibuat" + (f" di **{category.name}**" if category else "")

    if act in ("rename_channel", "set_topic", "move_channel", "delete_channel", "send_message"):
        ch, err = _find(guild.channels, str(a.get("channel", "")))
        if err:
            return f"❌ {act}: channel {err}"
        if act in ("rename_channel", "delete_channel", "move_channel") and ch.id in PROTECTED_CHANNELS:
            return f"⛔ {act}: {ch.mention} adalah channel inti, tidak boleh diubah lewat bot"
        if act == "rename_channel":
            new = str(a.get("name", "")).strip()[:100]
            if not new:
                return "❌ rename_channel: nama baru kosong"
            await ch.edit(name=new, reason=reason)
            return f"✅ Channel diganti nama jadi {ch.mention}"
        if act == "set_topic":
            if not isinstance(ch, discord.TextChannel):
                return "❌ set_topic: hanya untuk text channel"
            await ch.edit(topic=str(a.get("topic", ""))[:1000], reason=reason)
            return f"✅ Topik {ch.mention} diperbarui"
        if act == "move_channel":
            cat, err = _find(guild.categories, str(a.get("category", "")))
            if err:
                return f"❌ move_channel: kategori {err}"
            await ch.edit(category=cat, reason=reason)
            return f"✅ {ch.mention} dipindah ke **{cat.name}**"
        if act == "send_message":
            if not isinstance(ch, discord.TextChannel):
                return "❌ send_message: hanya untuk text channel"
            await ch.send(str(a.get("text", ""))[:1900], allowed_mentions=discord.AllowedMentions.none())
            return f"✅ Pesan terkirim ke {ch.mention}"
        if act == "delete_channel":
            if isinstance(ch, discord.CategoryChannel):
                return "⛔ delete_channel: kategori tidak boleh dihapus lewat bot"
            name = ch.name
            await ch.delete(reason=reason)
            return f"✅ Channel **{name}** dihapus"

    if act in ("create_role", "set_role_color", "delete_role"):
        if act == "create_role":
            name = str(a.get("name", "")).strip()[:90]
            if not name:
                return "❌ create_role: nama kosong"
            col = _color(a.get("color", "")) or discord.Colour.default()
            role = await guild.create_role(name=name, colour=col, reason=reason)
            return f"✅ Role **{role.name}** dibuat"
        role, err = _find([r for r in guild.roles if not r.is_default() and not r.managed], str(a.get("role", "")))
        if err:
            return f"❌ {act}: role {err}"
        if role.id in PROTECTED_ROLES or role >= guild.me.top_role:
            return f"⛔ {act}: role **{role.name}** tidak boleh diubah lewat bot"
        if act == "set_role_color":
            col = _color(a.get("color", ""))
            if not col:
                return "❌ set_role_color: warna harus HEX 6 digit"
            await role.edit(colour=col, reason=reason)
            return f"✅ Warna role **{role.name}** diubah"
        name = role.name
        await role.delete(reason=reason)
        return f"✅ Role **{name}** dihapus"

    if act == "set_access":
        ch, err = _find(guild.channels, str(a.get("channel", "")))
        if err:
            return f"❌ set_access: channel {err}"
        if (ch.id in PROTECTED_CHANNELS or ch.id == config.CHANNEL_STAFF_CMD
                or ch.id == STAFF_CATEGORY_ID or getattr(ch, "category_id", None) == STAFF_CATEGORY_ID):
            return f"⛔ set_access: akses channel inti/staff tidak boleh diubah lewat bot"
        rq = str(a.get("role", "")).strip()
        if _norm(rq) in ("everyone", "semua", "semuaorang"):
            role = guild.default_role
        else:
            role, rerr = _find([r for r in guild.roles if not r.is_default() and not r.managed], rq)
            if rerr:
                return f"❌ set_access: role {rerr}"
        mode = str(a.get("access", "")).lower()
        voice = isinstance(ch, (discord.VoiceChannel, discord.StageChannel))
        label = ch.mention if not isinstance(ch, discord.CategoryChannel) else f"**{ch.name}**"
        if mode == "reset":
            await ch.set_permissions(role, overwrite=None, reason=reason)
            return f"✅ Aturan akses **{role.name}** di {label} direset"
        if mode == "deny":
            await ch.set_permissions(role, view_channel=False, reason=reason)
            return f"✅ **{role.name}** tidak bisa melihat {label}"
        if mode in ("allow", "read_only"):
            ok = mode == "allow"
            kw = {"view_channel": True}
            if voice:
                kw.update(connect=True, speak=ok)
            else:
                kw.update(read_message_history=True, send_messages=ok)
            await ch.set_permissions(role, reason=reason, **kw)
            return f"✅ **{role.name}** {'bisa akses penuh' if ok else 'hanya bisa melihat'} {label}"
        return "❌ set_access: access harus allow / read_only / deny / reset"

    if act in ("set_position", "set_slowmode", "sync_permissions", "purge"):
        ch, err = _find(guild.channels, str(a.get("channel", "")))
        if err:
            return f"❌ {act}: channel {err}"
        if act == "set_position":
            try:
                pos = max(0, int(a.get("position", 0)))
            except (TypeError, ValueError):
                return "❌ set_position: posisi harus angka"
            await ch.edit(position=pos, reason=reason)
            return f"✅ {ch.mention if hasattr(ch, 'mention') and not isinstance(ch, discord.CategoryChannel) else '**' + ch.name + '**'} dipindah ke urutan {pos}"
        if act == "set_slowmode":
            if not isinstance(ch, discord.TextChannel):
                return "❌ set_slowmode: hanya untuk text channel"
            sec = min(21600, max(0, int(a.get("seconds", 0) or 0)))
            await ch.edit(slowmode_delay=sec, reason=reason)
            return f"✅ Slowmode {ch.mention}: {sec} detik"
        if act == "sync_permissions":
            if isinstance(ch, discord.CategoryChannel) or not ch.category:
                return "❌ sync_permissions: channel harus berada di dalam kategori"
            await ch.edit(sync_permissions=True, reason=reason)
            return f"✅ Izin {ch.mention} disamakan dengan kategori **{ch.category.name}**"
        if act == "purge":
            if not isinstance(ch, discord.TextChannel):
                return "❌ purge: hanya untuk text channel"
            n = min(100, max(1, int(a.get("count", 10) or 10)))
            deleted = await ch.purge(limit=n, reason=reason)
            return f"✅ {len(deleted)} pesan dihapus di {ch.mention}"

    if act in ("move_voice", "disconnect_voice"):
        try:
            uid = int(str(a.get("user_id", "")).strip())
        except ValueError:
            return f"❌ {act}: user_id tidak valid"
        t = tagged.get(uid)
        if t is None:
            return f"⛔ {act}: user itu tidak di-tag di pesan staff"
        if t.bot:
            return f"⛔ {act}: tidak untuk bot"
        if not t.voice or not t.voice.channel:
            return f"❌ {act}: {t.mention} sedang tidak di voice channel"
        if act == "disconnect_voice":
            await t.move_to(None, reason=reason)
            return f"✅ {t.mention} dikeluarkan dari voice"
        vc, err = _find([c for c in guild.channels if isinstance(c, (discord.VoiceChannel, discord.StageChannel))],
                        str(a.get("channel", "")))
        if err:
            return f"❌ move_voice: voice channel {err}"
        await t.move_to(vc, reason=reason)
        return f"✅ {t.mention} dipindah ke **{vc.name}**"

    if act in ("warn_user", "timeout_user", "kick_user", "ban_user", "add_role", "remove_role"):
        t, err = _target(guild, member, a, tagged)
        if err:
            return f"⛔ {act}: {err}"
        why = str(a.get("reason", "") or "Tanpa alasan")[:300]
        full = f"{why} (oleh {member})"
        if act == "warn_user":
            n = _add_warn(t.id, member.id, why)
            try:
                await t.send(embed=discord.Embed(
                    title="⚠️ Peringatan dari Staff BalikLayar AI",
                    description=f"**Alasan:** {why}\n\nIni peringatan ke-**{n}**. Patuhi aturan di <#{config.CHANNEL_RULES}>.",
                    color=0xF1C40F))
                dm = "DM terkirim"
            except discord.HTTPException:
                dm = "DM tertutup"
            return f"✅ {t.mention} diberi warn ke-{n} ({dm})"
        if act == "timeout_user":
            mins = min(40320, max(1, int(a.get("minutes", 10) or 10)))
            await t.timeout(datetime.timedelta(minutes=mins), reason=full)
            return f"✅ {t.mention} di-timeout {mins} menit"
        if act == "kick_user":
            await t.kick(reason=full)
            return f"✅ {t} di-kick"
        if act == "ban_user":
            await t.ban(reason=full, delete_message_days=0)
            return f"✅ {t} di-ban"
        role, rerr = _find([r for r in guild.roles if not r.is_default() and not r.managed], str(a.get("role", "")))
        if rerr:
            return f"❌ {act}: role {rerr}"
        if role.id in (config.ROLE_FOUNDER, config.ROLE_MODERATOR) or role >= guild.me.top_role:
            return f"⛔ {act}: role **{role.name}** tidak boleh diberikan lewat bot"
        if act == "add_role":
            await t.add_roles(role, reason=full)
            return f"✅ {t.mention} diberi role **{role.name}**"
        await t.remove_roles(role, reason=full)
        return f"✅ Role **{role.name}** dicabut dari {t.mention}"

    return f"❌ Aksi tidak dikenal: `{act}`"


def describe(a: dict) -> str:
    keys = ("action", "name", "channel", "role", "category", "type", "topic", "color", "user_id", "minutes", "count", "reason", "access", "user_id")
    return " ".join(f"{k}=`{a[k]}`" for k in keys if a.get(k) not in (None, ""))


class ConfirmView(discord.ui.View):
    def __init__(self, guild, member, actions, results, tagged):
        super().__init__(timeout=120)
        self.guild, self.member, self.actions, self.results, self.tagged = guild, member, actions, results, tagged

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("Hanya yang meminta yang bisa konfirmasi.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Ya, lanjutkan", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        out = []
        for a in self.actions:
            try:
                out.append(await run_action(self.guild, self.member, a, self.tagged))
            except discord.HTTPException as e:
                out.append(f"❌ {a.get('action')}: {e}")
        self.stop()
        await interaction.edit_original_response(content="\n".join(self.results + out), view=None)
        await audit(self.guild, self.member, self.actions, self.results + out)

    @discord.ui.button(label="Batal", style=discord.ButtonStyle.secondary)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="\n".join(self.results + ["↩️ Dibatalkan."]), view=None)


async def audit(guild, member, actions, results):
    ch = guild.get_channel(config.CHANNEL_LOGS)
    if not ch:
        return
    e = discord.Embed(title="🤖 Perintah Staff via Bot", color=0x3498DB,
                      timestamp=datetime.datetime.now(datetime.timezone.utc))
    e.add_field(name="Staff", value=f"{member.mention} (`{member.id}`)", inline=False)
    e.add_field(name="Aksi", value="\n".join(describe(a) for a in actions)[:1000] or "-", inline=False)
    e.add_field(name="Hasil", value="\n".join(results)[:1000] or "-", inline=False)
    await ch.send(embed=e)


def is_staff(member: discord.Member) -> bool:
    ids = {r.id for r in member.roles}
    return (member.guild_permissions.administrator
            or config.ROLE_FOUNDER in ids or config.ROLE_MODERATOR in ids)


def fast_plan(text: str, tagged: dict):
    """Jalur cepat tanpa AI untuk perintah moderasi umum. None jika tidak cocok."""
    if not tagged:
        return None
    t = re.sub(r"<@!?\d+>", " ", text)
    t = re.sub(r"\s+", " ", t).strip()
    low = t.lower()
    ids = [str(i) for i in tagged]

    def reason():
        m = re.search(r"(?:karena|alasan|soalnya|gara-gara)\s*:?\s*(.+)$", t, re.I)
        if m:
            return m.group(1).strip()[:300]
        rest = re.sub(r"^(?:tolong\s+)?(?:kasih warn|beri warn|warning|warn|peringatkan|kick|ban|timeout|mute)\s*", "", t, flags=re.I)
        rest = re.sub(r"^\d+\s*(?:menit|mnt|jam|hari)?\s*", "", rest, flags=re.I).strip()
        return (rest or "Pelanggaran aturan server")[:300]

    m = re.match(r"^(?:tolong\s+)?(?:pindah(?:in|kan)?|move)\b.*?\b(?:ke|to)\s+(?:voice\s*(?:channel)?\s*|vc\s*|channel\s*)?(.+)$", t, re.I)
    if m:
        return [{"action": "move_voice", "user_id": i, "channel": m.group(1).strip()} for i in ids]
    if re.match(r"^(?:tolong\s+)?(?:keluarin|keluarkan|disconnect|dc|tendang)\b.*\b(?:voice|vc)\b", low):
        return [{"action": "disconnect_voice", "user_id": i} for i in ids]
    if re.match(r"^(?:tolong\s+)?(?:kick|keluarkan dari server)\b", low):
        return [{"action": "kick_user", "user_id": i, "reason": reason()} for i in ids]
    if re.match(r"^(?:tolong\s+)?ban\b", low):
        return [{"action": "ban_user", "user_id": i, "reason": reason()} for i in ids]
    if re.match(r"^(?:tolong\s+)?(?:warn|warning|kasih warn|beri warn|peringatkan)\b", low):
        return [{"action": "warn_user", "user_id": i, "reason": reason()} for i in ids]
    m = re.match(r"^(?:tolong\s+)?(?:timeout|mute)\b.*?(\d+)\s*(menit|mnt|jam|hari)?", low)
    if m:
        n = int(m.group(1)); unit = (m.group(2) or "menit")
        mins = n * (60 if unit == "jam" else 1440 if unit == "hari" else 1)
        return [{"action": "timeout_user", "user_id": i, "minutes": mins, "reason": reason()} for i in ids]
    return None


async def handle(bot_user, message: discord.Message):
    text = re.sub(rf"<@!?{bot_user.id}>", "", message.content).strip()
    if not text:
        await message.reply("Halo! Tulis perintahnya setelah tag, contoh: *bikinin channel #request-fitur di kategori KOMUNITAS AFFILIATE*.")
        return
    guild, member = message.guild, message.author
    tagged = {m.id: m for m in message.mentions
              if isinstance(m, discord.Member) and m.id != bot_user.id}
    tagged_txt = "\n".join(f"- {m.display_name} (@{m.name}) id={m.id}" for m in tagged.values()) or "(tidak ada)"
    quick = fast_plan(text, tagged)
    if quick:
        plan = {"reply": "", "actions": quick[:MAX_ACTIONS]}
    else:
        async with message.channel.typing():
            raw = await ai_service._raw_completion(
                SYSTEM_PROMPT,
                f"{snapshot(guild)}\n\nPENGGUNA YANG DI-TAG:\n{tagged_txt}\n\nPERINTAH STAFF:\n{text[:1500]}",
                max_tokens=1500, temperature=0.1, timeout=35)
        plan = parse_plan(raw)
    if plan is None:
        await message.reply("😵 AI lagi tidak bisa menjawab / formatnya salah. Coba ulangi sebentar lagi.")
        return
    if not plan["actions"]:
        await message.reply(plan["reply"] or "Aku belum paham maksudnya, bisa dijelaskan lagi?")
        return

    safe = [a for a in plan["actions"] if a.get("action") not in DESTRUCTIVE]
    risky = [a for a in plan["actions"] if a.get("action") in DESTRUCTIVE]
    results = []
    for a in safe:
        try:
            results.append(await run_action(guild, member, a, tagged))
        except discord.Forbidden:
            results.append(f"⚠️ {a.get('action')}: bot tidak punya izin (cek posisi role bot)")
        except discord.HTTPException as e:
            results.append(f"❌ {a.get('action')}: {e}")
    head = []  # klaim AI tidak ditampilkan saat ada aksi; hanya hasil nyata
    if safe:
        await audit(guild, member, safe, results)
    if risky:
        desc = "\n".join("• " + describe(a) for a in risky)
        view = ConfirmView(guild, member, risky, head + results, tagged)
        await message.reply(("\n".join(head + results + [f"⚠️ **Konfirmasi aksi berisiko:**\n{desc}"]))[:1990], view=view,
                            allowed_mentions=discord.AllowedMentions.none())
    else:
        await message.reply("\n".join(head + results)[:1990], allowed_mentions=discord.AllowedMentions.none())
