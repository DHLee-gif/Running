"""
저장한 PPG CSV를 그래프로 확인

원신호에는 큰 고정값(약 10만) 위에 아주 작은 박동(약 0.2%)이 얹혀 있다.
그래서 1초 이동평균(느린 변화)을 빼서 박동만 남긴 그래프를 같이 그린다.

사용법: python tools/ppg_plot.py data/ppg_rest01.csv
"""
import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

path = sys.argv[1] if len(sys.argv) > 1 else "data/ppg_log.csv"
df = pd.read_csv(path)
t = ((df["t_ms"] - df["t_ms"].iloc[0]) / 1000.0).to_numpy()
red = df["red"].to_numpy(dtype=float)
ir = df["ir"].to_numpy(dtype=float)
fs = 1000.0 / df["t_ms"].diff().mean()


def moving_average(x, n):
    return np.convolve(x, np.ones(n) / n, mode="same")


# 박동만 남기기: (원신호 - 1초 평균) 후 0.1초 평균으로 잡음 다듬기
ir_beat = moving_average(ir - moving_average(ir, int(fs)), max(1, int(fs * 0.1)))
edge = int(fs)                                   # 앞뒤 1초는 이동평균 왜곡이 있어서 제외
keep = slice(edge, len(t) - edge)

print(f"샘플 {len(df)}개, 길이 {t[-1]:.1f}초, 샘플링 {fs:.1f}Hz")
print(f"IR 평균 {ir.mean():.0f}, Red 평균 {red.mean():.0f}")
print(f"박동 성분 크기(IR) 약 ±{np.std(ir_beat[keep]):.0f}")

fig, axes = plt.subplots(3, 1, figsize=(12, 8), sharex=True)
axes[0].plot(t, ir, color="purple", linewidth=0.8)
axes[0].set_ylabel("IR (raw)")
axes[0].set_title("Raw IR")
axes[1].plot(t, red, color="red", linewidth=0.8)
axes[1].set_ylabel("Red (raw)")
axes[1].set_title("Raw Red")
axes[2].plot(t[keep], ir_beat[keep], color="black", linewidth=0.9)
axes[2].axhline(0, color="gray", linewidth=0.6)
axes[2].set_ylabel("IR - 1s mean")
axes[2].set_xlabel("time (s)")
axes[2].set_title("Pulse wave (slow drift removed)")
for ax in axes:
    ax.grid(alpha=0.3)

plt.tight_layout()
out_png = path.rsplit(".", 1)[0] + ".png"
plt.savefig(out_png, dpi=120)
print(f"그래프 저장: {out_png}")
plt.show()