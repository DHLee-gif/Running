"""
한 시점의 PPG/IMU 주파수 성분을 그려서 IMU 거르기 과정을 눈으로 보여주는 스크립트
(hr_filter.py와 같은 규칙)

사용법:
    python tools/hr_spectrum.py data/hr_B120.csv --t 45 --watch 93
    python tools/hr_spectrum.py data/hr_B80.csv --t 30 --watch 90
결과:
    data/hr_B120_spec_t45.png
"""
import argparse

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

parser = argparse.ArgumentParser()
parser.add_argument("csv")
parser.add_argument("--t", type=float, required=True, help="볼 시점 (초). 이 시점 직전 --win초를 사용")
parser.add_argument("--win", type=float, default=10)
parser.add_argument("--watch", type=float, default=None, help="그 시점 워치 값 (그래프에 초록 점선)")
parser.add_argument("--band", type=float, nargs=2, default=[55, 150])
parser.add_argument("--lock", type=float, default=6)
parser.add_argument("--minrel", type=float, default=0.15)
parser.add_argument("--still", type=float, default=0.1)
args = parser.parse_args()


def spectrum(x, fs, pad=8):
    n = len(x)
    x = x - np.polyval(np.polyfit(np.arange(n), x, 1), np.arange(n))
    nfft = int(2 ** np.ceil(np.log2(n * pad)))
    mag = np.abs(np.fft.rfft(x * np.hanning(n), nfft))
    return np.fft.rfftfreq(nfft, 1 / fs) * 60, mag


def peaks_in_band(bpm, mag, lo, hi):
    idx = [i for i in range(1, len(mag) - 1)
           if lo <= bpm[i] <= hi and mag[i] > mag[i - 1] and mag[i] >= mag[i + 1]]
    idx.sort(key=lambda i: -mag[i])
    return [(bpm[i], mag[i]) for i in idx]


# ===== 데이터 =====
df = pd.read_csv(args.csv)
t = ((df["t_ms"] - df["t_ms"].iloc[0]) / 1000.0).to_numpy()
fs = 1000.0 / df["t_ms"].diff().mean()
ir = df["ir"].to_numpy(float)
mag = np.sqrt(df["ax"] ** 2 + df["ay"] ** 2 + df["az"] ** 2).to_numpy()
w = (t > args.t - args.win) & (t <= args.t)

# ===== ① PPG 심박 후보 =====
pb, ps = spectrum(ir[w], fs)
cands = peaks_in_band(pb, ps, *args.band)
top = cands[0][1]

# ===== ② IMU 흔들림 리듬 =====
amov = np.std(mag[w])
mb, ms = spectrum(mag[w], fs)
mp = peaks_in_band(mb, ms, 48, 180)
motion = mp[0][0]
base = motion / 2 if motion >= 70 else motion
bad = [base * k for k in range(1, 7)]

# ===== ③ 후보마다 판정 =====
print(f"파일 {args.csv}, {args.t - args.win:.0f}~{args.t:.0f}초")
print(f"흔들림 세기 amov = {amov:.3f} g  ({'거름' if amov >= args.still else '약함 → 거르지 않음'})")
print(f"IMU 가장 강한 리듬 = {motion:.1f} → 팔 리듬 = {base:.1f} → 버릴 리듬: "
      + ", ".join(f"{b:.0f}" for b in bad if b <= 200))
print(f"\n{'후보(bpm)':>9} {'세기':>6}  판정")
verdict = []
for c, m in cands:
    if amov < args.still:
        v = "남음"
    elif any(abs(c - b) <= args.lock for b in bad):
        k = int(round(c / base))
        v = f"버림: 팔 리듬 {base:.0f}의 {k}배 근처"
    elif any(abs(c - 2 * d) <= args.lock for d, _ in cands):
        v = "버림: 다른 후보의 2배 (배음)"
    elif m < args.minrel * top:
        v = "버림: 너무 약함 (잡음)"
    else:
        v = "남음"
    verdict.append(v)
    if m >= 0.05 * top:                      # 아주 작은 봉우리는 출력 생략
        print(f"{c:9.1f} {m / top:6.2f}  {v}")

before = cands[0][0]
left = [c for (c, _), v in zip(cands, verdict) if v == "남음"]
after = left[0] if left else before
print(f"\n거르기 전: {before:.1f} bpm  →  거른 후: {after:.1f} bpm"
      + (f"   (워치 {args.watch:.0f})" if args.watch else ""))

# ===== 그래프 =====
fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
xlim = (40, 200)

ax = axes[0]
ax.plot(pb, ps / top, color="purple", linewidth=1.2, label="PPG (IR) spectrum")
for b in bad:
    if xlim[0] <= b <= xlim[1] and amov >= args.still:
        ax.axvspan(b - args.lock, b + args.lock, color="gray", alpha=0.25)
ax.axvspan(0, 0, color="gray", alpha=0.25, label=f"removed: arm rhythm x1~6 (±{args.lock:.0f})")
ax.plot(before, 1.0, "o", color="tab:orange", markersize=11, label=f"before filter: {before:.1f}")
ax.plot(after, dict(cands)[after] / top, "*", color="tab:green", markersize=18,
        label=f"after filter: {after:.1f}")
if args.watch:
    ax.axvline(args.watch, color="green", linestyle=":", linewidth=1.5, label=f"watch: {args.watch:.0f}")
ax.set_ylabel("strength (max = 1)")
ax.set_title(f"PPG spectrum, {args.t - args.win:.0f}-{args.t:.0f} s")
ax.legend(loc="upper right")

ax = axes[1]
ax.plot(mb, ms / ms[(mb >= 48) & (mb <= 180)].max(), color="tab:blue", linewidth=1.2,
        label="IMU |a| spectrum")
for b in bad:
    if xlim[0] <= b <= xlim[1]:
        ax.axvline(b, color="gray", linestyle="--", linewidth=0.8)
ax.plot(motion, 1.0, "o", color="tab:blue", markersize=11, label=f"strongest motion: {motion:.1f}")
ax.set_ylabel("strength (max = 1)")
ax.set_xlabel("rhythm (per minute)")
ax.set_title(f"IMU spectrum (amov = {amov:.3f} g), dashed = arm rhythm {base:.0f} x k")
ax.legend(loc="upper right")

for a in axes:
    a.set_xlim(*xlim)
    a.set_ylim(0, 1.15)
    a.grid(alpha=0.3)
plt.tight_layout()
out = args.csv.rsplit(".", 1)[0] + f"_spec_t{args.t:.0f}.png"
plt.savefig(out, dpi=120)
print(f"그래프 저장: {out}")
plt.show()