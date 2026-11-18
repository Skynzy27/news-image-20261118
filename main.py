#!/usr/bin/env python3
"""News in one picture: Wednesday 18 November 2026.

A one-page newspaper drawn entirely in code (Python 3.13, standard library
only, no network). It renders 43 real stories from Wednesday 18 November
2026 -- 3 hero stories, 10 mid-grid stories and 30 "also on" stories --
with a masthead, vector illustrations drawn by this program, a world map
with numbered pins matching the story numbers, and a sources footer, then
writes the result to /output/entry.png (1024x1024, deterministic: two runs
write identical bytes).

Text is drawn from glyph bitmaps packed in font.bin (DejaVu Serif/Sans,
rasterized at 64px by a build-time tool; the entry program only reads the
file with zlib+struct). Nothing is fetched at runtime.
"""

import math
import os
import struct
import sys
import zlib

W, H = 1024, 1024

# ---- palette: newspaper cream, ink, navy, red, teal, gold -----------------
PAPER = (247, 241, 222)
INK = (26, 26, 26)
GREY = (107, 107, 107)
LIGHT_GREY = (200, 192, 172)
NAVY = (31, 56, 100)
NAVY_DARK = (22, 42, 78)
RED = (185, 28, 28)
TEAL = (14, 124, 123)
GOLD = (201, 162, 39)
SEA = (168, 200, 220)
SEA_DARK = (140, 180, 205)
LAND = (232, 220, 192)
LAND2 = (222, 206, 168)
GREEN = (46, 125, 50)
PURPLE = (103, 58, 140)
ORANGE = (214, 110, 30)
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)


# ---- PNG encoder (deterministic, stdlib only) ------------------------------
def _crc(chunk_type, data):
    return zlib.crc32(chunk_type + data) & 0xFFFFFFFF


def _chunk(chunk_type, data):
    return (struct.pack(">I", len(data)) + chunk_type + data
            + struct.pack(">I", _crc(chunk_type, data)))


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _filter_row(row, prev, ftype):
    n = len(row)
    out = bytearray(n)
    if ftype == 0:
        return bytes(row)
    if ftype == 1:  # Sub
        for i in range(n):
            a = row[i - 3] if i >= 3 else 0
            out[i] = (row[i] - a) & 0xFF
    elif ftype == 2:  # Up
        for i in range(n):
            out[i] = (row[i] - prev[i]) & 0xFF
    elif ftype == 4:  # Paeth
        for i in range(n):
            a = row[i - 3] if i >= 3 else 0
            b = prev[i]
            c = prev[i - 3] if i >= 3 else 0
            out[i] = (row[i] - _paeth(a, b, c)) & 0xFF
    return bytes(out)


_ABS = [b if b <= 127 else 256 - b for b in range(256)]


def encode_png(width, height, rgb):
    """rgb: bytes-like of width*height*3. Returns deterministic PNG bytes."""
    raw = bytearray()
    stride = width * 3
    prev = bytes(stride)
    for y in range(height):
        line = bytes(rgb[y * stride:(y + 1) * stride])
        if line == prev:
            raw.append(2)
            raw += bytes(stride)
            continue
        best = None
        best_score = None
        for ftype in (0, 1, 2, 4):
            cand = _filter_row(line, prev, ftype)
            score = 0
            for b in cand:
                score += _ABS[b]
            if best_score is None or score < best_score:
                best_score = score
                best = (ftype, cand)
        raw.append(best[0])
        raw += best[1]
        prev = line
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n"
    png += _chunk(b"IHDR", ihdr)
    png += _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += _chunk(b"IEND", b"")
    return png


# ---- canvas: an RGB buffer with drawing primitives -------------------------
class Canvas:
    def __init__(self, w, h, bg):
        self.w = w
        self.h = h
        self.buf = bytearray(w * h * 3)
        self.fill_rect(0, 0, w, h, bg)

    def _idx(self, x, y):
        return (y * self.w + x) * 3

    def set_px(self, x, y, color):
        if 0 <= x < self.w and 0 <= y < self.h:
            i = self._idx(x, y)
            self.buf[i] = color[0]
            self.buf[i + 1] = color[1]
            self.buf[i + 2] = color[2]

    def blend_px(self, x, y, color, alpha):
        """Blend color over the existing pixel; alpha 0..255."""
        if alpha <= 0 or not (0 <= x < self.w and 0 <= y < self.h):
            return
        i = self._idx(x, y)
        if alpha >= 255:
            self.buf[i] = color[0]
            self.buf[i + 1] = color[1]
            self.buf[i + 2] = color[2]
            return
        inv = 255 - alpha
        self.buf[i] = (color[0] * alpha + self.buf[i] * inv) // 255
        self.buf[i + 1] = (color[1] * alpha + self.buf[i + 1] * inv) // 255
        self.buf[i + 2] = (color[2] * alpha + self.buf[i + 2] * inv) // 255

    def fill_rect(self, x, y, w, h, color):
        x0 = max(0, x)
        y0 = max(0, y)
        x1 = min(self.w, x + w)
        y1 = min(self.h, y + h)
        if x1 <= x0 or y1 <= y0:
            return
        row = bytes(color) * (x1 - x0)
        for yy in range(y0, y1):
            i = self._idx(x0, yy)
            self.buf[i:i + len(row)] = row

    def rect(self, x, y, w, h, color, lw=1):
        self.fill_rect(x, y, w, lw, color)
        self.fill_rect(x, y + h - lw, w, lw, color)
        self.fill_rect(x, y, lw, h, color)
        self.fill_rect(x + w - lw, y, lw, h, color)

    def hline(self, x, y, w, color, lw=1):
        self.fill_rect(x, y, w, lw, color)

    def vline(self, x, y, h, color, lw=1):
        self.fill_rect(x, y, lw, h, color)

    def line(self, x0, y0, x1, y1, color, lw=1):
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        while True:
            if lw <= 1:
                self.set_px(x0, y0, color)
            else:
                r = lw // 2
                self.fill_rect(x0 - r, y0 - r, lw, lw, color)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def circle(self, cx, cy, r, color, fill=True):
        if fill:
            for dy in range(-r, r + 1):
                dx = int((r * r - dy * dy) ** 0.5)
                self.fill_rect(cx - dx, cy + dy, 2 * dx + 1, 1, color)
        else:
            steps = max(8, int(2 * math.pi * r))
            for i in range(steps):
                a = 2 * math.pi * i / steps
                self.set_px(int(cx + r * math.cos(a)),
                            int(cy + r * math.sin(a)), color)

    def ellipse(self, cx, cy, rx, ry, color):
        for dy in range(-ry, ry + 1):
            t = 1.0 - (dy * dy) / float(ry * ry)
            if t < 0:
                continue
            dx = int(rx * (t ** 0.5))
            self.fill_rect(cx - dx, cy + dy, 2 * dx + 1, 1, color)

    def polygon(self, pts, color):
        """Scanline fill of a polygon given as [(x, y), ...]."""
        pts = [(int(px), int(py)) for px, py in pts]
        if len(pts) < 3:
            return
        ys = [p[1] for p in pts]
        y0, y1 = max(0, min(ys)), min(self.h - 1, max(ys))
        n = len(pts)
        for y in range(y0, y1 + 1):
            xs = []
            for i in range(n):
                x1, yy1 = pts[i]
                x2, yy2 = pts[(i + 1) % n]
                if (yy1 <= y < yy2) or (yy2 <= y < yy1):
                    if yy2 != yy1:
                        x = x1 + (y - yy1) * (x2 - x1) / (yy2 - yy1)
                        xs.append(x)
            xs.sort()
            for i in range(0, len(xs) - 1, 2):
                xa = int(xs[i] + 0.5)
                xb = int(xs[i + 1] + 0.5)
                if xb >= xa:
                    self.fill_rect(xa, y, xb - xa + 1, 1, color)


