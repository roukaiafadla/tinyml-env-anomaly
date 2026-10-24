"""Train a dense autoencoder (default 3->8->2->8->3) and select the anomaly threshold.

Synthetic run (pipeline development only, never report these numbers):
    python ml/train_autoencoder.py --train data/synthetic/fake_normal.csv ^
        --eval data/synthetic/fake_anomaly.csv --outdir models/synthetic
Real run:
    python ml/train_autoencoder.py --train data/raw/session_X.csv ^
        --eval data/raw/anomaly_test_X.csv --outdir models/real
Options:
    --noise 0.15        denoising autoencoder (Gaussian noise on inputs, training only)
    --bottleneck 1      smaller latent code
    --features temp_c hum_pct light_raw motion     (needs a light sensor)
    --verbose           print every epoch
"""
import argparse
import json
import os

import keras
import numpy as np
import pandas as pd
from sklearn.metrics import precision_recall_fscore_support, roc_auc_score

DEFAULT_FEATURES = ["temp_c", "hum_pct", "motion"]
SKIP_AFTER_BOOT = 12   # drop ~60 s after each ESP32 reboot (sensors still settling)
BLOCK = 180            # 15 min of rows; unit of the block split below


def load(path, features):
    df = pd.read_csv(path, comment="#")
    cols = features + ["t_ms"]
    df[cols] = df[cols].apply(pd.to_numeric, errors="coerce")
    df = df.dropna(subset=cols).reset_index(drop=True)
    # t_ms resets to 0 on every reboot -> a decrease marks a new boot segment
    boot = (df["t_ms"].diff() < 0).cumsum()
    df = df[df.groupby(boot).cumcount() >= SKIP_AFTER_BOOT].reset_index(drop=True)
    return df


