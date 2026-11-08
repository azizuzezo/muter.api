"""Panel ganti warna nama (color roles) untuk member terverifikasi.

- 12 warna preset berbagi role "🎨 <Nama>" (dibuat otomatis saat pertama dipakai).
- Warna custom (HEX) membuat role pribadi "🎨 <username>" milik member itu saja.
- Semua role warna diletakkan tepat di bawah Moderator, jadi mengalahkan warna
  Kreator/Power User tapi tidak warna staff.
"""
import re

import discord

import config

PREFIX = "🎨 "
PRESETS = [
    ("Merah", "E74C3C", "🔴"),
    ("Oranye", "E67E22", "🟠"),
    ("Kuning", "F1C40F", "🟡"),
    ("Hijau", "2ECC71", "🟢"),
    ("Tosca", "1ABC9C", "🩵"),
    ("Biru", "3498DB", "🔵"),
    ("Ungu", "9B59B6", "🟣"),
    ("Pink", "FF69B4", "🌸"),
    ("Emas", "D4AF37", "🏆"),
    ("Putih", "ECF0F1", "⚪"),
    ("Neon Cyan", "00FFD5", "💠"),
    ("Magenta", "E91E8C", "💖"),
]
PRESET_NAMES = {PREFIX + n for n, _, _ in PRESETS}
ALLOWED_ROLES = (
    config.ROLE_KREATOR, config.ROLE_POWER_USER, config.ROLE_MODERATOR, config.ROLE_FOUNDER,
)
_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")


def _is_eligible(member: discord.Member) -> bool:
    return any(r.id in ALLOWED_ROLES for r in member.roles)


def _color_roles(member: discord.Member):
    return [r for r in member.roles if r.name.startswith(PREFIX)]


async def _place(guild: discord.Guild, role: discord.Role):
    mod = guild.get_role(config.ROLE_MODERATOR)
    if mod:
        try:
            await role.edit(position=mod.position, reason="Posisi color role")
        except discord.HTTPException:
            pass


async def _strip(member: discord.Member, keep: discord.Role | None = None):
    old = [r for r in _color_roles(member) if r != keep]
    if old:
        await member.remove_roles(*old, reason="Ganti warna")
    for r in old:  # hapus role custom pribadi yang sudah tidak dipakai
        if r.name not in PRESET_NAMES and not r.members:
            try:
                await r.delete(reason="Role warna custom tidak terpakai")
            except discord.HTTPException:
                pass


async def _apply_preset(interaction: discord.Interaction, name: str):
    member, guild = interaction.user, interaction.guild
    _, hexv, _ = next(p for p in PRESETS if p[0] == name)
    full = PREFIX + name
    role = discord.utils.get(guild.roles, name=full)
    if role is None:
        role = await guild.create_role(
            name=full, colour=discord.Colour(int(hexv, 16)), reason="Color role preset")
        await _place(guild, role)
    await _strip(member, keep=role)
    if role not in member.roles:
        await member.add_roles(role, reason="Pilih warna")
    await interaction.followup.send(f"✨ Warna namamu sekarang **{name}** (`#{hexv}`).", ephemeral=True)


class CustomColorModal(discord.ui.Modal, title="Warna Custom (HEX)"):
    hexcode = discord.ui.TextInput(
        label="Kode HEX (6 digit)", placeholder="contoh: FF5733", min_length=6, max_length=7)

    async def on_submit(self, interaction: discord.Interaction):
        m = _HEX_RE.match(self.hexcode.value.strip())
        if not m:
            await interaction.response.send_message(
                "❌ Format salah. Pakai 6 digit HEX, contoh `FF5733`.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        member, guild = interaction.user, interaction.guild
        value = int(m.group(1), 16) or 0x010101  # 000000 = "tanpa warna" di Discord
        mine = [r for r in _color_roles(member) if r.name not in PRESET_NAMES]
        if mine:
            role = mine[0]
            await role.edit(colour=discord.Colour(value), reason="Warna custom")
        else:
            role = await guild.create_role(
                name=PREFIX + member.name[:90], colour=discord.Colour(value),
                reason="Warna custom member")
            await _place(guild, role)
        await _strip(member, keep=role)
        if role not in member.roles:
            await member.add_roles(role, reason="Warna custom")
        await interaction.followup.send(f"🎨 Warna custom `#{m.group(1).upper()}` dipasang!", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        msg = "⚠️ Gagal mengatur warna. Pastikan role bot berada di atas role warna."
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)


class ColorSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            custom_id="baliklayar:color:select",
            placeholder="🎨 Pilih warna namamu...",
            options=[discord.SelectOption(label=n, value=n, emoji=e, description=f"#{h}")
                     for n, h, e in PRESETS],
        )

    async def callback(self, interaction: discord.Interaction):
        if not _is_eligible(interaction.user):
            await interaction.response.send_message(
                "🔒 Verifikasi dulu untuk jadi **Kreator**, baru bisa ganti warna.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            await _apply_preset(interaction, self.values[0])
        except discord.HTTPException:
            await interaction.followup.send(
                "⚠️ Gagal mengatur warna. Hubungi Moderator.", ephemeral=True)


class ColorRoleView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ColorSelect())

    @discord.ui.button(label="Warna Custom (HEX)", style=discord.ButtonStyle.primary,
                       emoji="🖌️", custom_id="baliklayar:color:custom")
    async def custom(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _is_eligible(interaction.user):
            await interaction.response.send_message(
                "🔒 Verifikasi dulu untuk jadi **Kreator**, baru bisa ganti warna.", ephemeral=True)
            return
        await interaction.response.send_modal(CustomColorModal())

    @discord.ui.button(label="Reset Warna", style=discord.ButtonStyle.secondary,
                       emoji="♻️", custom_id="baliklayar:color:reset")
    async def reset(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await _strip(interaction.user)
        await interaction.followup.send("♻️ Warna dikembalikan ke warna role bawaan.", ephemeral=True)


def build_embed() -> discord.Embed:
    swatches = "\n".join(f"{e}  **{n}**  `#{h}`" for n, h, e in PRESETS)
    embed = discord.Embed(
        title="🎨 Warna Nama Kamu",
        description=(
            "Bikin namamu menonjol di chat! Pilih warna favoritmu, atau buat sendiri.\n\n"
            f"{swatches}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🖌️ **Warna Custom** — masukkan kode HEX bebas (contoh `FF5733`)\n"
            "♻️ **Reset Warna** — balik ke warna role bawaan\n\n"
            "_Khusus member terverifikasi. Warna staff tetap prioritas._"
        ),
        color=0xE91E8C,
    )
    embed.set_footer(text="BalikLayar AI • Color Roles")
    return embed
