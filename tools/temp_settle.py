"""
온도 안정 시간 분석

센서를 피부에 붙인 뒤 언제부터 값을 믿을 수 있는지 계산한다.
    - 붙인 시점: 처음 --base초 평균(방 온도)보다 0.3°C 이상 오른 첫 순간 (자동 검출)
      → 처음 --base초 동안은 센서를 아무도 만지지 않아야 함
    - 최종 온도: 마지막 --tail초의 평균
    - 63% / 95% 시점: 처음 온도에서 최종 온도까지 그만큼 올라온 순간
    - 안정 시점: 최종 온도와 ±--tol°C 안으로 들어와서 끝까지 안 벗어나는 순간

사용법: python tools/temp_settle.py data/temp_settle01.csv
결과:   data/temp_settle01.png
"""
import argparse

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

parser = argparse.ArgumentParser()
parser.add_argument("csv")
parser.add_argument("--tail", type=float, default=60, help="최종 온도로 쓸 마지막 구간 (초)")
parser.add_argument("--base", type=float, default=20, help="방 온도로 쓸 처음 구간 (초)")
parser.add_argument("--tol", type=float, default=0.1, help="안정 판단 허용 범위 (°C)")
args = parser.parse_args()

df = pd.read_csv(args.csv)
t = ((df["t_ms"] - df["t_ms"].iloc[0]) / 1000.0).to_numpy()
temp = df["temp"].to_numpy(float)

# ===== 붙인 시점: 처음 --base초 평균보다 0.3°C 이상 오른 첫 순간 =====
start_temp = temp[t <= args.base].mean()
idx = np.where((t > args.base) & (temp > start_temp + 0.3))[0]
i0 = idx[0] if len(idx) else 0
t0 = t[i0]

final = temp[t >= t[-1] - args.tail].mean()
span = final - start_temp


def first_reach(frac):
    target = start_temp + frac * span
    j = np.where((t >= t0) & (temp >= target))[0]
    return t[j[0]] - t0 if len(j) else np.nan


t63, t95 = first_reach(0.63), first_reach(0.95)

# 안정: 최종 ±tol 밖에 있던 마지막 순간 이후
out = np.where((t >= t0) & (np.abs(temp - final) > args.tol))[0]
t_settle = (t[out[-1]] - t0) if len(out) else 0.0

print(f"파일: {args.csv}  ({t[-1] / 60:.1f}분)")
print(f"붙이기 전 온도: {start_temp:.2f}°C  (붙인 시점 {t0:.0f}초)")
print(f"최종 온도    : {final:.2f}°C  (마지막 {args.tail:.0f}초 평균)")
print(f"63% 도달     : {t63:.0f}초")
print(f"95% 도달     : {t95:.0f}초")
print(f"안정 (±{args.tol}°C): 붙인 뒤 {t_settle:.0f}초 = {t_settle / 60:.1f}분")

# 마지막 구간에도 계속 오르고 있으면 "최종 온도"가 아직 최종이 아님
tail = t >= t[-1] - args.tail
slope = np.polyfit(t[tail], temp[tail], 1)[0] * 60
print(f"마지막 {args.tail:.0f}초 변화: {slope:+.3f}°C/분", end="")
print("  ← 아직 변하는 중. 더 길게 기록하세요" if abs(slope) > 0.05 else "  (멈춤 ✅)")

fig, ax = plt.subplots(figsize=(11, 5))
ax.plot(t - t0, temp, color="tab:red", linewidth=1)
ax.axhline(final, color="gray", linestyle="--", linewidth=0.8, label=f"final {final:.2f}")
ax.axhspan(final - args.tol, final + args.tol, color="gray", alpha=0.15, label=f"±{args.tol}°C")
ax.axvline(0, color="k", linewidth=0.8, label="attached")
for tt, name, c in [(t63, "63%", "tab:orange"), (t95, "95%", "tab:blue"), (t_settle, "settled", "tab:green")]:
    if not np.isnan(tt):
        ax.axvline(tt, color=c, linestyle=":", linewidth=1.5, label=f"{name}: {tt:.0f}s")
ax.set_xlabel("time since attached (s)")
ax.set_ylabel("temperature (°C)")
ax.set_title("Skin temperature settling")
ax.legend(loc="lower right")
ax.grid(alpha=0.3)
plt.tight_layout()
out_png = args.csv.rsplit(".", 1)[0] + ".png"
plt.savefig(out_png, dpi=120)
print(f"그래프 저장: {out_png}")
plt.show()