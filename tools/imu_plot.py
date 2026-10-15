"""
저장한 IMU CSV를 그래프로 확인
사용법: python imu_plot.py walk01.csv
"""
import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

path = sys.argv[1] if len(sys.argv) > 1 else "imu_log.csv"
df = pd.read_csv(path)

# 시간(초)과 가속도 크기
t = (df["t_ms"] - df["t_ms"].iloc[0]) / 1000.0
mag = np.sqrt(df["ax"] ** 2 + df["ay"] ** 2 + df["az"] ** 2)

# 샘플링 속도 점검 (104Hz 근처여야 정상)
dt = df["t_ms"].diff().dropna()
print(f"샘플 수: {len(df)}, 길이: {t.iloc[-1]:.1f}s")
print(f"평균 간격: {dt.mean():.2f}ms → 약 {1000 / dt.mean():.1f}Hz")
print(f"최대 간격: {dt.max():.0f}ms (크게 튀면 데이터 누락)")
print(f"가속도 크기: 평균 {mag.mean():.3f}g, 최대 {mag.max():.3f}g")

fig, axes = plt.subplots(3, 1, figsize=(12, 9), sharex=True)

for col in ["ax", "ay", "az"]:
    axes[0].plot(t, df[col], label=col, linewidth=0.8)
axes[0].set_ylabel("accel (g)")
axes[0].set_title("Accelerometer XYZ")
axes[0].legend(loc="upper right")
axes[0].grid(alpha=0.3)

axes[1].plot(t, mag, color="black", linewidth=0.8)
axes[1].axhline(1.0, color="red", linestyle="--", linewidth=0.8, label="1g (gravity)")
axes[1].set_ylabel("|a| (g)")
axes[1].set_title("Acceleration magnitude  sqrt(ax²+ay²+az²)")
axes[1].legend(loc="upper right")
axes[1].grid(alpha=0.3)

for col in ["gx", "gy", "gz"]:
    axes[2].plot(t, df[col], label=col, linewidth=0.8)
axes[2].set_ylabel("gyro (dps)")
axes[2].set_xlabel("time (s)")
axes[2].set_title("Gyroscope XYZ")
axes[2].legend(loc="upper right")
axes[2].grid(alpha=0.3)

plt.tight_layout()
out_png = path.rsplit(".", 1)[0] + ".png"
plt.savefig(out_png, dpi=120)
print(f"그래프 저장: {out_png}")
plt.show()