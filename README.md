# TinyML Environmental Anomaly Detection on ESP32

Unsupervised, on-device anomaly detection for indoor environmental conditions.
A small autoencoder (101 parameters), quantized to INT8, is designed to run on an
ESP32 microcontroller with no cloud connection and no labeled anomaly data in
training.

## Motivation

Rule-based thresholds on single sensors (for example "alert if temperature > 30 °C")
miss anomalies that only show up in the joint behavior of several signals, such as
humidity rising without the expected temperature change, or a heat source appearing
in the room. This project learns what "normal" looks like across all sensors at once
and flags deviations, within the memory and compute budget of a microcontroller.

## System Overview

```
 DHT11 ─┐
        ├─ 5 s window ─▶ normalize (train mean/std) ─▶ autoencoder 3→8→2→8→3
 PIR  ──┘                                              (INT8, TFLite Micro)
                                                              │
                          OLED + red LED  ◀── MSE > threshold ◀┘
```

## Hardware

| Component | Role | Interface |
|---|---|---|
| ESP32 DevKit (30-pin) | MCU | n/a |
| DHT11 module | Temperature, relative humidity | 1-wire (GPIO4) |
| PIR HC-SR501 | Motion (latched per window) | Digital (GPIO27) |
| SSD1306 0.96" OLED | Status display | I2C (GPIO21/22) |
| Red LED + 220 Ω | Anomaly indicator / heartbeat | GPIO26 |

Pin mapping and design rationale: [`docs/wiring.md`](docs/wiring.md).
The design originally included an LDR light sensor; no usable module was available,
so the project runs with three features (see Known Limitations).

## Method

- **Features (3):** temperature (°C), humidity (%RH), motion (0/1, any motion within
  the 5 s window).
- **Model:** dense autoencoder 3→8→2→8→3 (101 trainable parameters). The 2-unit
  bottleneck forces a compressed joint representation of "normal".
- **Anomaly score:** per-sample reconstruction error (MSE).
- **Threshold τ:** 95th percentile of the error on held-out normal validation data.
- **Denoising option:** `--noise` adds Gaussian noise to the inputs during training
  only, which prevents the network from learning an identity map.
- **Deployment:** post-training INT8 quantization, TensorFlow Lite Micro.

Details and caveats: [`docs/methodology.md`](docs/methodology.md).

## Repository Layout

```
firmware/data_logger/   ESP32 sketch: sensor CSV logger
ml/                     autoencoder training and threshold selection
tools/                  serial capture, synthetic data generator
data/raw/               raw sessions captured from the device
docs/                   wiring and methodology notes
```

## Reproduce

Tested with Python 3.12.10 and TensorFlow 2.21.0 (TensorFlow does not support
Python 3.14).

```
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

python tools/serial_logger.py --port COM4          # capture a session
python ml/train_autoencoder.py --train data/raw/<session>.csv --outdir models/real
```

## Status

- [x] Wiring and hardware bring-up
- [x] Data logger firmware (validated on hardware)
- [ ] Data collection (normal behavior, at least one full day/night cycle)
- [ ] Autoencoder training and threshold selection on real data
- [ ] Baseline comparison (PCA / Mahalanobis)
- [ ] INT8 TFLite export, threshold recomputed on the quantized model
- [ ] On-device inference (TFLite Micro) with OLED/LED alerting
- [ ] Evaluation on held-out labeled anomalies
- [ ] Ablation with a light sensor, if one becomes available

## Results

_TBD. Will contain measured numbers only (detection rate, false alarms per hour,
model size, arena usage, inference latency)._

## Known Limitations

