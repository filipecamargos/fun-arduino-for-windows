# ============================================================
# 🪄 MAGIC WAND - SIMPLE TODDLER MAGIC
#
# Arduino sends:
#   LEFT
#   RIGHT
#   UP
#   DOWN
#   FORWARD
#   BACKWARD
#
# Windows displays ONE simple animation for each movement.
# ============================================================

import tkinter as tk
import serial
import threading
import random
import math
import time


# ============================================================
# SETTINGS
# ============================================================

SERIAL_PORT = "COM10"
BAUD_RATE = 115200

SCREEN_WIDTH = 1000
SCREEN_HEIGHT = 700


# ============================================================
# CREATE WINDOW
# ============================================================

root = tk.Tk()

root.title("🪄 Magic Wand")

root.geometry(f"{SCREEN_WIDTH}x{SCREEN_HEIGHT}")

root.configure(bg="#08051a")

# Try to make the window fill the screen.
root.attributes("-fullscreen", True)


# Get the actual screen size.
WIDTH = root.winfo_screenwidth()
HEIGHT = root.winfo_screenheight()


# Canvas = our magical world.
canvas = tk.Canvas(
    root,
    width=WIDTH,
    height=HEIGHT,
    bg="#08051a",
    highlightthickness=0
)

canvas.pack(fill="both", expand=True)


# ============================================================
# BACKGROUND
# ============================================================

# A few quiet stars.
# These stay still so the screen doesn't feel busy.

for i in range(35):

    x = random.randint(0, WIDTH)
    y = random.randint(0, HEIGHT)

    size = random.choice([1, 2, 3])

    canvas.create_oval(
        x - size,
        y - size,
        x + size,
        y + size,
        fill="#ffffff",
        outline=""
    )


# ============================================================
# CURRENT ANIMATION
# ============================================================

# Only ONE animation is allowed at a time.

animation_running = False


# ============================================================
# CLEAR SCREEN
# ============================================================

def clear_effects():

    """
    Remove everything except the quiet background stars.
    """

    canvas.delete("effect")


# ============================================================
# LEFT — BUTTERFLIES
# ============================================================

def butterfly_effect():

    global animation_running

    animation_running = True
    clear_effects()

    butterflies = []

    # Create a few butterflies.
    for i in range(6):

        x = -50 - i * 80
        y = random.randint(150, HEIGHT - 150)

        butterflies.append({
            "x": x,
            "y": y,
            "speed": random.uniform(7, 11),
            "size": random.randint(20, 35),
            "color": random.choice([
                "#ff66cc",
                "#66ccff",
                "#ffff66",
                "#cc66ff",
                "#66ffcc"
            ])
        })

    def animate():

        global animation_running

        # Move each butterfly.
        for b in butterflies:

            b["x"] += b["speed"]

            # Gentle up/down movement.
            b["y"] += math.sin(b["x"] / 30) * 2


        # Redraw.
        canvas.delete("effect")

        for b in butterflies:

            x = b["x"]
            y = b["y"]
            s = b["size"]

            # Left wing.
            canvas.create_oval(
                x - s,
                y - s // 2,
                x,
                y + s // 2,
                fill=b["color"],
                outline="",
                tags="effect"
            )

            # Right wing.
            canvas.create_oval(
                x,
                y - s // 2,
                x + s,
                y + s // 2,
                fill=b["color"],
                outline="",
                tags="effect"
            )

            # Body.
            canvas.create_oval(
                x - 4,
                y - 12,
                x + 4,
                y + 12,
                fill="#ffffff",
                outline="",
                tags="effect"
            )


        # Continue until butterflies leave the screen.
        if any(b["x"] < WIDTH + 100 for b in butterflies):

            root.after(30, animate)

        else:

            clear_effects()
            animation_running = False


    animate()


# ============================================================
# RIGHT — FISH
# ============================================================