# ---- bitmap fonts (glyphs packed in font.bin, rasterized at 64px) ----------
FONT_SIZE = 64


class Font:
    def __init__(self, glyphs):
        # glyphs: {codepoint: (advance, xoff, yoff, w, h, bitmap_bytes)}
        self.glyphs = glyphs

    def advance(self, ch):
        g = self.glyphs.get(ord(ch))
        return g[0] if g else 0

    def text_width(self, s, size):
        scale = size / FONT_SIZE
        return sum(self.advance(c) for c in s) * scale


def load_fonts(path):
    with open(path, "rb") as f:
        raw = zlib.decompress(f.read())
    off = 0
    assert raw[:4] == b"FNT1", "bad font file"
    off = 4
    (nfonts,) = struct.unpack_from(">I", raw, off)
    off += 4
    fonts = {}
    for _ in range(nfonts):
        (nlen,) = struct.unpack_from(">B", raw, off)
        off += 1
        name = raw[off:off + nlen].decode("ascii")
        off += nlen
        (nglyphs,) = struct.unpack_from(">I", raw, off)
        off += 4
        glyphs = {}
        for _ in range(nglyphs):
            cp, adv, xoff, yoff, w, h = struct.unpack_from(">IhhhHH", raw, off)
            off += 14
            nbytes = w * h
            bits = raw[off:off + nbytes]
            off += nbytes
            glyphs[cp] = (adv, xoff, yoff, w, h, bits)
        fonts[name] = Font(glyphs)
    return fonts


def _scale_glyph(bits, w, h, tw, th):
    """Box-filter downscale of a grayscale bitmap to (tw, th)."""
    if tw <= 0 or th <= 0 or w <= 0 or h <= 0:
        return b""
    out = bytearray(tw * th)
    for ty in range(th):
        y0 = ty * h // th
        y1 = (ty + 1) * h // th
        if y1 <= y0:
            y1 = y0 + 1
        for tx in range(tw):
            x0 = tx * w // tw
            x1 = (tx + 1) * w // tw
            if x1 <= x0:
                x1 = x0 + 1
            total = 0
            count = 0
            for yy in range(y0, min(y1, h)):
                base = yy * w
                for xx in range(x0, min(x1, w)):
                    total += bits[base + xx]
                    count += 1
            out[ty * tw + tx] = total // count if count else 0
    return bytes(out)


class Text:
    """Text renderer with a per-(font, size, char) scaled-glyph cache."""

    def __init__(self, canvas, fonts):
        self.cv = canvas
        self.fonts = fonts
        self.cache = {}

    def _scaled(self, font, size, ch):
        key = (font, size, ch)
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        f = self.fonts[font]
        g = f.glyphs.get(ord(ch))
        if g is None:
            res = (0, 0, 0, 0, 0, b"")
            self.cache[key] = res
            return res
        adv, xoff, yoff, w, h, bits = g
        scale = size / FONT_SIZE
        tw = max(1, int(round(w * scale))) if w else 0
        th = max(1, int(round(h * scale))) if h else 0
        sbits = _scale_glyph(bits, w, h, tw, th) if w and h else b""
        res = (int(round(adv * scale)), int(round(xoff * scale)),
               int(round(yoff * scale)), tw, th, sbits)
        self.cache[key] = res
        return res

    def width(self, s, font, size):
        return self.fonts[font].text_width(s, size)

    def draw(self, x, y, s, font, size, color):
        """Draw string s with its ascender top at y. Returns width drawn."""
        pen = x
        for ch in s:
            adv, xoff, yoff, tw, th, bits = self._scaled(font, size, ch)
            if tw and th:
                gx = pen + xoff
                gy = y + yoff
                for ty in range(th):
                    base = ty * tw
                    for tx in range(tw):
                        a = bits[base + tx]
                        if a:
                            self.cv.blend_px(gx + tx, gy + ty, color, a)
            pen += adv
        return pen - x

    def draw_center(self, cx, y, s, font, size, color):
        w = self.width(s, font, size)
        return self.draw(int(cx - w / 2), y, s, font, size, color)

    def draw_right(self, x, y, s, font, size, color):
        w = self.width(s, font, size)
        return self.draw(int(x - w), y, s, font, size, color)

    def wrap(self, s, font, size, max_w):
        """Greedy word wrap; returns a list of lines fitting max_w."""
        words = s.split(" ")
        lines = []
        cur = ""
        for word in words:
            trial = (cur + " " + word).strip()
            if self.width(trial, font, size) <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
        return lines

    def draw_wrapped(self, x, y, s, font, size, color, max_w, lh):
        lines = self.wrap(s, font, size, max_w)
        for i, line in enumerate(lines):
            self.draw(x, y + i * lh, line, font, size, color)
        return len(lines)


# ---- the day's news: 43 stories, Wednesday 18 November 2026 --------------
# Facts as reported that day (Reuters/AP/AFP/BBC/Al Jazeera/WHO/UN/NASA).
HEROES = [
    {
        "num": 1, "tag": "MIDDLE EAST · IRAN WAR", "tag_color": RED,
        "headline": "US strikes Qeshm missile site; Iran hits Bahrain and Kuwait",
        "deck": "Tehran says it downed a US MQ-9 drone; Kuwait says Patriots "
                "intercepted the attack.",
        "art": "gulf",
    },
    {
        "num": 2, "tag": "EUROPE · UKRAINE WAR", "tag_color": NAVY,
        "headline": "Kerch Bridge road span falls into the sea",
        "deck": "Second day of Ukrainian strikes; Russia claims a record 1,441 "
                "drones downed overnight.",
        "art": "kerch",
    },
    {
        "num": 3, "tag": "ASIA · DIPLOMACY", "tag_color": PURPLE,
        "headline": "Xi and Putin meet in Shenzhen ahead of Trump trilateral",
        "deck": "APEC opens; Xi hits protectionism, Putin hits sanctions; Trump "
                "flies in from Manila.",
        "art": "summit",
    },
]

