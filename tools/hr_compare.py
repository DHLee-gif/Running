"""
센서 심박 vs 워치 심박 시점별 비교 + IMU 걸음 리듬 확인

hr_trials.csv에 적은 워치 값(15·30·45·60초)과,
같은 시점 직전 --win초 동안의 센서 심박(박동 간격 중앙값)을 비교한다.
IMU |a|에서 걸음 리듬(spm)도 계산해서, 센서 심박이 걸음 리듬에 끌려갔는지(리듬 착각) 표시한다.

사용법:
    python tools/hr_compare.py
    python tools/hr_compare.py --trials data/hr_trials.csv --win 10
결과:
    data/hr_compare.csv  (시점별 표)
    data/hr_compare.png  (조건별 오차 + 센서 vs 워치)
"""
import argparse
import os

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

parser = argparse.ArgumentParser()
parser.add_argument("--trials", default="data/hr_trials.csv")
parser.add_argument("--win", type=float, default=10, help="각 시점 직전 몇 초로 센서 심박을 계산할지")
parser.add_argument("--skip", type=float, default=3, help="앞에서 버릴 시간 (초)")
parser.add_argument("--lock", type=float, default=5, help="센서 심박이 걸음 리듬과 이 bpm 이내면 리듬 착각 의심")
args = parser.parse_args()

POINTS = [15, 30, 45, 60]
data_dir = os.path.dirname(args.trials) or "."


def moving_average(x, n):
    return np.convolve(x, np.ones(n) / n, mode="same")


def find_beats(t, x, height, min_interval=0.33):
    beats, last_t = [], -1e9
    for i in range(1, len(x) - 1):
        if not (x[i] > x[i - 1] and x[i] >= x[i + 1]) or x[i] < height:
            continue
        if t[i] - last_t < min_interval:
            if beats and x[i] > x[beats[-1]]:
                beats[-1] = i
                last_t = t[i]
            continue
        beats.append(i)
        last_t = t[i]
    return np.array(beats, dtype=int)


def ppg_beat_times(t, ir, fs):
    """ppg_hr.py와 같은 방법: 1초 평균 빼기 → 뒤집기 → 0.1초 다듬기 → 봉우리."""
    pulse = -(ir - moving_average(ir, int(fs)))
    pulse = moving_average(pulse, max(1, int(fs * 0.1)))
    edge = int(fs)
    keep = np.zeros(len(t), bool)
    keep[edge:-edge] = True
    # 손가락이 안 닿은 구간(ir < 5만)이 있으면, 마지막으로 떨어진 시점 + 1.5초부터 사용
    start = args.skip
    off = np.where((ir < 50000) & (t < 15))[0]
    if len(off):
        start = max(start, t[off[-1]] + 1.5)
    keep &= t >= start    
    tk, pk = t[keep], pulse[keep]
    beats = find_beats(tk, pk, 0.5 * np.std(pk))
    return tk[beats]


def imu_cadence(t, df, fs):
    """|a|의 주파수 분석: 0.8~3.0Hz(48~180spm)에서 가장 강한 리듬 = 걸음 리듬."""
    m = t >= args.skip
    mag = np.sqrt(df["ax"] ** 2 + df["ay"] ** 2 + df["az"] ** 2).to_numpy()[m]
    mag = mag - mag.mean()
    if np.std(mag) < 0.02:                     # 거의 안 움직임 (서 있기)
        return np.nan
    spec = np.abs(np.fft.rfft(mag * np.hanning(len(mag))))
    freq = np.fft.rfftfreq(len(mag), 1 / fs)
    band = (freq >= 0.8) & (freq <= 3.0)
    return freq[band][np.argmax(spec[band])] * 60


trials = pd.read_csv(args.trials, skipinitialspace=True, encoding="utf-8-sig")
rows = []
for _, tr in trials.iterrows():
    path = os.path.join(data_dir, str(tr["file"]).strip())
    df = pd.read_csv(path)
    t = ((df["t_ms"] - df["t_ms"].iloc[0]) / 1000.0).to_numpy()
    fs = 1000.0 / df["t_ms"].diff().mean()
    bt = ppg_beat_times(t, df["ir"].to_numpy(float), fs)
    cad = imu_cadence(t, df, fs)

    for T in POINTS:
        watch = tr.get(f"w{T}")
        in_win = bt[(bt > T - args.win) & (bt <= T)]
        sensor = 60 / np.median(np.diff(in_win)) if len(in_win) >= 3 else np.nan
        # 리듬 착각: 센서는 걸음 리듬에 붙어 있는데, 워치(진짜 심박)는 걸음 리듬과 다를 때
        lock = (not np.isnan(cad)) and (not np.isnan(sensor)) and pd.notna(watch) \
            and abs(sensor - cad) <= args.lock and abs(watch - cad) > args.lock
        rows.append({"file": tr["file"], "arm": tr["arm"], "spm": tr["spm"],
                     "imu_spm": round(cad, 1) if not np.isnan(cad) else np.nan,
                     "t": T, "watch": watch, "sensor": round(sensor, 1),
                     "err": round(sensor - watch, 1) if pd.notna(watch) else np.nan,
                     "lock": "의심" if lock else ""})

res = pd.DataFrame(rows)
out_csv = os.path.join(data_dir, "hr_compare.csv")
res.to_csv(out_csv, index=False, encoding="utf-8-sig")

# ===== 출력 =====
pd.set_option("display.width", 120)
print(res.to_string(index=False))

summary = res.groupby("file", sort=False).agg(
    arm=("arm", "first"), spm=("spm", "first"), imu_spm=("imu_spm", "first"),
    mae=("err", lambda e: e.abs().mean()), bias=("err", "mean"),
    lock=("lock", lambda s: (s == "의심").sum()))
print("\n===== 조건별 요약 (mae: 평균 절대 오차, bias: +면 센서가 높음) =====")
print(summary.round(1).to_string())

# ===== 그래프 =====
fig, axes = plt.subplots(1, 2, figsize=(13, 5))
color = {"stand": "gray", "A": "tab:blue", "B": "tab:red"}

ax = axes[0]
ax.bar(range(len(summary)), summary["mae"], color=[color.get(a, "k") for a in summary["arm"]])
ax.set_xticks(range(len(summary)))
ax.set_xticklabels([f.replace("hr_", "").replace(".csv", "") for f in summary.index])
ax.set_ylabel("mean |sensor - watch| (bpm)")
ax.set_title("Error by condition (gray=stand, blue=A fixed, red=B swing)")
for i, v in enumerate(summary["mae"]):
    ax.text(i, v + 0.2, f"{v:.1f}", ha="center")

ax = axes[1]
for arm, g in res.groupby("arm"):
    ax.scatter(g["watch"], g["sensor"], color=color.get(arm, "k"), label=arm, s=40)
lo = np.nanmin(res[["watch", "sensor"]].to_numpy()) - 5
hi = np.nanmax(res[["watch", "sensor"]].to_numpy()) + 5
ax.plot([lo, hi], [lo, hi], "k--", linewidth=0.8, label="same")
ax.set_xlabel("watch (bpm)")
ax.set_ylabel("sensor (bpm)")
ax.set_title("Sensor vs watch (each point = one time point)")
ax.legend()
for a in axes:
    a.grid(alpha=0.3)

plt.tight_layout()
out_png = os.path.join(data_dir, "hr_compare.png")
plt.savefig(out_png, dpi=120)
print(f"\n표 저장: {out_csv}\n그래프 저장: {out_png}")
plt.show()