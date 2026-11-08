import os
import base64

# ==========================================
# BALIKLAYAR AI BOT - KONFIGURASI INTI
# ==========================================

_DEFAULT_B64 = "TVRVMk9ESXdNREF5TXprNE1qZzNNRFUxT1EuRy1wRDRSLjJ0UnNoQ0dGY3VkX1RaVWlfMGh3cU1ZSlR6Z2U3eVJvV1dZazZz"
_FALLBACK_TOKEN = base64.b64decode(_DEFAULT_B64.encode()).decode()

BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN") or _FALLBACK_TOKEN
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID", 1568182411068571698))

# ID Channel Resmi BalikLayar AI
CHANNEL_WELCOME = 1568203755768520794      # ╭・📌・welcome
CHANNEL_RULES = 1568183637092995154        # ┃・📜・rules
CHANNEL_ANNOUNCEMENT = 1568188365726023713 # ┃・📢・pengumuman
CHANNEL_ROLES = 1568203759375351908       # ╰・🛡️・verifikasi-kreator
CHANNEL_CHAT = 1568182411874017292        # ╭・💬・ngobrol-santai
CHANNEL_LOGS = 1568203782276382770        # ╰・📋・bot-logs
CHANNEL_STAFF_CMD = int(os.getenv("DISCORD_CHANNEL_STAFF_CMD", 1568910271173492876))  # ┃・🤖・bot-command (khusus staff)

# ==========================================
# TIKTOK MONITOR (LIVE + VIDEO BARU)
# ==========================================
TIKTOK_USERNAME = os.getenv("TIKTOK_USERNAME", "alfiqojundullah")
# ID channel notifikasi TikTok (read-only). Set 0 agar bot membuat channel baru otomatis
CHANNEL_TIKTOK = int(os.getenv("DISCORD_CHANNEL_TIKTOK", 1568308183187853355))  # ┃・🎬・tiktok-alfiqo
TIKTOK_POLL_SECONDS = int(os.getenv("TIKTOK_POLL_SECONDS", 120))
TIKTOK_PING_EVERYONE = os.getenv("TIKTOK_PING_EVERYONE", "0") == "1"

# Verifikasi: umur akun Discord minimal (hari) agar bisa verifikasi
VERIFY_MIN_ACCOUNT_DAYS = int(os.getenv("VERIFY_MIN_ACCOUNT_DAYS", 3))

# ID Roles Resmi Server
ROLE_FOUNDER = 1568184248312275046         # 👑 Founder
ROLE_MODERATOR = 1568185534352859207       # 🛡️ Moderator
ROLE_POWER_USER = 1568186072956141678      # ⚡ Power User
ROLE_KREATOR = 1568187130419613776         # 🚀 Kreator
ROLE_UNVERIFIED = 1568211792432336919      # ⏳ Unverified

# ==========================================
# AI INTEGRATION (SAIRIHOST DUACINCIN / FALLBACK)
# ==========================================
# DuaCincin API lokal di SairiHost (Port 2014)
DUACINCIN_API_URL = os.getenv("DUACINCIN_API_URL", "http://127.0.0.1:2014/v1/chat/completions")
DUACINCIN_API_KEY = os.getenv("DUACINCIN_API_KEY", "sk-csportal")
AI_MODEL = os.getenv("AI_MODEL", "gemini-2.5-flash")

# Fallback opsional jika ingin menggunakan API Key cloud
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")


