#include <Arduino_LSM9DS1.h>

// =========================================================
// 🪄 TODDLER MAGIC WAND — CALM MOTION DETECTOR (v2)
//
// This is your original working sketch, extended with more
// gestures. The CORE is untouched on purpose:
//   1. Waits for a strong movement.
//   2. Determines the direction.
//   3. Sends ONE message.
//   4. Waits for the wand to become still.
//   5. Then becomes ready for the next wave.
//
// NEW gestures are added as extra checks stacked on top of
// that same core, so nothing about what already worked has
// changed:
//   - Diagonals (UP_LEFT, UP_RIGHT, DOWN_LEFT, DOWN_RIGHT):
//     an extra check before the original LEFT/RIGHT/UP/DOWN
//     logic, only used when X and Y are BOTH clearly moving.
//   - TAP: a single very sharp spike (checked with a higher
//     threshold than a normal wave, decided the same instant
//     a normal direction would be).
//   - BALL: two TAPs close together in time.
//   - SHAKE: several waves in a row, close together in time.
//   - SPIN / CIRCLE / SQUARE: these come from a SEPARATE,
//     independent check on the gyroscope (rotation sensor),
//     since spinning the wand shows up there, not in the
//     accelerometer jerk the rest of this sketch watches.
//     It only pays attention while the direction-detector
//     above is idle, so the two don't confuse each other.
// =========================================================


// ---------------------------------------------------------
// SETTINGS — the two you already tuned are unchanged.
// ---------------------------------------------------------

// How strong the movement needs to be.
//
// If the wand triggers too easily:
//     increase this to 1.0 or 1.2
//
// If it is too difficult to trigger:
//     decrease this to 0.6 or 0.7
//
const float MOTION_THRESHOLD = 1.0;


// How little movement counts as "still".
//
// The wand has to settle down below this level before
// another movement can be detected.
//
const float STILL_THRESHOLD = 0.25;


// --- new settings for the extra gestures ------------------

// A TAP has to be noticeably sharper than a normal wave.
// If TAP is too easy to trigger by accident, raise this.
// If TAP never triggers, lower it (but keep it above
// MOTION_THRESHOLD or every wave will look like a tap).
const float TAP_SPIKE_THRESHOLD = 2.2;

// Two TAPs this close together (in milliseconds) count as
// one BALL instead.
const unsigned long DOUBLE_TAP_MS = 550;

// How close in time (ms) a group of waves needs to be to
// count as a SHAKE, and how many waves are needed.
const unsigned long SHAKE_WINDOW_MS = 700;
const int SHAKE_MIN_TRIGGERS = 4;

// For a diagonal, X and Y both need to be clearly moving,
// and roughly similar in size. 0.6 means the smaller of the
// two must be at least 60% of the bigger one.
const float DIAGONAL_RATIO = 0.6;

// --- rotation settings (SPIN / CIRCLE / SQUARE) -----------
// These use the gyroscope, not the accelerometer, so they
// have their own thresholds in degrees-per-second and total
// degrees turned.
const float ROT_START_DPS   = 80.0;   // rotation speed that begins a spin/circle
const float ROT_STILL_DPS   = 40.0;   // must drop below this to consider it over
const float ROT_TOTAL_DEG   = 220.0;  // total rotation needed to count at all
const unsigned long SPIN_FAST_MS = 400;  // faster than this whole turn = SPIN
const int SQUARE_MIN_JERKS = 3;          // corners feel like sudden jerks


// ---------------------------------------------------------
// STATE — direction detector (original)
// ---------------------------------------------------------

// The wand starts ready to detect a movement.
bool readyForMotion = true;

// Previous acceleration reading.
float previousX = 0;
float previousY = 0;
float previousZ = 0;

// --- new state: TAP / BALL / SHAKE ------------------------

unsigned long lastTapTime = 0;
bool waitingSecondTap = false;

unsigned long triggerHistory[6] = {0, 0, 0, 0, 0, 0};
int triggerHistoryPos = 0;

// --- new state: rotation detector (SPIN / CIRCLE / SQUARE) --