MID = [
    {
        "num": 4, "tag": "AMERICAS · POLITICS", "tag_color": RED,
        "headline": "Peltola wins Alaska; Democrats take Senate 56\u201344",
        "deck": "Beat Dan Sullivan; ninth flip; biggest majority since 2009.",
        "art": "senate",
    },
    {
        "num": 5, "tag": "US · BUSINESS", "tag_color": NAVY,
        "headline": "Nvidia guides to $130bn; shares jump 3.5%",
        "deck": "Q3 sales $115.8bn, up 103%; board rejects rehiring Huang.",
        "art": "nvidia",
    },
    {
        "num": 6, "tag": "SCIENCE · SPACE", "tag_color": NAVY_DARK,
        "headline": "Voyager 1 reaches one light-day from Earth",
        "deck": "16 billion miles out at 5:16am ET; farthest human-made object.",
        "art": "voyager",
    },
    {
        "num": 7, "tag": "AFRICA · HEALTH", "tag_color": GREEN,
        "headline": "Ebola in DR Congo tops 11,000 cases",
        "deck": "Doubled in three months; 5,500 dead; 3 in 4 young children die.",
        "art": "ebola",
    },
    {
        "num": 8, "tag": "OCEANIA · WEATHER", "tag_color": TEAL,
        "headline": "Cyclone Xavier hits Cook Islands at Category 5",
        "deck": "Pukapuka and Nassau brace for dangerous conditions.",
        "art": "cyclone",
    },
    {
        "num": 9, "tag": "AMERICAS · HEALTH", "tag_color": RED,
        "headline": "US loses measles-free status after 26 years",
        "deck": "5,412 cases in 2026, 10 deaths; highest total since 1991.",
        "art": "measles",
    },
    {
        "num": 10, "tag": "TECH · MARKETS", "tag_color": PURPLE,
        "headline": "Anthropic to price $64bn IPO tonight",
        "deck": "825m shares at $70\u201378, book 6x covered; Nasdaq debut Thursday.",
        "art": "anthropic",
    },
    {
        "num": 11, "tag": "ASIA · ECONOMY", "tag_color": TEAL,
        "headline": "Indonesia lifts rates to 6% as rupiah firms",
        "deck": "BI hikes 25bps; rupiah Rp18,239 per dollar; stocks up to 5,360.",
        "art": "bi",
    },
    {
        "num": 12, "tag": "MIDDLE EAST · GAZA", "tag_color": ORANGE,
        "headline": "Gaza: cold kills in tents as truce frays",
        "deck": "Israeli tanks push into central Gaza, 3 killed; Board of Peace warns.",
        "art": "gaza",
    },
    {
        "num": 13, "tag": "AFRICA · WAR", "tag_color": GREEN,
        "headline": "Sudan: drones cause 3 in 4 war deaths, UN says",
        "deck": "2,230+ civilians killed in Jan\u2013Oct, 1,630+ by drone strikes.",
        "art": "sudan",
    },
]

ALSO = [
    (14, "Russia: record 1,441 drones downed in one night"),
    (15, "Kyiv: missiles hit North, South Dnipro bridges"),
    (16, "UN: Ukraine civilian deaths top all of 2025"),
    (17, "Putin \u2018not ready\u2019 for serious Ukraine talks"),
    (18, "Europe seeks Ukraine talks seat; Moscow says no"),
    (19, "Berlin: allies to meet Thu; Merz hosts summit"),
    (20, "UK: sanctions 8 settlement firms, Tzav 9"),
    (21, "Australia: sanctions 3 Israelis, 4 groups"),
    (22, "Israel: Kahana elected Knesset speaker, 66\u201352"),
    (23, "Houthis fire 5 drones at Saudi pipeline"),
    (24, "Iran: more tankers hit mines; talks with Oman"),
    (25, "China\u2013Canada: more tariff cuts after talks"),
    (26, "US tightens AI-chip curbs; China vows retaliation"),
    (27, "Taiwan: 9 PLA jets cross median line"),
    (28, "S. Korea: Lee asks Xi for joint peace push"),
    (29, "Japan: jets scrambled over Russian plane"),
    (30, "Indonesia: MPR to pick VP on Dec 9"),
    (31, "Indonesia: Prabowo at ASEAN Manila"),
    (32, "India: Cyclone Akvan nears Andhra; 200,000 out"),
    (33, "COP31: heat plan as phase-out talks stall"),
    (34, "ICJ to rule Thu on Myanmar case"),
    (35, "France: 146,000 march over cost of living"),
    (36, "Ethiopia: Tigray bans gold mining"),
    (37, "Somalia: president accuses UAE of meddling"),
    (38, "DRC rebels take Bukondo hill in South Kivu"),
    (39, "Quake 6.0 hits Papua New Guinea; 5.3 Romania"),
    (40, "US revokes 350,000+ Trump-era visas"),
    (41, "Football: Norway 3\u20132 Denmark; Haaland double"),
    (42, "Football: USA 2\u20130 Haiti; Mexico 1\u20130 Jamaica"),
    (43, "Cyberattack hits Zoom, CNN, HSBC, IKEA sites"),
]

# Region colours for map pins / legend.
REGION_COLORS = {
    "americas": (185, 28, 28),
    "europe": (31, 86, 180),
    "middle-east": (214, 110, 30),
    "asia": (103, 58, 140),
    "africa": (46, 125, 50),
    "oceania": (14, 124, 123),
    "global": (107, 107, 107),
}
PIN_REGION = {
    1: "middle-east", 2: "europe", 3: "asia", 4: "americas",
    5: "americas", 6: "global", 7: "africa", 8: "oceania",
    9: "americas", 10: "americas", 11: "asia", 12: "middle-east",
    13: "africa",
}
DOT_REGION = {
    14: "europe", 15: "europe", 16: "global", 17: "europe",
    18: "europe", 19: "europe", 20: "europe", 21: "oceania",
    22: "middle-east", 23: "middle-east", 24: "middle-east",
    25: "asia", 26: "americas", 27: "asia", 28: "asia", 29: "asia",
    30: "asia", 31: "asia", 32: "asia", 33: "global", 34: "europe",
    35: "europe", 36: "africa", 37: "africa", 38: "africa",
    39: "oceania", 40: "americas", 41: "europe", 42: "americas",
    43: "global",
}

