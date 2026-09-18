# ============================================================
# MAGIC WAND - TODDLER EDITION v2
#
# Arduino sends one word per line, for example:
#   LEFT  RIGHT  UP  DOWN  FORWARD  BACKWARD
#   SHAKE  SPIN  TAP  CIRCLE          <-- new ones
#
# Anything the Arduino does not send yet can still be tested
# on the keyboard (see KEYBOARD section at the bottom).
#
# HOW IT BEHAVES NOW
#   * A NEW movement instantly wipes the screen and starts the
#     new animation. The child never has to wait.
#   * Repeating the SAME movement quickly does NOT restart it,
#     it piles MORE magic on top (so shaking keeps building).
#   * 5 fast repeats of the same movement = MEGA MAGIC surprise.
#   * Everything runs on a single 60 fps loop, and shapes are
#     MOVED instead of deleted and redrawn, which is what makes
#     this version far smoother than the old one.
# ============================================================

import math
import random
import sys
import threading
import time
import tkinter as tk
from queue import Queue, Empty

# pyserial is optional: without it you can still play with keys.
try:
    import serial
    from serial.tools import list_ports
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False

# Windows beeps are optional too.
try:
    import winsound
    HAS_SOUND = True
except ImportError:
    HAS_SOUND = False


# ============================================================
# SETTINGS
# ============================================================

SERIAL_PORT = "AUTO"      # "AUTO" to hunt for the board, or "COM10"
BAUD_RATE = 115200

FULLSCREEN = True
SOUND_ON = True

FRAME_MS = 16             # ~60 frames per second
BG = "#07041a"

# Repeating the same gesture inside this many seconds adds
# more magic instead of restarting the animation.
REPEAT_WINDOW = 0.45

# This many fast repeats triggers the big surprise.
COMBO_FOR_MEGA = 5

IDLE_SECONDS = 25.0       # after this, gentle "wave me" sparkles


NEON = [
    "#ff2fb9", "#ffd400", "#00e5ff", "#7cff3f",
    "#ff7a18", "#b06cff", "#ffffff", "#ff4d4d",
]


# ============================================================
# WINDOW
# ============================================================

root = tk.Tk()
root.title("Magic Wand")
root.configure(bg=BG)

if FULLSCREEN:
    root.attributes("-fullscreen", True)
else:
    root.geometry("1000x700")

root.update_idletasks()

WIDTH = root.winfo_screenwidth() if FULLSCREEN else 1000
HEIGHT = root.winfo_screenheight() if FULLSCREEN else 700

canvas = tk.Canvas(root, width=WIDTH, height=HEIGHT,
                   bg=BG, highlightthickness=0)
canvas.pack(fill="both", expand=True)

BIG_FONT = max(28, int(HEIGHT * 0.085))


# ============================================================
# SMALL HELPERS
# ============================================================

def hex_to_rgb(h):
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_to_hex(r, g, b):
    return "#%02x%02x%02x" % (int(r) & 255, int(g) & 255, int(b) & 255)


def mix(color_a, color_b, t):
    """Blend two colours. t=0 gives a, t=1 gives b."""
    t = max(0.0, min(1.0, t))
    r1, g1, b1 = hex_to_rgb(color_a)
    r2, g2, b2 = hex_to_rgb(color_b)
    return rgb_to_hex(r1 + (r2 - r1) * t,
                      g1 + (g2 - g1) * t,
                      b1 + (b2 - b1) * t)


def pick():
    return random.choice(NEON)


# ============================================================
# SOUND
# ============================================================
# Real little sound effects instead of flat beeps: chimes,
# whooshes, pops, and a boing, all synthesized from scratch
# (no sound files needed) and rendered ONCE at startup, so
# playing one later is instant and never stutters the animation.

import io
import struct
import wave

SAMPLE_RATE = 22050


def _shape(kind, phase):
    """One sample of a waveform at this phase (radians)."""
    if kind == "sine":
        return math.sin(phase)
    if kind == "triangle":
        x = (phase / math.tau) % 1.0
        return 4 * abs(x - 0.5) - 1
    if kind == "square":
        return 1.0 if math.sin(phase) >= 0 else -1.0
    if kind == "saw":
        x = (phase / math.tau) % 1.0
        return 2 * x - 1
    if kind == "noise":
        return random.uniform(-1, 1)
    return math.sin(phase)


def _envelope(t, dur, attack=0.012, release=0.09):
    """0..1 volume shape: quick fade in, hold, fade out."""
    if t < attack:
        return t / attack
    rel_start = max(attack, dur - release)
    if t > rel_start:
        return max(0.0, (dur - t) / max(1e-6, dur - rel_start))
    return 1.0


def _note(buf, start_s, dur, f0, f1=None, kind="sine", vol=0.5,
          harmonics=None, attack=0.012, release=0.09):
    """Mix one note (with an optional pitch glide) into buf."""
    f1 = f0 if f1 is None else f1
    n = max(1, int(dur * SAMPLE_RATE))
    phase = 0.0
    for i in range(n):
        t = i / SAMPLE_RATE
        frac = i / max(1, n - 1)
        freq = f0 + (f1 - f0) * frac
        phase += math.tau * freq / SAMPLE_RATE
        env = _envelope(t, dur, attack, release)
        val = _shape(kind, phase) * vol * env
        if harmonics:
            for mult, amp in harmonics:
                val += _shape(kind, phase * mult) * vol * amp * env
        idx = start_s + i
        if 0 <= idx < len(buf):
            buf[idx] += val


