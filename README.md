# TinyML Environmental Anomaly Detection on ESP32

Unsupervised, fully on-device anomaly detection for indoor environmental
conditions. A 118-parameter autoencoder, quantized to INT8, runs on an ESP32
microcontroller with no cloud, no network, and no labeled anomaly data required
for training.

## Motivation

Rule-based thresholds on single sensors (e.g. "alert if temp > 30 °C") miss
anomalies that are only visible in the *joint* behavior of several signals, such as
light changing without the expected temperature response, or motion at
atypical conditions. This project learns what "normal" looks like across all
sensors at once and flags deviations, within the memory and compute budget of a
microcontroller.

## System Overview

```
 DHT11 ─┐
 LDR  ──┤  5 s window   ┌────────────┐   ┌───────────────┐   ┌──────────────┐
 PIR  ──┼──────────────▶│ Normalize  │──▶│ Autoencoder   │──▶│ MSE vs. τ    │──▶ OLED + LED
        │  (4 features) │ (train μ,σ)│   │ 4→8→2→8→4     │   │ anomaly flag │
        │               └────────────┘   │ INT8 TFLite   │   └──────────────┘
        │                                └───────────────┘
        └────────────── all inference on ESP32 (TFLite Micro) ──────────────
```

## Hardware

| Component | Role | Interface |
|---|---|---|
| ESP32 NodeMCU | MCU | n/a |
| DHT11 | Temperature, relative humidity | 1-wire (GPIO4) |
| LDR module | Ambient light (raw 12-bit ADC) | ADC1 (GPIO34) |
| PIR sensor | Motion (latched per window) | Digital (GPIO27) |
| SSD1306 0.96" OLED | Status display | I2C (GPIO21/22) |
| Red LED | Anomaly indicator | GPIO26 |

Full pin mapping and design rationale: [`docs/wiring.md`](docs/wiring.md)

## Method

- **Features (4):** temperature (°C), humidity (%RH), light (raw ADC),
  motion (0/1, any motion within the 5 s window).
- **Model:** dense autoencoder 4→8→2→8→4 (118 trainable parameters). The
  2-unit bottleneck forces a compressed joint representation of "normal".
- **Anomaly score:** per-sample reconstruction error (MSE).
- **Threshold τ:** 95th percentile of reconstruction error on normal data.
- **Deployment:** post-training INT8 quantization, TensorFlow Lite Micro.

## Repository Layout

```
firmware/data_logger/   ESP32 sketch: 4-sensor CSV logger
tools/                  Host-side utilities (serial capture, data generators)
data/raw/               Raw sessions captured from the device
docs/                   Wiring and design notes
```

## Status

- [ ] Data logger firmware
- [ ] Data collection (normal behavior, ≥ 1 full day/night cycle)
- [ ] Autoencoder training + threshold selection
- [ ] INT8 TFLite export
- [ ] On-device inference (TFLite Micro) + OLED/LED alerting
- [ ] Evaluation on held-out labeled anomalies

## Results

_TBD. Will be filled with measured numbers only (detection rate, false-positive
rate, model size, arena usage, inference latency)._

## Known Limitations

- DHT11 accuracy is ±2 °C / ±5 %RH with integer resolution (quantized signal).
- Light is a raw ADC value, not calibrated lux.
- Motion is binary per window; no activity-level information.
- Model is trained on one environment; deployment elsewhere requires retraining.