def fish_effect():

    global animation_running

    animation_running = True
    clear_effects()

    fish = []

    for i in range(5):

        fish.append({
            "x": WIDTH + i * 100,
            "y": random.randint(180, HEIGHT - 180),
            "speed": random.uniform(6, 10),
            "size": random.randint(25, 45),
            "color": random.choice([
                "#ff8844",
                "#44ccff",
                "#ff66cc",
                "#ffff55",
                "#aa66ff"
            ])
        })

    def animate():

        global animation_running

        canvas.delete("effect")

        for f in fish:

            f["x"] -= f["speed"]

            x = f["x"]
            y = f["y"]
            s = f["size"]

            # Fish body.
            canvas.create_oval(
                x - s,
                y - s // 2,
                x + s,
                y + s // 2,
                fill=f["color"],
                outline="",
                tags="effect"
            )

            # Tail.
            canvas.create_polygon(
                x + s,
                y,
                x + s + s // 2,
                y - s // 2,
                x + s + s // 2,
                y + s // 2,
                fill=f["color"],
                outline="",
                tags="effect"
            )

            # Eye.
            canvas.create_oval(
                x - s // 2,
                y - 7,
                x - s // 2 + 10,
                y + 3,
                fill="white",
                outline="",
                tags="effect"
            )


        if any(f["x"] > -100 for f in fish):

            root.after(35, animate)

        else:

            clear_effects()
            animation_running = False


    animate()


# ============================================================
# UP — RAINBOW
# ============================================================

def rainbow_effect():

    global animation_running

    animation_running = True
    clear_effects()

    colors = [
        "#ff4444",
        "#ff8844",
        "#ffff44",
        "#44ff66",
        "#44ccff",
        "#6666ff",
        "#cc66ff"
    ]

    progress = 0

    def animate():

        global animation_running

        nonlocal progress

        canvas.delete("effect")

        progress += 12

        # Rainbow grows upward from the bottom.
        for i, color in enumerate(colors):

            offset = i * 12

            x1 = WIDTH // 2 - 300 + offset
            x2 = WIDTH // 2 + 300 - offset

            bottom = HEIGHT + 100
            top = HEIGHT - progress + offset

            canvas.create_arc(
                x1,
                top,
                x2,
                bottom,
                start=180,
                extent=180,
                style="arc",
                width=12,
                outline=color,
                tags="effect"
            )


        if progress < 500:

            root.after(30, animate)

        else:

            root.after(700, finish)


    def finish():

        global animation_running

        clear_effects()
        animation_running = False


    animate()


# ============================================================
# DOWN — FLOWERS
# ============================================================

def flower_effect():

    global animation_running

    animation_running = True
    clear_effects()

    flowers = []

    for i in range(8):

        flowers.append({
            "x": 70 + i * (WIDTH - 140) // 7,
            "height": 0,
            "target": random.randint(120, 260),
            "color": random.choice([
                "#ff66aa",
                "#ffff55",
                "#aa66ff",
                "#66ddff",
                "#ff8844"
            ])
        })

    def animate():

        global animation_running

        canvas.delete("effect")

        finished = True

        for f in flowers:

            if f["height"] < f["target"]:

                f["height"] += 8
                finished = False

            x = f["x"]
            bottom = HEIGHT
            top = HEIGHT - f["height"]

            # Stem.
            canvas.create_line(
                x,
                bottom,
                x,
                top,
                fill="#55dd55",
                width=8,
                tags="effect"
            )

            # Flower.
            for angle in range(0, 360, 72):

                a = math.radians(angle)

                px = x + math.cos(a) * 28
                py = top + math.sin(a) * 28

                canvas.create_oval(
                    px - 15,
                    py - 15,
                    px + 15,
                    py + 15,
                    fill=f["color"],
                    outline="",
                    tags="effect"
                )

            # Center.
            canvas.create_oval(
                x - 13,
                top - 13,
                x + 13,
                top + 13,
                fill="#ffff66",
                outline="",
                tags="effect"
            )


        if not finished:

            root.after(35, animate)

        else:

            root.after(900, finish)


    def finish():

        global animation_running

        clear_effects()
        animation_running = False


    animate()


# ============================================================
# FORWARD — BIG MAGIC STAR
# ============================================================

