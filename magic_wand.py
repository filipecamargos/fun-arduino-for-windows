import serial
import tkinter as tk
import random
import math

# ---------------------------------------------------------
# MAGIC WAND WINDOWS PROGRAM
#
# Arduino sends:
#
#     MAGIC
#
# This program listens for that message and creates
# colorful magic on the screen.
# ---------------------------------------------------------

# Your Arduino is currently on COM10.
ARDUINO_PORT = "COM10"

# Arduino is using 115200 baud.
BAUD_RATE = 115200


# ---------------------------------------------------------
# Connect to Arduino
# ---------------------------------------------------------

try:
    arduino = serial.Serial(
        ARDUINO_PORT,
        BAUD_RATE,
        timeout=0.05
    )

    print("Connected to Arduino on", ARDUINO_PORT)

except Exception as error:
    print("Could not connect to Arduino.")
    print(error)
    print()
    print("Make sure:")
    print("1. Arduino is plugged in.")
    print("2. COM10 is correct.")
    print("3. Serial Monitor is CLOSED.")


# ---------------------------------------------------------
# Create the window
# ---------------------------------------------------------

window = tk.Tk()

window.title("Magic Wand")

# Start with a large window.
window.geometry("1000x700")

# Dark background.
window.configure(bg="#10152f")


# Canvas is where our magic will appear.
canvas = tk.Canvas(
    window,
    bg="#10152f",
    highlightthickness=0
)

canvas.pack(
    fill="both",
    expand=True
)


# ---------------------------------------------------------
# Magic particles
# ---------------------------------------------------------

particles = []


def create_magic():
    """
    Create a big colorful explosion of magic.
    """

    width = canvas.winfo_width()
    height = canvas.winfo_height()

    center_x = width / 2
    center_y = height / 2

    colors = [
        "#ff4fa3",
        "#55c7ff",
        "#ffe066",
        "#8cff98",
        "#b58cff",
        "#ff914d"
    ]

    # Create lots of particles.
    for i in range(100):

        angle = random.uniform(0, math.pi * 2)

        speed = random.uniform(3, 10)

        particle = {
            "x": center_x,
            "y": center_y,

            "dx": math.cos(angle) * speed,
            "dy": math.sin(angle) * speed,

            "size": random.randint(4, 10),

            "life": 40,

            "color": random.choice(colors)
        }

        particles.append(particle)

    # Put a big message on screen.
    canvas.create_text(
        center_x,
        center_y,
        text="✨ MAGIC! ✨",
        fill="white",
        font=("Arial", 48, "bold"),
        tags="magic_text"
    )

    # Remove the message after a short time.
    window.after(
        600,
        lambda: canvas.delete("magic_text")
    )


# ---------------------------------------------------------
# Animate particles
# ---------------------------------------------------------

def animate():

    # Update every particle.
    for particle in particles:

        particle["x"] += particle["dx"]
        particle["y"] += particle["dy"]

        # Slowly make particles fall.
        particle["dy"] += 0.15

        particle["life"] -= 1

    # Remove particles that are finished.
    particles[:] = [
        p for p in particles
        if p["life"] > 0
    ]

    # Clear the canvas.
    canvas.delete("particle")

    # Draw every particle.
    for particle in particles:

        x = particle["x"]
        y = particle["y"]
        size = particle["size"]

        canvas.create_oval(
            x - size,
            y - size,
            x + size,
            y + size,
            fill=particle["color"],
            outline="",
            tags="particle"
        )

    # Run this function again.
    window.after(30, animate)


# ---------------------------------------------------------
# Listen for Arduino messages
# ---------------------------------------------------------

def check_arduino():

    try:

        # Check whether Arduino sent anything.
        if arduino.in_waiting:

            message = arduino.readline().decode(
                "utf-8",
                errors="ignore"
            ).strip()

            print("Arduino:", message)

            # Arduino told us MAGIC!
            if message == "MAGIC":

                create_magic()

    except Exception as error:

        print("Arduino communication error:")
        print(error)

    # Check again very soon.
    window.after(20, check_arduino)


# ---------------------------------------------------------
# Start everything
# ---------------------------------------------------------

animate()

check_arduino()

window.mainloop()