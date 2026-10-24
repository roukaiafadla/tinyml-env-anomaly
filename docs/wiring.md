# Wiring Guide

Target board: ESP32 NodeMCU (30/38-pin DevKit, "ESP32 Dev Module" in Arduino IDE).

## Pin Mapping

| Component | Component pin | ESP32 pin | Notes |
|---|---|---|---|
| DHT11 | VCC | 3V3 | |
| DHT11 | DATA | GPIO4 | Needs a pull-up to 3V3 (10 kΩ). Most 3-pin modules have one built in. |
| DHT11 | GND | GND | |
| LDR module | VCC | 3V3 | Powered at 3.3 V so AO can never exceed the ADC range |
| LDR module | AO | GPIO34 | ADC1_CH6, input-only |
| LDR module | GND | GND | |
| PIR (HC-SR501) | VCC | VIN (5 V) | The module needs 5 V to operate |
| PIR (HC-SR501) | OUT | GPIO27 | OUT is 3.3 V logic, safe for the ESP32 |
| PIR (HC-SR501) | GND | GND | |
| OLED SSD1306 | VCC | 3V3 | |
| OLED SSD1306 | SDA | GPIO21 | Default I2C SDA |
| OLED SSD1306 | SCL | GPIO22 | Default I2C SCL |
| OLED SSD1306 | GND | GND | I2C address 0x3C |
| Red LED | Anode (+) via resistor | GPIO26 | 220–330 Ω series resistor |
| Red LED | Cathode (-) | GND | |

## Breadboard Power Rails

- Rail A: 3V3 and GND from the ESP32 (DHT11, LDR, OLED, LED return)
- Rail B: VIN (5 V from USB) and GND (PIR only)
- All grounds must be common (tie GND of both rails to an ESP32 GND pin).

## Design Decisions

**LDR on ADC1, not ADC2.** ADC2 is shared with the Wi-Fi driver and returns errors
while the radio is active. Wi-Fi is not used in this project, but the pin choice
guarantees the firmware can never hit that conflict.

**LDR module powered from 3V3.** The ESP32 ADC saturates near 3.3 V and its inputs are
not 5 V tolerant. Powering the module at 3.3 V keeps AO inside the safe range.

**PIR powered from 5 V, read at 3.3 V.** The HC-SR501 regulator needs more than 3.3 V,
but its output pin is driven at 3.3 V, so no level shifting is required.

**Strapping and flash pins avoided.** GPIO 0, 2, 5, 12, 15 influence boot mode and
GPIO 6–11 are wired to the internal flash. None are used here.

**LDR polarity is module-dependent.** Some modules output a higher value in the dark,
others in the light. The autoencoder is indifferent to the sign, but the polarity must
stay fixed for the entire project (data collection and deployment).

## PIR Configuration (HC-SR501)

- Time-delay potentiometer: turn to minimum, so the output pulse is short and the
  5 s sampling window keeps temporal resolution.
- Trigger jumper: set to **H** (repeatable trigger).
- Allow about 30 s warm-up after power-up; the firmware waits for this before logging.

## Bring-up Checklist

1. Power the board from USB only, with no sensors connected, and confirm it boots.
2. Connect the OLED and confirm the I2C device is found at 0x3C.
3. Connect the DHT11 and confirm there are no `# DHT_READ_FAIL` lines in the serial output.
4. Cover and uncover the LDR, and confirm `light_raw` changes strongly.
5. Wave a hand in front of the PIR, and confirm `motion=1` appears.
6. Confirm the LED blinks once per logged row.