bool rotating = false;
unsigned long rotStartMs = 0;
float rotSumX = 0, rotSumY = 0, rotSumZ = 0;
float lastRotMag = 0;
int rotRisingDir = 0;
int rotJerkCount = 0;

unsigned long lastLoopMs = 0;


// ---------------------------------------------------------
// SETUP
// ---------------------------------------------------------

void setup() {

  // Start USB communication with Windows.
  Serial.begin(115200);


  // Start the motion sensor.
  if (!IMU.begin()) {

    Serial.println("IMU FAILED!");

    // Stop here if the sensor doesn't work.
    while (1);
  }


  Serial.println();
  Serial.println("==============================");
  Serial.println("     🪄 MAGIC WAND READY!");
  Serial.println("==============================");
  Serial.println();
  Serial.println("Wave the wand!");
  Serial.println();


  // Wait for the first sensor reading.
  while (!IMU.accelerationAvailable()) {
    delay(10);
  }


  // Save the initial reading.
  IMU.readAcceleration(
    previousX,
    previousY,
    previousZ
  );

  lastLoopMs = millis();
}


// ---------------------------------------------------------
// MAIN LOOP
// ---------------------------------------------------------

void loop() {

  unsigned long now = millis();
  float dt = (now - lastLoopMs) / 1000.0;
  if (dt <= 0 || dt > 0.3) dt = 0.05;   // guard against a stalled first sample
  lastLoopMs = now;


  // =========================================================
  // PART A — the original direction detector, extended.
  // =========================================================

  // Only work when a new sensor reading is available.
  if (IMU.accelerationAvailable()) {

    float x;
    float y;
    float z;


    // Read the sensor.
    IMU.readAcceleration(x, y, z);


    // -----------------------------------------------------
    // Calculate how much each axis changed.
    // -----------------------------------------------------

    float changeX = x - previousX;
    float changeY = y - previousY;
    float changeZ = z - previousZ;


    // Absolute values tell us movement strength.
    float absX = abs(changeX);
    float absY = abs(changeY);
    float absZ = abs(changeZ);


    // Find the strongest movement.
    float strongestMovement = max(
      absX,
      max(absY, absZ)
    );


    // =====================================================
    // WAND IS READY
    // =====================================================

    if (readyForMotion) {

      // Is there a strong enough movement?
      if (strongestMovement > MOTION_THRESHOLD) {

        // A new impulse just started. Remember when, for
        // the SHAKE check below.
        triggerHistoryPos = (triggerHistoryPos + 1) % 6;
        triggerHistory[triggerHistoryPos] = now;

        int recentCount = 0;
        for (int i = 0; i < 6; i++) {
          if (triggerHistory[i] != 0 && (now - triggerHistory[i]) <= SHAKE_WINDOW_MS) {
            recentCount++;
          }
        }


        // -------------------------------------------------
        // SHAKE — several waves in a row, close together.
        // -------------------------------------------------

        if (recentCount >= SHAKE_MIN_TRIGGERS) {

          Serial.println("SHAKE");
          waitingSecondTap = false;
        }


        // -------------------------------------------------
        // TAP / BALL — one very sharp spike (two close
        // together in time count as BALL instead).
        // -------------------------------------------------

        else if (strongestMovement > TAP_SPIKE_THRESHOLD) {

          if (waitingSecondTap && (now - lastTapTime) <= DOUBLE_TAP_MS) {

            Serial.println("BALL");
            waitingSecondTap = false;

          } else {

            Serial.println("TAP");
            waitingSecondTap = true;
            lastTapTime = now;
          }
        }


        // -------------------------------------------------
        // DIAGONAL — X and Y are both clearly moving and
        // roughly equally strong, and Z isn't the bigger one.
        // -------------------------------------------------

        else if (
          absX > MOTION_THRESHOLD &&
          absY > MOTION_THRESHOLD &&
          min(absX, absY) >= max(absX, absY) * DIAGONAL_RATIO &&
          absZ < max(absX, absY)
        ) {

          // Same LEFT/RIGHT swap as the original code below.
          String horiz = (changeX > 0) ? "LEFT" : "RIGHT";
          String vert  = (changeY > 0) ? "UP" : "DOWN";

          Serial.println(vert + "_" + horiz);
          waitingSecondTap = false;
        }


        // -------------------------------------------------
        // X AXIS
        //
        // We already discovered that YOUR wand has
        // LEFT and RIGHT reversed.
        //
        // So we intentionally swap them here.
        // -------------------------------------------------

        else if (
          absX >= absY &&
          absX >= absZ
        ) {

          if (changeX > 0) {

            Serial.println("LEFT");

          } else {

            Serial.println("RIGHT");
          }

          waitingSecondTap = false;
        }


        // -------------------------------------------------
        // Y AXIS
        // -------------------------------------------------

        else if (
          absY >= absX &&
          absY >= absZ
        ) {

          if (changeY > 0) {

            Serial.println("UP");

          } else {

            Serial.println("DOWN");
          }

          waitingSecondTap = false;
        }


        // -------------------------------------------------
        // Z AXIS
        // -------------------------------------------------

        else {

          if (changeZ > 0) {

            Serial.println("FORWARD");

          } else {

            Serial.println("BACKWARD");
          }

          waitingSecondTap = false;
        }


        // -------------------------------------------------
        // IMPORTANT:
        //
        // We just detected ONE movement.
        //
        // Do NOT detect another movement until the wand
        // settles down.
        // -------------------------------------------------

        readyForMotion = false;
      }
    }


    // =====================================================
    // WAIT FOR THE WAND TO BECOME STILL
    // =====================================================

    else {

      // If movement is now very small, the wand has
      // probably finished its wave.

      if (strongestMovement < STILL_THRESHOLD) {

        readyForMotion = true;

      }
    }


    // Save the current reading.
    previousX = x;
    previousY = y;
    previousZ = z;
  }


  // =========================================================
  // PART B — rotation detector: SPIN / CIRCLE / SQUARE.
  //
  // Independent from Part A above. Only pays attention while
  // the direction detector is idle (readyForMotion == true),
  // so a translational wave and a rotation don't get mixed up.
  // =========================================================

  if (IMU.gyroscopeAvailable() && readyForMotion) {

    float gx, gy, gz;
    IMU.readGyroscope(gx, gy, gz);   // degrees per second

    float rotMag = sqrt(gx * gx + gy * gy + gz * gz);

    if (!rotating) {

      if (rotMag > ROT_START_DPS) {

        rotating = true;
        rotStartMs = now;
        rotSumX = rotSumY = rotSumZ = 0;
        lastRotMag = rotMag;
        rotRisingDir = 0;
        rotJerkCount = 0;
      }

    } else {

      rotSumX += abs(gx) * dt;
      rotSumY += abs(gy) * dt;
      rotSumZ += abs(gz) * dt;

      int dir = (rotMag > lastRotMag) ? 1 : (rotMag < lastRotMag ? -1 : rotRisingDir);
      if (rotRisingDir == 1 && dir == -1) rotJerkCount++;   // a local peak = one jerk
      rotRisingDir = dir;
      lastRotMag = rotMag;

      if (rotMag < ROT_STILL_DPS) {

        // The rotation just ended. Decide what it was.
        float maxRot = max(rotSumX, max(rotSumY, rotSumZ));
        unsigned long rotDuration = now - rotStartMs;

        if (maxRot >= ROT_TOTAL_DEG) {

          if (rotJerkCount >= SQUARE_MIN_JERKS) {

            Serial.println("SQUARE");     // corners jerk mid-turn

          } else if (rotDuration < SPIN_FAST_MS) {

            Serial.println("SPIN");       // fast full turn

          } else {

            Serial.println("CIRCLE");     // smooth, slower loop
          }
        }
        // if it didn't add up to a full rotation, it was just
        // noise from a normal wave — say nothing.

        rotating = false;
      }
    }
  }


  // Sensor update rate.
  delay(50);
}