def block_split(n):
    """Contiguous 15-min blocks assigned 14:3:3 (70/15/15) in a repeating 5 h pattern.

    WHY not a plain chronological split: with only ~1 day of data, the last 15%
    would be one time of day that the model never trained on, and the diurnal
    cycle would be mistaken for anomalies. Blocks keep every time of day
    represented in train/val/test, and are long enough that neighbouring
    (autocorrelated) samples rarely straddle two sets. With several days of data,
    prefer a plain chronological split.
    """
    slot = (np.arange(n) // BLOCK) % 20
    return slot < 14, (slot >= 14) & (slot < 17), slot >= 17


def build_model(n_in, n_latent, noise=0.0):
    inp = keras.Input(shape=(n_in,))
    x = inp
    if noise > 0:
        # Denoising autoencoder: Gaussian noise on the input during training ONLY
        # (the layer is the identity at inference). The target stays the clean
        # input, so the network cannot simply copy its input and must learn the
        # structure of normal data. Prevents the identity-mapping failure.
        x = keras.layers.GaussianNoise(noise)(x)
    x = keras.layers.Dense(8, activation="relu")(x)
    z = keras.layers.Dense(n_latent, name="bottleneck")(x)   # linear latent code
    x = keras.layers.Dense(8, activation="relu")(z)
    out = keras.layers.Dense(n_in)(x)                        # linear: normalized values are signed
    m = keras.Model(inp, out)
    m.compile(optimizer=keras.optimizers.Adam(1e-3), loss="mse")
    return m


def recon_error(model, X):
    """Per-sample MSE over the features: e(x) = mean_i (x_i - xhat_i)^2."""
    Xh = model.predict(X, verbose=0, batch_size=1024)
    return np.mean((X - Xh) ** 2, axis=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", required=True, help="CSV of NORMAL behaviour")
    ap.add_argument("--eval", default=None, help="CSV with a 0/1 'label' column")
    ap.add_argument("--outdir", default="models/real")
    ap.add_argument("--features", nargs="+", default=DEFAULT_FEATURES)
    ap.add_argument("--bottleneck", type=int, default=2)
    ap.add_argument("--noise", type=float, default=0.15,
                    help="input noise std (normalized units) for a denoising AE")
    ap.add_argument("--epochs", type=int, default=200)
    ap.add_argument("--percentile", type=float, default=95.0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--verbose", action="store_true", help="print every epoch")
    args = ap.parse_args()
    features = args.features
    keras.utils.set_random_seed(args.seed)
    os.makedirs(args.outdir, exist_ok=True)

    df = load(args.train, features)
    X = df[features].to_numpy("float32")
    tr, va, te = block_split(len(X))

    # Scaler is fitted on TRAIN ONLY, then reused on val/test/eval and on the ESP32.
    mu, sd = X[tr].mean(0), X[tr].std(0)
    sd = np.where(sd < 1e-6, 1.0, sd)
    norm = lambda a: ((a - mu) / sd).astype("float32")
    Xtr, Xva, Xte = norm(X[tr]), norm(X[va]), norm(X[te])
    print(f"features: {features}")
    print(f"rows: train={len(Xtr)} val={len(Xva)} test={len(Xte)}")

    n_in = len(features)
    model = build_model(n_in, args.bottleneck, args.noise)
    # n -> 8 -> b -> 8 -> n  has  17*(n+b) + 16  parameters (noise layer has none)
    assert model.count_params() == 17 * (n_in + args.bottleneck) + 16, model.count_params()
    print(f"parameters: {model.count_params()}  noise: {args.noise}")
    es = keras.callbacks.EarlyStopping(monitor="val_loss", patience=10,
                                       restore_best_weights=True)
    hist = model.fit(Xtr, Xtr, validation_data=(Xva, Xva), epochs=args.epochs,
                     batch_size=64, callbacks=[es], verbose=2 if args.verbose else 0)
    n_ep = len(hist.history["loss"])
    print(f"epochs run: {n_ep}, best val_loss: {min(hist.history['val_loss']):.2e}")
    if n_ep == args.epochs:
        print("WARNING: epoch cap reached without early stopping; model may be under-trained")

    # Threshold: empirical percentile of the error on HELD-OUT normal data (val).
    e_tr, e_va, e_te = (recon_error(model, a) for a in (Xtr, Xva, Xte))
    tau = float(np.percentile(e_va, args.percentile))
    print(f"\ntau (p{args.percentile:g} of val error) = {tau:.2e}")
    print(f"train-set p{args.percentile:g} = {np.percentile(e_tr, args.percentile):.2e} (optimistic)")
    print(f"normal test FPR = {(e_te > tau).mean():.3f} "
          f"(expected ~{1 - args.percentile / 100:.3f})")

    # Diagnostic: is the exceedance rate uniform, or clustered in a few time blocks?
    blk = (np.arange(len(X)) // BLOCK)[te]
    for b in np.unique(blk):
        print(f"  test block {b:3d}: exceed rate = {(e_te[blk == b] > tau).mean():.2f}")

    if args.eval:
        de = load(args.eval, features)
        Xe = norm(de[features].to_numpy("float32"))
        y = de["label"].to_numpy().astype(int)
        e = recon_error(model, Xe)
        pred = (e > tau).astype(int)
        p, r, f1, _ = precision_recall_fscore_support(y, pred, average="binary",
                                                      zero_division=0)
        print(f"\nlabeled eval ({len(y)} rows, {y.sum()} anomalous)")
        print(f"AUC={roc_auc_score(y, e):.3f}  precision={p:.3f}  recall={r:.3f}  "
              f"F1={f1:.3f}  FPR={pred[y == 0].mean():.3f}")

    # Save a noise-free copy (same weights) so conversion/deployment never sees
    # the training-only noise layer.
    infer = build_model(n_in, args.bottleneck, noise=0.0)
    infer.set_weights(model.get_weights())
    infer.save(os.path.join(args.outdir, "ae_float.keras"))
    with open(os.path.join(args.outdir, "scaler.json"), "w") as f:
        json.dump({"features": features, "mean": mu.tolist(), "std": sd.tolist()}, f, indent=2)
    with open(os.path.join(args.outdir, "threshold_float.json"), "w") as f:
        json.dump({"percentile": args.percentile, "tau": tau, "noise": args.noise,
                   "bottleneck": args.bottleneck, "epochs_run": n_ep,
                   "fit_on": "validation (held-out normal)", "n_val": int(len(Xva))}, f, indent=2)


if __name__ == "__main__":
    main()