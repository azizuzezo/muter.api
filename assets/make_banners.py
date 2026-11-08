"""Generate banner channel BalikLayar AI (1200x360). Jalankan: python assets/make_banners.py"""
import math, os, random
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

W, H = 1200, 360
OUT = os.path.join(os.path.dirname(__file__), "banners")
BOLD = "/usr/share/fonts/google-noto/NotoSans-Bold.ttf"
REG = "/usr/share/fonts/google-noto/NotoSans-Regular.ttf"
if not os.path.exists(BOLD):  # fallback Windows
    BOLD, REG = "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/arial.ttf"

# nama file, judul, subjudul, warna aksen, warna aksen 2
BANNERS = [
    ("rules", "RULES", "Aturan main komunitas BalikLayar AI", (255, 140, 66), (255, 77, 109)),
    ("welcome", "WELCOME", "Selamat datang di rumah kreator affiliate", (64, 196, 255), (124, 92, 255)),
    ("verifikasi", "VERIFIKASI", "Satu klik untuk jadi Kreator resmi", (46, 204, 113), (26, 188, 156)),
    ("warna-role", "WARNA ROLE", "Bikin namamu paling menonjol", (233, 30, 140), (155, 89, 182)),
    ("pengumuman", "PENGUMUMAN", "Update & info penting terbaru", (241, 196, 15), (255, 140, 66)),
    ("tiktok", "TIKTOK LIVE", "Notifikasi LIVE & video baru", (0, 242, 234), (255, 0, 80)),
]

def blend(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))

def make(name, title, sub, c1, c2):
    random.seed(name)
    base = Image.new("RGB", (W, H), (10, 11, 22))
    px = base.load()
    for y in range(H):  # gradasi gelap halus
        for x in range(W):
            t = (x / W) * 0.6 + (y / H) * 0.4
            px[x, y] = blend((9, 10, 20), (22, 16, 38), t)
    glow = Image.new("RGB", (W, H), (0, 0, 0))
    g = ImageDraw.Draw(glow)
    g.ellipse((W - 520, -200, W + 120, 360), fill=tuple(int(v * .55) for v in c1))
    g.ellipse((W - 760, 120, W - 140, 560), fill=tuple(int(v * .40) for v in c2))
    glow = glow.filter(ImageFilter.GaussianBlur(110))
    base = ImageChops.add(base, glow)
    d = ImageDraw.Draw(base, "RGBA")
    for _ in range(70):  # bintang/partikel kecil
        x, y, r = random.randint(0, W), random.randint(0, H), random.choice((1, 1, 2))
        d.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, random.randint(40, 120)))
    # garis diagonal dekoratif kanan
    for i in range(6):
        x0 = W - 380 + i * 46
        d.line((x0, H, x0 + 240, 0), fill=blend(c1, c2, i / 5) + (46,), width=3)
    # logo BalikLayar (rounded) + cincin aksen
    cx, cy, S = W - 170, H // 2, 200
    d.ellipse((cx - 150, cy - 150, cx + 150, cy + 150), outline=blend(c1, c2, .5) + (70,), width=2)
    halo = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(halo).rounded_rectangle(
        (cx - S // 2 - 6, cy - S // 2 - 6, cx + S // 2 + 6, cy + S // 2 + 6), 48, fill=blend(c1, c2, .5) + (150,))
    base.paste(halo.filter(ImageFilter.GaussianBlur(22)), (0, 0), halo.filter(ImageFilter.GaussianBlur(22)))
    logo = Image.open(os.path.join(os.path.dirname(__file__), "logo_baliklayar.png")).convert("RGBA").resize((S, S), Image.LANCZOS)
    m = Image.new("L", (S, S), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, S - 1, S - 1), 44, fill=255)
    base.paste(logo, (cx - S // 2, cy - S // 2), m)
    d = ImageDraw.Draw(base, "RGBA")
    d.rounded_rectangle((cx - S // 2, cy - S // 2, cx + S // 2, cy + S // 2), 44, outline=c1 + (200,), width=3)
    # teks
    tag = ImageFont.truetype(BOLD, 22)
    f1 = ImageFont.truetype(BOLD, 92 if len(title) < 10 else 76)
    f2 = ImageFont.truetype(REG, 30)
    d.rounded_rectangle((70, 70, 70 + 232, 70 + 40), 20, fill=blend(c1, c2, .3) + (60,), outline=c1 + (160,))
    d.text((70 + 116, 90), "BALIKLAYAR AI", font=tag, fill=(255, 255, 255, 235), anchor="mm")
    # judul dengan gradasi aksen
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).text((68, 128), title, font=f1, fill=255)
    grad = Image.new("RGB", (W, H))
    gp = ImageDraw.Draw(grad)
    for x in range(W):
        gp.line((x, 0, x, H), fill=blend((255, 255, 255), c1, min(1, x / 760)))
    base.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(base, "RGBA")
    d.text((72, 246), sub, font=f2, fill=(205, 210, 230, 235))
    d.rounded_rectangle((72, 300, 72 + 120, 306), 3, fill=c1 + (255,))
    d.rounded_rectangle((72 + 130, 300, 72 + 170, 306), 3, fill=c2 + (255,))
    base.save(os.path.join(OUT, f"{name}.png"), optimize=True)

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for b in BANNERS:
        make(*b)
    print("ok", len(BANNERS))
