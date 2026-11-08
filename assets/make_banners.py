"""Generate banner channel BalikLayar AI (1600x480). Jalankan: python assets/make_banners.py
Butuh: pillow, numpy."""
import math, os, random
import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(__file__)
OUT = os.path.join(HERE, "banners")
SS = 2                      # supersampling
W, H = 1600 * SS, 480 * SS
OW, OH = 1600, 480
BOLD = "/usr/share/fonts/google-noto/NotoSans-Bold.ttf"
REG = "/usr/share/fonts/google-noto/NotoSans-Regular.ttf"
if not os.path.exists(BOLD):
    BOLD, REG = "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/arial.ttf"

BANNERS = [
    ("rules", "RULES", "Aturan main komunitas BalikLayar AI", (255, 140, 66), (255, 77, 109), "doc"),
    ("welcome", "WELCOME", "Selamat datang di rumah kreator affiliate", (64, 196, 255), (124, 92, 255), "spark"),
    ("verifikasi", "VERIFIKASI", "Satu klik untuk jadi Kreator resmi", (46, 204, 113), (26, 188, 156), "shield"),
    ("warna-role", "WARNA ROLE", "Bikin namamu paling menonjol", (233, 30, 140), (155, 89, 182), "palette"),
    ("pengumuman", "PENGUMUMAN", "Update & info penting terbaru", (255, 193, 7), (255, 112, 67), "mega"),
    ("ai-settings", "AI SETTINGS", "Ganti API key, base URL & model", (124, 92, 255), (64, 196, 255), "key"),
    ("tiktok", "TIKTOK LIVE", "Notifikasi LIVE & video baru", (0, 242, 234), (255, 0, 80), "play"),
]

def s(v): return int(v * SS)
def blend(a, b, t): return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))
def font(p, size): return ImageFont.truetype(p, s(size))

def glow_layer(blobs):
    layer = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(layer)
    for x, y, r, col, k in blobs:
        d.ellipse((s(x - r), s(y - r), s(x + r), s(y + r)), fill=tuple(int(c * k) for c in col))
    return layer.filter(ImageFilter.GaussianBlur(s(95)))

def background(c1, c2, seed):
    random.seed(seed); np.random.seed(abs(hash(seed)) % 2**32)
    xx, yy = np.meshgrid(np.linspace(0, 1, W), np.linspace(0, 1, H))
    t = np.clip(xx * .65 + yy * .35, 0, 1)[..., None]
    a, b = np.array((7, 8, 18)), np.array((20, 14, 36))
    base = Image.fromarray((a + (b - a) * t).astype("uint8"))
    base = ImageChops.add(base, glow_layer([
        (1330, 90, 330, c1, .70), (1150, 470, 340, c2, .55),
        (520, 560, 330, c2, .20), (60, 40, 240, c1, .16)]))
    # vignette
    v = np.clip(1 - ((xx - .45) ** 2 * .9 + (yy - .5) ** 2 * 1.3), .45, 1)[..., None]
    base = Image.fromarray((np.array(base) * v).astype("uint8"))
    d = ImageDraw.Draw(base, "RGBA")
    # pola titik (grid) memudar ke kanan
    for gx in range(0, 1600, 28):
        for gy in range(0, 480, 28):
            a_ = int(70 * max(0, (gx / 1600 - .25)) * 1.4)
            if a_ > 4:
                d.ellipse((s(gx) - 2, s(gy) - 2, s(gx) + 2, s(gy) + 2), fill=(255, 255, 255, a_))
    # garis diagonal aksen
    for i in range(9):
        x0 = 980 + i * 52
        d.line((s(x0), H, s(x0 + 330), 0), fill=blend(c1, c2, i / 8) + (40,), width=s(2))
    # bokeh
    for _ in range(26):
        x, y, r = random.randint(700, 1600), random.randint(0, 480), random.choice((6, 9, 14, 22))
        col = blend(c1, c2, random.random())
        d.ellipse((s(x - r), s(y - r), s(x + r), s(y + r)), fill=col + (random.randint(18, 50),))
    for _ in range(90):
        x, y, r = random.randint(0, 1600), random.randint(0, 480), random.choice((1, 1, 2))
        d.ellipse((s(x - r), s(y - r), s(x + r), s(y + r)), fill=(255, 255, 255, random.randint(40, 140)))
    return base

def glass(base, box, radius, c1, c2, alpha=46):
    x0, y0, x1, y1 = [s(v) for v in box]
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((x0, y0 + s(12), x1, y1 + s(12)), s(radius), fill=(0, 0, 0, 160))
    sh = sh.filter(ImageFilter.GaussianBlur(s(18)))
    base.paste(sh, (0, 0), sh)
    d = ImageDraw.Draw(base, "RGBA")
    d.rounded_rectangle((x0, y0, x1, y1), s(radius), fill=(255, 255, 255, alpha))
    d.rounded_rectangle((x0, y0, x1, y1), s(radius), outline=blend(c1, c2, .4) + (170,), width=s(2))

