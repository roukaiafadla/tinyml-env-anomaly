# Wiring Guide

Target board: ESP32 DevKit (30-pin, "ESP32 Dev Module" in Arduino IDE).

## Pin Mapping

| Component | Component pin | ESP32 pin | Notes |
|---|---|---|---|
| DHT11 module (3-pin) | `-` | GND | Pin order with pins up: `-`, power, `S` |
| DHT11 module | middle | 3V3 | Pull-up is on the module |
| DHT11 module | `S` | GPIO4 (D4) | |
| PIR (HC-SR501) | VCC | VIN (5 V) | Needs 5 V to operate |
| PIR (HC-SR501) | OUT | GPIO27 (D27) | OUT is 3.3 V logic, safe for the ESP32 |
| PIR (HC-SR501) | GND | GND | |
| OLED SSD1306 | GND | GND | Silkscreen order: GND VCC SCL SDA |
| OLED SSD1306 | VCC | 3V3 | |
| OLED SSD1306 | SCL | GPIO22 (D22) | I2C address 0x3C |
| OLED SSD1306 | SDA | GPIO21 (D21) | |
| Red LED | Anode (long leg) via 220 ohm resistor | GPIO26 (D26) | |
| Red LED | Cathode (short leg) | GND | |

## Not used: light sensor

The project was designed with a fourth feature (ambient light via an LDR module on
ADC1, GPIO34). No LDR module was available: the module in the kit turned out to be
an IR obstacle-avoidance sensor (digital output only), which cannot provide an
analog light level. The firmware and training code therefore use three features.
Adding light later only requires wiring an LDR module's analog output to GPIO34,
extending the sketch, and passing `--features` to the training script.

## Power

- 3V3 rail: DHT11, OLED
- 5 V (VIN): PIR only
- All grounds common.

## Design Decisions

**PIR powered from 5 V, read at 3.3 V.** The HC-SR501 regulator needs more than 3.3 V,
but its output pin is driven at 3.3 V, so no level shifting is required.

**Strapping and flash pins avoided.** GPIO 0, 2, 5, 12, 15 influence boot mode and
GPIO 6-11 are wired to the internal flash. None are used here.

## PIR Configuration (HC-SR501)

- Time-delay pot: minimum, so the output pulse is short and the 5 s sampling
  window keeps temporal resolution.
- Trigger jumper: **H** (repeatable trigger).
- About 30 s warm-up after power-up; the firmware waits for this before logging.

## Bring-up Checklist (completed)

1. Power from USB with no sensors connected and confirm the board boots.
2. Connect the OLED and confirm it initializes (no `# OLED_INIT_FAIL` line).
3. Connect the DHT11 and confirm there are no `# DHT_READ_FAIL` lines.
4. Wave a hand in front of the PIR and confirm `motion=1` appears.
5. Confirm the LED blinks once per logged row.