# (lon, lat) of every story for the map pins/dots.
PIN_LONLAT = {
    1: (50.6, 26.2), 2: (36.5, 45.3), 3: (114.0, 22.5),
    4: (-152.0, 64.0), 5: (-122.0, 37.4), 6: (-80.6, 28.4),
    7: (29.5, 1.5), 8: (-165.8, -10.9), 9: (-98.0, 39.0),
    10: (-74.0, 40.7), 11: (106.8, -6.2), 12: (34.5, 31.5),
    13: (32.5, 15.5), 14: (34.0, 55.0), 15: (30.5, 50.45),
    16: (33.0, 49.0), 17: (40.0, 56.0), 18: (4.35, 50.85),
    19: (13.4, 52.5), 20: (-0.1, 51.5), 21: (149.1, -35.3),
    22: (41.0, 32.0), 23: (38.0, 24.0), 24: (57.5, 25.8),
    25: (116.4, 39.9), 26: (-77.0, 38.9), 27: (121.0, 25.0),
    28: (127.0, 37.5), 29: (130.4, 33.6), 30: (113.5, -8.0),
    31: (121.0, 14.6), 32: (80.0, 16.0), 33: (30.7, 36.9),
    34: (4.3, 52.1), 35: (2.35, 48.85), 36: (39.0, 13.5),
    37: (45.3, 2.0), 38: (27.0, -3.5), 39: (147.0, -6.5),
    40: (-95.0, 32.0), 41: (10.75, 59.9), 42: (-84.5, 39.1),
    43: (8.0, 50.0),
}


# ---- world map (simplified continent outlines, lon/lat) ----------------------
NORTH_AMERICA = [
    (-168, 66), (-161, 58), (-153, 58), (-147, 60), (-140, 60), (-135, 57),
    (-130, 54), (-125, 49), (-124, 42), (-120, 34), (-114, 29), (-110, 24),
    (-105, 20), (-97, 16), (-94, 17), (-90, 14), (-86, 12), (-83, 9),
    (-79, 9), (-81, 13), (-84, 16), (-87, 21), (-90, 21), (-91, 19),
    (-96, 19), (-97, 26), (-93, 30), (-89, 30), (-84, 30), (-81, 26),
    (-80, 32), (-76, 35), (-74, 40), (-70, 42), (-68, 45), (-65, 44),
    (-60, 47), (-55, 52), (-60, 55), (-65, 60), (-68, 58), (-78, 62),
    (-85, 66), (-92, 66), (-95, 69), (-110, 68), (-125, 70), (-140, 70),
    (-155, 71), (-162, 70), (-168, 66),
]
GREENLAND = [
    (-58, 64), (-52, 60), (-43, 60), (-40, 64), (-32, 68), (-22, 70),
    (-20, 74), (-25, 78), (-35, 80), (-50, 80), (-58, 76), (-62, 72),
    (-58, 64),
]
SOUTH_AMERICA = [
    (-79, 9), (-77, 4), (-80, -3), (-81, -6), (-77, -12), (-72, -18),
    (-70, -23), (-70, -30), (-72, -37), (-73, -44), (-74, -50), (-70, -54),
    (-66, -55), (-68, -50), (-65, -45), (-62, -41), (-58, -35), (-52, -32),
    (-48, -28), (-41, -23), (-39, -17), (-35, -9), (-35, -6), (-40, -3),
    (-44, -2), (-50, 0), (-53, 4), (-58, 6), (-62, 9), (-68, 11),
    (-72, 12), (-76, 10), (-79, 9),
]
AFRICA = [
    (-6, 35), (-10, 31), (-15, 27), (-17, 21), (-17, 15), (-15, 11),
    (-12, 8), (-8, 5), (-4, 5), (0, 6), (6, 4), (9, 4), (9, 0), (12, -5),
    (13, -10), (12, -17), (14, -22), (16, -28), (20, -35), (26, -34),
    (32, -29), (35, -24), (40, -16), (40, -10), (42, -4), (46, 0), (51, 2),
    (51, 10), (48, 11), (44, 11), (43, 12), (40, 15), (38, 18), (37, 22),
    (35, 28), (34, 31), (32, 31), (30, 32), (27, 33), (22, 33), (19, 32),
    (15, 32), (11, 34), (10, 37), (6, 37), (-6, 35),
]
EURASIA = [
    (-9, 37), (-9, 43), (-2, 44), (-1, 46), (-4, 48), (-2, 49), (2, 51),
    (5, 53), (8, 55), (8, 57), (10, 59), (5, 60), (5, 62), (10, 64),
    (13, 66), (18, 69), (25, 71), (30, 70), (35, 68), (40, 68), (45, 68),
    (50, 69), (55, 68), (60, 69), (65, 69), (70, 72), (75, 73), (80, 73),
    (85, 74), (90, 75), (95, 76), (100, 77), (105, 78), (110, 74),
    (115, 73), (120, 73), (125, 72), (130, 72), (135, 72), (140, 72),
    (145, 72), (150, 70), (155, 69), (158, 66), (162, 64), (170, 66),
    (178, 65), (178, 62), (170, 60), (162, 58), (158, 52), (156, 50),
    (152, 51), (148, 52), (144, 53), (142, 54), (141, 48), (140, 42),
    (135, 40), (130, 38), (127, 35), (126, 33), (122, 31), (120, 28),
    (118, 25), (112, 22), (108, 20), (105, 18), (103, 16), (100, 14),
    (98, 12), (100, 8), (102, 6), (104, 2), (100, 5), (98, 8), (97, 12),
    (94, 16), (92, 20), (90, 22), (88, 21), (86, 20), (82, 17), (80, 15),
    (80, 10), (77, 8), (76, 10), (73, 16), (70, 20), (67, 23), (62, 25),
    (58, 25), (54, 26), (51, 28), (49, 30), (48, 29), (50, 26), (52, 24),
    (55, 24), (58, 23), (55, 17), (52, 15), (48, 14), (44, 13), (42, 15),
    (40, 20), (38, 24), (36, 28), (35, 29), (34, 31), (36, 36), (33, 36),
    (30, 36), (27, 37), (26, 38), (23, 36), (22, 37), (19, 40), (15, 44),
    (12, 45), (10, 44), (8, 44), (6, 43), (3, 42), (0, 39), (-1, 37),
]
AUSTRALIA = [
    (114, -22), (114, -30), (115, -35), (118, -35), (124, -33), (129, -32),
    (132, -32), (135, -35), (138, -35), (140, -38), (145, -38), (150, -37),
    (153, -32), (153, -27), (150, -23), (146, -19), (142, -15), (142, -11),
    (137, -12), (135, -15), (132, -12), (130, -13), (126, -14), (122, -17),
    (118, -20), (114, -22),
]
ISLANDS = [
    [(-5, 50), (-3, 53), (-5, 56), (-3, 58), (-1, 57), (0, 53), (1, 51),
     (-3, 50)],  # Great Britain
    [(-10, 52), (-8, 55), (-6, 55), (-6, 52), (-8, 51), (-10, 52)],  # Ireland
    [(130, 31), (132, 33), (134, 34), (136, 35), (138, 35), (140, 36),
     (141, 38), (141, 41), (142, 43), (144, 44), (142, 45), (140, 43),
     (139, 40), (137, 37), (135, 34), (132, 33)],  # Japan
    [(95, 5), (98, 3), (101, 0), (104, -3), (106, -6), (104, -6), (101, -3),
     (98, 1), (95, 5)],  # Sumatra
    [(109, 1), (111, 3), (114, 4), (117, 6), (119, 2), (117, -2), (114, -4),
     (110, -3), (109, 1)],  # Borneo
    [(105, -6), (108, -7), (111, -7), (114, -8), (114, -9), (110, -8),
     (106, -7), (105, -6)],  # Java
    [(131, -1), (136, -2), (141, -3), (146, -6), (150, -8), (147, -9),
     (142, -8), (138, -7), (134, -4), (131, -1)],  # New Guinea
    [(44, -16), (47, -15), (50, -16), (49, -20), (47, -24), (45, -25),
     (43, -22), (43, -18), (44, -16)],  # Madagascar
    [(167, -45), (170, -43), (173, -41), (175, -39), (177, -38), (175, -37),
     (173, -40), (170, -42), (167, -45)],  # New Zealand (North)
    [(168, -44), (170, -46), (167, -46), (166, -44)],  # New Zealand (South)
    [(-22, 64), (-18, 63), (-14, 64), (-15, 66), (-20, 66), (-24, 65),
     (-22, 64)],  # Iceland
    [(80, 9), (81, 8), (80, 6), (79, 7), (80, 9)],  # Sri Lanka
]


