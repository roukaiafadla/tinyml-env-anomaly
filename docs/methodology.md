# Methodology

## Features
temp_c, hum_pct, motion (1 if any PIR trigger occurred within the 5 s window).
One sample per 5 s. Rows from the first 60 s after each reboot are dropped in
training (sensor settling and PIR warm-up).

## Normalization
Per-feature standardization, x' = (x - mu) / sigma, with mu and sigma computed
on the training split only and exported for the firmware (scaler.json).

## Model
Dense autoencoder 3 -> 8 -> 2 -> 8 -> 3 (ReLU hidden layers, linear bottleneck and
output), 101 trainable parameters, MSE loss. Optional denoising training: Gaussian
noise on the input during training only, clean target.

## Anomaly score and threshold
Score: e(x) = (1/3) * sum_i (x'_i - xhat_i)^2.
Threshold: tau = empirical 95th percentile of e on held-out normal validation data,
so P(e > tau | normal) = 0.05 if samples are exchangeable. A percentile is used
instead of mu + k*sigma because e is a sum of squares (skewed, heavy-tailed).
Training-set errors are not used: the model fits them, so they are biased low.

## Data split
Contiguous 15-minute blocks assigned to train/validation/test (70/15/15) so that
every time of day appears in each set. A plain chronological split is preferred
when several days are available.

## Known caveats
- Autocorrelation: consecutive samples are strongly correlated and the error varies
  with time of day, so the 5% false-alarm guarantee holds per independent regime,
  not per sample. Calibrate on several days, report uncertainty (block bootstrap),
  report false alarms per hour at several percentiles, and evaluate at event level.
  A k-consecutive debounce rule removes isolated false positives but not sustained
  excursions.
- Identity mapping: a network with enough capacity reconstructs everything,
  including anomalies. The bottleneck size, training length and input noise must be
  chosen on validation data, never on the test anomalies.
- Quantization: INT8 rounding adds a noise floor to the reconstruction error. The
  threshold must be recomputed on the quantized model and must sit well above that
  floor.