def _render(notes, tail=0.08):
    """notes: list of dicts -> one mixed-down WAV, as bytes."""
    total = max(n["start"] + n["dur"] for n in notes) + tail
    buf = [0.0] * int(total * SAMPLE_RATE)
    for n in notes:
        _note(buf, int(n["start"] * SAMPLE_RATE), n["dur"], n["f0"],
              n.get("f1"), n.get("kind", "sine"), n.get("vol", 0.5),
              n.get("harmonics"), n.get("attack", 0.012),
              n.get("release", 0.09))
    peak = max(0.9, max((abs(x) for x in buf), default=0.9))
    scale = 0.9 / peak
    pcm = bytearray()
    for x in buf:
        v = max(-1.0, min(1.0, x * scale))
        pcm += struct.pack("<h", int(v * 32767))
    bio = io.BytesIO()
    with wave.open(bio, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(bytes(pcm))
    return bio.getvalue()


def _chime(freqs, step=0.09, note_dur=0.16, kind="triangle", vol=0.4):
    """A quick little run of notes, one after another."""
    return [{"start": i * step, "dur": note_dur, "f0": f, "kind": kind,
              "vol": vol, "harmonics": [(2, 0.15)]}
            for i, f in enumerate(freqs)]


def _build_sound_bank():
    bank = {}

    # LEFT - butterflies: light fluttery rising chime.
    bank["LEFT"] = _render(_chime([880, 1046, 1244, 1568], step=0.07,
                                  note_dur=0.14, kind="triangle", vol=0.35))

    # RIGHT - fish: bubbly descending "blub" glides.
    bank["RIGHT"] = _render([
        {"start": 0.00, "dur": 0.12, "f0": 500, "f1": 320, "kind": "sine", "vol": 0.4},
        {"start": 0.10, "dur": 0.12, "f0": 620, "f1": 380, "kind": "sine", "vol": 0.4},
        {"start": 0.20, "dur": 0.14, "f0": 760, "f1": 420, "kind": "sine", "vol": 0.4},
    ])

    # UP - rainbow: sparkly rising arpeggio with shimmer.
    bank["UP"] = _render(_chime([523, 659, 784, 988, 1318], step=0.07,
                                note_dur=0.2, kind="sine", vol=0.32))

    # DOWN - flowers: a soft rising "bloom" then a tiny pop.
    bank["DOWN"] = _render([
        {"start": 0.0, "dur": 0.45, "f0": 300, "f1": 700, "kind": "sine",
         "vol": 0.35, "attack": 0.15, "release": 0.2,
         "harmonics": [(2, 0.12)]},
        {"start": 0.42, "dur": 0.08, "f0": 1400, "f1": 1400, "kind": "triangle",
         "vol": 0.3, "attack": 0.005, "release": 0.06},
    ])

    # FORWARD - fireworks: a whoosh up, then a crackly burst.
    forward_notes = [
        {"start": 0.0, "dur": 0.22, "f0": 300, "f1": 1800, "kind": "saw",
         "vol": 0.3, "attack": 0.01, "release": 0.1},
    ]
    for i in range(10):
        forward_notes.append({
            "start": 0.2 + random.uniform(0, 0.2), "dur": 0.05,
            "f0": random.uniform(1500, 3500), "kind": "noise",
            "vol": 0.12, "attack": 0.002, "release": 0.03,
        })
    bank["FORWARD"] = _render(forward_notes)

    # BACKWARD - bubbles: soft ascending blub tones.
    bank["BACKWARD"] = _render([
        {"start": 0.00, "dur": 0.16, "f0": 300, "f1": 420, "kind": "sine", "vol": 0.35},
        {"start": 0.14, "dur": 0.16, "f0": 380, "f1": 520, "kind": "sine", "vol": 0.35},
        {"start": 0.28, "dur": 0.18, "f0": 460, "f1": 640, "kind": "sine", "vol": 0.35},
    ])

    # SHAKE - confetti: a giggly rattling cascade of notes.
    shake_freqs = [random.choice([784, 988, 1175, 1318, 1568]) for _ in range(9)]
    bank["SHAKE"] = _render(_chime(shake_freqs, step=0.055, note_dur=0.08,
                                   kind="square", vol=0.22))

    # SPIN - galaxy: a fast whirring pitch sweep up then down.
    bank["SPIN"] = _render([
        {"start": 0.0, "dur": 0.18, "f0": 400, "f1": 1400, "kind": "saw", "vol": 0.28},
        {"start": 0.16, "dur": 0.18, "f0": 1400, "f1": 500, "kind": "saw", "vol": 0.28},
    ])

    # TAP - lightning: one bright zap with a tiny click.
    bank["TAP"] = _render([
        {"start": 0.0, "dur": 0.02, "f0": 3000, "kind": "noise", "vol": 0.25,
         "attack": 0.001, "release": 0.015},
        {"start": 0.0, "dur": 0.14, "f0": 1800, "f1": 700, "kind": "square",
         "vol": 0.3, "attack": 0.002, "release": 0.1},
    ])

    # CIRCLE - sun: a warm sustained "ta-da" chord.
    bank["CIRCLE"] = _render([
        {"start": 0.0, "dur": 0.7, "f0": 523, "kind": "sine", "vol": 0.22,
         "attack": 0.05, "release": 0.35, "harmonics": [(2, 0.15), (3, 0.08)]},
        {"start": 0.05, "dur": 0.65, "f0": 659, "kind": "sine", "vol": 0.2,
         "attack": 0.05, "release": 0.35},
        {"start": 0.1, "dur": 0.6, "f0": 784, "kind": "sine", "vol": 0.2,
         "attack": 0.05, "release": 0.35},
    ])

    # Diagonals - short directional whoosh variants.
    bank["UP_LEFT"] = _render([
        {"start": 0.0, "dur": 0.28, "f0": 500, "f1": 1500, "kind": "sine", "vol": 0.3}])
    bank["UP_RIGHT"] = _render([
        {"start": 0.0, "dur": 0.28, "f0": 500, "f1": 1700, "kind": "triangle", "vol": 0.3}])
    bank["DOWN_LEFT"] = _render([
        {"start": 0.0, "dur": 0.28, "f0": 1600, "f1": 400, "kind": "sine", "vol": 0.3}])
    bank["DOWN_RIGHT"] = _render([
        {"start": 0.0, "dur": 0.28, "f0": 1600, "f1": 500, "kind": "triangle", "vol": 0.3}])

    # SQUARE - four blocky little beeps, matching the four sides.
    bank["SQUARE"] = _render(_chime([392, 392, 523, 523], step=0.14,
                                    note_dur=0.12, kind="square", vol=0.3))

    # BALL - a boing: pitch dips like a bounce, twice.
    bank["BALL"] = _render([
        {"start": 0.00, "dur": 0.16, "f0": 900, "f1": 300, "kind": "sine", "vol": 0.35},
        {"start": 0.18, "dur": 0.12, "f0": 700, "f1": 350, "kind": "sine", "vol": 0.28},
    ])

    # MEGA - the big surprise: an ascending fanfare with sparkle.
    mega_notes = _chime([523, 659, 784, 988, 1175, 1568], step=0.09,
                        note_dur=0.22, kind="triangle", vol=0.34)
    mega_notes.append({"start": 0.7, "dur": 0.5, "f0": 1568, "kind": "sine",
                       "vol": 0.25, "attack": 0.02, "release": 0.35,
                       "harmonics": [(2, 0.2), (3, 0.1)]})
    bank["MEGA"] = _render(mega_notes)

    return bank


SOUND_BANK = _build_sound_bank() if HAS_SOUND else {}


def play_sound(name):
    if not (HAS_SOUND and SOUND_ON):
        return
    data = SOUND_BANK.get(name)
    if not data:
        return

    def run():
        try:
            winsound.PlaySound(data, winsound.SND_MEMORY | winsound.SND_ASYNC)
        except Exception:
            pass

    threading.Thread(target=run, daemon=True).start()


# ============================================================
# SPRITE ENGINE
# ============================================================
# A sprite creates its canvas shapes ONCE, then every frame it
# just moves them with canvas.coords(). That is the big speed
# difference compared with deleting and recreating shapes.

sprites = []


class Sprite:
    def __init__(self):
        self.items = []
        self.alive = True

    def own(self, item_id):
        self.items.append(item_id)
        return item_id

    def update(self, dt):
        pass

    def destroy(self):
        for item_id in self.items:
            canvas.delete(item_id)
        self.items = []


def add(sprite):
    sprites.append(sprite)
    return sprite


def clear_all():
    for s in sprites:
        s.destroy()
    sprites.clear()
    canvas.delete("fx")


# ---------- background stars (they survive every clear) ------

stars = []
for _ in range(60):
    sx = random.randint(0, WIDTH)
    sy = random.randint(0, HEIGHT)
    ss = random.choice([1, 1, 2, 3])
    stars.append(canvas.create_oval(sx - ss, sy - ss, sx + ss, sy + ss,
                                    fill="#ffffff", outline="",
                                    tags="star"))


def twinkle():
    for item_id in random.sample(stars, 6):
        canvas.itemconfig(item_id,
                          fill=random.choice(["#ffffff", "#8899ff", "#556088"]))


# ============================================================
# BASIC SPRITES USED EVERYWHERE
# ============================================================

class Spark(Sprite):
    """A dot that flies, shrinks and fades out."""

    def __init__(self, x, y, vx, vy, size, color,
                 life=0.9, gravity=0.0, drag=1.0):
        super().__init__()
        self.x, self.y = x, y
        self.vx, self.vy = vx, vy
        self.size = size
        self.color = color
        self.life = life
        self.max_life = life
        self.gravity = gravity
        self.drag = drag
        self.id = self.own(canvas.create_oval(
            x - size, y - size, x + size, y + size,
            fill=color, outline="", tags="fx"))

    def update(self, dt):
        self.vy += self.gravity * dt
        self.vx *= self.drag
        self.vy *= self.drag
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.life -= dt
        if self.life <= 0:
            self.alive = False
            return
        k = self.life / self.max_life
        s = max(1.0, self.size * k)
        canvas.coords(self.id, self.x - s, self.y - s, self.x + s, self.y + s)
        canvas.itemconfig(self.id, fill=mix(BG, self.color, 0.25 + 0.75 * k))


class Flash(Sprite):
    """A full screen colour wash that fades away fast."""

    def __init__(self, color, life=0.35, strength=0.55):
        super().__init__()
        self.color = color
        self.life = life
        self.max_life = life
        self.strength = strength
        self.id = self.own(canvas.create_rectangle(
            0, 0, WIDTH, HEIGHT, fill=color, outline="", tags="fx"))
        canvas.tag_lower(self.id)

    def update(self, dt):
        self.life -= dt
        if self.life <= 0:
            self.alive = False
            return
        k = self.life / self.max_life
        canvas.itemconfig(self.id, fill=mix(BG, self.color, k * self.strength))


class Word(Sprite):
    """Big bouncing word + emoji announcing the gesture."""

    def __init__(self, text, color, hold=1.3):
        super().__init__()
        self.t = 0.0
        self.hold = hold
        self.color = color
        self.id = self.own(canvas.create_text(
            WIDTH // 2, int(HEIGHT * 0.15), text=text,
            font=("Segoe UI Black", 10), fill=color, tags="fx"))

    def update(self, dt):
        self.t += dt
        if self.t < 0.18:                       # pop in
            size = int(BIG_FONT * (self.t / 0.18))
        elif self.t < self.hold:                # gentle wobble
            size = int(BIG_FONT + BIG_FONT * 0.06 * math.sin(self.t * 14))
        elif self.t < self.hold + 0.3:          # shrink away
            size = int(BIG_FONT * (1 - (self.t - self.hold) / 0.3))
        else:
            self.alive = False
            return
        canvas.itemconfig(self.id, font=("Segoe UI Black", max(2, size)))


def burst(x, y, color=None, count=34, power=520, gravity=340, life=1.0):
    """A firework style explosion of sparks."""
    for _ in range(count):
        a = random.uniform(0, math.tau)
        sp = random.uniform(power * 0.25, power)
        add(Spark(x, y,
                  math.cos(a) * sp, math.sin(a) * sp,
                  random.uniform(3, 9),
                  color or pick(),
                  life=random.uniform(life * 0.6, life),
                  gravity=gravity, drag=0.985))


# ============================================================
# GESTURE SPRITES
# ============================================================

class Butterfly(Sprite):
    def __init__(self, x, y, direction=1):
        super().__init__()
        self.x, self.y = x, y
        self.dir = direction
        self.speed = random.uniform(420, 700)
        self.size = random.randint(26, 46)
        self.color = pick()
        self.phase = random.uniform(0, 6)
        self.t = random.uniform(0, 6)
        s = self.size
        self.lw = self.own(canvas.create_oval(0, 0, 1, 1, fill=self.color,
                                              outline="", tags="fx"))
        self.rw = self.own(canvas.create_oval(0, 0, 1, 1, fill=self.color,
                                              outline="", tags="fx"))
        self.body = self.own(canvas.create_oval(0, 0, 1, 1, fill="#ffffff",
                                                outline="", tags="fx"))
        self.trail_timer = 0.0
        del s

    def update(self, dt):
        self.t += dt
        self.phase += dt * 16
        self.x += self.speed * self.dir * dt
        self.y += math.sin(self.t * 3.4) * 150 * dt

        wing = 0.2 + 0.8 * abs(math.sin(self.phase))
        w = self.size * wing
        h = self.size * 0.55
        canvas.coords(self.lw, self.x - w, self.y - h, self.x, self.y + h)
        canvas.coords(self.rw, self.x, self.y - h, self.x + w, self.y + h)
        canvas.coords(self.body, self.x - 5, self.y - 13,
                      self.x + 5, self.y + 13)

        self.trail_timer -= dt
        if self.trail_timer <= 0:
            self.trail_timer = 0.05
            add(Spark(self.x, self.y, 0, 40, 4, self.color, life=0.5))

        if self.x < -160 or self.x > WIDTH + 160:
            self.alive = False


class Fish(Sprite):
    def __init__(self, x, y, direction=-1):
        super().__init__()
        self.x, self.y = x, y
        self.dir = direction
        self.speed = random.uniform(380, 640)
        self.size = random.randint(30, 52)
        self.color = pick()
        self.t = random.uniform(0, 6)
        self.body = self.own(canvas.create_oval(0, 0, 1, 1, fill=self.color,
                                                outline="", tags="fx"))
        self.tail = self.own(canvas.create_polygon(0, 0, 0, 0, 0, 0,
                                                   fill=self.color,
                                                   outline="", tags="fx"))
        self.eye = self.own(canvas.create_oval(0, 0, 1, 1, fill="#ffffff",
                                               outline="", tags="fx"))
        self.pupil = self.own(canvas.create_oval(0, 0, 1, 1, fill="#111111",
                                                 outline="", tags="fx"))

    def update(self, dt):
        self.t += dt
        self.x += self.speed * self.dir * dt
        self.y += math.sin(self.t * 4) * 90 * dt
        s = self.size
        d = self.dir
        canvas.coords(self.body, self.x - s, self.y - s * 0.5,
                      self.x + s, self.y + s * 0.5)

        swish = math.sin(self.t * 18) * s * 0.35
        tx = self.x - s * d
        canvas.coords(self.tail,
                      tx, self.y,
                      tx - s * 0.7 * d, self.y - s * 0.5 + swish,
                      tx - s * 0.7 * d, self.y + s * 0.5 + swish)

        ex = self.x + s * 0.45 * d
        canvas.coords(self.eye, ex - 9, self.y - 13, ex + 9, self.y + 5)
        canvas.coords(self.pupil, ex - 4, self.y - 9, ex + 4, self.y - 1)

        if self.x < -220 or self.x > WIDTH + 220:
            self.alive = False


class Flower(Sprite):
    def __init__(self, x, target, delay=0.0):
        super().__init__()
        self.x = x
        self.target = target
        self.h = 0.0
        self.delay = delay
        self.color = pick()
        self.popped = False
        self.t = 0.0
        self.stem = self.own(canvas.create_line(x, HEIGHT, x, HEIGHT,
                                                fill="#4ce660", width=9,
                                                tags="fx"))
        self.petals = [self.own(canvas.create_oval(0, 0, 1, 1,
                                                   fill=self.color,
                                                   outline="", tags="fx"))
                       for _ in range(6)]
        self.center = self.own(canvas.create_oval(0, 0, 1, 1,
                                                  fill="#ffe14d",
                                                  outline="", tags="fx"))

    def update(self, dt):
        self.t += dt
        if self.t < self.delay:
            return
        if self.h < self.target:
            self.h = min(self.target, self.h + 900 * dt)
        elif not self.popped:
            self.popped = True
            burst(self.x, HEIGHT - self.h, self.color,
                  count=12, power=220, gravity=200, life=0.6)

        top = HEIGHT - self.h
        sway = math.sin(self.t * 3 + self.x) * 10
        canvas.coords(self.stem, self.x, HEIGHT, self.x + sway, top)

        grow = min(1.0, self.h / max(1.0, self.target))
        pr = 20 * grow
        for i, petal in enumerate(self.petals):
            a = math.radians(i * 60) + self.t * 0.8
            px = self.x + sway + math.cos(a) * 30 * grow
            py = top + math.sin(a) * 30 * grow
            canvas.coords(petal, px - pr, py - pr, px + pr, py + pr)

        cr = 15 * grow
        canvas.coords(self.center, self.x + sway - cr, top - cr,
                      self.x + sway + cr, top + cr)


class Bubble(Sprite):
    def __init__(self, x, y):
        super().__init__()
        self.x, self.y = x, y
        self.size = random.randint(18, 55)
        self.speed = random.uniform(160, 320)
        self.t = random.uniform(0, 6)
        self.color = random.choice(["#8ae7ff", "#c9a7ff", "#ffffff", "#7cff3f"])
        self.ring = self.own(canvas.create_oval(0, 0, 1, 1, outline=self.color,
                                                width=3, tags="fx"))
        self.shine = self.own(canvas.create_oval(0, 0, 1, 1, fill="#ffffff",
                                                 outline="", tags="fx"))

    def update(self, dt):
        self.t += dt
        self.y -= self.speed * dt
        self.x += math.sin(self.t * 2.2) * 60 * dt
        s = self.size
        canvas.coords(self.ring, self.x - s, self.y - s, self.x + s, self.y + s)
        canvas.coords(self.shine, self.x - s * 0.5, self.y - s * 0.6,
                      self.x - s * 0.2, self.y - s * 0.3)
        if self.y < -s - 10:
            self.alive = False
            add(Spark(self.x, 0, 0, 60, 6, self.color, life=0.4))


class Confetti(Sprite):
    def __init__(self, x, y):
        super().__init__()
        self.x, self.y = x, y
        self.vx = random.uniform(-160, 160)
        self.vy = random.uniform(120, 420)
        self.size = random.uniform(10, 20)
        self.spin = random.uniform(-9, 9)
        self.angle = random.uniform(0, 6)
        self.color = pick()
        self.id = self.own(canvas.create_polygon(0, 0, 0, 0, 0, 0, 0, 0,
                                                 fill=self.color,
                                                 outline="", tags="fx"))

    def update(self, dt):
        self.vy += 260 * dt
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.angle += self.spin * dt
        w = self.size
        h = self.size * (0.35 + 0.65 * abs(math.sin(self.angle * 1.7)))
        ca, sa = math.cos(self.angle), math.sin(self.angle)
        pts = []
        for dx, dy in ((-w, -h), (w, -h), (w, h), (-w, h)):
            pts += [self.x + dx * ca - dy * sa, self.y + dx * sa + dy * ca]
        canvas.coords(self.id, *pts)
        if self.y > HEIGHT + 60:
            self.alive = False


class Orbiter(Sprite):
    """Used for the swirling galaxy."""

    def __init__(self, cx, cy, radius, angle, speed, color, size):
        super().__init__()
        self.cx, self.cy = cx, cy
        self.r = radius
        self.a = angle
        self.speed = speed
        self.color = color
        self.size = size
        self.life = 2.6
        self.id = self.own(canvas.create_oval(0, 0, 1, 1, fill=color,
                                              outline="", tags="fx"))

    def update(self, dt):
        self.life -= dt
        self.a += self.speed * dt
        self.r += 190 * dt
        x = self.cx + math.cos(self.a) * self.r
        y = self.cy + math.sin(self.a) * self.r * 0.62
        s = self.size
        canvas.coords(self.id, x - s, y - s, x + s, y + s)
        if self.life <= 0 or self.r > max(WIDTH, HEIGHT):
            self.alive = False


class Bolt(Sprite):
    """A jagged lightning bolt that flickers then vanishes."""

    def __init__(self, x1, y1, x2, y2, color="#ffffff"):
        super().__init__()
        pts = []
        steps = 12
        for i in range(steps + 1):
            t = i / steps
            jx = random.uniform(-45, 45) if 0 < i < steps else 0
            jy = random.uniform(-25, 25) if 0 < i < steps else 0
            pts += [x1 + (x2 - x1) * t + jx, y1 + (y2 - y1) * t + jy]
        self.id = self.own(canvas.create_line(*pts, fill=color, width=9,
                                              capstyle="round", tags="fx"))
        self.life = 0.45
        self.color = color

    def update(self, dt):
        self.life -= dt
        if self.life <= 0:
            self.alive = False
            return
        on = int(self.life * 40) % 2 == 0
        canvas.itemconfig(self.id,
                          fill=self.color if on else mix(BG, self.color, 0.3),
                          width=9 if on else 4)


class SunFace(Sprite):
    """A huge smiley sun that grows, spins its rays and blinks."""

    def __init__(self, cx, cy):
        super().__init__()
        self.cx, self.cy = cx, cy
        self.t = 0.0
        self.R = min(WIDTH, HEIGHT) * 0.22
        self.rays = [self.own(canvas.create_line(0, 0, 0, 0, fill="#ffd400",
                                                 width=12, capstyle="round",
                                                 tags="fx"))
                     for _ in range(14)]
        self.face = self.own(canvas.create_oval(0, 0, 1, 1, fill="#ffe14d",
                                                outline="", tags="fx"))
        self.eye1 = self.own(canvas.create_oval(0, 0, 1, 1, fill="#2b1a00",
                                                outline="", tags="fx"))
        self.eye2 = self.own(canvas.create_oval(0, 0, 1, 1, fill="#2b1a00",
                                                outline="", tags="fx"))
        self.mouth = self.own(canvas.create_arc(0, 0, 1, 1, start=200,
                                                extent=140, style="arc",
                                                outline="#2b1a00", width=12,
                                                tags="fx"))

    def update(self, dt):
        self.t += dt
        grow = min(1.0, self.t / 0.35)
        bounce = 1 + 0.05 * math.sin(self.t * 7)
        r = self.R * grow * bounce
        cx, cy = self.cx, self.cy

        for i, ray in enumerate(self.rays):
            a = math.radians(i * (360 / len(self.rays))) + self.t * 0.9
            canvas.coords(ray,
                          cx + math.cos(a) * r * 1.15,
                          cy + math.sin(a) * r * 1.15,
                          cx + math.cos(a) * r * 1.55,
                          cy + math.sin(a) * r * 1.55)

        canvas.coords(self.face, cx - r, cy - r, cx + r, cy + r)

        blink = (self.t % 2.2) > 2.0
        eh = r * (0.03 if blink else 0.13)
        for eye, side in ((self.eye1, -1), (self.eye2, 1)):
            ex = cx + side * r * 0.36
            ey = cy - r * 0.2
            canvas.coords(eye, ex - r * 0.1, ey - eh, ex + r * 0.1, ey + eh)

        canvas.coords(self.mouth, cx - r * 0.55, cy - r * 0.35,
                      cx + r * 0.55, cy + r * 0.65)

        if self.t > 3.2:
            self.alive = False


class Rocket(Sprite):
    def __init__(self, x):
        super().__init__()
        self.x = x
        self.y = HEIGHT + 60
        self.speed = random.uniform(700, 1000)
        self.color = pick()
        self.body = self.own(canvas.create_polygon(0, 0, 0, 0, 0, 0,
                                                   fill=self.color,
                                                   outline="", tags="fx"))
        self.timer = 0.0

    def update(self, dt):
        self.y -= self.speed * dt
        canvas.coords(self.body,
                      self.x, self.y - 34,
                      self.x - 20, self.y + 24,
                      self.x + 20, self.y + 24)
        self.timer -= dt
        if self.timer <= 0:
            self.timer = 0.02
            add(Spark(self.x, self.y + 26,
                      random.uniform(-90, 90), random.uniform(120, 300),
                      random.uniform(4, 9),
                      random.choice(["#ffd400", "#ff7a18", "#ffffff"]),
                      life=0.45))
        if self.y < HEIGHT * 0.3:
            self.alive = False
            burst(self.x, self.y, self.color, count=40, power=560)


# ---------- diagonal movement sprites -------------------------

class Comet(Sprite):
    """A bright streak that shoots across the screen leaving sparks.
    Used for the UP_LEFT and DOWN_LEFT diagonal gestures."""

    def __init__(self, x, y, dx, dy, color, size=15):
        super().__init__()
        self.x, self.y = x, y
        self.dx, self.dy = dx, dy
        self.color = color
        self.size = size
        self.trail_timer = 0.0
        self.id = self.own(canvas.create_oval(0, 0, 1, 1, fill=color,
                                              outline="#ffffff", width=2,
                                              tags="fx"))

    def update(self, dt):
        self.x += self.dx * dt
        self.y += self.dy * dt
        s = self.size
        canvas.coords(self.id, self.x - s, self.y - s, self.x + s, self.y + s)

        self.trail_timer -= dt
        if self.trail_timer <= 0:
            self.trail_timer = 0.018
            add(Spark(self.x, self.y,
                      -self.dx * 0.15 + random.uniform(-40, 40),
                      -self.dy * 0.15 + random.uniform(-40, 40),
                      random.uniform(4, 9), self.color,
                      life=0.5, drag=0.96))

        if (self.x < -140 or self.x > WIDTH + 140 or
                self.y < -140 or self.y > HEIGHT + 140):
            self.alive = False


class Kite(Sprite):
    """A diamond kite with a wavy dotted tail, for the UP_RIGHT gesture."""

    def __init__(self, x, y, dx, dy, color):
        super().__init__()
        self.x, self.y = x, y
        self.dx, self.dy = dx, dy
        self.color = color
        self.history = []
        self.body = self.own(canvas.create_polygon(0, 0, 0, 0, 0, 0, 0, 0,
                                                   fill=color,
                                                   outline="#ffffff",
                                                   width=2, tags="fx"))
        self.tail = [self.own(canvas.create_oval(0, 0, 1, 1, fill=color,
                                                 outline="", tags="fx"))
                     for _ in range(7)]

    def update(self, dt):
        self.x += self.dx * dt
        self.y += self.dy * dt
        s = 26
        canvas.coords(self.body,
                      self.x, self.y - s,
                      self.x + s * 0.75, self.y,
                      self.x, self.y + s,
                      self.x - s * 0.75, self.y)

        self.history.insert(0, (self.x, self.y))
        if len(self.history) > 90:
            self.history.pop()

        for i, dot in enumerate(self.tail):
            idx = min(len(self.history) - 1, (i + 1) * 9)
            hx, hy = self.history[idx]
            wob = math.sin(idx * 0.3 + self.x * 0.01) * 10
            ds = 8 - i * 0.8
            canvas.coords(dot, hx - ds + wob, hy - ds, hx + ds + wob, hy + ds)

        if (self.x < -160 or self.x > WIDTH + 160 or
                self.y < -160 or self.y > HEIGHT + 160):
            self.alive = False


class PaperPlane(Sprite):
    """A little paper airplane gliding diagonally, for DOWN_RIGHT."""

    def __init__(self, x, y, dx, dy, color):
        super().__init__()
        self.x, self.y = x, y
        self.dx, self.dy = dx, dy
        self.color = color
        self.angle = math.atan2(dy, dx)
        self.t = 0.0
        self.trail_timer = 0.0
        self.id = self.own(canvas.create_polygon(0, 0, 0, 0, 0, 0,
                                                 fill=color,
                                                 outline="#ffffff", width=1,
                                                 tags="fx"))

    def update(self, dt):
        self.t += dt
        self.x += self.dx * dt
        self.y += self.dy * dt
        wob = math.sin(self.t * 6) * 0.15
        a = self.angle + wob
        s = 22
        nose = (self.x + math.cos(a) * s, self.y + math.sin(a) * s)
        left = (self.x + math.cos(a + 2.5) * s * 0.7,
                self.y + math.sin(a + 2.5) * s * 0.7)
        right = (self.x + math.cos(a - 2.5) * s * 0.7,
                 self.y + math.sin(a - 2.5) * s * 0.7)
        canvas.coords(self.id, *nose, *left, *right)

        self.trail_timer -= dt
        if self.trail_timer <= 0:
            self.trail_timer = 0.05
            add(Spark(self.x, self.y, 0, 0, 3, "#ffffff", life=0.35, drag=0.9))

        if (self.x < -160 or self.x > WIDTH + 160 or
                self.y < -160 or self.y > HEIGHT + 160):
            self.alive = False


# ---------- shape sprites: square and ball ---------------------

class SquareRing(Sprite):
    """A square outline that grows from the centre, cycling colours."""

    def __init__(self, cx, cy):
        super().__init__()
        self.cx, self.cy = cx, cy
        self.t = 0.0
        self.color_i = 0.0
        self.id = self.own(canvas.create_rectangle(0, 0, 1, 1,
                                                   outline="#ffffff",
                                                   width=14, tags="fx"))

    def update(self, dt):
        self.t += dt
        self.color_i += dt * 1.4
        grow = min(1.0, self.t / 0.6)
        half = min(WIDTH, HEIGHT) * 0.32 * grow
        c1 = NEON[int(self.color_i) % len(NEON)]
        c2 = NEON[int(self.color_i + 1) % len(NEON)]
        color = mix(c1, c2, self.color_i % 1)
        canvas.coords(self.id, self.cx - half, self.cy - half,
                      self.cx + half, self.cy + half)
        canvas.itemconfig(self.id, outline=color)
        if self.t > 3.2:
            self.alive = False


class FallingBlock(Sprite):
    """A little square block that drops in and lands with a squash."""

    def __init__(self, x, target_y, color, delay=0.0):
        super().__init__()
        self.x = x
        self.y = -60.0
        self.target_y = target_y
        self.color = color
        self.delay = delay
        self.t = 0.0
        self.vy = 0.0
        self.landed = False
        self.size = 24
        self.id = self.own(canvas.create_rectangle(0, 0, 1, 1, fill=color,
                                                   outline="#ffffff",
                                                   width=2, tags="fx"))

    def update(self, dt):
        self.t += dt
        if self.t < self.delay:
            return
        if not self.landed:
            self.vy += 1400 * dt
            self.y += self.vy * dt
            if self.y >= self.target_y:
                self.y = self.target_y
                self.landed = True
                burst(self.x, self.y, self.color, count=10,
                      power=180, gravity=250, life=0.4)
        s = self.size
        squash = 1.0
        if self.landed and self.t - self.delay < 0.15:
            squash = 1.5
        canvas.coords(self.id, self.x - s, self.y - s / squash,
                      self.x + s, self.y + s * squash)
        if self.landed and self.t - self.delay > 2.2:
            self.alive = False


class BouncingBall(Sprite):
    """A ball that bounces across the screen, squashing on impact."""

    def __init__(self, x, y, vx, color, size=34):
        super().__init__()
        self.x, self.y = x, y
        self.vx = vx
        self.vy = random.uniform(-120, -60)
        self.color = color
        self.size = size
        self.squash = 1.0
        self.floor = HEIGHT - 80
        self.bounces = 0
        self.trail_timer = 0.0
        self.id = self.own(canvas.create_oval(0, 0, 1, 1, fill=color,
                                              outline="#ffffff", width=2,
                                              tags="fx"))

    def update(self, dt):
        self.vy += 1500 * dt
        self.x += self.vx * dt
        self.y += self.vy * dt

        if self.y >= self.floor:
            self.y = self.floor
            self.vy = -self.vy * 0.72
            self.bounces += 1
            self.squash = 1.6
            burst(self.x, self.floor + self.size * 0.5, self.color,
                  count=10, power=200, gravity=260, life=0.35)

        self.squash += (1.0 - self.squash) * min(1.0, dt * 10)
        s = self.size
        canvas.coords(self.id, self.x - s / self.squash,
                      self.y - s * self.squash,
                      self.x + s / self.squash,
                      self.y + s * self.squash)

        self.trail_timer -= dt
        if self.trail_timer <= 0:
            self.trail_timer = 0.03
            add(Spark(self.x, self.y, 0, 0, 5, self.color, life=0.3))

        if self.x < -100 or self.x > WIDTH + 100 or self.bounces > 6:
            self.alive = False


# ============================================================
# SCENES - one per gesture
# ============================================================
# A scene function builds the first sprites and may return an
# update(dt) function for anything that keeps spawning.

def scene_butterflies():
    add(Flash("#ff2fb9"))
    add(Word("BUTTERFLIES!", "#ff8ad8"))
    for i in range(9):
        add(Butterfly(-80 - i * 110,
                      random.randint(120, HEIGHT - 120), direction=1))
    return None


def scene_fish():
    add(Flash("#00e5ff"))
    add(Word("FISHIES!", "#8ae7ff"))
    for i in range(8):
        add(Fish(WIDTH + 90 + i * 130,
                 random.randint(140, HEIGHT - 140), direction=-1))
    state = {"t": 0.0}

    def update(dt):
        state["t"] += dt
        if random.random() < dt * 9:
            add(Bubble(random.randint(0, WIDTH), HEIGHT + 30))
    return update


def scene_rainbow():
    add(Flash("#7cff3f"))
    add(Word("RAINBOW!", "#ffd400"))
    colors = ["#ff4d4d", "#ff7a18", "#ffd400", "#7cff3f",
              "#00e5ff", "#6b6bff", "#b06cff"]
    arcs = []
    for i, c in enumerate(colors):
        arcs.append(canvas.create_arc(0, 0, 1, 1, start=0, extent=180,
                                      style="arc", width=22, outline=c,
                                      tags="fx"))

    class Rainbow(Sprite):
        def __init__(self):
            super().__init__()
            self.items = list(arcs)
            self.t = 0.0

        def update(self, dt):
            self.t += dt
            grow = min(1.0, self.t / 0.55)
            span = WIDTH * 0.42 * grow
            for i, arc in enumerate(self.items):
                off = i * 26 * grow
                canvas.coords(arc,
                              WIDTH / 2 - span + off, HEIGHT - span * 0.95 + off,
                              WIDTH / 2 + span - off, HEIGHT + span * 0.95 - off)
            if self.t > 3.0:
                self.alive = False

    add(Rainbow())
    for i in range(3):
        add(Rocket(WIDTH * (0.25 + 0.25 * i)))
    return None


def scene_flowers():
    add(Flash("#7cff3f"))
    add(Word("FLOWERS!", "#7cff3f"))
    n = 9
    for i in range(n):
        x = WIDTH * (i + 0.5) / n
        add(Flower(x, random.randint(160, 320), delay=i * 0.05))
    return None


def scene_fireworks():
    add(Flash("#ffd400", strength=0.7))
    add(Word("MAGIC!", "#ffe14d"))
    burst(WIDTH / 2, HEIGHT / 2, count=60, power=700)
    state = {"t": 0.0, "next": 0.25, "n": 0}

    def update(dt):
        state["t"] += dt
        if state["t"] >= state["next"] and state["n"] < 7:
            state["n"] += 1
            state["next"] = state["t"] + 0.3
            burst(random.uniform(WIDTH * 0.15, WIDTH * 0.85),
                  random.uniform(HEIGHT * 0.15, HEIGHT * 0.6),
                  count=40, power=620)
    return update


def scene_bubbles():
    add(Flash("#8ae7ff"))
    add(Word("BUBBLES!", "#8ae7ff"))
    for _ in range(14):
        add(Bubble(random.randint(40, WIDTH - 40),
                   HEIGHT + random.randint(20, 400)))
    state = {"t": 0.0}

    def update(dt):
        state["t"] += dt
        if state["t"] < 2.5 and random.random() < dt * 12:
            add(Bubble(random.randint(40, WIDTH - 40), HEIGHT + 40))
    return update


def scene_confetti():
    add(Flash("#ff2fb9", strength=0.7))
    add(Word("PARTY!", "#ff2fb9"))
    for _ in range(60):
        add(Confetti(random.randint(0, WIDTH), random.randint(-300, -20)))
    state = {"t": 0.0}

    def update(dt):
        state["t"] += dt
        if state["t"] < 2.0:
            for _ in range(int(60 * dt) + 1):
                add(Confetti(random.randint(0, WIDTH), -30))
    return update


def scene_galaxy():
    add(Flash("#b06cff"))
    add(Word("SPIN!", "#b06cff"))
    cx, cy = WIDTH / 2, HEIGHT / 2
    state = {"t": 0.0, "a": 0.0}

    def update(dt):
        state["t"] += dt
        state["a"] += dt * 7
        if state["t"] < 2.2:
            for i in range(3):
                a = state["a"] + i * math.tau / 3
                add(Orbiter(cx, cy, 20, a, 3.2, pick(),
                            random.uniform(4, 11)))
    return update


def scene_lightning():
    add(Flash("#ffffff", life=0.2, strength=0.85))
    add(Word("ZAP!", "#00e5ff"))
    state = {"t": 0.0, "next": 0.0, "n": 0}

    def update(dt):
        state["t"] += dt
        if state["t"] >= state["next"] and state["n"] < 6:
            state["n"] += 1
            state["next"] = state["t"] + random.uniform(0.15, 0.3)
            x = random.uniform(WIDTH * 0.2, WIDTH * 0.8)
            add(Bolt(x, -20, x + random.uniform(-250, 250), HEIGHT * 0.8,
                     random.choice(["#ffffff", "#00e5ff", "#ffd400"])))
            burst(x, HEIGHT * 0.8, "#00e5ff", count=18, power=380)
    return update


def scene_sun():
    add(Flash("#ffd400"))
    add(Word("HELLO SUN!", "#ffd400"))
    add(SunFace(WIDTH / 2, HEIGHT * 0.55))
    return None


def scene_mega():
    add(Flash("#ffffff", life=0.5, strength=0.9))
    add(Word("MEGA MAGIC!", "#ffffff", hold=2.0))
    for _ in range(40):
        add(Confetti(random.randint(0, WIDTH), random.randint(-400, -20)))
    for i in range(4):
        add(Butterfly(-80 - i * 150, random.randint(120, HEIGHT - 120)))
        add(Fish(WIDTH + 80 + i * 150, random.randint(140, HEIGHT - 140)))
    add(SunFace(WIDTH / 2, HEIGHT * 0.55))
    state = {"t": 0.0, "next": 0.1}

    def update(dt):
        state["t"] += dt
        if state["t"] >= state["next"] and state["t"] < 3.0:
            state["next"] = state["t"] + 0.22
            burst(random.uniform(0, WIDTH), random.uniform(0, HEIGHT * 0.7),
                  count=35, power=650)
    return update


def scene_idle():
    """Gentle invitation when nobody has waved for a while."""
    add(Word("WAVE THE WAND!", "#6b6bff", hold=2.4))
    state = {"t": 0.0}

    def update(dt):
        state["t"] += dt
        if random.random() < dt * 6:
            add(Spark(random.uniform(0, WIDTH), HEIGHT + 10,
                      random.uniform(-30, 30), random.uniform(-90, -180),
                      random.uniform(3, 7), pick(), life=2.5))
    return update


# ---------- diagonal scenes -----------------------------------

def scene_comet_up_left():
    add(Flash("#66ccff"))
    add(Word("WHOOSH!", "#66ccff"))
    for i in range(7):
        x = WIDTH + 60 + i * 90
        y = HEIGHT + 60 + i * 40
        speed = random.uniform(780, 1050)
        add(Comet(x, y, -speed, -speed * 0.6, pick()))
    return None


def scene_kite_up_right():
    add(Flash("#ffd400"))
    add(Word("FLY HIGH!", "#ffd400"))
    for i in range(4):
        x = -80 - i * 140
        y = HEIGHT + 60 + i * 60
        speed = random.uniform(340, 480)
        add(Kite(x, y, speed, -speed * 0.65, pick()))
    return None


def scene_meteor_down_left():
    add(Flash("#ff7a18"))
    add(Word("METEORS!", "#ff7a18"))
    state = {"t": 0.0, "next": 0.0, "n": 0}

    def update(dt):
        state["t"] += dt
        if state["t"] >= state["next"] and state["n"] < 16:
            state["n"] += 1
            state["next"] = state["t"] + random.uniform(0.07, 0.16)
            x = random.uniform(WIDTH * 0.4, WIDTH + 100)
            y = random.uniform(-100, HEIGHT * 0.3)
            speed = random.uniform(700, 1000)
            add(Comet(x, y, -speed, speed * 0.55,
                      random.choice(["#ff7a18", "#ffd400", "#ff4d4d"])))
    return update


def scene_plane_down_right():
    add(Flash("#7cff3f"))
    add(Word("TAKE OFF!", "#7cff3f"))
    for i in range(4):
        x = -100 - i * 160
        y = -60 - i * 50
        speed = random.uniform(380, 520)
        add(PaperPlane(x, y, speed, speed * 0.6, pick()))
    return None


# ---------- shape scenes ---------------------------------------

def scene_square():
    add(Flash("#ff4d4d"))
    add(Word("SQUARE!", "#ff4d4d"))
    cx, cy = WIDTH / 2, HEIGHT / 2
    add(SquareRing(cx, cy))
    half = min(WIDTH, HEIGHT) * 0.32
    top = cy - half
    n = 7
    for i in range(n):
        x = cx - half + (i + 0.5) * (2 * half / n)
        add(FallingBlock(x, top, pick(), delay=i * 0.08))
    return None


def scene_ball():
    add(Flash("#00e5ff"))
    add(Word("BOUNCE!", "#00e5ff"))
    for i in range(3):
        add(BouncingBall(-60 - i * 120, HEIGHT - 300,
                         random.uniform(520, 680), pick(),
                         size=random.randint(28, 42)))
    return None


# gesture name -> (scene builder, colour used for the extra magic)
SCENES = {
    "LEFT":       (scene_butterflies, "#ff2fb9"),
    "RIGHT":      (scene_fish, "#00e5ff"),
    "UP":         (scene_rainbow, "#ffd400"),
    "DOWN":       (scene_flowers, "#7cff3f"),
    "FORWARD":    (scene_fireworks, "#ffe14d"),
    "BACKWARD":   (scene_bubbles, "#8ae7ff"),
    "SHAKE":      (scene_confetti, "#ff2fb9"),
    "SPIN":       (scene_galaxy, "#b06cff"),
    "TAP":        (scene_lightning, "#00e5ff"),
    "CIRCLE":     (scene_sun, "#ffd400"),
    "UP_LEFT":    (scene_comet_up_left, "#66ccff"),
    "UP_RIGHT":   (scene_kite_up_right, "#ffd400"),
    "DOWN_LEFT":  (scene_meteor_down_left, "#ff7a18"),
    "DOWN_RIGHT": (scene_plane_down_right, "#7cff3f"),
    "SQUARE":     (scene_square, "#ff4d4d"),
    "BALL":       (scene_ball, "#00e5ff"),
}

# Names your Arduino might already use for the same idea.
ALIASES = {
    "TWIST": "SPIN", "ROLL": "SPIN", "SWIRL": "SPIN",
    "ZAP": "TAP", "HIT": "TAP", "FLICK": "TAP", "POKE": "TAP",
    "WIGGLE": "SHAKE", "SHAKE_IT": "SHAKE",
    "PUSH": "FORWARD", "PULL": "BACKWARD",
    "LOOP": "CIRCLE", "ROUND": "CIRCLE",
    # diagonals
    "NW": "UP_LEFT", "UPLEFT": "UP_LEFT", "DIAG_UP_LEFT": "UP_LEFT",
    "NE": "UP_RIGHT", "UPRIGHT": "UP_RIGHT", "DIAG_UP_RIGHT": "UP_RIGHT",
    "SW": "DOWN_LEFT", "DOWNLEFT": "DOWN_LEFT", "DIAG_DOWN_LEFT": "DOWN_LEFT",
    "SE": "DOWN_RIGHT", "DOWNRIGHT": "DOWN_RIGHT", "DIAG_DOWN_RIGHT": "DOWN_RIGHT",
    # shapes
    "BOX": "SQUARE", "RECT": "SQUARE", "RECTANGLE": "SQUARE",
    "SPHERE": "BALL", "DROP": "BALL",
}


# ============================================================
# SCENE CONTROL
# ============================================================

current_update = None
last_gesture = None
last_gesture_time = 0.0
combo_count = 0
last_input_time = time.perf_counter()
idle_showing = False


def start_scene(builder):
    global current_update
    clear_all()
    twinkle()
    current_update = builder()


def extra_magic(gesture, color):
    """Same gesture repeated fast: add more instead of restarting."""
    x = random.uniform(WIDTH * 0.1, WIDTH * 0.9)
    y = random.uniform(HEIGHT * 0.15, HEIGHT * 0.75)
    burst(x, y, color, count=26, power=560)
    if gesture == "SHAKE":
        for _ in range(18):
            add(Confetti(random.randint(0, WIDTH), -30))
    elif gesture == "LEFT":
        add(Butterfly(-80, random.randint(120, HEIGHT - 120)))
    elif gesture == "RIGHT":
        add(Fish(WIDTH + 80, random.randint(140, HEIGHT - 140)))
    elif gesture == "BACKWARD":
        for _ in range(5):
            add(Bubble(random.randint(40, WIDTH - 40), HEIGHT + 30))
    elif gesture == "UP":
        add(Rocket(random.uniform(WIDTH * 0.2, WIDTH * 0.8)))
    elif gesture == "UP_LEFT":
        add(Comet(WIDTH + 60, HEIGHT + 60, -900, -540, color))
    elif gesture == "UP_RIGHT":
        add(Kite(-80, HEIGHT + 60, 420, -270, color))
    elif gesture == "DOWN_LEFT":
        add(Comet(WIDTH + 60, -60, -900, 500, color))
    elif gesture == "DOWN_RIGHT":
        add(PaperPlane(-100, -60, 450, 270, color))
    elif gesture == "SQUARE":
        add(FallingBlock(x, y - 200, color))
    elif gesture == "BALL":
        add(BouncingBall(-60, HEIGHT - 300, 600, color,
                         size=random.randint(28, 42)))


def handle_command(raw):
    global last_gesture, last_gesture_time, combo_count
    global last_input_time, idle_showing

    gesture = raw.strip().upper()
    gesture = ALIASES.get(gesture, gesture)
    if gesture not in SCENES:
        return

    now = time.perf_counter()
    last_input_time = now
    idle_showing = False

    builder, color = SCENES[gesture]
    repeat = (gesture == last_gesture and
              now - last_gesture_time < REPEAT_WINDOW)

    if repeat:
        combo_count += 1
    else:
        combo_count = 1

    last_gesture = gesture
    last_gesture_time = now

    print("WAND:", gesture, "combo", combo_count)

    # Enough fast repeats: the big surprise.
    if combo_count >= COMBO_FOR_MEGA:
        combo_count = 0
        last_gesture = None
        play_sound("MEGA")
        start_scene(scene_mega)
        return

    if repeat:
        # Keep the current animation, just make it bigger.
        play_sound(gesture)
        extra_magic(gesture, color)
    else:
        # A DIFFERENT movement: wipe the screen, start fresh.
        play_sound(gesture)
        start_scene(builder)


# ============================================================
# MAIN LOOP - runs at about 60 fps
# ============================================================

commands = Queue()
_last_time = time.perf_counter()
_twinkle_timer = 0.0


def tick():
    global _last_time, current_update, _twinkle_timer
    global idle_showing, last_input_time

    now = time.perf_counter()
    dt = now - _last_time
    _last_time = now
    dt = min(dt, 0.05)          # never take a giant step after a hiccup

    # 1. gestures that arrived from the serial thread
    while True:
        try:
            handle_command(commands.get_nowait())
        except Empty:
            break

    # 2. the scene's own spawner
    if current_update is not None:
        current_update(dt)

    # 3. every sprite
    dead = []
    for s in sprites:
        s.update(dt)
        if not s.alive:
            dead.append(s)
    for s in dead:
        s.destroy()
        sprites.remove(s)

    # 4. quiet background twinkle
    _twinkle_timer -= dt
    if _twinkle_timer <= 0:
        _twinkle_timer = 0.4
        twinkle()

    # 5. nobody playing? invite them
    if (not idle_showing) and (now - last_input_time > IDLE_SECONDS):
        idle_showing = True
        start_scene(scene_idle)
        last_input_time = now - IDLE_SECONDS + 12

    root.after(FRAME_MS, tick)


# ============================================================
# ARDUINO
# ============================================================

def find_port():
    if SERIAL_PORT != "AUTO":
        return SERIAL_PORT
    for p in list_ports.comports():
        text = (p.description or "") + (p.manufacturer or "")
        if any(k in text.lower() for k in
               ("arduino", "ch340", "usb serial", "wch", "silicon labs")):
            return p.device
    ports = list(list_ports.comports())
    return ports[0].device if ports else None


def listen_to_arduino():
    """Connects, reads lines, and reconnects on its own if unplugged."""
    if not HAS_SERIAL:
        print("pyserial not installed - keyboard mode only.")
        print("Install it with:  pip install pyserial")
        return

    while True:
        port = find_port()
        if port is None:
            print("No serial port found. Retrying in 2s...")
            time.sleep(2)
            continue
        try:
            print("Connecting to", port, "...")
            with serial.Serial(port, BAUD_RATE, timeout=1) as ard:
                print("Connected! Wave the magic wand.")
                while True:
                    line = ard.readline().decode("utf-8", "ignore").strip()
                    if line:
                        commands.put(line)
        except Exception as e:
            print("Serial problem:", e)
            print("Is the Arduino Serial Monitor still open? Retrying...")
            time.sleep(2)


threading.Thread(target=listen_to_arduino, daemon=True).start()


# ============================================================
# KEYBOARD - so you can test without the wand
# ============================================================
#   Arrow keys = LEFT / RIGHT / UP / DOWN
#   f = FORWARD   b = BACKWARD   s = SHAKE
#   p = SPIN      z = TAP        c = CIRCLE
#   q = UP_LEFT   e = UP_RIGHT
#   a = DOWN_LEFT d = DOWN_RIGHT
#   r = SQUARE    t = BALL
#   m = MEGA      ESC = quit

KEYS = {
    "Left": "LEFT", "Right": "RIGHT", "Up": "UP", "Down": "DOWN",
    "f": "FORWARD", "b": "BACKWARD", "s": "SHAKE",
    "p": "SPIN", "z": "TAP", "c": "CIRCLE",
    "q": "UP_LEFT", "e": "UP_RIGHT",
    "a": "DOWN_LEFT", "d": "DOWN_RIGHT",
    "r": "SQUARE", "t": "BALL",
}


def on_key(event):
    if event.keysym == "Escape":
        root.destroy()
        return
    if event.keysym == "m":
        play_sound("MEGA")
        start_scene(scene_mega)
        return
    name = KEYS.get(event.keysym) or KEYS.get(event.char)
    if name:
        commands.put(name)


root.bind("<Key>", on_key)

# Tapping the screen also makes magic, which toddlers find first.
canvas.bind("<Button-1>", lambda e: commands.put("TAP"))


# ============================================================
# GO
# ============================================================

print("Magic Wand ready. ESC to quit.")
start_scene(scene_idle)
root.after(FRAME_MS, tick)
root.mainloop()