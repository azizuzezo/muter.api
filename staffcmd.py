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
import re

import discord

import ai_service
import config

MAX_ACTIONS = 6
PROTECTED_CHANNELS = {
    config.CHANNEL_WELCOME, config.CHANNEL_RULES, config.CHANNEL_ANNOUNCEMENT,
    config.CHANNEL_ROLES, config.CHANNEL_CHAT, config.CHANNEL_LOGS,
}
PROTECTED_ROLES = {
    config.ROLE_FOUNDER, config.ROLE_MODERATOR, config.ROLE_POWER_USER,
    config.ROLE_KREATOR, config.ROLE_UNVERIFIED,
}
DESTRUCTIVE = {"delete_channel", "delete_role"}

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

Aturan:
- Maksimal 6 aksi. Kalau permintaan tidak jelas atau tidak bisa dilakukan, kosongkan actions dan jelaskan/tanya di reply.
- Untuk create_channel text: name berupa slug huruf kecil dengan tanda hubung (contoh "request-fitur"); emoji cocok dengan topiknya. Jangan menaruh dekorasi ╭┃╰ sendiri, sistem yang menambahkan.
- Jangan pernah mengubah izin/permission, memberi role ke orang, kick/ban. Itu di luar kemampuanmu; tolak lewat reply.
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
            lines.append(f"   - ({ch.type.name}) {ch.name}")
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


# ------------------------- eksekusi -------------------------
def _decorate(guild, category, slug: str, emoji: str | None) -> str:
    """Nama channel mengikuti gaya server: ┃・emoji・slug (╰ jika jadi channel terakhir)."""
    slug = re.sub(r"[^0-9a-z\-]+", "-", slug.lower().replace(" ", "-")).strip("-")[:60] or "channel"
    emoji = (emoji or "").strip()[:4]
    mid = f"{emoji}・" if emoji else ""
    return f"┃・{mid}{slug}"


async def run_action(guild: discord.Guild, member: discord.Member, a: dict) -> str:
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

    return f"❌ Aksi tidak dikenal: `{act}`"


def describe(a: dict) -> str:
    keys = ("action", "name", "channel", "role", "category", "type", "topic", "color")
    return " ".join(f"{k}=`{a[k]}`" for k in keys if a.get(k) not in (None, ""))


class ConfirmView(discord.ui.View):
    def __init__(self, guild, member, actions, results):
        super().__init__(timeout=120)
        self.guild, self.member, self.actions, self.results = guild, member, actions, results

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("Hanya yang meminta yang bisa konfirmasi.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Ya, hapus", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        out = []
        for a in self.actions:
            try:
                out.append(await run_action(self.guild, self.member, a))
            except discord.HTTPException as e:
                out.append(f"❌ {a.get('action')}: {e}")
        self.stop()
        await interaction.edit_original_response(content="\n".join(self.results + out), view=None)
        await audit(self.guild, self.member, self.actions, self.results + out)

    @discord.ui.button(label="Batal", style=discord.ButtonStyle.secondary)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="\n".join(self.results + ["↩️ Penghapusan dibatalkan."]), view=None)


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


async def handle(bot_user, message: discord.Message):
    text = re.sub(rf"<@!?{bot_user.id}>", "", message.content).strip()
    if not text:
        await message.reply("Halo! Tulis perintahnya setelah tag, contoh: *bikinin channel #request-fitur di kategori KOMUNITAS AFFILIATE*.")
        return
    guild, member = message.guild, message.author
    async with message.channel.typing():
        raw = await ai_service._raw_completion(
            SYSTEM_PROMPT, f"{snapshot(guild)}\n\nPERINTAH STAFF:\n{text[:1500]}",
            max_tokens=900, temperature=0.1, timeout=40)
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
            results.append(await run_action(guild, member, a))
        except discord.Forbidden:
            results.append(f"⚠️ {a.get('action')}: bot tidak punya izin (cek posisi role bot)")
        except discord.HTTPException as e:
            results.append(f"❌ {a.get('action')}: {e}")
    head = [plan["reply"]] if plan["reply"] else []
    if safe:
        await audit(guild, member, safe, results)
    if risky:
        desc = "\n".join("• " + describe(a) for a in risky)
        view = ConfirmView(guild, member, risky, head + results)
        await message.reply("\n".join(head + results + [f"⚠️ **Konfirmasi penghapusan:**\n{desc}"]), view=view,
                            allowed_mentions=discord.AllowedMentions.none())
    else:
        await message.reply("\n".join(head + results)[:1990], allowed_mentions=discord.AllowedMentions.none())