def icon(d, kind, cx, cy, size, c1, c2):
    col = (255, 255, 255, 245); acc = c1 + (255,); u = size / 100
    P = lambda x, y: (s(cx + x * u), s(cy + y * u))
    if kind == "doc":
        d.rounded_rectangle((*P(-26, -34), *P(26, 34)), s(8 * u), fill=col)
        for i, w in enumerate((38, 38, 26)):
            d.rounded_rectangle((*P(-16, -20 + i * 14), *P(-16 + w, -14 + i * 14)), s(3 * u), fill=acc if i == 0 else (60, 60, 80, 255))
    elif kind == "shield":
        pts = [P(0, -38), P(32, -26), P(32, 6), P(0, 38), P(-32, 6), P(-32, -26)]
        d.polygon(pts, fill=col)
        d.line([P(-14, 2), P(-3, 14), P(17, -12)], fill=acc, width=s(9 * u), joint="curve")
    elif kind == "palette":
        for i, cc in enumerate((c1, c2, (255, 255, 255), blend(c1, c2, .5))):
            ang = i * math.pi / 2 + math.pi / 4
            x, y = 22 * math.cos(ang), 22 * math.sin(ang)
            d.ellipse((*P(x - 15, y - 15), *P(x + 15, y + 15)), fill=cc + (255,))
    elif kind == "mega":
        d.polygon([P(-30, -10), P(10, -10), P(34, -30), P(34, 30), P(10, 10), P(-30, 10)], fill=col)
        d.rounded_rectangle((*P(-22, 8), *P(-8, 34)), s(5 * u), fill=acc)
    elif kind == "play":
        d.polygon([P(-14, -26), P(-14, 26), P(30, 0)], fill=col)
        d.polygon([P(-19, -26), P(-19, 26), P(25, 0)], fill=(0, 242, 234, 90))
    elif kind == "key":
        d.ellipse((*P(-34, -22), *P(2, 14)), fill=col)
        d.ellipse((*P(-22, -10), *P(-10, 2)), fill=(30, 30, 50, 255))
        d.rounded_rectangle((*P(-4, -6), *P(36, 4)), s(4 * u), fill=col)
        d.rounded_rectangle((*P(22, 2), *P(30, 16)), s(3 * u), fill=acc)
    elif kind == "spark":
        pts = []
        for k in range(8):
            ang = math.pi / 4 * k - math.pi / 2
            rad = 38 if k % 2 == 0 else 9
            pts.append(P(rad * math.cos(ang), rad * math.sin(ang)))
        d.polygon(pts, fill=col)

def make(name, title, sub, c1, c2, kind):
    base = background(c1, c2, name)
    logo = Image.open(os.path.join(HERE, "logo_baliklayar.png")).convert("RGBA")

    # kartu kaca kanan + logo besar
    glass(base, (1130, 70, 1530, 410), 44, c1, c2, 30)
    S_ = 236
    cx, cy = 1330, 240
    halo = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(halo).rounded_rectangle(
        (s(cx - S_ / 2 - 8), s(cy - S_ / 2 - 8), s(cx + S_ / 2 + 8), s(cy + S_ / 2 + 8)),
        s(56), fill=blend(c1, c2, .5) + (190,))
    halo = halo.filter(ImageFilter.GaussianBlur(s(26)))
    base.paste(halo, (0, 0), halo)
    lg = logo.resize((s(S_), s(S_)), Image.LANCZOS)
    m = Image.new("L", lg.size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, lg.size[0] - 1, lg.size[1] - 1), s(54), fill=255)
    base.paste(lg, (s(cx - S_ / 2), s(cy - S_ / 2)), m)
    d = ImageDraw.Draw(base, "RGBA")
    d.rounded_rectangle((s(cx - S_ / 2), s(cy - S_ / 2), s(cx + S_ / 2), s(cy + S_ / 2)), s(54),
                        outline=blend(c1, c2, .2) + (230,), width=s(3))

    # chip ikon channel (kiri-atas kartu)
    chip = (1096, 60, 1196, 160)
    glass(base, chip, 28, c1, c2, 60)
    d = ImageDraw.Draw(base, "RGBA")
    icon(d, kind, 1146, 110, 62, c1, c2)

    # teks
    tag = font(BOLD, 24)
    d.rounded_rectangle((s(88), s(84), s(88 + 270), s(84 + 48)), s(24), fill=blend(c1, c2, .3) + (70,),
                        outline=c1 + (200,), width=s(2))
    d.ellipse((s(108), s(102), s(120), s(114)), fill=c1 + (255,))
    d.text((s(132), s(108)), "BALIKLAYAR AI", font=tag, fill=(255, 255, 255, 240), anchor="lm")

    fs = 128 if len(title) < 9 else (104 if len(title) < 12 else 92)
    f1, f2 = font(BOLD, fs), font(REG, 34)
    # bayangan + gradasi judul
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(sh).text((s(88), s(158)), title, font=f1, fill=c1 + (170,))
    sh = sh.filter(ImageFilter.GaussianBlur(s(22)))
    base.paste(sh, (0, 0), sh)
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).text((s(88), s(150)), title, font=f1, fill=255)
    gx = np.clip(np.linspace(0, 1, W) / 0.62, 0, 1)
    grad = np.zeros((H, W, 3), dtype="uint8")
    for i in range(3):
        grad[..., i] = (255 + (c1[i] - 255) * gx)[None, :]
    base.paste(Image.fromarray(grad), (0, 0), mask)
    d = ImageDraw.Draw(base, "RGBA")
    d.text((s(92), s(334)), sub, font=f2, fill=(214, 218, 238, 240))
    d.rounded_rectangle((s(92), s(392), s(92 + 150), s(400)), s(4), fill=c1 + (255,))
    d.rounded_rectangle((s(92 + 162), s(392), s(92 + 162 + 54), s(400)), s(4), fill=c2 + (255,))
    d.rounded_rectangle((s(92 + 228), s(392), s(92 + 228 + 20), s(400)), s(4), fill=(255, 255, 255, 120))

    base.resize((OW, OH), Image.LANCZOS).save(os.path.join(OUT, f"{name}.png"), optimize=True)

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for b in BANNERS:
        make(*b)
    print("ok", len(BANNERS))
