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
# Short cheerful bleeps. They run in their own thread so the
# animation never stutters while a note is playing.

TUNES = {
    "LEFT":     [(880, 90), (1175, 90), (1568, 130)],
    "RIGHT":    [(1568, 90), (1175, 90), (880, 130)],
    "UP":       [(784, 80), (988, 80), (1175, 80), (1568, 160)],
    "DOWN":     [(1568, 80), (1175, 80), (784, 150)],
    "FORWARD":  [(1319, 70), (1760, 70), (2093, 180)],
    "BACKWARD": [(523, 90), (659, 90), (784, 90)],
    "SHAKE":    [(1046, 60), (1318, 60), (1046, 60), (1318, 120)],
    "SPIN":     [(659, 60), (880, 60), (1175, 60), (1568, 60), (2093, 120)],
    "TAP":      [(2093, 60), (1568, 120)],
    "CIRCLE":   [(1046, 110), (1318, 110), (1568, 220)],
    "MEGA":     [(784, 80), (988, 80), (1175, 80), (1568, 80),
                 (1976, 80), (2349, 250)],
}


def play_sound(name):
    if not (HAS_SOUND and SOUND_ON):
        return
    notes = TUNES.get(name)
    if not notes:
        return

    def run():
        try:
            for freq, ms in notes:
                winsound.Beep(freq, ms)
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


# gesture name -> (scene builder, colour used for the extra magic)
SCENES = {
    "LEFT":     (scene_butterflies, "#ff2fb9"),
    "RIGHT":    (scene_fish, "#00e5ff"),
    "UP":       (scene_rainbow, "#ffd400"),
    "DOWN":     (scene_flowers, "#7cff3f"),
    "FORWARD":  (scene_fireworks, "#ffe14d"),
    "BACKWARD": (scene_bubbles, "#8ae7ff"),
    "SHAKE":    (scene_confetti, "#ff2fb9"),
    "SPIN":     (scene_galaxy, "#b06cff"),
    "TAP":      (scene_lightning, "#00e5ff"),
    "CIRCLE":   (scene_sun, "#ffd400"),
}

# Names your Arduino might already use for the same idea.
ALIASES = {
    "TWIST": "SPIN", "ROLL": "SPIN", "SWIRL": "SPIN",
    "ZAP": "TAP", "HIT": "TAP", "FLICK": "TAP", "POKE": "TAP",
    "WIGGLE": "SHAKE", "SHAKE_IT": "SHAKE",
    "PUSH": "FORWARD", "PULL": "BACKWARD",
    "LOOP": "CIRCLE", "ROUND": "CIRCLE",
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
#   m = MEGA      ESC = quit

KEYS = {
    "Left": "LEFT", "Right": "RIGHT", "Up": "UP", "Down": "DOWN",
    "f": "FORWARD", "b": "BACKWARD", "s": "SHAKE",
    "p": "SPIN", "z": "TAP", "c": "CIRCLE",
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