#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SB Cyber Journey - "OSI vs TCP/IP" Instagram Reel generator
============================================================
1080 x 1920 (9:16) | 30 FPS | 750 frames | exactly 25 s | H.264 / YUV420p | English only

Modes
-----
  python make_osi_tcpip_reel.py --validate          quick checks + sample frames + contact sheet
  python make_osi_tcpip_reel.py --validate --full   same, but also renders all 750 frames (no encode)
  python make_osi_tcpip_reel.py --preview           live preview window (ESC quit, SPACE pause, <- -> seek, R restart)
  python make_osi_tcpip_reel.py --frame 300         save a single frame as PNG
  python make_osi_tcpip_reel.py --render            render + export SB_Cyber_Journey_OSI_vs_TCPIP_Reel.mp4

Logo:  assets/sb_cyber_journey_logo.png  (next to this script). If it is missing a placeholder
       shield is drawn instead and the program keeps running.
FFmpeg: must be on PATH, or set FFMPEG_PATH, or put ffmpeg.exe in ./ffmpeg/bin/ or next to this script.

Everything is a pure function of time t (timestamp based), so preview and render look identical.
"""
import os
import sys
import math
import time
import shutil
import argparse
import random
import subprocess

# Headless rendering unless a live preview window is requested.
if "--preview" not in sys.argv:
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

try:
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except Exception:
    pass

try:
    import numpy as np
    import pygame
except ImportError as exc:
    sys.exit("Missing dependency: %s\nRun:  python -m pip install pygame numpy pillow" % exc.name)

try:
    from PIL import Image
except ImportError:  # Pillow is optional (logo loading + contact sheet)
    Image = None

# ----------------------------------------------------------------------------
# Video constants
# ----------------------------------------------------------------------------
W, H = 1080, 1920
FPS = 30
DURATION = 25
TOTAL_FRAMES = FPS * DURATION  # 750
SAFE_X0, SAFE_X1, SAFE_Y0, SAFE_Y1 = 80, 900, 220, 1550
PW = SAFE_X1 - SAFE_X0         # 820
CX = (SAFE_X0 + SAFE_X1) // 2  # 490 : centre of the safe column

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH = os.path.join(BASE_DIR, "assets", "sb_cyber_journey_logo.png")
OUTPUT_NAME = "SB_Cyber_Journey_OSI_vs_TCPIP_Reel.mp4"

SCENES = [("hook", 0, 3), ("osi", 3, 10), ("tcpip", 10, 16), ("compare", 16, 21), ("brand", 21, 25)]

# ----------------------------------------------------------------------------
# Colours
# ----------------------------------------------------------------------------
NAVY = (5, 8, 22)
CYAN = (0, 229, 255)
BLUE = (60, 140, 255)
PURPLE = (150, 90, 255)
PURPLE_L = (190, 150, 255)
MAGENTA = (215, 75, 235)
WHITE = (240, 248, 255)
DIM = (150, 175, 205)
GREY = (130, 145, 175)

# ----------------------------------------------------------------------------
# Content (technically checked)
# ----------------------------------------------------------------------------
OSI_LAYERS = [
    (7, "Application", "HTTP, DNS, SMTP"),
    (6, "Presentation", "Data formats, encoding, encryption concepts"),
    (5, "Session", "Communication sessions"),
    (4, "Transport", "TCP, UDP, ports"),
    (3, "Network", "IP addressing, routing"),
    (2, "Data Link", "Frames, MAC addresses"),
    (1, "Physical", "Bits, electrical, optical, radio signals"),
]
TCP_LAYERS = [
    ("Application", "HTTP, DNS, DHCP", "OSI 7 + 6 + 5"),
    ("Transport", "TCP and UDP", "OSI 4"),
    ("Internet", "IP and routing", "OSI 3"),
    ("Network Access", "Ethernet and Wi-Fi link technologies", "OSI 2 + 1"),
]
OSI_TO_TCP = [0, 0, 0, 1, 2, 3, 3]
GROUP_COL = [(0, 229, 255), (60, 140, 255), (150, 90, 255), (215, 75, 235)]
OSI_COL = [(0, 229, 255), (0, 198, 255), (24, 166, 255), (60, 140, 255),
           (150, 90, 255), (190, 80, 245), (215, 75, 235)]

CHIP_COL = {"DATA": CYAN, "TCP": BLUE, "IP": PURPLE, "ETH": MAGENTA, "FCS": GREY, "BITS": CYAN}

# (PDU label, [(chip, is_newly_added)])
OSI_STAGES = [
    ("DATA - APPLICATION MESSAGE", [("DATA", 1)]),
    ("DATA - ENCODED / ENCRYPTED", [("DATA", 1)]),
    ("DATA - SESSION CONTEXT", [("DATA", 1)]),
    ("SEGMENT (TCP) / DATAGRAM (UDP)", [("TCP", 1), ("DATA", 0)]),
    ("PACKET", [("IP", 1), ("TCP", 0), ("DATA", 0)]),
    ("FRAME", [("ETH", 1), ("IP", 0), ("TCP", 0), ("DATA", 0), ("FCS", 1)]),
    ("BITS ON THE WIRE", [("BITS", 1)]),
]
TCP_STAGES = [
    ("MESSAGE (APPLICATION DATA)", [("DATA", 1)]),
    ("TCP SEGMENT / UDP DATAGRAM", [("TCP", 1), ("DATA", 0)]),
    ("IP PACKET", [("IP", 1), ("TCP", 0), ("DATA", 0)]),
    ("FRAME (ETHERNET / WI-FI)", [("ETH", 1), ("IP", 0), ("TCP", 0), ("DATA", 0), ("FCS", 1)]),
    ("BITS / SIGNALS", [("BITS", 1)]),
]

# Layer geometry (all inside the safe column)
OSI_RECTS = [pygame.Rect(SAFE_X0, 290 + k * 164, PW, 150) for k in range(7)]   # 290..1424
TCP_RECTS = [pygame.Rect(SAFE_X0, 290 + k * 245, PW, 215) for k in range(4)]   # 290..1240
CMP_OSI = [pygame.Rect(110, 300 + k * 72, 790, 64) for k in range(7)]          # 300..796
CMP_TCP = [pygame.Rect(110, 890 + k * 112, 790, 100) for k in range(4)]        # 890..1326
STRIP_RECT = pygame.Rect(SAFE_X0, 1446, PW, 100)                               # encapsulation strip

S_DUR = 2.7 / 7.0    # seconds per OSI layer while the packet goes down
R_DUR = 1.25 / 7.0   # seconds per OSI layer on the receiver sweep

# ----------------------------------------------------------------------------
# Math helpers
# ----------------------------------------------------------------------------
def clamp(x, a=0.0, b=1.0):
    return a if x < a else b if x > b else x


def lerp(a, b, u):
    return a + (b - a) * u


def seg(t, a, b):
    """Normalised progress of t inside [a, b], clamped to 0..1."""
    if b <= a:
        return 1.0 if t >= a else 0.0
    return clamp((t - a) / (b - a))


def e_out(u):
    return 1.0 - (1.0 - u) ** 3


def e_in(u):
    return u * u * u


def e_inout(u):
    return u * u * (3.0 - 2.0 * u)


def e_back(u):
    c1 = 1.70158
    c3 = c1 + 1.0
    return 1.0 + c3 * (u - 1.0) ** 3 + c1 * (u - 1.0) ** 2


def mix(c1, c2, u):
    u = clamp(u)
    return tuple(int(lerp(a, b, u)) for a, b in zip(c1, c2))


def scale_col(c, k):
    return tuple(int(clamp(v * k, 0, 255)) for v in c)


def lerp_rect(a, b, u):
    return pygame.Rect(int(lerp(a.x, b.x, u)), int(lerp(a.y, b.y, u)),
                       int(lerp(a.w, b.w, u)), int(lerp(a.h, b.h, u)))


def poly_info(pts):
    cum = [0.0]
    for a, b in zip(pts, pts[1:]):
        cum.append(cum[-1] + math.dist(a, b))
    return cum


def poly_at(pts, cum, u):
    total = cum[-1]
    if total <= 0:
        return pts[0]
    d = clamp(u) * total
    for i in range(1, len(cum)):
        if d <= cum[i]:
            sl = (cum[i] - cum[i - 1]) or 1.0
            k = (d - cum[i - 1]) / sl
            return (lerp(pts[i - 1][0], pts[i][0], k), lerp(pts[i - 1][1], pts[i][1], k))
    return pts[-1]


def draw_poly_progress(frame, pts, u, color, width):
    total = sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))
    if total <= 0 or u <= 0:
        return
    left = u * total
    for a, b in zip(pts, pts[1:]):
        length = math.dist(a, b)
        if left >= length:
            pygame.draw.line(frame, color, a, b, width)
            left -= length
        else:
            if length > 0:
                k = left / length
                pygame.draw.line(frame, color, a, (a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k), width)
            break


# ----------------------------------------------------------------------------
# Camera (zoom + parallax applied to background layers by coordinate transform)
# ----------------------------------------------------------------------------
def zoom_at(t):
    if t < 2.5:
        return 1.0 + 0.08 * e_inout(seg(t, 0, 2.5))
    if t < 3.0:
        return lerp(1.08, 1.40, e_in(seg(t, 2.5, 3.0)))
    if t < 4.2:
        return lerp(1.40, 1.0, e_out(seg(t, 3.0, 4.2)))
    if t < 21.0:
        return 1.0 + 0.04 * seg(t, 4.2, 21.0)
    return 1.04 + 0.16 * e_inout(seg(t, 21.0, 25.0))


class Cam:
    __slots__ = ("z", "px", "py")

    def __init__(self, t):
        self.z = zoom_at(t)
        self.px = 14.0 * math.sin(t * 0.6)
        self.py = 22.0 * math.sin(t * 0.4 + 1.0)

    def zf(self, depth=1.0):
        return 1.0 + (self.z - 1.0) * depth

    def pt(self, x, y, depth=1.0):
        z = self.zf(depth)
        return ((x - W / 2) * z + W / 2 + self.px * depth, (y - H / 2) * z + H / 2 + self.py * depth)


# ----------------------------------------------------------------------------
# Fonts / text
# ----------------------------------------------------------------------------
FONT_NAMES = "bahnschrift,segoeui,arial,dejavusans,freesans"
_font_cache = {}
_fit_cache = {}
_parts_cache = {}
TEXT_LOG = None  # list while validating


def font(size, bold=True):
    key = (int(size), bold)
    f = _font_cache.get(key)
    if f is None:
        f = pygame.font.SysFont(FONT_NAMES, int(size), bold=bold)
        _font_cache[key] = f
    return f


def fit_font(text, max_w, size, bold=True, min_size=20):
    key = (text, max_w, size, bold)
    f = _fit_cache.get(key)
    if f is None:
        s = int(size)
        while s > min_size and font(s, bold).size(text)[0] > max_w:
            s -= 2
        f = font(s, bold)
        _fit_cache[key] = f
    return f


def blit_img(frame, img, center, scale=1.0, alpha=1.0):
    if alpha <= 0.01:
        return None
    if abs(scale - 1.0) > 0.005:
        img = pygame.transform.smoothscale(
            img, (max(1, int(img.get_width() * scale)), max(1, int(img.get_height() * scale))))
    if alpha < 0.995:
        img = img.copy()
        img.set_alpha(int(255 * alpha))
    r = img.get_rect(center=(int(center[0]), int(center[1])))
    frame.blit(img, r)
    return r


def draw_text(frame, text, pos, size, color=WHITE, bold=True, anchor="center", max_w=None,
              alpha=1.0, scale=1.0, check=True):
    f = fit_font(text, max_w, size, bold) if max_w else font(size, bold)
    img = f.render(text, True, color)
    w, h = img.get_size()
    cx, cy = pos
    if anchor == "midleft":
        cx = pos[0] + w * scale / 2.0
    elif anchor == "midright":
        cx = pos[0] - w * scale / 2.0
    r = blit_img(frame, img, (cx, cy), scale, alpha)
    if r is not None and TEXT_LOG is not None and check and alpha >= 0.9 and 0.95 <= scale <= 1.05:
        TEXT_LOG.append((text, r.copy()))
    return r


def render_parts(parts, size, max_w):
    key = (tuple(parts), size, max_w)
    s = _parts_cache.get(key)
    if s is not None:
        return s
    sz = size
    while True:
        f = font(sz, True)
        widths = [f.size(t)[0] for t, _ in parts]
        if sum(widths) <= max_w or sz <= 24:
            break
        sz -= 2
    surf = pygame.Surface((sum(widths), f.get_linesize()), pygame.SRCALPHA)
    x = 0
    for (t, c), w in zip(parts, widths):
        surf.blit(f.render(t, True, c), (x, 0))
        x += w
    _parts_cache[key] = surf
    return surf


def with_alpha(frame, rect, alpha, fn, pad=30):
    """Run fn(target, local_rect); when alpha < 1 draw into a temporary surface and fade it in."""
    global TEXT_LOG
    if alpha <= 0.01:
        return
    if alpha >= 0.99:
        fn(frame, rect)
        return
    tmp = pygame.Surface((rect.w + 2 * pad, rect.h + 2 * pad), pygame.SRCALPHA)
    saved = TEXT_LOG
    TEXT_LOG = None
    try:
        fn(tmp, pygame.Rect(pad, pad, rect.w, rect.h))
    finally:
        TEXT_LOG = saved
    tmp.set_alpha(int(255 * alpha))
    frame.blit(tmp, (rect.x - pad, rect.y - pad))


# ----------------------------------------------------------------------------
# Glow + post-processing
# ----------------------------------------------------------------------------
_glow_cache = {}


def add_glow(frame, pos, radius, color, k=1.0):
    radius = min(int(radius), 170)
    if k <= 0.03 or radius < 6:
        return
    col = tuple((min(255, int(c * k)) // 16) * 16 for c in color)
    if max(col) < 16:
        return
    rq = max(8, radius // 4 * 4)
    key = (col, rq)
    spr = _glow_cache.get(key)
    if spr is None:
        if len(_glow_cache) > 500:
            _glow_cache.clear()
        n = rq * 2
        yy, xx = np.mgrid[0:n, 0:n]
        d = np.hypot(xx - rq + 0.5, yy - rq + 0.5) / rq
        f = np.clip(1.0 - d, 0.0, 1.0) ** 2.2
        arr = np.zeros((n, n, 3), dtype=np.uint8)
        for i in range(3):
            arr[:, :, i] = (f * col[i]).astype(np.uint8)
        spr = pygame.surfarray.make_surface(np.ascontiguousarray(arr.swapaxes(0, 1)))
        _glow_cache[key] = spr
    frame.blit(spr, (int(pos[0]) - rq, int(pos[1]) - rq), special_flags=pygame.BLEND_RGB_ADD)


def bloom(frame):
    s1 = pygame.transform.smoothscale(frame, (W // 8, H // 8))
    s2 = pygame.transform.smoothscale(s1, (W // 24, H // 24))
    b2 = pygame.transform.smoothscale(s2, (W, H))
    b2.fill((95, 95, 95), special_flags=pygame.BLEND_RGB_MULT)
    frame.blit(b2, (0, 0), special_flags=pygame.BLEND_RGB_ADD)
    b1 = pygame.transform.smoothscale(s1, (W, H))
    b1.fill((60, 60, 60), special_flags=pygame.BLEND_RGB_MULT)
    frame.blit(b1, (0, 0), special_flags=pygame.BLEND_RGB_ADD)


# ----------------------------------------------------------------------------
# Icons
# ----------------------------------------------------------------------------
def draw_computer(frame, c, s, col, lit=0.0, k=1.0):
    x, y = c
    cc = scale_col(col, (0.62 + 0.38 * lit) * k)
    mon = pygame.Rect(0, 0, max(8, int(110 * s)), max(6, int(74 * s)))
    mon.center = (int(x), int(y - 8 * s))
    br = max(3, int(9 * s))
    bw = max(2, int(4 * s))
    pygame.draw.rect(frame, scale_col((7, 14, 34), k), mon, border_radius=br)
    pygame.draw.rect(frame, cc, mon, bw, border_radius=br)
    for j in range(3):
        ly = mon.y + int((18 + j * 17) * s)
        pygame.draw.line(frame, scale_col(col, (0.4 + 0.5 * lit) * k),
                         (mon.x + int(16 * s), ly), (mon.x + int((78 - j * 16) * s), ly), max(2, int(3 * s)))
    pygame.draw.rect(frame, cc, (int(x - 7 * s), mon.bottom, max(2, int(14 * s)), max(2, int(14 * s))))
    pygame.draw.rect(frame, cc, (int(x - 30 * s), mon.bottom + int(14 * s), max(6, int(60 * s)), max(2, int(6 * s))),
                     border_radius=3)
    if lit > 0.02:
        add_glow(frame, (x, y), int(95 * s), col, 0.55 * lit * k)


def draw_server(frame, c, s, col, lit=0.0, k=1.0):
    x, y = c
    cc = scale_col(col, (0.62 + 0.38 * lit) * k)
    for j in range(3):
        r = pygame.Rect(0, 0, max(8, int(96 * s)), max(6, int(30 * s)))
        r.center = (int(x), int(y + (j - 1) * 38 * s))
        pygame.draw.rect(frame, scale_col((7, 14, 34), k), r, border_radius=max(3, int(7 * s)))
        pygame.draw.rect(frame, cc, r, max(2, int(3 * s)), border_radius=max(3, int(7 * s)))
        pygame.draw.circle(frame, scale_col(CYAN, (0.5 + 0.5 * lit) * k), (r.x + int(14 * s), r.centery), max(2, int(4 * s)))
        pygame.draw.circle(frame, scale_col(PURPLE_L, 0.8 * k), (r.x + int(28 * s), r.centery), max(2, int(4 * s)))
        pygame.draw.line(frame, scale_col(col, 0.5 * k), (r.x + int(46 * s), r.centery), (r.right - int(12 * s), r.centery),
                         max(2, int(3 * s)))
    if lit > 0.02:
        add_glow(frame, (x, y), int(100 * s), col, 0.55 * lit * k)


def draw_router(frame, c, s, col, lit=0.0, k=1.0):
    x, y = c
    cc = scale_col(col, (0.62 + 0.38 * lit) * k)
    r = pygame.Rect(0, 0, max(8, int(100 * s)), max(6, int(36 * s)))
    r.center = (int(x), int(y + 6 * s))
    for dx in (-30, 30):
        pygame.draw.line(frame, cc, (int(x + dx * s), r.top), (int(x + dx * 1.5 * s), r.top - int(30 * s)), max(2, int(4 * s)))
        pygame.draw.circle(frame, cc, (int(x + dx * 1.5 * s), r.top - int(30 * s)), max(2, int(5 * s)))
    pygame.draw.rect(frame, scale_col((7, 14, 34), k), r, border_radius=max(3, int(9 * s)))
    pygame.draw.rect(frame, cc, r, max(2, int(4 * s)), border_radius=max(3, int(9 * s)))
    for j in range(3):
        pygame.draw.circle(frame, scale_col(CYAN, (0.4 + 0.6 * lit) * k), (r.x + int((24 + j * 26) * s), r.centery), max(2, int(5 * s)))
    if lit > 0.02:
        add_glow(frame, (x, y), int(90 * s), col, 0.6 * lit * k)


# ----------------------------------------------------------------------------
# Procedural assets (built once)
# ----------------------------------------------------------------------------
BG_BASE = VIGNETTE = None
NET_NODES, NET_EDGES, NET_PULSES, ICON_NODES, ICON_SET = [], [], [], [], set()
CIRCUITS, PARTS = [], []
LOGO_FIT, LOGO_STATUS = None, "not loaded"


def build_background():
    yy = np.linspace(0.0, 1.0, H)[:, None]
    top = np.array([12, 20, 56], float)
    mid = np.array([5, 8, 22], float)
    bot = np.array([1, 3, 9], float)
    grad = np.where(yy < 0.5, top + (mid - top) * (yy / 0.5), mid + (bot - mid) * ((yy - 0.5) / 0.5))  # (H,3)
    base = np.broadcast_to(grad[None, :, :], (W, H, 3)).copy()
    xs = np.linspace(-1, 1, W)[:, None]
    ys = np.linspace(-1, 1, H)[None, :]
    d = np.hypot(xs * 0.8, (ys - 0.1) * 0.55)
    glow = np.clip(1.0 - d * 1.1, 0, 1) ** 2
    base += glow[:, :, None] * np.array([0, 28, 48], float)
    surf = pygame.surfarray.make_surface(np.clip(base, 0, 255).astype(np.uint8))
    r = np.sqrt((xs * 0.9) ** 2 + (ys * 0.75) ** 2)
    v = 1.0 - 0.45 * np.clip(r - 0.35, 0, 1) ** 1.4
    varr = np.repeat(np.clip(255 * v, 0, 255).astype(np.uint8)[:, :, None], 3, axis=2)
    return surf, pygame.surfarray.make_surface(varr)


def build_network(rng):
    cols, rows = 5, 8
    nodes, idx = [], {}
    for r in range(rows):
        for c in range(cols):
            idx[(c, r)] = len(nodes)
            nodes.append((-60 + c * 300 + rng.randint(-60, 60), -60 + r * 290 + rng.randint(-60, 60), c, r))
    edges = []
    for r in range(rows):
        for c in range(cols):
            a = idx[(c, r)]
            if c + 1 < cols:
                edges.append((a, idx[(c + 1, r)]))
            if r + 1 < rows:
                edges.append((a, idx[(c, r + 1)]))
            if c + 1 < cols and r + 1 < rows and rng.random() < 0.35:
                edges.append((a, idx[(c + 1, r + 1)]))
    pulses = [(rng.randrange(len(edges)), rng.uniform(0.10, 0.28), rng.random(), rng.random() < 0.5) for _ in range(44)]
    icons = [i for i, (x, y, c, r) in enumerate(nodes) if 70 < x < 1010 and 90 < y < 1830 and (c + r) % 2 == 0]
    return nodes, edges, pulses, icons


def build_circuits(rng):
    dirs = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]
    out = []
    for _ in range(22):
        x = rng.choice([rng.randint(0, W), 0, W])
        y = rng.randint(0, H)
        di = rng.randrange(8)
        pts = [(x, y)]
        for _ in range(rng.randint(4, 8)):
            ln = rng.randint(70, 240)
            x += dirs[di][0] * ln
            y += dirs[di][1] * ln
            pts.append((x, y))
            di = (di + rng.choice([-1, 1])) % 8
        out.append((pts, poly_info(pts)))
    return out


def build_logo():
    """Load the real logo (aspect preserved). Fall back to a placeholder shield if it is missing."""
    box = 340
    if os.path.isfile(LOGO_PATH):
        try:
            if Image is not None:
                im = Image.open(LOGO_PATH).convert("RGBA")
                data = im.tobytes()
                surf = pygame.image.frombuffer(data, im.size, "RGBA").convert_alpha().copy()
            else:
                surf = pygame.image.load(LOGO_PATH).convert_alpha()
            sc = min(box / surf.get_width(), box / surf.get_height())
            size = (max(1, int(surf.get_width() * sc)), max(1, int(surf.get_height() * sc)))
            return pygame.transform.smoothscale(surf, size), "loaded: %s (%dx%d -> %dx%d)" % (
                LOGO_PATH, surf.get_width(), surf.get_height(), size[0], size[1])
        except Exception as exc:  # noqa
            status = "could not load logo (%s) - using placeholder" % exc
    else:
        status = "logo file not found at %s - using placeholder shield" % LOGO_PATH
    s = pygame.Surface((300, 340), pygame.SRCALPHA)
    pts = [(150, 8), (284, 52), (284, 170), (150, 332), (16, 170), (16, 52)]
    pygame.draw.polygon(s, (8, 20, 50), pts)
    pygame.draw.polygon(s, CYAN, pts, 8)
    pygame.draw.polygon(s, PURPLE, [(150, 40), (252, 72), (252, 164), (150, 290), (48, 164), (48, 72)], 3)
    t = font(120, True).render("SB", True, WHITE)
    s.blit(t, t.get_rect(center=(150, 160)))
    return s, status


def init_assets():
    global BG_BASE, VIGNETTE, NET_NODES, NET_EDGES, NET_PULSES, ICON_NODES, ICON_SET, CIRCUITS, PARTS
    global LOGO_FIT, LOGO_STATUS
    BG_BASE, VIGNETTE = build_background()
    rng = random.Random(2025)
    NET_NODES, NET_EDGES, NET_PULSES, ICON_NODES = build_network(rng)
    ICON_SET = set(ICON_NODES)
    CIRCUITS = build_circuits(rng)
    PARTS = [(rng.uniform(0, W), rng.uniform(0, H + 120), rng.uniform(14, 60), rng.choice([1, 2, 2, 3]),
              rng.uniform(0, 6.28)) for _ in range(90)]
    LOGO_FIT, LOGO_STATUS = build_logo()


def init_pygame(preview=False):
    pygame.display.init()
    pygame.font.init()
    screen = pygame.display.set_mode((540, 960) if preview else (64, 64))
    if preview:
        pygame.display.set_caption("SB Cyber Journey - OSI vs TCP/IP preview")
    init_assets()
    return screen


# ----------------------------------------------------------------------------
# Background layers
# ----------------------------------------------------------------------------
def draw_circuits(frame, cam, t, ci):
    d = 0.35
    col = scale_col((0, 70, 105), ci)
    for n, (pts, cum) in enumerate(CIRCUITS):
        tp = [cam.pt(x, y, d) for x, y in pts]
        pygame.draw.lines(frame, col, False, tp, 2)
        pygame.draw.circle(frame, col, (int(tp[0][0]), int(tp[0][1])), 6, 2)
        pygame.draw.circle(frame, col, (int(tp[-1][0]), int(tp[-1][1])), 6, 2)
        if n % 3 == 0:
            p = poly_at(pts, cum, (t * 0.10 + n * 0.137) % 1.0)
            q = cam.pt(p[0], p[1], d)
            add_glow(frame, q, 26, CYAN, 0.55 * ci)
            pygame.draw.circle(frame, scale_col(CYAN, 0.9 * ci), (int(q[0]), int(q[1])), 3)


def draw_grid(frame, cam, t, gi):
    d = 0.6
    for k in range(-2, 15):
        x = k * 90
        wave = 0.5 + 0.5 * math.sin(t * 1.3 + k * 0.7)
        c = scale_col((0, 100, 140), (0.25 + 0.55 * wave) * gi * (1.5 if k % 4 == 0 else 1.0))
        pygame.draw.line(frame, c, cam.pt(x, -250, d), cam.pt(x, H + 250, d), 2)
    off = (t * 50.0) % 90.0
    for k in range(-3, 26):
        y = k * 90 - off
        wave = 0.5 + 0.5 * math.sin(t * 1.1 - k * 0.5)
        c = scale_col((0, 100, 140), (0.25 + 0.55 * wave) * gi * (1.5 if k % 4 == 0 else 1.0))
        pygame.draw.line(frame, c, cam.pt(-250, y, d), cam.pt(W + 250, y, d), 2)


def draw_particles(frame, cam, t):
    for x0, y0, spd, sz, ph in PARTS:
        y = (y0 - spd * t) % (H + 120) - 60
        x = x0 + 18 * math.sin(t * 0.7 + ph)
        px, py = cam.pt(x, y, 0.5)
        tw = 0.45 + 0.55 * math.sin(t * 2.1 + ph * 3) ** 2
        pygame.draw.circle(frame, scale_col((120, 230, 255), tw * 0.9), (int(px), int(py)), sz)


def draw_scan(frame, t):
    y = int((t * 430) % (H + 500)) - 250
    for j in range(-8, 9):
        yy = y + j * 3
        if 0 <= yy < H:
            a = 1.0 - abs(j) / 9.0
            frame.fill((0, int(26 * a), int(38 * a)), (0, yy, W, 3), special_flags=pygame.BLEND_RGB_ADD)


def draw_network(frame, cam, t, ni, show_icons, npulse):
    zf = cam.zf()
    pts = [cam.pt(x, y) for x, y, _, _ in NET_NODES]
    ec = scale_col((0, 125, 170), ni)
    for a, b in NET_EDGES:
        pygame.draw.line(frame, ec, pts[a], pts[b], max(1, int(2 * zf)))
    nc = scale_col(CYAN, 0.45 + 0.55 * ni)
    for i, p in enumerate(pts):
        if show_icons and i in ICON_SET:
            continue
        pygame.draw.circle(frame, nc, (int(p[0]), int(p[1])), max(3, int(6 * zf)))
        if ni > 0.5:
            add_glow(frame, p, int(26 * zf), CYAN, 0.25 * ni * (0.5 + 0.5 * math.sin(t * 2.0 + i)))
    for ei, spd, ph, rev in NET_PULSES[:npulse]:
        a, b = NET_EDGES[ei]
        u = (t * spd + ph) % 1.0
        if rev:
            u = 1.0 - u
        for tr in range(5):
            uu = u + (tr * 0.035 if rev else -tr * 0.035)
            if not 0.0 <= uu <= 1.0:
                continue
            x = lerp(pts[a][0], pts[b][0], uu)
            y = lerp(pts[a][1], pts[b][1], uu)
            pygame.draw.circle(frame, scale_col((170, 245, 255), (1 - tr / 5.0) * (0.35 + 0.65 * ni)),
                               (int(x), int(y)), max(2, int((6 - tr) * zf)))
            if tr == 0:
                add_glow(frame, (x, y), int(30 * zf), CYAN, 0.7 * ni)
    if show_icons:
        for n, i in enumerate(ICON_NODES):
            u = e_back(seg(t, 21.0 + 0.06 * n, 21.5 + 0.06 * n))
            if u > 0.02:
                draw_computer(frame, pts[i], 0.75 * zf * u, CYAN, lit=0.35 + 0.35 * math.sin(t * 2.2 + i))


# ----------------------------------------------------------------------------
# Scene 1 - Hook (0-3 s)
# ----------------------------------------------------------------------------
HOOK_PATH = [(180, 1380), (390, 1190), (560, 1300), (700, 1070), (860, 900)]
HOOK_CUM = poly_info(HOOK_PATH)


def draw_hook(frame, cam, t):
    if t >= 3.05:
        return
    zf = cam.zf()
    pts = [cam.pt(x, y) for x, y in HOOK_PATH]
    reveal = seg(t, 0.1, 0.6)
    for a, b in zip(pts, pts[1:]):
        pygame.draw.line(frame, scale_col((0, 95, 130), reveal), a, b, max(2, int(3 * zf)))
    u = e_inout(seg(t, 0.5, 2.3))
    draw_poly_progress(frame, pts, u, CYAN, max(3, int(6 * zf)))
    total = HOOK_CUM[-1]
    fade = 1.0 - seg(t, 2.6, 3.0)
    for i in range(1, len(pts) - 1):
        lit = 1.0 if u >= HOOK_CUM[i] / total else 0.0
        draw_router(frame, pts[i], 0.62 * zf, CYAN, lit=lit, k=reveal)
    pc_lit = 0.5 + 0.5 * math.sin(t * 9.0) if t < 0.9 else 0.3
    draw_computer(frame, pts[0], 1.0 * zf, CYAN, lit=pc_lit, k=reveal)
    srv_lit = 0.3 + 0.7 * (1.0 - seg(t, 2.3, 3.0)) if u >= 1.0 else 0.25
    draw_server(frame, pts[-1], 1.0 * zf, CYAN, lit=srv_lit, k=reveal)
    draw_text(frame, "YOUR DEVICE", (pts[0][0], pts[0][1] + 92 * zf), 28, DIM, alpha=reveal * fade, check=False)
    draw_text(frame, "SERVER", (pts[-1][0], pts[-1][1] + 98 * zf), 28, DIM, alpha=reveal * fade, check=False)
    if 0.0 < u < 1.0:
        for k in range(12):
            p = poly_at(HOOK_PATH, HOOK_CUM, max(0.0, u - 0.012 * k))
            q = cam.pt(p[0], p[1])
            pygame.draw.circle(frame, scale_col((190, 245, 255), 1 - k / 12.0), (int(q[0]), int(q[1])),
                               max(3, int((15 - k) * zf)))
        p = poly_at(HOOK_PATH, HOOK_CUM, u)
        q = cam.pt(p[0], p[1])
        add_glow(frame, q, int(70 * zf), CYAN, 0.95)
        pygame.draw.circle(frame, WHITE, (int(q[0]), int(q[1])), max(4, int(8 * zf)))
    if t > 2.3:
        ring = seg(t, 2.3, 2.9)
        pygame.draw.circle(frame, scale_col(CYAN, 1 - ring), (int(pts[-1][0]), int(pts[-1][1])),
                           int((40 + 170 * ring) * zf), 3)
    # headline
    a1 = min(seg(t, 0.15, 0.5), 1.0 - seg(t, 1.9, 2.3))
    if a1 > 0:
        sc = lerp(0.7, 1.0, e_back(seg(t, 0.15, 0.6)))
        off = -e_in(seg(t, 1.9, 2.3)) * 130
        draw_text(frame, "HOW DOES DATA", (CX, 380 + off), 110, WHITE, max_w=PW, alpha=a1, scale=sc)
        draw_text(frame, "TRAVEL?", (CX, 520 + off), 150, CYAN, max_w=PW, alpha=a1, scale=sc)
    a3 = min(seg(t, 2.25, 2.55), 1.0 - seg(t, 2.75, 3.0))
    if a3 > 0:
        img = render_parts([("OSI", CYAN), (" vs ", WHITE), ("TCP/IP", PURPLE_L)], 120, PW)
        sc = lerp(0.7, 1.0, e_back(seg(t, 2.25, 2.7))) * lerp(1.0, 1.5, e_in(seg(t, 2.75, 3.0)))
        r = blit_img(frame, img, (CX, 470), sc, a3)
        if r is not None and TEXT_LOG is not None and a3 >= 0.9 and 0.95 <= sc <= 1.05:
            TEXT_LOG.append(("OSI vs TCP/IP", r.copy()))


# ----------------------------------------------------------------------------
# Panels / strip / labels (scenes 2-4)
# ----------------------------------------------------------------------------
def panel_body(target, r, color, lit, num, title, subs, title_size, sub_size, text_a):
    rad = max(10, min(22, r.h // 5))
    base = mix((7, 12, 30), color, 0.10 + 0.30 * lit)
    pygame.draw.rect(target, base, r, border_radius=rad)
    if lit > 0.05:
        for k in range(1, 5):
            pygame.draw.rect(target, scale_col(color, 0.55 * lit * (1 - k / 5.0)), r.inflate(8 * k, 8 * k), 2,
                             border_radius=rad + 3 * k)
    pygame.draw.rect(target, mix(scale_col(color, 0.7), WHITE, 0.35 * lit), r, 3 + int(3 * lit), border_radius=rad)
    pygame.draw.rect(target, color, pygame.Rect(r.x + 14, r.y + 16, 8, r.h - 32), border_radius=4)
    left = r.x + 44
    if num is not None:
        br = min(40, int(0.34 * r.h))
        c = (r.x + 36 + br, r.centery)
        pygame.draw.circle(target, mix((7, 12, 30), color, 0.35), c, br)
        pygame.draw.circle(target, color, c, br, 3)
        draw_text(target, str(num), c, int(br * 1.15), WHITE, alpha=text_a, check=False)
        left = r.x + 36 + 2 * br + 22
    avail = r.right - left - 24
    if subs:
        if r.h >= 120:
            ty, sy = r.centery - int(0.22 * r.h), r.centery + int(0.24 * r.h)
        else:
            ty, sy = r.centery - int(0.24 * r.h), r.centery + int(0.27 * r.h)
    else:
        ty, sy = r.centery, r.centery
    draw_text(target, title, (left, ty), title_size, WHITE, anchor="midleft", max_w=avail, alpha=text_a)
    for text, a in subs:
        if a * text_a > 0.02:
            draw_text(target, text, (left, sy), sub_size, mix(DIM, color, 0.25), bold=False, anchor="midleft",
                      max_w=avail, alpha=a * text_a)


def hl_glow(t, t0, dur):
    if t < t0:
        return 0.0
    if t < t0 + dur:
        return 1.0
    return max(0.0, 1.0 - (t - t0 - dur) / 0.6) * 0.45


def swap_dx(t):
    """Sender stack slides out, receiver stack slides in (7.6-8.15 s)."""
    if t < 7.6 or t >= 8.15:
        return 0
    if t < 7.85:
        return int(-1100 * e_in(seg(t, 7.6, 7.85)))
    return int(1100 * (1.0 - e_out(seg(t, 7.85, 8.15))))


def draw_osi_panels(frame, t):
    if t < 3.0 or t >= 10.5:
        return
    m = e_inout(seg(t, 9.4, 10.4))
    dx = swap_dx(t)
    for i, (num, name, sub) in enumerate(OSI_LAYERS):
        ti = 3.0 + 0.28 * i
        u = e_out(seg(t, ti, ti + 0.5))
        if u <= 0.0:
            continue
        g = OSI_TO_TCP[i]
        rect = lerp_rect(OSI_RECTS[i], TCP_RECTS[g], m) if m > 0 else OSI_RECTS[i].copy()
        rect.x += int((1 - u) * 1000 + dx)
        rv = (1.0 - seg(t, ti + 0.4, ti + 1.0)) * 0.9
        lit = max(rv, hl_glow(t, 4.9 + i * S_DUR, S_DUR), hl_glow(t, 8.15 + (6 - i) * R_DUR, R_DUR))
        col = mix(OSI_COL[i], GROUP_COL[g], m)
        alpha = 1.0 - seg(m, 0.55, 1.0)
        ta = 1.0 - seg(m, 0.0, 0.4)
        with_alpha(frame, rect, alpha,
                   lambda tg, r, _c=col, _l=lit, _n=num, _nm=name, _s=sub, _ta=ta:
                   panel_body(tg, r, _c, _l, _n, _nm, [(_s, 1.0)], 52, 32, _ta))


def draw_tcp_panels(frame, t):
    if t < 9.4 or t >= 21.3:
        return
    m = e_inout(seg(t, 9.4, 10.4))
    a_in = seg(m, 0.45, 1.0) if t < 10.4 else 1.0
    m4 = e_inout(seg(t, 16.0, 16.9))
    ex = e_in(seg(t, 20.5, 21.2))
    for k, (name, sub, mapping) in enumerate(TCP_LAYERS):
        rect = lerp_rect(TCP_RECTS[k], CMP_TCP[k], m4)
        rect.x += int(ex * 1100)
        lit = max((1.0 - seg(t, 10.4, 11.0)) * 0.5, hl_glow(t, 10.9 + 0.6 * k, 0.6),
                  hl_glow(t, 15.1 + 0.22 * (3 - k), 0.22), hl_glow(t, 17.2 + 0.38 * k + 0.3, 0.6))
        subs = [(sub, 1.0 - seg(m4, 0.0, 0.5)), (mapping, seg(m4, 0.5, 1.0))]
        tsz = int(lerp(58, 40, m4))
        ssz = int(lerp(36, 28, m4))
        with_alpha(frame, rect, a_in,
                   lambda tg, r, _k=k, _l=lit, _nm=name, _su=subs, _t=tsz, _s=ssz:
                   panel_body(tg, r, GROUP_COL[_k], _l, None, _nm, _su, _t, _s, 1.0))


LABELS = [
    (3.4, 4.9, "OSI MODEL - 7 LAYERS", CYAN, None),
    (4.9, 7.6, "SENDER - ENCAPSULATION", CYAN, "down"),
    (8.15, 9.3, "RECEIVER - DECAPSULATION", PURPLE_L, "up"),
    (10.4, 10.9, "TCP/IP MODEL - 4 LAYERS", PURPLE_L, None),
    (10.9, 13.3, "SENDER - ENCAPSULATION", CYAN, "down"),
    (13.3, 14.9, "ROUTED ACROSS THE NETWORK", BLUE, None),
    (14.9, 15.95, "RECEIVER - DECAPSULATION", PURPLE_L, "up"),
]


def draw_mode_label(frame, text, color, arrow, alpha, y=250):
    r = draw_text(frame, text, (CX, y), 38, color, max_w=PW - 70, alpha=alpha)
    if r is not None and arrow:
        ax, ay, s = r.left - 34, y, 14
        if arrow == "down":
            pts = [(ax - s, ay - s * 0.6), (ax + s, ay - s * 0.6), (ax, ay + s)]
        else:
            pts = [(ax - s, ay + s * 0.6), (ax + s, ay + s * 0.6), (ax, ay - s)]
        pygame.draw.polygon(frame, scale_col(color, alpha), pts)


def draw_labels(frame, t):
    for t0, t1, text, col, arrow in LABELS:
        a = min(seg(t, t0, t0 + 0.25), 1.0 - seg(t, t1 - 0.2, t1))
        if a > 0.01:
            draw_mode_label(frame, text.replace(" - ", " \u2014 "), col, arrow, a)


def bits_text(t):
    p = "1011001011010010"
    k = int(t * 14) % len(p)
    return " ".join((p[k:] + p[:k])[:12])


def draw_strip(frame, label, chips, t, dx=0, alpha=1.0):
    if alpha <= 0.01:
        return
    rect = STRIP_RECT.move(dx, 0)
    label = label.replace(" - ", " \u2014 ")

    def body(tg, r):
        pygame.draw.rect(tg, (6, 10, 26), r, border_radius=16)
        pygame.draw.rect(tg, scale_col(CYAN, 0.35), r, 2, border_radius=16)
        draw_text(tg, label, (r.centerx, r.y + 22), 28, DIM, max_w=r.w - 30)
        size = 32
        while True:
            f = font(size, True)
            items = []
            for name, new in chips:
                txt = bits_text(t) if name == "BITS" else name
                items.append((name, txt, new, f.size(txt)[0] + 30))
            total = sum(i[3] for i in items) + 10 * (len(items) - 1)
            if total <= r.w - 30 or size <= 20:
                break
            size -= 2
        x = r.centerx - total // 2
        cy = r.y + 68
        for name, txt, new, w in items:
            col = CHIP_COL.get(name, CYAN)
            cr = pygame.Rect(x, cy - 24, w, 48)
            pygame.draw.rect(tg, mix((8, 14, 34), col, 0.45 if new else 0.22), cr, border_radius=10)
            pygame.draw.rect(tg, col if new else scale_col(col, 0.6), cr, 3 if new else 2, border_radius=10)
            draw_text(tg, txt, cr.center, size, WHITE, check=False)
            x += w + 10

    with_alpha(frame, rect, alpha, body)


def strip_state(t):
    if 4.7 <= t < 9.5:
        a = min(seg(t, 4.7, 4.95), 1.0 - seg(t, 9.2, 9.5))
        dx, rec = 0, False
        if t < 7.6:
            idx = int(clamp(int((t - 4.9) / S_DUR), 0, 6))
        elif t < 8.15:
            idx, dx = 6, swap_dx(t)
        else:
            idx, rec = int(clamp(6 - int((t - 8.15) / R_DUR), 0, 6)), True
        label, chips = OSI_STAGES[idx]
        if rec and idx == 0:
            label = "DATA - DELIVERED TO THE APPLICATION"
        return label, chips, dx, a
    if 10.7 <= t < 16.3:
        a = min(seg(t, 10.7, 10.95), 1.0 - seg(t, 15.9, 16.2))
        rec = False
        if t < 13.3:
            k = int(clamp(int((t - 10.9) / 0.6), 0, 3))
            st = 4 if (k == 3 and t - 10.9 - 1.8 > 0.3) else k
        elif t < 15.1:
            st = 4
        else:
            st = int(clamp(3 - int((t - 15.1) / 0.22), 0, 3))
            rec = True
        label, chips = TCP_STAGES[st]
        if rec and st == 0:
            label = "DATA - DELIVERED TO THE APPLICATION"
        return label, chips, 0, a
    return None


def rail_f(t):
    if 4.9 <= t < 7.6:
        return "osi", clamp((t - 4.9) / S_DUR - 0.5, 0, 6)
    if 8.15 <= t < 9.35:
        return "osi", clamp(6 - ((t - 8.15) / R_DUR - 0.5), 0, 6)
    if 10.9 <= t < 13.3:
        return "tcp", clamp((t - 10.9) / 0.6 - 0.5, 0, 3)
    if 15.1 <= t < 15.98:
        return "tcp", clamp(3 - ((t - 15.1) / 0.22 - 0.5), 0, 3)
    return None


def rail_y(kind, f):
    R = OSI_RECTS if kind == "osi" else TCP_RECTS
    return R[0].centery + f * (R[1].centery - R[0].centery)


def draw_rail(frame, t):
    cur = rail_f(t)
    if not cur:
        return
    kind, f = cur
    for k in range(7, 0, -1):
        prev = rail_f(t - 0.03 * k)
        if prev and prev[0] == kind:
            pygame.draw.circle(frame, scale_col(CYAN, (1 - k / 8.0) * 0.8), (44, int(rail_y(kind, prev[1]))), max(2, 9 - k))
    y = rail_y(kind, f)
    add_glow(frame, (44, y), 46, CYAN, 0.9)
    pygame.draw.line(frame, CYAN, (44, y), (78, y), 4)
    pygame.draw.circle(frame, WHITE, (44, int(y)), 9)


JY = 1345
J_PTS = [(150, JY), (370, JY), (590, JY), (810, JY)]
J_CUM = poly_info(J_PTS)


def draw_journey(frame, t):
    k = min(seg(t, 10.6, 11.1), 1.0 - seg(t, 15.9, 16.3))
    if k <= 0.01:
        return
    u = e_inout(seg(t, 13.3, 14.9))
    for a, b in zip(J_PTS, J_PTS[1:]):
        pygame.draw.line(frame, scale_col((0, 95, 130), k), a, b, 4)
    draw_poly_progress(frame, J_PTS, u, scale_col(CYAN, k), 6)
    pc_lit = 0.6 + 0.4 * math.sin(t * 9.0) if 10.9 <= t < 13.6 else 0.25
    sv_lit = 0.5 + 0.5 * math.sin(t * 9.0) if 14.7 <= t < 16.0 else 0.25
    draw_computer(frame, J_PTS[0], 0.8, CYAN, lit=pc_lit, k=k)
    for i in (1, 2):
        near = clamp(1.0 - abs(u - i / 3.0) * 6.0, 0, 1) + (0.25 if u > i / 3.0 else 0.0)
        draw_router(frame, J_PTS[i], 0.8, CYAN, lit=clamp(near), k=k)
    draw_server(frame, J_PTS[3], 0.8, CYAN, lit=sv_lit, k=k)
    for (x, y), name in zip(J_PTS, ("YOUR DEVICE", "ROUTER", "ROUTER", "SERVER")):
        draw_text(frame, name, (x, JY + 70), 24, DIM, alpha=k, check=False)
    if 0.0 < u < 1.0:
        for j in range(10):
            p = poly_at(J_PTS, J_CUM, max(0.0, u - 0.012 * j))
            pygame.draw.circle(frame, scale_col((190, 245, 255), 1 - j / 10.0), (int(p[0]), int(p[1])), max(3, 12 - j))
        p = poly_at(J_PTS, J_CUM, u)
        add_glow(frame, p, 60, CYAN, 0.95)
        pygame.draw.circle(frame, WHITE, (int(p[0]), int(p[1])), 7)


# ----------------------------------------------------------------------------
# Scene 4 - comparison
# ----------------------------------------------------------------------------
def build_connectors():
    lanes = {1: 94, 2: 78, 3: 62}
    out = []
    for i in range(7):
        g = OSI_TO_TCP[i]
        ro, rt = CMP_OSI[i], CMP_TCP[g]
        if g == 0:
            pts = [(ro.right, ro.centery), (952, ro.centery), (952, rt.centery), (rt.right, rt.centery)]
        else:
            ln = lanes[g]
            pts = [(ro.left, ro.centery), (ln, ro.centery), (ln, rt.centery), (rt.left, rt.centery)]
        out.append((g, pts, poly_info(pts)))
    return out


CONNS = build_connectors()


def draw_compare(frame, t):
    if t < 16.0 or t >= 21.3:
        return
    ex = e_in(seg(t, 20.5, 21.2))
    m4 = e_inout(seg(t, 16.0, 16.9))
    fade_h = 1.0 - seg(t, 20.6, 21.0)
    ha = seg(t, 16.2, 16.6) * fade_h
    if ha > 0.01:
        draw_text(frame, "OSI MODEL \u2014 7 LAYERS", (CX, 258), 42, CYAN, max_w=PW - 20, alpha=ha)
    hb = seg(t, 15.95, 16.15) * fade_h
    if hb > 0.01:
        draw_text(frame, "TCP/IP MODEL \u2014 4 LAYERS", (CX, lerp(250, 846, m4)), 42, PURPLE_L, max_w=PW - 20, alpha=hb)
    for i, (num, name, _sub) in enumerate(OSI_LAYERS):
        d = 16.3 + 0.09 * i
        u = e_out(seg(t, d, d + 0.45))
        if u <= 0.0:
            continue
        g = OSI_TO_TCP[i]
        rect = CMP_OSI[i].move(int(-(1 - u) * 900 - ex * 1100), 0)
        lit = hl_glow(t, 17.2 + 0.38 * g, 0.6)
        with_alpha(frame, rect, 1.0,
                   lambda tg, r, _g=g, _l=lit, _n=num, _nm=name:
                   panel_body(tg, r, GROUP_COL[_g], _l, _n, _nm, [], 34, 26, 1.0))
    ac = 1.0 - seg(t, 20.5, 21.0)
    if ac > 0.01:
        for n, (g, pts, cum) in enumerate(CONNS):
            t0 = 17.2 + 0.38 * g
            u = e_inout(seg(t, t0, t0 + 0.6))
            if u <= 0.0:
                continue
            col = GROUP_COL[g]
            draw_poly_progress(frame, pts, u, scale_col(col, ac), 4)
            if u >= 1.0 and t >= 18.8:
                p = poly_at(pts, cum, ((t - 18.8) * 0.6 + n * 0.17) % 1.0)
                add_glow(frame, p, 28, col, 0.9 * ac)
                pygame.draw.circle(frame, scale_col(WHITE, ac), (int(p[0]), int(p[1])), 5)
    ca = seg(t, 18.6, 19.1) * (1.0 - seg(t, 20.4, 20.9))
    if ca > 0.01:
        box = pygame.Rect(SAFE_X0, 1346, PW, 196)

        def body(tg, r):
            pygame.draw.rect(tg, (5, 9, 26), r, border_radius=22)
            pygame.draw.rect(tg, scale_col(CYAN, 0.4), r, 2, border_radius=22)
            lines = ["OSI is a reference model.", "TCP/IP is a practical protocol suite", "and layered architecture."]
            for j, ln in enumerate(lines):
                draw_text(tg, ln, (r.centerx, r.y + 30 + j * 42), 34, WHITE, bold=(j == 0), max_w=r.w - 40)
            draw_text(tg, "CONCEPTUAL MAPPING \u2014 NOT A PERFECT 1:1 MATCH", (r.centerx, r.y + 162), 26, CYAN,
                      max_w=r.w - 30)

        with_alpha(frame, box, ca, body)


# ----------------------------------------------------------------------------
# Scene 5 - brand ending
# ----------------------------------------------------------------------------
def draw_brand(frame, t):
    if t < 20.9:
        return
    plate = pygame.Rect(SAFE_X0, 300, PW, 900)

    def pbody(tg, r):
        pygame.draw.rect(tg, (4, 8, 24), r, border_radius=36)
        pygame.draw.rect(tg, scale_col(CYAN, 0.45), r, 3, border_radius=36)

    with_alpha(frame, plate, seg(t, 21.0, 21.6) * 0.62, pbody)

    def line(text, y, size, color, t0, t1=None):
        t1 = t1 if t1 is not None else t0 + 0.45
        a = seg(t, t0, t0 + 0.4)
        if a > 0.01:
            sc = lerp(0.7, 1.0, e_back(seg(t, t0, t1)))
            draw_text(frame, text, (CX, y), size, color, max_w=PW - 50, alpha=a, scale=sc)

    line("UNDERSTAND THE LAYERS.", 390, 60, WHITE, 21.3)
    line("UNDERSTAND THE NETWORK.", 480, 60, CYAN, 22.1)
    la = seg(t, 23.0, 23.4)
    if la > 0.01 and LOGO_FIT is not None:
        sc = lerp(0.6, 1.0, e_back(seg(t, 23.0, 23.6)))
        add_glow(frame, (CX, 770), 210, CYAN, 0.55 * la * (0.8 + 0.2 * math.sin(t * 3)))
        blit_img(frame, LOGO_FIT, (CX, 770), sc, la)
    line("SB CYBER JOURNEY", 1050, 84, WHITE, 23.3)
    line("LEARN \u2022 PRACTICE \u2022 SECURE \u2022 GROW", 1130, 40, CYAN, 23.8)


# ----------------------------------------------------------------------------
# Frame composition
# ----------------------------------------------------------------------------
def render_frame(frame, t):
    cam = Cam(t)
    frame.blit(BG_BASE, (0, 0))
    if t < 3.4:
        ni, gi = lerp(0.95, 0.30, seg(t, 2.4, 3.4)), lerp(1.0, 0.65, seg(t, 2.4, 3.4))
    elif t < 20.6:
        ni, gi = 0.30, 0.65
    else:
        s = seg(t, 20.6, 21.8)
        ni, gi = lerp(0.30, 1.0, s), lerp(0.65, 0.95, s)
    npulse = 14 if t < 20.6 else int(lerp(14, 40, seg(t, 20.6, 22.0)))
    draw_circuits(frame, cam, t, 0.8)
    draw_grid(frame, cam, t, gi)
    draw_network(frame, cam, t, ni, t >= 21.0, npulse)
    draw_particles(frame, cam, t)
    draw_scan(frame, t)

    draw_hook(frame, cam, t)
    draw_osi_panels(frame, t)
    draw_tcp_panels(frame, t)
    draw_compare(frame, t)
    draw_labels(frame, t)
    st = strip_state(t)
    if st:
        draw_strip(frame, st[0], st[1], t, st[2], st[3])
    draw_rail(frame, t)
    draw_journey(frame, t)
    draw_brand(frame, t)

    for tb in (3.0, 10.0, 16.0, 21.0):
        k = int(36 * max(0.0, 1.0 - abs(t - tb) / 0.22))
        if k > 0:
            frame.fill((0, k, int(k * 1.1)), special_flags=pygame.BLEND_RGB_ADD)
    bloom(frame)
    frame.blit(VIGNETTE, (0, 0), special_flags=pygame.BLEND_RGB_MULT)
    return frame


def scene_at(t):
    for name, a, b in SCENES:
        if a <= t < b:
            return name
    return SCENES[-1][0]


_to_bytes = getattr(pygame.image, "tobytes", None) or pygame.image.tostring


def frame_bytes(frame):
    return _to_bytes(frame, "RGB")


# ----------------------------------------------------------------------------
# FFmpeg helpers
# ----------------------------------------------------------------------------
def find_ffmpeg():
    cands = [os.environ.get("FFMPEG_PATH"), shutil.which("ffmpeg"),
             os.path.join(BASE_DIR, "ffmpeg", "bin", "ffmpeg.exe"), os.path.join(BASE_DIR, "ffmpeg.exe"),
             os.path.join(BASE_DIR, "ffmpeg", "ffmpeg.exe")]
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


def find_tool(name, ffmpeg_path):
    exe = name + (".exe" if os.name == "nt" else "")
    if ffmpeg_path:
        c = os.path.join(os.path.dirname(ffmpeg_path), exe)
        if os.path.isfile(c):
            return c
    return shutil.which(name)


def build_ffmpeg_cmd(ffmpeg, out, crf, preset, music):
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (W, H),
           "-r", str(FPS), "-i", "-"]
    if music:
        cmd += ["-i", music]
    cmd += ["-map", "0:v:0"]
    if music:
        cmd += ["-map", "1:a:0", "-c:a", "aac", "-b:a", "192k", "-af", "afade=t=out:st=23.5:d=1.5"]
    cmd += ["-vf", "scale=out_color_matrix=bt709:out_range=tv", "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
            "-profile:v", "high", "-level:v", "4.2", "-pix_fmt", "yuv420p", "-g", "60", "-bf", "2",
            "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
            "-r", str(FPS), "-frames:v", str(TOTAL_FRAMES), "-t", str(DURATION), "-movflags", "+faststart", out]
    return cmd


def probe_output(ffmpeg, out):
    ffprobe = find_tool("ffprobe", ffmpeg)
    if not ffprobe:
        print("[WARN] ffprobe not found - skipping output verification")
        return True
    res = subprocess.run([ffprobe, "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                          "stream=codec_name,width,height,pix_fmt,r_frame_rate,nb_read_frames,duration",
                          "-of", "default=noprint_wrappers=1", out], capture_output=True, text=True)
    info = dict(line.split("=", 1) for line in res.stdout.splitlines() if "=" in line)
    print("ffprobe:", info)
    ok = True
    checks = [("codec_name", "h264"), ("width", "1080"), ("height", "1920"), ("pix_fmt", "yuv420p"),
              ("r_frame_rate", "30/1"), ("nb_read_frames", "750")]
    for key, want in checks:
        good = info.get(key) == want
        ok &= good
        print("  [%s] %s = %s (expected %s)" % ("OK" if good else "FAIL", key, info.get(key), want))
    try:
        dur = float(info.get("duration", "0"))
        good = abs(dur - 25.0) < 0.05
    except ValueError:
        good, dur = False, None
    ok &= good
    print("  [%s] duration = %s (expected 25.0)" % ("OK" if good else "FAIL", dur))
    return ok


# ----------------------------------------------------------------------------
# Modes
# ----------------------------------------------------------------------------
def safe(s):
    return str(s).encode("ascii", "replace").decode()


def validate(full=False):
    global TEXT_LOG
    fails, warns = [], []

    def ok(msg):
        print("[OK]   " + msg)

    def warn(msg):
        warns.append(msg)
        print("[WARN] " + msg)

    def fail(msg):
        fails.append(msg)
        print("[FAIL] " + msg)

    print("Python %s | pygame %s | numpy %s | Pillow %s" % (
        sys.version.split()[0], pygame.version.ver, np.__version__, "yes" if Image else "no (optional)"))
    if int(pygame.version.ver.split(".")[0]) < 2:
        fail("pygame 2.x required (pip install -U pygame)")
    init_pygame()
    ff = find_ffmpeg()
    if ff:
        ver = subprocess.run([ff, "-version"], capture_output=True, text=True).stdout.splitlines()[:1]
        ok("FFmpeg: %s (%s)" % (ff, ver[0] if ver else "?"))
        enc = subprocess.run([ff, "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
        if "libx264" in enc:
            ok("libx264 encoder available")
        else:
            fail("this FFmpeg build has no libx264 encoder - install a full build (gyan.dev)")
    else:
        warn("FFmpeg not found (needed only for --render). Add it to PATH or set FFMPEG_PATH.")

    if TOTAL_FRAMES == 750 and FPS * DURATION == TOTAL_FRAMES and (W, H) == (1080, 1920):
        ok("timing constants: %dx%d @ %d FPS x %d s = %d frames" % (W, H, FPS, DURATION, TOTAL_FRAMES))
    else:
        fail("timing constants are wrong")
    contiguous = SCENES[0][1] == 0 and SCENES[-1][2] == DURATION and all(
        a[2] == b[1] for a, b in zip(SCENES, SCENES[1:]))
    (ok if contiguous else fail)("scene boundaries contiguous: " + ", ".join(
        "%s %d-%ds (frames %d-%d)" % (n, a, b, a * FPS, b * FPS - 1) for n, a, b in SCENES))

    found = [n for n in FONT_NAMES.split(",") if pygame.font.match_font(n)]
    if found:
        ok("fonts found: " + ", ".join(found) + " (first match is used)")
    else:
        warn("none of the preferred fonts were found - pygame default font will be used (layout auto-fits)")
    (ok if LOGO_STATUS.startswith("loaded") else warn)("logo: " + safe(LOGO_STATUS))
    if LOGO_FIT is not None:
        ok("logo drawn at %dx%d (aspect ratio preserved, never stretched)" % LOGO_FIT.get_size())

    samples = [(0.0, "hook start", False), (1.5, "hook headline", True), (2.5, "OSI vs TCP/IP title", False),
               (3.5, "osi slide-in", False), (6.0, "osi encapsulation", True), (7.9, "stack swap", False),
               (8.8, "osi receiver", True), (10.0, "morph 7 -> 4", False), (12.0, "tcp/ip sender", True),
               (14.2, "routers journey", True), (15.5, "tcp/ip receiver", True), (17.6, "compare mapping", False),
               (19.5, "compare final", True), (20.9, "exit to brand", False), (22.5, "brand network", True),
               (24.9667, "final frame", True)]
    outdir = os.path.join(BASE_DIR, "validation_frames")
    os.makedirs(outdir, exist_ok=True)
    frame = pygame.Surface((W, H))
    thumbs = []
    for t, label, check_text in samples:
        TEXT_LOG = [] if check_text else None
        try:
            render_frame(frame, t)
        except Exception as exc:  # noqa
            fail("render error at t=%.2f (%s): %r" % (t, label, exc))
            TEXT_LOG = None
            continue
        if frame.get_size() != (W, H):
            fail("wrong frame size at t=%.2f" % t)
        avg = pygame.transform.average_color(frame)
        if sum(avg[:3]) < 12:
            fail("t=%.2f (%s): frame looks blank (avg colour %s)" % (t, label, avg[:3]))
        for nm, rc in (("left", (0, 0, 8, H)), ("right", (W - 8, 0, 8, H)), ("top", (0, 0, W, 8)), ("bottom", (0, H - 8, W, 8))):
            if sum(pygame.transform.average_color(frame, rc)[:3]) == 0:
                fail("t=%.2f (%s): pure-black %s border (black bar?)" % (t, label, nm))
        if TEXT_LOG is not None:
            for text, r in TEXT_LOG:
                if r.left < SAFE_X0 - 2 or r.right > SAFE_X1 + 2 or r.top < SAFE_Y0 - 2 or r.bottom > SAFE_Y1 + 2:
                    warn("t=%.2f text outside safe area: '%s' %s" % (t, safe(text), tuple(r)))
            for i in range(len(TEXT_LOG)):
                for j in range(i + 1, len(TEXT_LOG)):
                    if TEXT_LOG[i][1].colliderect(TEXT_LOG[j][1]):
                        warn("t=%.2f overlapping text: '%s' / '%s'" % (t, safe(TEXT_LOG[i][0]), safe(TEXT_LOG[j][0])))
        TEXT_LOG = None
        path = os.path.join(outdir, "t%05.2f_%s.png" % (t, label.replace(" ", "_").replace(">", "").replace("/", "")))
        pygame.image.save(frame, path)
        thumbs.append((t, label, pygame.transform.smoothscale(frame, (270, 480))))
    ok("rendered %d sample frames -> %s" % (len(thumbs), outdir))

    # motion check: consecutive frames must differ
    a = pygame.transform.smoothscale(render_frame(frame, 12.0), (135, 240)).copy()
    b = pygame.transform.smoothscale(render_frame(frame, 12.0 + 1.0 / FPS), (135, 240)).copy()
    diff = float(np.abs(pygame.surfarray.array3d(a).astype(int) - pygame.surfarray.array3d(b).astype(int)).mean())
    (ok if diff > 0 else warn)("frame-to-frame motion check (mean diff %.3f)" % diff)

    # contact sheet
    if thumbs:
        cols = 4
        rows = (len(thumbs) + cols - 1) // cols
        sheet = pygame.Surface((cols * 270, rows * 480))
        for i, (_, _, th) in enumerate(thumbs):
            sheet.blit(th, ((i % cols) * 270, (i // cols) * 480))
        sp = os.path.join(BASE_DIR, "validation_contact_sheet.png")
        pygame.image.save(sheet, sp)
        ok("contact sheet: " + sp)

    # speed estimate / optional full pass
    t0 = time.time()
    for i in range(0, 10):
        render_frame(frame, 6.0 + i / FPS)
        frame_bytes(frame)
    per = (time.time() - t0) / 10
    print("[INFO] ~%.0f ms/frame -> estimated full render ~%.1f min (excluding x264 time)" % (per * 1000, per * TOTAL_FRAMES / 60))
    if full:
        print("Rendering all %d frames (no encoding)..." % TOTAL_FRAMES)
        t0 = time.time()
        low = 1e9
        for i in range(TOTAL_FRAMES):
            render_frame(frame, i / FPS)
            low = min(low, sum(pygame.transform.average_color(frame)[:3]))
        ok("all %d frames rendered without errors in %.1f s (darkest frame avg-sum %.0f)" % (TOTAL_FRAMES, time.time() - t0, low))
        if low < 12:
            fail("at least one near-black frame detected")

    print("\nRESULT: %s  (%d failure(s), %d warning(s))" % ("FAIL" if fails else "PASS", len(fails), len(warns)))
    print("Note: validation checks the program's own rules; it does not replace watching the exported video once.")
    return 1 if fails else 0


def render(args):
    ff = find_ffmpeg()
    if not ff:
        sys.exit("FFmpeg not found. Install it and add it to PATH, or set FFMPEG_PATH (see README).")
    init_pygame()
    print("Logo:", safe(LOGO_STATUS))
    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    cmd = build_ffmpeg_cmd(ff, out, args.crf, args.preset, args.music)
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    frame = pygame.Surface((W, H))
    start = time.time()
    try:
        for i in range(TOTAL_FRAMES):
            render_frame(frame, i / FPS)
            proc.stdin.write(frame_bytes(frame))
            if i % 15 == 0 or i == TOTAL_FRAMES - 1:
                el = time.time() - start
                eta = el / (i + 1) * (TOTAL_FRAMES - i - 1)
                print("\rframe %d/%d  (%.0f%%)  elapsed %.0fs  eta %.0fs " % (i + 1, TOTAL_FRAMES, 100 * (i + 1) / TOTAL_FRAMES, el, eta),
                      end="", flush=True)
        proc.stdin.close()
    except (BrokenPipeError, OSError):
        err = proc.stderr.read().decode(errors="replace")
        sys.exit("\nFFmpeg stopped early:\n" + err)
    err = proc.stderr.read().decode(errors="replace")
    rc = proc.wait()
    print()
    if rc != 0:
        sys.exit("FFmpeg failed (code %d):\n%s" % (rc, err))
    print("Done in %.1f s -> %s" % (time.time() - start, out))
    return 0 if probe_output(ff, out) else 1


def preview():
    screen = init_pygame(preview=True)
    frame = pygame.Surface((W, H))
    clock = pygame.time.Clock()
    play_t, paused, running = 0.0, False, True
    while running:
        dt = clock.tick(30) / 1000.0
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT or (ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE):
                running = False
            elif ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_SPACE:
                    paused = not paused
                elif ev.key == pygame.K_r:
                    play_t = 0.0
                elif ev.key == pygame.K_RIGHT:
                    play_t = min(DURATION - 1.0 / FPS, play_t + 1.0)
                elif ev.key == pygame.K_LEFT:
                    play_t = max(0.0, play_t - 1.0)
        if not paused:
            play_t = (play_t + dt) % DURATION
        render_frame(frame, play_t)
        screen.blit(pygame.transform.smoothscale(frame, (540, 960)), (0, 0))
        pygame.display.flip()
        pygame.display.set_caption("t=%.2fs  scene=%s  %.0f fps%s" % (play_t, scene_at(play_t), clock.get_fps(), "  [paused]" if paused else ""))
    pygame.quit()
    return 0


def save_frame(n):
    init_pygame()
    n = int(clamp(n, 0, TOTAL_FRAMES - 1))
    frame = pygame.Surface((W, H))
    render_frame(frame, n / FPS)
    path = os.path.join(BASE_DIR, "frame_%04d.png" % n)
    pygame.image.save(frame, path)
    print("saved", path)
    return 0


def main():
    ap = argparse.ArgumentParser(description="SB Cyber Journey - OSI vs TCP/IP Instagram Reel generator")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--validate", action="store_true", help="run checks and write sample frames")
    g.add_argument("--preview", action="store_true", help="live preview window")
    g.add_argument("--render", action="store_true", help="render and export the MP4")
    g.add_argument("--frame", type=int, metavar="N", help="save frame N (0-749) as PNG")
    ap.add_argument("--full", action="store_true", help="with --validate: render all 750 frames (no encoding)")
    ap.add_argument("--out", default=os.path.join(BASE_DIR, OUTPUT_NAME), help="output MP4 path")
    ap.add_argument("--music", default=None, help="optional audio file to mix in (AAC, fades out at the end)")
    ap.add_argument("--crf", type=int, default=16, help="x264 quality (lower = better, default 16)")
    ap.add_argument("--preset", default="slow", help="x264 preset (default slow)")
    args = ap.parse_args()
    if args.preview:
        return preview()
    if args.render:
        return render(args)
    if args.frame is not None:
        return save_frame(args.frame)
    return validate(full=args.full)


if __name__ == "__main__":
    sys.exit(main())
