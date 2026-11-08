#!/usr/bin/env python3
"""
BalikLayar AI - Official All-in-One Core Bot
Fitur:
1. ONBOARDING & ROLE ⏳ UNVERIFIED:
   - Member baru menyelesaikan Onboarding (dengan logo TikTok & IG) dan otomatis mendapatkan role ⏳ Unverified.
   - Sebelum verifikasi, member HANYA BISA MELIHAT channel informasi.
2. AUTO-VERIFIKASI REAL HUMAN (INSTAN & PASTI HAPUS UNVERIFIED):
   - Member klik tombol [ 🛡️ Saya Manusia (Verifikasi Otomatis) ] di #verifikasi-kreator.
   - Bot otomatis MENCABUT role ⏳ Unverified dan MEMASANG role 🚀 Kreator seketika!
   - Seluruh channel komunitas affiliate & video AI langsung terbuka.
3. AUTO-MOD PERMINTAAN OWNER:
   - Deteksi jualan akun / tools liar (Gemini Pro, CapCut, Canva, Tools Kompetitor BL, dll).
   - Auto-Delete pesan & AUTO-KICK pelanggar seketika!
   - Audit log pelanggaran ke #bot-logs.
4. Built-in Moderasi & Slash Commands (/clear, /setup-verifikasi, /server-stats, /prompt-ide, /say).
"""

import discord
from discord.ext import commands
from discord import app_commands
import random
import datetime
import re

import config
import ai_service
import colorroles
from tiktok_monitor import TikTokMonitor

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

class BalikLayarBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        self.add_view(HumanVerificationView())
        self.add_view(colorroles.ColorRoleView())
        guild = discord.Object(id=config.GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        print("✅ Slash Commands berhasil disinkronkan ke server BalikLayar AI!")

bot = BalikLayarBot()
tiktok_monitor = TikTokMonitor(bot)


# Channel verifikasi hanya untuk tombol: tutup thread yang dibuat member di sana.
@bot.event
async def on_thread_create(thread: discord.Thread):
    if thread.parent_id == config.CHANNEL_ROLES:
        try:
            await thread.delete(reason="Thread tidak diizinkan di channel verifikasi")
        except Exception as e:
            print(f"❌ Gagal menghapus thread di verifikasi: {e}")

# ====================================================================
# 1. PERSISTENT VIEW - AUTO-VERIFIKASI REAL HUMAN (INSTAN & BERSIH)
# ====================================================================

class HumanVerificationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Saya Manusia (Verifikasi Otomatis)",
        style=discord.ButtonStyle.success,
        emoji="🛡️",
        custom_id="baliklayar:verify:human"
    )
    async def btn_verify_human(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        if not guild:
            return

        # Syarat umur akun: tolak akun yang terlalu baru (biasanya bot/akun spam)
        age_days = (discord.utils.utcnow() - interaction.user.created_at).days
        if age_days < config.VERIFY_MIN_ACCOUNT_DAYS:
            await interaction.response.send_message(
                f"⏳ Akun Discord kamu baru berumur **{age_days} hari**. "
                f"Verifikasi dibuka untuk akun berumur minimal **{config.VERIFY_MIN_ACCOUNT_DAYS} hari**. "
                "Coba lagi nanti ya, atau hubungi Moderator kalau ini akun utamamu.",
                ephemeral=True
            )
            logs_ch = bot.get_channel(config.CHANNEL_LOGS)
            if logs_ch:
                await logs_ch.send(embed=discord.Embed(
                    title="⏳ Verifikasi Ditolak (Akun Terlalu Baru)",
                    description=f"**User**: {interaction.user.mention} (`{interaction.user.id}`)\n**Umur akun**: {age_days} hari",
                    color=0xF1C40F,
                    timestamp=datetime.datetime.now(datetime.timezone.utc)
                ))
            return

        await interaction.response.send_modal(VerifyQuestionModal())


class VerifyQuestionModal(discord.ui.Modal, title="Verifikasi Real Human"):
    def __init__(self):
        super().__init__()
        a, b = random.randint(2, 9), random.randint(2, 9)
        self.answer = a + b
        self.jawaban = discord.ui.TextInput(label=f"Berapa {a} + {b} ?", max_length=3, required=True)
        self.add_item(self.jawaban)

    async def on_submit(self, interaction: discord.Interaction):
        if self.jawaban.value.strip() != str(self.answer):
            await interaction.response.send_message("❌ Jawaban salah. Klik tombol verifikasi lagi untuk mencoba ulang.", ephemeral=True)
            return
        await complete_verification(interaction)


async def complete_verification(interaction: discord.Interaction):
    guild = interaction.guild
    # Ambil data member terbaru langsung dari Discord API agar role akurat
    try:
        member = await guild.fetch_member(interaction.user.id)
    except Exception:
        member = interaction.user

    role_kreator = guild.get_role(config.ROLE_KREATOR)
    role_unverified = guild.get_role(config.ROLE_UNVERIFIED)

    if not role_kreator:
        await interaction.response.send_message("❌ Role `🚀 Kreator` tidak ditemukan di server.", ephemeral=True)
        return

    # 1. Hapus role ⏳ Unverified secara mutlak jika masih menempel
    unverified_removed = False
    if role_unverified and role_unverified in member.roles:
        try:
            await member.remove_roles(role_unverified, reason="Verifikasi Sukses: Unverified dicopot")
            unverified_removed = True
            print(f"✓ Role Unverified berhasil dicopot dari {member.name}")
        except Exception as e:
            print(f"❌ Gagal mencopot role Unverified dari {member.name}: {e}")

    # 2. Pasang role 🚀 Kreator jika belum punya
    kreator_added = False
    if role_kreator not in member.roles:
        try:
            await member.add_roles(role_kreator, reason="Verifikasi Sukses: Role Kreator aktif")
            kreator_added = True
            print(f"✓ Role Kreator berhasil dipasang ke {member.name}")
        except discord.Forbidden:
            await interaction.response.send_message(
                "⚠️ **Izin Bot Terhalang**: Pastikan role `BalikLayar Bot` berada di atas role `🚀 Kreator` di Server Settings > Roles.",
                ephemeral=True
            )
            return
        except Exception as e:
            await interaction.response.send_message(f"❌ Terjadi kesalahan saat verifikasi: {e}", ephemeral=True)
            return

    # 3. Berikan pesan konfirmasi
    success_embed = discord.Embed(
        title="🎉 Verifikasi Real Human Berhasil!",
        description=(
            f"Selamat {member.mention}! Akunmu telah berhasil diverifikasi oleh sistem.\n\n"
            "**Status Keanggotaan:**\n"
            "• Status: **Real Human (Terverifikasi)**\n"
            "• Role aktif: **🚀 Kreator**\n"
            "• Status lama: `⏳ Unverified` *(telah dicopot)*\n\n"
            "Seluruh channel komunitas, ide video AI, dan resource affiliate sekarang telah terbuka penuh!\n\n"
            "Silakan mulai berdiskusi di <#1568182411874017292> atau intip tren video di <#1568188713463451709>! 🚀"
        ),
        color=0x2ECC71
    )
    await interaction.response.send_message(embed=success_embed, ephemeral=True)

    # 4. Catat ke #bot-logs
    logs_ch = bot.get_channel(config.CHANNEL_LOGS)
    if logs_ch:
        log_embed = discord.Embed(
            title="✅ Member Terverifikasi Otomatis (Real Human)",
            description=f"**User**: {member.mention} (`{member.id}`)\n**Role Diberikan**: `🚀 Kreator`\n**Role Dicopot**: `⏳ Unverified`",
            color=0x2ECC71,
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        if member.avatar:
            log_embed.set_thumbnail(url=member.avatar.url)
        await logs_ch.send(embed=log_embed)


# ====================================================================
# 2. EVENT: BOT SIAP & MONITORING
# ====================================================================

@bot.event
async def on_ready():
    print(f"🤖 Bot Online: {bot.user.name} (ID: {bot.user.id})")
    activity = discord.Activity(
        type=discord.ActivityType.watching,
        name="Komunitas BalikLayar AI 🛡️"
    )
    await bot.change_presence(status=discord.Status.online, activity=activity)
    tiktok_monitor.start()

    # Kunci channel verifikasi: member tidak bisa membuat thread / mengirim chat
    guild = bot.get_guild(config.GUILD_ID)
    verif_ch = guild.get_channel(config.CHANNEL_ROLES) if guild else None
    if verif_ch:
        try:
            await verif_ch.set_permissions(
                guild.default_role,
                create_public_threads=False,
                create_private_threads=False,
                send_messages_in_threads=False,
                reason="Verifikasi: nonaktifkan pembuatan thread",
            )
        except Exception as e:
            print(f"⚠️ Gagal mengunci thread di channel verifikasi: {e}")

    logs_ch = bot.get_channel(config.CHANNEL_LOGS)
    if logs_ch:
        embed = discord.Embed(
            title="🟢 Core Bot Online & Verifikasi Siap",
            description=f"**{bot.user.name}** aktif.\n🛡️ **Auto-Verifikasi & Role Swap: AKTIF**\n⛔ **Auto-Kick Jualan Liar: AKTIF**",
            color=0x00FFA3,
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        await logs_ch.send(embed=embed)


# ====================================================================
# 3. AUTO-MOD: DETEKSI JUALAN TOOLS & AUTO-KICK
# ====================================================================

# --- Tahap 1: saringan cepat (tidak peduli urutan kata, posisi, atau baris baru) ---
_PRODUCT_RE = re.compile(
    r"gemini|capcut|canva|chat\s*gpt|\bgpt\b|claude|midjourney|freepik|envato|grok|perplexity|veo|"
    r"\bakun\b|\btools?\b|premium|\bpro\b|lisensi|license|sharing|private|"
    r"netflix|spotify|youtube\s*premium|vpn", re.I)
_SALES_RE = re.compile(
    r"\bjual\b|dijual|jualan|\bready\b|open\s*order|\bpo\b|\bsewa\b|disewakan|promo|diskon|murmer|murah|"
    r"harga|\border\b|pesan\s*sekarang|garansi|testi|bergaransi|stok|slot|\bdm\b|\bpm\b|"
    r"hubungi|chat\s*(?:me|aku|saya)|wa\.me|whatsapp|\bwa\b|t\.me|telegram|minat|"
    r"\b\d+\s*(?:k|rb|ribu)\b|rp\.?\s*\d+", re.I)
_ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u2060\ufeff]")


def looks_like_selling(text: str) -> bool:
    t = _ZERO_WIDTH_RE.sub("", text)
    return bool(_PRODUCT_RE.search(t) and _SALES_RE.search(t))


# --- Tahap 2: AI menilai konteks. Kick HANYA jika AI yakin ini jualan. ---
SELLING_KICK_CONFIDENCE = 80


async def detect_selling(message: discord.Message):
    """Return (is_violation, alasan). Tidak pernah kick jika AI gagal atau ragu: kasus itu dikirim ke #bot-logs untuk review staff."""
    content = message.content or ""
    if len(content) < 8 or not looks_like_selling(content):
        return False, ""

    result = await ai_service.classify_selling(content)

    async def flag_for_review(title: str, reason: str):
        logs_ch = bot.get_channel(config.CHANNEL_LOGS)
        if not logs_ch:
            return
        emb = discord.Embed(title=title, color=0xF1C40F, timestamp=datetime.datetime.now(datetime.timezone.utc))
        emb.add_field(name="👤 Penulis", value=f"{message.author.mention} (`{message.author.id}`)", inline=True)
        emb.add_field(name="📍 Pesan", value=f"[Lompat ke pesan]({message.jump_url})", inline=True)
        emb.add_field(name="🧠 Analisis AI", value=reason or "-", inline=False)
        emb.add_field(name="📝 Isi", value=f"```{content[:900]}```", inline=False)
        try:
            await logs_ch.send(embed=emb)
        except Exception:
            pass

    if result is None:
        await flag_for_review("⚠️ Pesan mencurigakan (AI tidak bisa menganalisis, tidak ada tindakan)", "AI tidak merespons / output tidak valid")
        return False, ""
    if not result["selling"]:
        return False, result["reason"]
    if result["confidence"] < SELLING_KICK_CONFIDENCE:
        await flag_for_review(f"🔎 Kemungkinan jualan, perlu review staff (yakin {result['confidence']}%)", result["reason"])
        return False, result["reason"]
    return True, f"{result['reason']} (yakin {result['confidence']}%)"


def build_server_context(guild: discord.Guild, member: discord.Member, channel) -> str:
    if not guild:
        return ""
    member_count = getattr(guild, "member_count", len(guild.members))
    user_roles = [r.name for r in getattr(member, "roles", []) if r.name != "@everyone"]
    roles_str = ", ".join(user_roles) if user_roles else "Member Baru"
    channel_name = getattr(channel, "name", "channel umum")

    return (
        f"- Nama Komunitas: BalikLayar AI (duacincin.id)\n"
        f"- Total Anggota: {member_count} member aktif\n"
        f"- Status Bot & Node: Online 24/7 di Cloud SairiHost (AMD EPYC, port 2014, operasional normal)\n"
        f"- Saluran Aktif: #{channel_name}\n"
        f"- Data Penanya: Tag Mention=<@{member.id}> (Nama: {member.display_name}, Role: {roles_str})\n"
        f"- Data Founder: Tag Mention=<@799987598726135818> (Nama: Alfiqo)\n"
        f"- Data Moderator: Tag Mention=<@&1568185534352859207>\n"
        f"- Data Kreator: Tag Mention=<@&1568187130419613776>\n"
        f"- Fitur Aktif: Auto-Verifikasi Kreator & Auto-Kick jualan liar\n"
        f"- Saluran Utama: #welcome, #rules, #pengumuman, #ngobrol-santai, #ide-dan-tren, #tanya-jawab, #pamer-komisi, #showcase-video, #resource-share"
    )

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    content = message.content
    member_roles = [r.id for r in getattr(message.author, "roles", [])]
    is_staff = (
        message.author.guild_permissions.administrator
        or config.ROLE_FOUNDER in member_roles
        or config.ROLE_MODERATOR in member_roles
    )

    # 1. AUTO-MOD CHECK: Khusus member biasa (Staff bebas memposting)
    if not is_staff:
        is_violation, ai_reason = await detect_selling(message)
        if is_violation:
            try:
                await message.delete()
            except:
                pass

            try:
                dm_embed = discord.Embed(
                    title="⛔ Kamu Telah Dikeluarkan (KICK) dari BalikLayar AI",
                    description=(
                        "Kamu dikeluarkan secara otomatis karena melanggar **ATURAN KERAS OWNER**:\n\n"
                        "❌ **Dilarang memposting atau memperjualbelikan akun & tools apapun tanpa izin Admin.**\n"
                        "*(Termasuk jualan Gemini Pro, CapCut, Canva, akun premium, atau tools kompetitor BalikLayar AI)*.\n\n"
                        "Jika ingin berjualan atau bermitra resmi, wajib menghubungi Owner/Admin terlebih dahulu."
                    ),
                    color=0xFF0000
                )
                await message.author.send(embed=dm_embed)
            except:
                pass

            try:
                await message.author.kick(reason="Auto-Mod Owner: Jualan tools/akun tanpa izin")
                print(f"🚨 AUTO-KICK: {message.author.name} ({message.author.id})")
            except Exception as e:
                print(f"❌ Gagal kick {message.author.name}: {e}")

            warning_msg = (
                f"⛔ **PERINGATAN KERAS:**\n"
                f"{message.author.mention} telah **dikeluarkan otomatis (KICK)** oleh sistem!\n"
                f"**Alasan:** Dilarang keras posting atau jualan akun/tools tanpa izin Admin/Owner. "
                f"Patuhi aturan di <#{config.CHANNEL_RULES}>!"
            )
            await message.channel.send(warning_msg, delete_after=15)

            logs_ch = bot.get_channel(config.CHANNEL_LOGS)
            if logs_ch:
                log_embed = discord.Embed(
                    title="🚨 [AUTO-KICK] Pelanggaran Jualan Liar Terdeteksi",
                    color=0xFF0000,
                    timestamp=datetime.datetime.now(datetime.timezone.utc)
                )
                log_embed.add_field(name="👤 Pelanggar", value=f"{message.author.mention} (`{message.author.id}`)", inline=True)
                log_embed.add_field(name="📍 Channel", value=message.channel.mention, inline=True)
                log_embed.add_field(name="📝 Isi Pesan", value=f"```{content[:1000]}```", inline=False)
                log_embed.add_field(name="🧠 Analisis AI", value=ai_reason or "-", inline=False)
                log_embed.add_field(name="⚡ Tindakan", value="Pesan Dihapus + User Di-KICK Otomatis", inline=False)
                await logs_ch.send(embed=log_embed)

            return

    # Trigger AI Mention: Jika member mention bot (@BalikLayar Bot)
    if bot.user in message.mentions and not message.mention_everyone:
        clean_text = re.sub(rf"<@!?{bot.user.id}>", "", message.content).strip()
        if not clean_text:
            await message.reply(
                "Ada yang bisa dibantu seputar video AI atau strategi affiliate hari ini? Langsung sebut aja topik atau pertanyaan yang mau kamu bahas! 🚀"
            )
            return

        # Cek jika Founder / Moderator melatih bot lewat mention
        user_roles = [r.id for r in getattr(message.author, "roles", [])]
        is_staff = config.ROLE_FOUNDER in user_roles or config.ROLE_MODERATOR in user_roles or message.author.guild_permissions.administrator
        train_match = re.search(r"(?i)\b(tolong\s+)?(ingat|catat|pelajari)\s*(ini)?\s*:\s*(.*)", clean_text)
        if is_staff and train_match:
            learned_info = train_match.group(4).strip()
            if learned_info:
                success = ai_service.add_training_memory("Instruksi Chat Langsung", learned_info, message.author.display_name)
                if success:
                    embed = discord.Embed(
                        title="🧠 Ingatan Baru Berhasil Disimpan Permanen!",
                        description=(
                            f"Siap {message.author.mention}! Saya sudah mencatat dan mengingat informasi ini ke memori permanen:\n\n"
                            f"> *\"{learned_info}\"*\n\n"
                            f"✅ *Mulai sekarang, saya akan selalu menggunakan informasi ini setiap kali ada member yang bertanya seputar topik tersebut.*"
                        ),
                        color=0x2ECC71
                    )
                    await message.reply(embed=embed)
                    return

        async with message.channel.typing():
            ctx = build_server_context(message.guild, message.author, message.channel)

            # Ambil 3 riwayat chat terakhir untuk ingatan percakapan nyambung
            chat_history = ""
            try:
                hist_msgs = [m async for m in message.channel.history(limit=4, before=message)]
                if hist_msgs:
                    chat_history = "\n".join([f"{m.author.display_name}: {m.content[:200]}" for m in reversed(hist_msgs) if m.content])
            except Exception:
                pass

            ai_reply = await ai_service.query_ai(clean_text, message.author.display_name, server_context=ctx, chat_history=chat_history)
            if len(ai_reply) > 1950:
                ai_reply = ai_reply[:1940] + "...\n*(terpotong batas Discord)*"
            allowed = discord.AllowedMentions(users=True, roles=True, everyone=False, replied_user=True)
            await message.reply(ai_reply, mention_author=True, allowed_mentions=allowed)
        return

    await bot.process_commands(message)



# ====================================================================
# 4. EVENT: AUTO-WELCOME & ASSIGN ROLE ⏳ UNVERIFIED
# ====================================================================

@bot.event
async def on_member_join(member: discord.Member):
    guild = member.guild
    if guild.id != config.GUILD_ID:
        return

    unverified_role = guild.get_role(config.ROLE_UNVERIFIED)
    if unverified_role:
        try:
            await member.add_roles(unverified_role)
            print(f"⏳ Role 'Unverified' diberikan ke {member.name}")
        except Exception as e:
            print(f"❌ Gagal memberikan role Unverified: {e}")

    welcome_ch = bot.get_channel(config.CHANNEL_WELCOME)
    if welcome_ch:
        embed = discord.Embed(
            title=f"👋 Halo {member.display_name}, Selamat Datang di BalikLayar AI!",
            description=(
                f"Senang sekali kamu bergabung dengan kami, {member.mention}!\n\n"
                "Komunitas ini adalah wadah untuk para creator & affiliate bertukar strategi video AI, "
                "belajar prompt viral, dan berbagi hasil komisi.\n\n"
                "**🚀 Langkah Verifikasi Kamu:**\n"
                f"1. 📜 Pahami aturan server di <#{config.CHANNEL_RULES}>\n"
                f"2. 🛡️ Lakukan verifikasi di <#{config.CHANNEL_ROLES}> untuk mengaktifkan role Kreator & membuka seluruh channel!\n"
                f"3. 💬 Sapa teman-teman lainnya di <#{config.CHANNEL_CHAT}>\n\n"
                f"*Kamu adalah member ke-{guild.member_count}! Enjoy your stay!* ✨"
            ),
            color=0x5865F2,
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        if member.avatar:
            embed.set_thumbnail(url=member.avatar.url)
        embed.set_footer(text="BalikLayar AI • Creative Hub", icon_url=guild.icon.url if guild.icon else None)
        await welcome_ch.send(content=f"Selamat datang {member.mention}! 🎉", embed=embed)

    # DM selamat datang berisi langkah awal (diabaikan jika DM member tertutup)
    try:
        await member.send(embed=discord.Embed(
            title="👋 Selamat datang di BalikLayar AI!",
            description=(
                "Biar akses komunitasmu terbuka penuh, ikuti 3 langkah ini:\n\n"
                f"1. 📜 Baca aturan di <#{config.CHANNEL_RULES}>\n"
                f"2. 🛡️ Verifikasi di <#{config.CHANNEL_ROLES}> (klik tombol hijau, jawab 1 pertanyaan singkat)\n"
                f"3. 💬 Kenalan di <#{config.CHANNEL_CHAT}>\n\n"
                "Tanya apa saja seputar video AI & affiliate: mention bot atau pakai `/tanya-ai`. 🚀"
            ),
            color=0x5865F2
        ))
    except Exception:
        pass

    logs_ch = bot.get_channel(config.CHANNEL_LOGS)
    if logs_ch:
        log_embed = discord.Embed(
            title="📥 Member Baru Bergabung",
            description=f"**User**: {member.mention} (`{member.id}`)\n**Status**: `⏳ Unverified`",
            color=0x3498DB,
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        if member.avatar:
            log_embed.set_thumbnail(url=member.avatar.url)
        await logs_ch.send(embed=log_embed)


# ====================================================================
# 5. SLASH COMMANDS
# ====================================================================

@bot.tree.command(name="setup-verifikasi", description="Pasang panel verifikasi otomatis Real Human ke channel")
@app_commands.default_permissions(administrator=True)
async def setup_verifikasi(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🛡️ Verifikasi Anggota Resmi (Anti-Bot Gate)",
        description=(
            "Selamat datang di server komunitas resmi **BalikLayar AI**!\n\n"
            "Untuk mencegah akun bot spam dan memastikan seluruh anggota adalah manusia sungguhan, "
            "silakan lakukan verifikasi instan dengan menekan tombol hijau di bawah.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "**Setelah klik tombol, sistem akan otomatis:**\n"
            "• Memverifikasi bahwa kamu adalah **Real Human**.\n"
            "• Mencopot status `⏳ Unverified`.\n"
            "• Memberikan role resmi **🚀 Kreator** ke akunmu secara instan.\n"
            "• Membuka akses penuh ke seluruh channel komunitas & resource affiliate!\n\n"
            "👇 **Tekan tombol di bawah untuk verifikasi instan:**"
        ),
        color=0x2ECC71
    )
    embed.set_footer(text="BalikLayar AI • Automated Real Human Verification 🛡️")

    view = HumanVerificationView()
    channel = bot.get_channel(config.CHANNEL_ROLES)
    if channel:
        await channel.send(embed=embed, view=view)
        await interaction.response.send_message(f"✅ Panel verifikasi otomatis dipasang di <#{config.CHANNEL_ROLES}>!", ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed, view=view)


@bot.tree.command(name="setup-warna", description="Pasang panel ganti warna role ke channel ini")
@app_commands.default_permissions(administrator=True)
async def setup_warna(interaction: discord.Interaction):
    await interaction.channel.send(embed=colorroles.build_embed(), view=colorroles.ColorRoleView())
    await interaction.response.send_message("✅ Panel warna dipasang.", ephemeral=True)


@bot.tree.command(name="clear", description="Bersihkan sejumlah pesan dari channel (Khusus Moderator/Admin)")
@app_commands.describe(jumlah="Berapa banyak pesan yang ingin dihapus (1-100)")
@app_commands.default_permissions(manage_messages=True)
async def clear_messages(interaction: discord.Interaction, jumlah: int):
    if jumlah < 1 or jumlah > 100:
        await interaction.response.send_message("❌ Jumlah pesan harus antara 1 sampai 100.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=jumlah)
    await interaction.followup.send(f"🧹 Berhasil menghapus **{len(deleted)}** pesan.", ephemeral=True)


@bot.tree.command(name="say", description="Kirim pesan atau pengumuman melalui bot")
@app_commands.describe(pesan="Teks pesan yang ingin disampaikan bot", channel="Channel tujuan (opsional)")
@app_commands.default_permissions(administrator=True)
async def say(interaction: discord.Interaction, pesan: str, channel: discord.TextChannel = None):
    target = channel or interaction.channel
    await target.send(pesan)
    await interaction.response.send_message(f"✅ Pesan berhasil dikirim ke {target.mention}!", ephemeral=True)


@bot.tree.command(name="server-stats", description="Lihat statistik lengkap server BalikLayar AI")
async def server_stats(interaction: discord.Interaction):
    guild = interaction.guild
    embed = discord.Embed(
        title=f"📊 Statistik Server {guild.name}",
        color=0x00FFA3,
        timestamp=datetime.datetime.now(datetime.timezone.utc)
    )
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)

    text_channels = len([c for c in guild.channels if isinstance(c, discord.TextChannel)])
    voice_channels = len([c for c in guild.channels if isinstance(c, discord.VoiceChannel)])

    embed.add_field(name="👑 Founder", value=f"<@{guild.owner_id}>", inline=True)
    embed.add_field(name="👥 Total Member", value=str(guild.member_count), inline=True)
    embed.add_field(name="🎭 Total Role", value=str(len(guild.roles)), inline=True)
    embed.add_field(name="💬 Text Channels", value=str(text_channels), inline=True)
    embed.add_field(name="🔊 Voice Channels", value=str(voice_channels), inline=True)
    embed.add_field(name="🚀 Dibuat Pada", value=f"<t:{int(guild.created_at.timestamp())}:D>", inline=True)

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="prompt-ide", description="Dapatkan ide hook & prompt video AI viral untuk affiliate")
async def prompt_ide(interaction: discord.Interaction):
    prompts = [
        {
            "hook": "🔥 Hook Kontroversial: 'Semua orang salah cara pakai AI ini...'",
            "ide": "Tunjukkan 1 fitur rahasia tools AI yang mempermudah editing dalam 10 detik, lalu call-to-action ke link bio.",
            "formula": "[Masalah umum penonton] + [Solusi instan via tools] + [Trik rahasia yang jarang diketahui]."
        },
        {
            "hook": "💡 Hook Transformasi: 'Dari 0 komisi jadi tembus 2 digit cuma modal HP & video AI...'",
            "ide": "Spill cuplikan workflow editing kamu dari ide -> render -> komisi masuk. Bangun empati dan rasa penasaran.",
            "formula": "[Kondisi awal/struggle] + [Titik balik setelah pakai workflow AI] + [Bukti hasil konkret]."
        },
        {
            "hook": "⚡ Hook Komparasi: 'Edit manual 3 jam vs Edit pakai AI 3 menit...'",
            "ide": "Split screen video: sisi kiri proses manual yang ribet, sisi kanan proses cepat dengan tools AI rekomendasi kamu.",
            "formula": "[Perbandingan ekstrem waktu/usaha] + [Hasil visual yang identik] + [Rekomendasi tools di bio]."
        }
    ]
    p = random.choice(prompts)
    embed = discord.Embed(
        title="💡 Ide Konten & Hook AI Viral",
        description=f"**{p['hook']}**\n\n**Konsep Video:**\n{p['ide']}\n\n**Struktur Formula:**\n`{p['formula']}`",
        color=0xE74C3C
    )
    embed.set_footer(text="Gunakan ide ini untuk konten showcase atau komisi berikutnya! 🎬")
    await interaction.response.send_message(embed=embed)


# ====================================================================
# PERINTAH AI: KONSULTASI KONTEN, HOOK & STRATEGI AFFILIATE
# ====================================================================

@bot.tree.command(name="tanya-ai", description="Tanya apa saja seputar tips video AI, hook viral, dan strategi affiliate")
@app_commands.describe(pertanyaan="Topik atau pertanyaan yang ingin kamu tanyakan ke AI")
async def cmd_tanya_ai(interaction: discord.Interaction, pertanyaan: str):
    await interaction.response.defer(thinking=True)
    ctx = build_server_context(interaction.guild, interaction.user, interaction.channel)
    reply = await ai_service.query_ai(pertanyaan, interaction.user.display_name, server_context=ctx)
    if len(reply) > 1950:
        reply = reply[:1940] + "...\n*(terpotong batas Discord)*"
    allowed = discord.AllowedMentions(users=True, roles=True, everyone=False)
    await interaction.followup.send(reply, allowed_mentions=allowed)



@bot.tree.command(name="ide-konten", description="Dapatkan 3 ide video pendek viral + hook pembuka untuk niche kamu")
@app_commands.describe(niche="Niche konten (misal: affiliate fashion, tutorial AI, review gadget)")
async def cmd_ide_konten(interaction: discord.Interaction, niche: str):
    await interaction.response.defer(thinking=True)
    prompt = (
        f"Buatkan 3 ide konten video pendek (TikTok/Reels/Shorts) berpotensi viral untuk niche '{niche}'.\n"
        "Untuk setiap ide sertakan:\n"
        "1. Judul & Konsep Singkat\n"
        "2. Hook pembuka 3 detik pertama (bikin penasaran/pattern interrupt)\n"
        "3. Call-to-Action (CTA) affiliate yang halus dan menjual"
    )
    reply = await ai_service.query_ai(prompt, interaction.user.display_name)
    if len(reply) > 1950:
        reply = reply[:1940] + "...\n*(terpotong batas Discord)*"
    allowed = discord.AllowedMentions(users=True, roles=True, everyone=False)
    await interaction.followup.send(reply, allowed_mentions=allowed)


@bot.tree.command(name="bedah-hook", description="Bedah naskah hook video kamu dan berikan 3 alternatif yang lebih mematikan")
@app_commands.describe(hook="Teks kalimat hook 3 detik pertama video kamu")
async def cmd_bedah_hook(interaction: discord.Interaction, hook: str):
    await interaction.response.defer(thinking=True)
    prompt = (
        f"Bedah kalimat hook video ini: \"{hook}\"\n"
        "1. Berikan skor kekuatan hook (1-10) dan alasan singkatnya.\n"
        "2. Berikan 3 alternatif variasi hook yang jauh lebih memikat, bikin penasaran, dan memicu retensi penonton tinggi."
    )
    reply = await ai_service.query_ai(prompt, interaction.user.display_name)
    if len(reply) > 1950:
        reply = reply[:1940] + "...\n*(terpotong batas Discord)*"
    allowed = discord.AllowedMentions(users=True, roles=True, everyone=False)
    await interaction.followup.send(reply, allowed_mentions=allowed)


@bot.tree.command(name="train", description="Ajarkan pengetahuan/fakta baru ke memori permanen AI BalikLayar (Khusus Staff)")
@app_commands.describe(
    topik="Topik atau judul materi (misal: Jadwal Kelas, Promo Diskon, Link Pendaftaran)",
    informasi="Detail fakta/informasi lengkap yang harus selalu diingat oleh AI"
)
async def cmd_train(interaction: discord.Interaction, topik: str, informasi: str):
    user_roles = [r.id for r in getattr(interaction.user, "roles", [])]
    is_staff = (
        interaction.user.guild_permissions.administrator
        or config.ROLE_FOUNDER in user_roles
        or config.ROLE_MODERATOR in user_roles
    )
    if not is_staff:
        await interaction.response.send_message("❌ Perintah ini khusus untuk Founder dan Moderator.", ephemeral=True)
        return

    success = ai_service.add_training_memory(topik, informasi, interaction.user.display_name)
    if success:
        embed = discord.Embed(
            title="🧠 Pengetahuan Baru Berhasil Disimpan Permanen!",
            description=(
                f"**Topik:** `{topik}`\n"
                f"**Informasi:**\n> {informasi}\n\n"
                f"✅ **Tersimpan ke Knowledge Base permanen (`knowledge.md`)!**\n"
                f"Mulai sekarang, bot akan selalu menggunakan informasi ini setiap kali ada pertanyaan terkait."
            ),
            color=0x2ECC71
        )
        await interaction.response.send_message(embed=embed)
    else:
        await interaction.response.send_message("❌ Gagal menyimpan pengetahuan baru ke memori.", ephemeral=True)


@bot.tree.command(name="help", description="Daftar fitur dan perintah BalikLayar Core Bot")
async def bot_help(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🤖 BalikLayar AI - Core Bot Menu",
        description="Bot inti resmi untuk automasi, verifikasi instan real human, dan kecerdasan AI server BalikLayar AI.",
        color=0x5865F2
    )
    embed.add_field(
        name="🛡️ Auto-Verifikasi Real Human:",
        value="Member cukup klik tombol hijau di `#verifikasi-kreator` untuk membuktikan dia manusia asli, mencopot role `⏳ Unverified`, dan bot otomatis langsung memberikan role `🚀 Kreator`!",
        inline=False
    )
    embed.add_field(
        name="🧠 Fitur AI Creator Assistant:",
        value="• **Mention Bot**: `@BalikLayar Bot <pertanyaan>` di channel mana saja.\n• `/tanya-ai <pertanyaan>` : Tanya apa saja seputar AI & affiliate.\n• `/ide-konten <niche>` : Dapatkan 3 ide video viral + hook pembuka.\n• `/bedah-hook <hook>` : Analisis & buat variasi hook mematikan.",
        inline=False
    )
    embed.add_field(
        name="🚨 Proteksi Auto-Mod:",
        value="Auto-Kick & Auto-Delete langsung bagi siapapun yang memposting/menjual tools liar.",
        inline=False
    )
    embed.add_field(
        name="👤 Perintah Umum:",
        value="• `/server-stats` : Ringkasan statistik komunitas.\n• `/prompt-ide` : Inspirasi hook video viral.\n• `/help` : Panduan bantuan bot.",
        inline=False
    )
    embed.add_field(
        name="👑 Perintah Staff / Admin:",
        value="• `/setup-verifikasi` : Pasang panel tombol verifikasi real human.\n• `/clear <jumlah>` : Hapus pesan spam.\n• `/say <pesan>` : Kirim pesan resmi bot.",
        inline=False
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


if __name__ == "__main__":
    print("🚀 Menjalankan BalikLayar Core Bot...")
    bot.run(config.BOT_TOKEN)
