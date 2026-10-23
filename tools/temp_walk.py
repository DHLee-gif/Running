"""
제자리걸음 중 피부 온도 변화 분석 (실험 3)

구간 (로거 시작 기준, 초):
    안정  0 ~ --walk[0]
    걷기  --walk[0] ~ --walk[1]
    회복  --walk[1] ~ 끝

계산
    - 기준 온도: 걷기 직전 60초 평균
    - 걷기 중 최저/최고 온도와 그 시각 (처음에 내려가는지, 나중에 오르는지)
    - 걷기 끝 온도, 회복 끝 온도 (기준 대비 변화)
    - 구간별 변화 속도 (°C/분)
    - 회복: 기준 ±0.1°C 안으로 돌아오는 데 걸린 시간

사용법: python tools/temp_walk.py data/temp_walk01.csv --walk 600 1200
결과:   data/temp_walk01.png
"""
import argparse

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

parser = argparse.ArgumentParser()
parser.add_argument("csv")
parser.add_argument("--walk", type=float, nargs=2, default=[600, 1200], help="걷기 시작, 끝 (초)")
parser.add_argument("--tol", type=float, default=0.1)
parser.add_argument("--smooth", type=float, default=10, help="이동평균 (초). 센서 잔흔들림 제거용")
args = parser.parse_args()

df = pd.read_csv(args.csv)
t = ((df["t_ms"] - df["t_ms"].iloc[0]) / 1000.0).to_numpy()
raw = df["temp"].to_numpy(float)
fs = 1 / np.median(np.diff(t))
n = max(1, int(round(args.smooth * fs)))
temp = pd.Series(raw).rolling(n, center=True, min_periods=1).mean().to_numpy()

w0, w1 = args.walk
rest, walk, rec = t < w0, (t >= w0) & (t < w1), t >= w1


def slope(mask):
    if mask.sum() < 3:
        return np.nan
    return np.polyfit(t[mask], temp[mask], 1)[0] * 60


base = temp[(t >= w0 - 60) & (t < w0)].mean()
i_min = np.argmin(np.where(walk, temp, np.inf))
i_max = np.argmax(np.where(walk, temp, -np.inf))
end_walk = temp[(t >= w1 - 30) & (t < w1)].mean()
end_rec = temp[t >= t[-1] - 30].mean()

# 회복: 걷기 끝난 뒤 처음으로 기준 ±tol 안에 들어온 시각
back = np.where(rec & (np.abs(temp - base) <= args.tol))[0]
t_back = t[back[0]] - w1 if len(back) else np.nan

print(f"파일: {args.csv}  ({t[-1] / 60:.1f}분), {args.smooth:g}초 이동평균 적용")
print(f"구간: 안정 0~{w0 / 60:.0f}분 / 걷기 {w0 / 60:.0f}~{w1 / 60:.0f}분 / 회복 {w1 / 60:.0f}분~")
print(f"\n기준 온도 (걷기 직전 1분)  : {base:.2f}°C")
print(f"걷기 중 최저               : {temp[i_min]:.2f}°C ({temp[i_min] - base:+.2f}), 걷기 시작 {(t[i_min] - w0) / 60:.1f}분 후")
print(f"걷기 중 최고               : {temp[i_max]:.2f}°C ({temp[i_max] - base:+.2f}), 걷기 시작 {(t[i_max] - w0) / 60:.1f}분 후")
print(f"걷기 끝 (마지막 30초)      : {end_walk:.2f}°C ({end_walk - base:+.2f})")
print(f"회복 끝 (마지막 30초)      : {end_rec:.2f}°C ({end_rec - base:+.2f})")
print(f"기준 ±{args.tol}°C로 돌아옴    : " + (f"걷기 끝난 뒤 {t_back / 60:.1f}분" if not np.isnan(t_back) else "돌아오지 않음"))
print(f"\n변화 속도 (°C/분)  안정 마지막 3분 {slope((t >= w0 - 180) & rest):+.3f} / "
      f"걷기 {slope(walk):+.3f} / 회복 {slope(rec):+.3f}")
print("※ 안정 마지막 3분이 0에 가깝지 않으면 아직 덜 안정된 상태에서 걷기를 시작한 것")

fig, ax = plt.subplots(figsize=(12, 5))
ax.axvspan(0, w0 / 60, color="tab:blue", alpha=0.07, label="rest")
ax.axvspan(w0 / 60, w1 / 60, color="tab:orange", alpha=0.12, label="walking")
ax.axvspan(w1 / 60, t[-1] / 60, color="tab:green", alpha=0.07, label="recovery")
ax.plot(t / 60, raw, color="lightgray", linewidth=0.8, label="raw")
ax.plot(t / 60, temp, color="tab:red", linewidth=1.5, label=f"{args.smooth:g}s average")
ax.axhline(base, color="gray", linestyle="--", linewidth=0.8, label=f"baseline {base:.2f}")
ax.plot(t[i_min] / 60, temp[i_min], "v", color="tab:blue", markersize=10, label=f"walk min {temp[i_min]:.2f}")
ax.plot(t[i_max] / 60, temp[i_max], "^", color="tab:red", markersize=10, label=f"walk max {temp[i_max]:.2f}")
lo = np.percentile(temp[t > 120], 1) - 0.3        # 붙이기 전 방 온도 구간은 축에서 제외
hi = temp.max() + 0.2
ax.set_ylim(lo, hi)
ax.set_xlabel("time (min)")
ax.set_ylabel("skin temperature (°C)")
ax.set_title("Skin temperature: rest → walking in place → recovery")
ax.legend(loc="lower right", fontsize=8, ncol=2)
ax.grid(alpha=0.3)
plt.tight_layout()
out_png = args.csv.rsplit(".", 1)[0] + ".png"
plt.savefig(out_png, dpi=120)
print(f"\n그래프 저장: {out_png}")
plt.show()