def star_effect():

    global animation_running

    animation_running = True
    clear_effects()

    particles = []

    center_x = WIDTH // 2
    center_y = HEIGHT // 2

    # Create particles flying outward.
    for i in range(80):

        angle = random.uniform(0, math.pi * 2)

        speed = random.uniform(4, 14)

        particles.append({
            "x": center_x,
            "y": center_y,
            "dx": math.cos(angle) * speed,
            "dy": math.sin(angle) * speed,
            "size": random.randint(3, 10),
            "color": random.choice([
                "#ffffff",
                "#ffff66",
                "#66ffff",
                "#ff66ff",
                "#ff8844"
            ])
        })


    frame = 0

    def animate():

        global animation_running

        nonlocal frame

        frame += 1

        canvas.delete("effect")

        # Draw the central star.
        if frame < 30:

            size = frame * 7

            canvas.create_text(
                center_x,
                center_y,
                text="★",
                font=("Arial", size),
                fill="#ffff88",
                tags="effect"
            )


        # Move particles.
        for p in particles:

            p["x"] += p["dx"]
            p["y"] += p["dy"]

            s = p["size"]

            canvas.create_oval(
                p["x"] - s,
                p["y"] - s,
                p["x"] + s,
                p["y"] + s,
                fill=p["color"],
                outline="",
                tags="effect"
            )


        if frame < 80:

            root.after(30, animate)

        else:

            clear_effects()
            animation_running = False


    animate()


# ============================================================
# BACKWARD — BUBBLES
# ============================================================

def bubble_effect():

    global animation_running

    animation_running = True
    clear_effects()

    bubbles = []

    for i in range(15):

        bubbles.append({
            "x": random.randint(50, WIDTH - 50),
            "y": HEIGHT + random.randint(20, 300),
            "speed": random.uniform(2, 5),
            "size": random.randint(15, 45)
        })


    frame = 0

    def animate():

        global animation_running

        nonlocal frame

        frame += 1

        canvas.delete("effect")

        for b in bubbles:

            b["y"] -= b["speed"]

            x = b["x"]
            y = b["y"]
            s = b["size"]

            canvas.create_oval(
                x - s,
                y - s,
                x + s,
                y + s,
                outline="#88ddff",
                width=3,
                tags="effect"
            )


        if frame < 150:

            root.after(35, animate)

        else:

            clear_effects()
            animation_running = False


    animate()


# ============================================================
# RECEIVE ARDUINO COMMAND
# ============================================================

def handle_command(command):

    global animation_running

    command = command.strip().upper()

    print("WAND:", command)

    # Ignore anything we don't recognize.
    if command not in [
        "LEFT",
        "RIGHT",
        "UP",
        "DOWN",
        "FORWARD",
        "BACKWARD"
    ]:
        return


    # VERY IMPORTANT:
    #
    # If an animation is already running, ignore another
    # command. This keeps the screen calm.
    #
    if animation_running:
        return


    # Tkinter must update the screen from its own thread.
    # root.after() safely schedules the animation.
    if command == "LEFT":

        root.after(0, butterfly_effect)

    elif command == "RIGHT":

        root.after(0, fish_effect)

    elif command == "UP":

        root.after(0, rainbow_effect)

    elif command == "DOWN":

        root.after(0, flower_effect)

    elif command == "FORWARD":

        root.after(0, star_effect)

    elif command == "BACKWARD":

        root.after(0, bubble_effect)


# ============================================================
# LISTEN TO ARDUINO
# ============================================================

def listen_to_arduino():

    print("Connecting to Arduino on", SERIAL_PORT)

    try:

        arduino = serial.Serial(
            SERIAL_PORT,
            BAUD_RATE,
            timeout=1
        )

        print("Connected!")
        print("Wave the magic wand!")


        while True:

            line = arduino.readline().decode(
                "utf-8",
                errors="ignore"
            ).strip()

            if line:

                handle_command(line)


    except Exception as e:

        print()
        print("Could not connect to Arduino.")
        print("Make sure:")
        print("  1. Arduino is plugged in")
        print("  2. Serial Monitor is CLOSED")
        print("  3. COM10 is correct")
        print()
        print("Error:", e)


# ============================================================
# START ARDUINO LISTENER
# ============================================================

thread = threading.Thread(
    target=listen_to_arduino,
    daemon=True
)

thread.start()


# ============================================================
# ESC = EXIT
# ============================================================

root.bind(
    "<Escape>",
    lambda event: root.destroy()
)


# ============================================================
# START WINDOWS PROGRAM
# ============================================================

root.mainloop()