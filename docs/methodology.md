# Methodology

## Features
temp_c, hum_pct, motion (1 if any PIR trigger occurred within the 5 s window). One sample every 5 s.

## Data preparation
- Each CSV is cleaned separately: rows with missing or non-numeric fields are dropped.
- A reboot is a drop in t_ms together with a time gap of more than 20 s (the firmware waits about 30 s after boot). The first 12 samples (about 60 s) after every reboot, including the start of a session, are discarded while the sensors settle. A drop in t_ms without a time gap is a damaged value, not a reboot, and is ignored.
- Sessions are concatenated, then cut into contiguous blocks of 180 samples (15 minutes).

## Data split
Blocks are assigned to train / validation / test (70 / 15 / 15) in a repeating 20-block pattern, so every recording period contributes to every set. Neighbouring blocks are correlated, so this estimate is optimistic about new days; a whole-session hold-out is planned. With several days of data a chronological split is preferable.

## Normalization
Per-feature standardization x' = (x - mu) / sigma, with mu and sigma computed on the training blocks only. They are exported (scaler.json, model_params.h) and must be applied identically on the device.

## Model
Dense autoencoder 3 -> 8 -> 2 -> 8 -> 3 (ReLU hidden layers, linear bottleneck and output), 101 trainable parameters, MSE loss, Adam (learning rate 1e-3), early stopping on validation loss (patience 10, best weights restored). Optional denoising training adds Gaussian noise to the inputs during training only (--noise); the reported results use no noise.

## Anomaly score and threshold
Score: e(x) = (1/3) * sum_i (x'_i - xhat_i)^2.
Threshold: tau = empirical 95th percentile of e on held-out normal validation blocks, so P(e > tau | normal) = 0.05 if samples were exchangeable. A percentile is used instead of mu + k*sigma because e is a sum of squares (skewed, heavy-tailed). Training errors are not used, because the model fits them (biased low).

## INT8 quantization
Full-integer post-training quantization with the TensorFlow Lite converter, using 500 random normalized training samples as the representative dataset; input and output tensors are int8. The INT8 model is run sample by sample in Python exactly as the firmware will: quantize with the input scale and zero point, invoke, dequantize the output, and compute the MSE against the float normalized input. tau is recomputed as the 95th percentile of those errors. Exported to the model directory: model_int8.tflite, thresholds_int8.json, model_data.h (model bytes) and model_params.h (mean, std, scales, zero points, tau).

## Planned on-device pipeline
read sensors -> normalize -> quantize -> invoke -> dequantize -> MSE -> compare with tau (INT8) -> LED / OLED. The on-device scores will be checked against the Python INT8 scores on the same recorded rows.

## Known caveats
- Autocorrelation: consecutive samples are strongly correlated and the error varies with time of day, so the 5% false-alarm figure holds per independent regime, not per sample. Calibrate on several days, report uncertainty (block bootstrap), report false alarms per hour at several percentiles, and evaluate at event level. A k-consecutive debounce rule removes isolated false positives but not sustained excursions.
- Drift: slow changes such as a room drying out can move readings outside the training range and raise the false-alarm rate (seen in the last ~21 minutes of the reading-room recording).
- Identity mapping: a network with enough capacity reconstructs everything, including anomalies. Bottleneck size, training length and input noise must be chosen on validation data, never on test anomalies.
- Quantization: INT8 rounding adds a noise floor to the reconstruction error. The threshold must be recomputed on the quantized model and must sit well above that floor.