# ---- mini flags -------------------------------------------------------------
def mini_flag(cv, x, y, w, h, kind):
    if kind == "us":
        cv.fill_rect(x, y, w, h, WHITE)
        for i in range(7):
            cv.fill_rect(x, y + i * h // 7, w, max(1, h // 14),
                         (185, 28, 28))
        cv.fill_rect(x, y, w * 2 // 5, h * 4 // 7, NAVY)
        for r in range(4):
            for c in range(5):
                cv.set_px(x + 3 + c * (w // 6), y + 3 + r * (h // 5), WHITE)
    elif kind == "china":
        cv.fill_rect(x, y, w, h, (222, 20, 20))
        star(cv, x + w // 5, y + h // 3, max(3, h // 4), (255, 222, 0))
        for dx, dy in ((3 * w // 5, h // 6), (4 * w // 5, h // 4),
                       (3 * w // 5, h // 2), (4 * w // 5, h // 2)):
            cv.set_px(x + dx, y + dy, (255, 222, 0))
            cv.set_px(x + dx + 1, y + dy, (255, 222, 0))
    elif kind == "russia":
        cv.fill_rect(x, y, w, h // 3, WHITE)
        cv.fill_rect(x, y + h // 3, w, h // 3, (0, 60, 160))
        cv.fill_rect(x, y + 2 * h // 3, w, h - 2 * h // 3, (220, 20, 20))
    elif kind == "drc":
        cv.fill_rect(x, y, w, h, (0, 122, 185))
        cv.line(x, y + h, x + w, y, (206, 0, 0), 3)
        cv.line(x, y + h, x + w, y, (255, 215, 0), 1)
        star(cv, x + w // 4, y + h // 4, 2, (255, 215, 0))
    elif kind == "mexico":
        cv.fill_rect(x, y, w // 3, h, (0, 122, 51))
        cv.fill_rect(x + w // 3, y, w // 3, h, WHITE)
        cv.fill_rect(x + 2 * w // 3, y, w - 2 * w // 3, h, (206, 0, 0))
    elif kind == "bolivia":
        cv.fill_rect(x, y, w, h // 3, (206, 0, 0))
        cv.fill_rect(x, y + h // 3, w, h // 3, (255, 215, 0))
        cv.fill_rect(x, y + 2 * h // 3, w, h - 2 * h // 3, (0, 122, 51))
    elif kind == "indonesia":
        cv.fill_rect(x, y, w, h // 2, (206, 0, 0))
        cv.fill_rect(x, y + h // 2, w, h - h // 2, WHITE)


def star(cv, cx, cy, r, color):
    """A small five-pointed star centred on (cx, cy)."""
    pts = []
    for i in range(10):
        ang = -math.pi / 2 + i * math.pi / 5
        rr = r if i % 2 == 0 else r * 0.45
        pts.append((cx + rr * math.cos(ang), cy + rr * math.sin(ang)))
    cv.polygon(pts, color)


def burst(cv, cx, cy, r, color1, color2):
    """Starburst explosion: alternating long/short spikes."""
    for i in range(12):
        a = 2 * math.pi * i / 12
        rr = r if i % 2 == 0 else r * 0.45
        x2 = int(cx + rr * math.cos(a))
        y2 = int(cy + rr * math.sin(a))
        cv.line(cx, cy, x2, y2, color1, 3)
    cv.circle(cx, cy, max(2, r // 3), color2)


# ---- hero illustrations ------------------------------------------------------
def art_gulf(cv, tx, x, y, w, h):
    cv.fill_rect(x, y, w, h, SEA)
    # Iran (top) and Arabia (bottom) land
    cv.polygon([(x, y), (x + w, y), (x + w, y + h * 0.30),
                (x + w * 0.55, y + h * 0.38), (x, y + h * 0.30)], LAND)
    cv.polygon([(x, y + h), (x + w, y + h), (x + w, y + h * 0.72),
                (x + w * 0.60, y + h * 0.66), (x + w * 0.30, y + h * 0.78),
                (x, y + h * 0.72)], LAND2)
    # Bahrain, Qeshm and Kuwait
    cv.ellipse(x + int(w * 0.42), y + int(h * 0.52), 7, 5, LAND)
    cv.ellipse(x + int(w * 0.72), y + int(h * 0.44), 14, 6, LAND)
    cv.ellipse(x + int(w * 0.28), y + int(h * 0.40), 5, 4, LAND2)
    # drone tracks (dotted) from Iran toward Bahrain and Kuwait
    for i in range(5):
        dx = x + int(w * (0.55 + i * 0.035))
        dy = y + int(h * (0.30 + i * 0.045))
        cv.circle(dx, dy, 2, RED)
    for i in range(4):
        dx = x + int(w * (0.48 - i * 0.05))
        dy = y + int(h * (0.30 + i * 0.025))
        cv.circle(dx, dy, 2, RED)
    cv.line(x + int(w * 0.55), y + int(h * 0.30), x + int(w * 0.44),
            y + int(h * 0.52), RED, 1)
    # US strike arrow from the sea toward Qeshm
    cv.line(x + int(w * 0.86), y + int(h * 0.62), x + int(w * 0.74),
            y + int(h * 0.46), NAVY, 2)
    cv.polygon([(x + int(w * 0.74), y + int(h * 0.46)),
                (x + int(w * 0.78), y + int(h * 0.50)),
                (x + int(w * 0.72), y + int(h * 0.50))], NAVY)
    tx.draw(x + 8, y + 6, "IRAN", "sans-bold", 10, INK)
    tx.draw(x + int(w * 0.70), y + int(h * 0.20), "QESHM", "sans-bold", 9, INK)
    tx.draw(x + int(w * 0.36), y + int(h * 0.58), "BAHRAIN", "sans-bold", 9, INK)
    tx.draw(x + int(w * 0.06), y + int(h * 0.30), "KUWAIT", "sans-bold", 9, INK)
    tx.draw_right(x + w - 8, y + h - 14, "HORMUZ", "sans-bold", 9, INK)
    cv.fill_rect(x + int(w * 0.40), y + int(h * 0.34), 108, 15, RED)
    tx.draw(x + int(w * 0.40) + 5, y + int(h * 0.34) + 3, "DRONES DOWNED",
            "sans-bold", 9, WHITE)
    cv.fill_rect(x + int(w * 0.60), y + int(h * 0.56), 84, 15, NAVY)
    tx.draw(x + int(w * 0.60) + 5, y + int(h * 0.56) + 3, "US STRIKES",
            "sans-bold", 9, WHITE)


def art_kerch(cv, tx, x, y, w, h):
    cv.fill_rect(x, y, w, h, SEA)
    # land: Crimea (left) and Russia (right)
    cv.polygon([(x, y), (x + w * 0.34, y), (x + w * 0.30, y + h * 0.42),
                (x + w * 0.12, y + h * 0.42), (x, y + h * 0.30)], LAND)
    cv.polygon([(x + w, y), (x + w * 0.72, y), (x + w * 0.74, y + h * 0.40),
                (x + w * 0.90, y + h * 0.40), (x + w, y + h * 0.28)], LAND)
    # waves
    for i in range(6):
        wx = x + 12 + i * 52
        cv.line(wx, y + h - 18, wx + 22, y + h - 18, SEA_DARK, 2)
        cv.line(wx + 8, y + h - 10, wx + 30, y + h - 10, SEA_DARK, 2)
    # bridge deck with a broken, fallen span in the middle
    by = y + int(h * 0.42)
    cv.fill_rect(x + 6, by, int(w * 0.42), 5, INK)
    cv.fill_rect(x + int(w * 0.58), by, int(w * 0.40), 5, INK)
    cv.polygon([(x + int(w * 0.48), by + 4), (x + int(w * 0.56), by + 4),
                (x + int(w * 0.52), by + 26), (x + int(w * 0.46), by + 22)],
               INK)
    for px in (0.14, 0.28, 0.66, 0.80, 0.92):
        cv.fill_rect(x + int(w * px), by + 5, 3, 16, INK)
    burst(cv, x + int(w * 0.52), by - 6, 16, (255, 140, 0), (255, 220, 0))
    # jets
    for jx in (0.10, 0.86):
        jxx, jyy = x + int(w * jx), y + 14
        cv.polygon([(jxx, jyy), (jxx + 14, jyy + 4), (jxx, jyy + 8)], INK)
    tx.draw(x + 8, y + 6, "CRIMEA", "sans-bold", 10, INK)
    tx.draw_right(x + w - 8, y + 6, "RUSSIA", "sans-bold", 10, INK)
    cv.fill_rect(x, y + h - 16, w, 16, NAVY)
    tx.draw(x + 8, y + h - 13, "KERCH STRAIT \u00b7 SPAN FALLS INTO THE SEA",
            "sans-bold", 9, WHITE)


def art_summit(cv, tx, x, y, w, h):
    cv.fill_rect(x, y, w, h, (238, 232, 245))
    cv.fill_rect(x, y, w, 22, PURPLE)
    tx.draw_center(x + w // 2, y + 5, "XI \u00b7 PUTIN \u00b7 TRUMP IN SHENZHEN",
                   "sans-bold", 11, WHITE)
    flags = [("china", "CHINA"), ("russia", "RUSSIA"), ("us", "USA")]
    fw, fh = 62, 30
    gap = (w - 3 * fw) // 4
    for i, (kind, label) in enumerate(flags):
        fx = x + gap + i * (fw + gap)
        fy = y + 26
        mini_flag(cv, fx, fy, fw, fh, kind)
        cv.rect(fx, fy, fw, fh, INK, 1)
        tx.draw_center(fx + fw // 2, fy + fh + 3, label, "sans-bold", 9, INK)
    # table line
    cv.fill_rect(x + 16, y + h - 28, w - 32, 5, (120, 72, 20))
    cv.fill_rect(x + 16, y + h - 23, w - 32, 3, (90, 52, 14))
    cv.fill_rect(x, y + h - 16, w, 16, PURPLE)
    tx.draw_center(x + w // 2, y + h - 13, "TRILATERAL WITH TRUMP ON THURSDAY",
                   "sans-bold", 9, WHITE)


# ---- mid-grid illustrations (small strips) -----------------------------------
def art_senate(cv, tx, x, y, w, h):
    cv.fill_rect(x, y, w, h, (232, 235, 242))
    cv.fill_rect(x + 8, y + 8, 100, 14, (31, 86, 180))
    cv.fill_rect(x + 108, y + 8, 78, 14, RED)
    tx.draw(x + 8, y + 26, "DEM 56", "sans-bold", 10, (31, 86, 180))
    tx.draw(x + 108, y + 26, "GOP 44", "sans-bold", 10, RED)


def art_nvidia(cv, tx, x, y, w, h):
    cv.fill_rect(x, y, w, h, (16, 16, 16))
    bars = [10, 16, 14, 22, 30, 38]
    bx = x + 10
    for i, bh in enumerate(bars):
        cv.fill_rect(bx + i * 12, y + h - 8 - bh, 8, bh,
                     (118, 200, 70) if i < 5 else (160, 230, 110))
    tx.draw(x + 88, y + 6, "$115.8BN", "sans-bold", 13, (118, 200, 70))
    tx.draw(x + 88, y + 24, "GUIDES $130BN", "sans-bold", 11, WHITE)


def art_voyager(cv, tx, x, y, w, h):
    cv.fill_rect(x, y, w, h, (16, 20, 40))
    for sx, sy in ((12, 8), (30, 30), (52, 12), (76, 34), (96, 10),
                   (120, 28), (140, 8), (170, 32), (186, 14), (60, 40)):
        cv.set_px(x + sx, y + sy, WHITE)
        cv.set_px(x + sx + 1, y + sy, (200, 200, 200))
    # probe: gold dish + body + antenna
    cv.circle(x + 160, y + 20, 9, (201, 162, 39), fill=False)
    cv.line(x + 160, y + 20, x + 160, y + 11, (201, 162, 39), 1)
    cv.fill_rect(x + 152, y + 24, 16, 8, (180, 180, 180))
    cv.line(x + 152, y + 28, x + 138, y + 34, (180, 180, 180), 1)
    tx.draw(x + 8, y + 6, "1 LIGHT-DAY", "sans-bold", 12, WHITE)
    tx.draw(x + 8, y + 24, "16 BILLION MILES", "sans-bold", 9, (180, 190, 220))
    tx.draw(x + 8, y + h - 12, "NASA JPL", "sans-bold", 8, GREY)


def art_ebola(cv, tx, x, y, w, h):
    cv.fill_rect(x, y, w, h, (232, 240, 235))
    mini_flag(cv, x + 6, y + 8, 30, 20, "drc")
    cv.fill_rect(x + 42, y + 6, 26, 26, WHITE)
    cv.rect(x + 42, y + 6, 26, 26, RED, 1)
    cv.fill_rect(x + 52, y + 11, 6, 16, RED)
    cv.fill_rect(x + 47, y + 16, 16, 6, RED)
    cv.fill_rect(x + 74, y + 8, 112, 16, RED)
    tx.draw(x + 79, y + 11, "11,000+ CASES", "sans-bold", 10, WHITE)
    tx.draw(x + 6, y + h - 12, "DR CONGO", "sans-bold", 8, GREY)


def art_cyclone(cv, tx, x, y, w, h):
    cv.fill_rect(x, y, w, h, (222, 235, 242))
    cx, cy = x + 30, y + h // 2
    for r, col in ((20, SEA_DARK), (15, TEAL), (10, SEA_DARK), (5, TEAL)):
        cv.circle(cx, cy, r, col, fill=False)
    cv.circle(cx, cy, 3, RED)
    tx.draw(x + 62, y + 6, "CAT 5", "sans-bold", 14, RED)
    tx.draw(x + 62, y + 24, "COOK ISLANDS", "sans-bold", 10, INK)
    tx.draw(x + 62, y + h - 12, "PUKAPUKA \u00b7 NASSAU", "sans-bold", 8, GREY)


def art_measles(cv, tx, x, y, w, h):
    cv.fill_rect(x, y, w, h, (245, 235, 230))
    fx = x + 8
    for kind in ("us", "mexico", "bolivia"):
        mini_flag(cv, fx, y + 8, 34, 20, kind)
        cv.rect(fx, y + 8, 34, 20, INK, 1)
        fx += 40
    for dx, dy in ((150, 10), (164, 22), (150, 30), (178, 12)):
        cv.circle(x + dx, y + dy, 4, RED)
        cv.circle(x + dx, y + dy, 2, (255, 150, 150))
    tx.draw(x + 8, y + h - 12, "US \u00b7 MEXICO \u00b7 BOLIVIA", "sans-bold", 8, GREY)


def art_anthropic(cv, tx, x, y, w, h):
    cv.fill_rect(x, y, w, h, (16, 16, 16))
    pts = [(x + 8, y + 38), (x + 24, y + 34), (x + 40, y + 36),
           (x + 56, y + 24), (x + 72, y + 16), (x + 84, y + 8)]
    for i in range(len(pts) - 1):
        cv.line(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1],
                (201, 162, 39), 2)
    tx.draw(x + 92, y + 6, "$70\u201378", "sans-bold", 13, (201, 162, 39))
    tx.draw(x + 92, y + 24, "IPO TONIGHT", "sans-bold", 11, WHITE)
    tx.draw(x + 92, y + h - 12, "ANT \u00b7 NASDAQ", "sans-bold", 9, (160, 160, 160))


def art_bi(cv, tx, x, y, w, h):
    cv.fill_rect(x, y, w, h, (232, 240, 232))
    pts = [(x + 8, y + 38), (x + 30, y + 32), (x + 52, y + 34),
           (x + 74, y + 26), (x + 96, y + 20)]
    for i in range(len(pts) - 1):
        cv.line(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], GREEN, 2)
    tx.draw(x + 8, y + 4, "BI-RATE 6.00%", "sans-bold", 12, INK)
    tx.draw(x + 100, y + 24, "RUPIAH FIRMS", "sans-bold", 10, GREEN)


def art_gaza(cv, tx, x, y, w, h):
    cv.fill_rect(x, y, w, h, (238, 228, 205))
    for i, tx0 in enumerate((6, 40, 74)):
        cv.polygon([(x + tx0, y + h - 8), (x + tx0 + 15, y + 12),
                    (x + tx0 + 30, y + h - 8)], WHITE)
        cv.line(x + tx0, y + h - 8, x + tx0 + 15, y + 12, GREY, 1)
        cv.line(x + tx0 + 30, y + h - 8, x + tx0 + 15, y + 12, GREY, 1)
    cv.fill_rect(x + 168, y + 6, 22, 13, RED)
    tx.draw(x + 171, y + 8, "AID", "sans-bold", 8, WHITE)
    tx.draw(x + 112, y + 24, "TRUCE AT RISK", "sans-bold", 9, INK)
    tx.draw(x + 112, y + 35, "COLD KILLS", "sans-bold", 9, INK)


def art_sudan(cv, tx, x, y, w, h):
    cv.fill_rect(x, y, w, h, (238, 232, 222))
    cx, cy = x + 38, y + 18
    cv.ellipse(cx, cy, 18, 5, (60, 60, 60))
    cv.line(cx - 14, cy - 4, cx - 24, cy - 12, (60, 60, 60), 2)
    cv.line(cx + 14, cy - 4, cx + 24, cy - 12, (60, 60, 60), 2)
    cv.line(cx - 14, cy + 4, cx - 24, cy + 12, (60, 60, 60), 2)
    cv.line(cx + 14, cy + 4, cx + 24, cy + 12, (60, 60, 60), 2)
    for rx, ry in ((-24, -12), (24, -12), (-24, 12), (24, 12)):
        cv.circle(cx + rx, cy + ry, 4, (60, 60, 60), fill=False)
    tx.draw(x + 72, y + 6, "2,230 KILLED", "sans-bold", 12, INK)
    tx.draw(x + 72, y + 22, "3 IN 4 DEATHS", "sans-bold", 10, RED)
    tx.draw(x + 72, y + h - 12, "BY DRONE", "sans-bold", 9, GREY)


ART = {
    "gulf": art_gulf, "kerch": art_kerch, "summit": art_summit,
    "senate": art_senate, "nvidia": art_nvidia, "voyager": art_voyager,
    "ebola": art_ebola, "cyclone": art_cyclone, "measles": art_measles,
    "anthropic": art_anthropic, "bi": art_bi, "gaza": art_gaza,
    "sudan": art_sudan,
}


# ---- layout -----------------------------------------------------------------
def draw_tag(tx, x, y, num, tag, color):
    tx.cv.fill_rect(x, y, 16, 16, color)
    tx.draw_center(x + 8, y + 3, str(num), "sans-bold", 11, WHITE)
    tx.draw(x + 22, y + 2, tag, "sans-bold", 11, color)


def draw_map(cv, tx, x, y, w, h):
    cv.fill_rect(x, y, w, h, SEA)
    lon0, lon1, lat0, lat1 = -180.0, 180.0, -58.0, 84.0
    scale = min(w / (lon1 - lon0), h / (lat1 - lat0))
    mw = (lon1 - lon0) * scale
    mh = (lat1 - lat0) * scale
    ox = x + (w - mw) / 2
    oy = y + (h - mh) / 2

    def proj(lon, lat):
        return (ox + (lon - lon0) * scale, oy + (lat1 - lat) * scale)

    # graticule
    for lon in range(-150, 181, 30):
        px, _ = proj(lon, 0)
        cv.vline(int(px), int(oy), int(mh), SEA_DARK, 1)
    for lat in range(-30, 85, 30):
        _, py = proj(0, lat)
        cv.hline(int(ox), int(py), int(mw), SEA_DARK, 1)
    # land
    for poly in (NORTH_AMERICA, GREENLAND, SOUTH_AMERICA, AFRICA, EURASIA,
                 AUSTRALIA) + tuple(ISLANDS):
        cv.polygon([proj(lon, lat) for lon, lat in poly], LAND)
    # numbered pins (stories 1-13)
    for num in range(1, 14):
        lon, lat = PIN_LONLAT[num]
        px, py = proj(lon, lat)
        color = REGION_COLORS[PIN_REGION[num]]
        cv.circle(int(px), int(py), 8, WHITE)
        cv.circle(int(px), int(py), 7, color)
        tx.draw_center(int(px), int(py) - 5, str(num), "sans-bold", 10, WHITE)
    # dots (stories 14-43)
    for num in range(14, 44):
        lon, lat = PIN_LONLAT[num]
        px, py = proj(lon, lat)
        cv.circle(int(px), int(py), 3, REGION_COLORS[DOT_REGION[num]])


def render(cv, tx):
    # ---- masthead ----
    tx.draw(10, 12, "THE WORLD\u2019S NEWS IN ONE PICTURE", "sans-bold", 11, RED)
    tx.draw_right(1014, 12, "43 STORIES \u00b7 6 CONTINENTS \u00b7 ALL FROM WEDNESDAY",
                  "sans-bold", 11, NAVY)
    tx.draw(10, 26, "Wednesday 18 November 2026", "serif-bold", 56, INK)
    cv.hline(10, 100, 1004, INK, 2)
    cv.hline(10, 104, 1004, INK, 1)

    # ---- heroes ----
    hero_xs = [10, 348, 686]
    for i, hero in enumerate(HEROES):
        hx = hero_xs[i]
        ART[hero["art"]](cv, tx, hx, 114, 328, 100)
        draw_tag(tx, hx, 220, hero["num"], hero["tag"], hero["tag_color"])
        n = tx.draw_wrapped(hx, 238, hero["headline"], "sans-bold", 20, INK,
                            328, 23)
        deck_y = 238 + n * 23 + 4
        tx.draw_wrapped(hx, deck_y, hero["deck"], "sans", 12, INK, 328, 15)

    # ---- mid grid: 2 rows x 5 cards ----
    mid_xs = [10, 212, 415, 617, 820]
    for row in range(2):
        for col in range(5):
            card = MID[row * 5 + col]
            cx = mid_xs[col]
            cy = 358 + row * 134
            ART[card["art"]](cv, tx, cx, cy, 194, 46)
            draw_tag(tx, cx, cy + 50, card["num"], card["tag"],
                     card["tag_color"])
            n = tx.draw_wrapped(cx, cy + 68, card["headline"], "sans-bold",
                                13, INK, 194, 15)
            tx.draw_wrapped(cx, cy + 68 + n * 15 + 2, card["deck"], "sans",
                            10, INK, 194, 12)

    # ---- bottom strip ----
    cv.hline(10, 622, 1004, INK, 2)
    tx.draw(10, 630, "WHERE IT HAPPENED", "sans-bold", 13, NAVY)
    tx.draw(508, 630, "ALSO ON WEDNESDAY 18 NOVEMBER", "sans-bold", 13, NAVY)
    cv.vline(502, 630, 326, LIGHT_GREY, 1)
    draw_map(cv, tx, 10, 650, 486, 228)
    # legend
    lx, ly = 10, 890
    legend1 = [("Americas", "americas"), ("Europe", "europe"),
               ("Middle East", "middle-east"), ("Asia", "asia")]
    legend2 = [("Africa", "africa"), ("Oceania", "oceania"),
               ("Global & space", "global")]
    px = lx
    for label, region in legend1:
        cv.fill_rect(px, ly, 8, 8, REGION_COLORS[region])
        px += 12
        px += tx.draw(px, ly - 1, label, "sans", 10, INK) + 14
    px = lx
    for label, region in legend2:
        cv.fill_rect(px, ly + 18, 8, 8, REGION_COLORS[region])
        px += 12
        px += tx.draw(px, ly + 17, label, "sans", 10, INK) + 14
    tx.draw(10, 934, "Pins: stories 1\u201313 \u00b7 dots: 14\u201343",
            "sans", 10, GREY)
    # also-on list: 2 columns x 15 rows
    for i, (num, text) in enumerate(ALSO):
        col = i // 15
        row = i % 15
        ax = 508 + col * 253
        ay = 650 + row * 20
        region = DOT_REGION[num]
        tx.draw(ax, ay, str(num), "sans-bold", 10, REGION_COLORS[region])
        size = 10
        if tx.width(text, "sans", size) > 228:
            size = 9
        tx.draw(ax + 18, ay, text, "sans", size, INK)

    # ---- footer ----
    cv.hline(10, 962, 1004, INK, 1)
    tx.draw(10, 970, "Every story here happened or was first reported on "
            "Wednesday 18 November 2026. Contested claims are marked as claims.",
            "sans", 10, INK)
    tx.draw(10, 988, "Sources: Reuters, AP, AFP, BBC, Al Jazeera, WHO, UN, "
            "NASA. Original drawings.", "sans", 10, GREY)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    fonts = load_fonts(os.path.join(here, "font.bin"))
    cv = Canvas(W, H, PAPER)
    tx = Text(cv, fonts)
    render(cv, tx)
    png = encode_png(W, H, cv.buf)
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "entry.png")
    with open(out_path, "wb") as f:
        f.write(png)
    print("wrote %s: %d bytes" % (out_path, len(png)))


if __name__ == "__main__":
    main()
