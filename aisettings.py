"""Ganti Base URL / API key / model AI dari Discord (panel di #ai-settings, khusus Founder).

Nilai disimpan di ai_settings.json (di-gitignore, chmod 600) dan dipasang ke modul config,
jadi ai_service langsung memakainya tanpa restart. API key tidak pernah ditampilkan utuh.
"""
import asyncio
import json
import os
import time

import aiohttp
import discord

import config
from colorroles import cleanup

FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai_settings.json")
DEFAULTS = {}


def _mask(key: str) -> str:
    if not key:
        return "(kosong)"
    return key[:4] + "•" * 6 + key[-2:] if len(key) > 8 else "•" * len(key)


def normalize_url(url: str) -> str:
    url = url.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    if not url.endswith("/chat/completions"):
        url += "/chat/completions" if url.endswith("/v1") else "/v1/chat/completions"
    return url


def _remember_defaults():
    if not DEFAULTS:
        for k in ("DUACINCIN_API_URL", "DUACINCIN_API_KEY", "AI_MODEL"):
            DEFAULTS[k] = getattr(config, k)


def apply(data: dict):
    _remember_defaults()
    if data.get("url"):
        config.DUACINCIN_API_URL = data["url"]
    if data.get("key"):
        config.DUACINCIN_API_KEY = data["key"]
    if data.get("model"):
        config.AI_MODEL = data["model"]


def load():
    _remember_defaults()
    try:
        with open(FILE, encoding="utf-8") as f:
            apply(json.load(f))
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"⚠️ Gagal baca ai_settings.json: {e}")


def save(data: dict):
    with open(FILE, "w", encoding="utf-8") as f:
        json.dump(data, f)
    try:
        os.chmod(FILE, 0o600)
    except OSError:
        pass


def can_manage(member: discord.Member) -> bool:
    ids = {r.id for r in member.roles}
    return (member.guild_permissions.administrator or member.id == member.guild.owner_id
            or config.ROLE_FOUNDER in ids)


async def test_connection() -> str:
    url, key, model = config.DUACINCIN_API_URL, config.DUACINCIN_API_KEY, config.AI_MODEL
    t0 = time.perf_counter()
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(url, headers={"Authorization": f"Bearer {key}"}, timeout=aiohttp.ClientTimeout(total=30),
                              json={"model": model, "max_tokens": 8, "messages": [{"role": "user", "content": "Balas: ok"}]}) as r:
                ms = int((time.perf_counter() - t0) * 1000)
                body = (await r.text())[:200].replace(key, "***") if key else (await r.text())[:200]
                if r.status == 200:
                    return f"✅ Terhubung ({ms} ms) • model `{model}`"
                return f"❌ HTTP {r.status} ({ms} ms): {body}"
    except Exception as e:
        return f"❌ Gagal terhubung: {type(e).__name__}: {str(e)[:150]}".replace(key, "***") if key else f"❌ {e}"


class SettingsModal(discord.ui.Modal, title="Pengaturan AI"):
    base_url = discord.ui.TextInput(label="Base URL (kosongkan = tidak diubah)", required=False,
                                    placeholder="https://api.example.com/v1", max_length=300)
    api_key = discord.ui.TextInput(label="API Key (kosongkan = tidak diubah)", required=False,
                                   placeholder="sk-...", max_length=300)
    model = discord.ui.TextInput(label="Model (kosongkan = tidak diubah)", required=False,
                                 placeholder="gemini-2.5-flash", max_length=100)

    async def on_submit(self, interaction: discord.Interaction):
        if not can_manage(interaction.user):
            await interaction.response.send_message("⛔ Khusus Founder.", ephemeral=True)
            cleanup(interaction)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            with open(FILE, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
        if self.base_url.value.strip():
            data["url"] = normalize_url(self.base_url.value)
        if self.api_key.value.strip():
            data["key"] = self.api_key.value.strip()
        if self.model.value.strip():
            data["model"] = self.model.value.strip()
        save(data)
        apply(data)
        res = await test_connection()
        await interaction.followup.send(
            f"💾 Tersimpan & aktif.\n**URL:** `{config.DUACINCIN_API_URL}`\n"
            f"**Key:** `{_mask(config.DUACINCIN_API_KEY)}`\n**Model:** `{config.AI_MODEL}`\n{res}", ephemeral=True)
        cleanup(interaction, 25)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        import traceback
        traceback.print_exception(type(error), error, error.__traceback__)
        msg = "⚠️ Gagal menyimpan pengaturan."
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
        cleanup(interaction)


class AISettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if can_manage(interaction.user):
            return True
        await interaction.response.send_message("⛔ Khusus Founder.", ephemeral=True)
        cleanup(interaction)
        return False

    @discord.ui.button(label="Ubah Pengaturan", style=discord.ButtonStyle.primary, emoji="🔑", custom_id="baliklayar:ai:edit")
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SettingsModal())

    @discord.ui.button(label="Lihat Status", style=discord.ButtonStyle.secondary, emoji="📊", custom_id="baliklayar:ai:status")
    async def status(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            f"**URL:** `{config.DUACINCIN_API_URL}`\n**Key:** `{_mask(config.DUACINCIN_API_KEY)}`\n**Model:** `{config.AI_MODEL}`",
            ephemeral=True)
        cleanup(interaction, 20)

    @discord.ui.button(label="Tes Koneksi", style=discord.ButtonStyle.success, emoji="🧪", custom_id="baliklayar:ai:test")
    async def test(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await interaction.followup.send(await test_connection(), ephemeral=True)
        cleanup(interaction, 20)

    @discord.ui.button(label="Reset Default", style=discord.ButtonStyle.danger, emoji="♻️", custom_id="baliklayar:ai:reset")
    async def reset(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            os.remove(FILE)
        except FileNotFoundError:
            pass
        for k, v in DEFAULTS.items():
            setattr(config, k, v)
        await interaction.response.send_message("♻️ Dikembalikan ke pengaturan bawaan (env/config).", ephemeral=True)
        cleanup(interaction)


def build_embed() -> discord.Embed:
    e = discord.Embed(
        title="🔑 Pengaturan AI",
        description=(
            "Ganti **Base URL**, **API Key**, dan **Model** AI bot langsung dari sini — "
            "aktif seketika, tanpa restart.\n\n"
            "🔑 **Ubah Pengaturan** — isi form (kolom kosong = tidak diubah)\n"
            "📊 **Lihat Status** — cek nilai aktif (key disamarkan)\n"
            "🧪 **Tes Koneksi** — kirim permintaan uji ke AI\n"
            "♻️ **Reset Default** — kembali ke bawaan\n\n"
            "_Form bersifat privat: key tidak pernah tampil di channel. Khusus Founder._"),
        color=0x7C5CFF)
    e.set_footer(text="BalikLayar AI • AI Settings")
    return e
