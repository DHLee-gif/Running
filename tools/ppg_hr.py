"""
PPG(IR) 신호에서 심박수를 계산하는 스크립트

방법 (걸음 검출과 같은 구조):
    ① 1초 이동평균을 빼서 느린 변화(숨쉬기, 손가락 압력)를 지움
    ② 위아래를 뒤집음 (피가 몰리면 IR이 줄어드니까, 박동이 아래로 찍힘 → 위로 올림)
    ③ 0.1초 이동평균으로 잔잡음 다듬기
    ④ 봉우리 찾기: 일정 크기 이상 + 직전 봉우리와 0.33초 이상 (= 최대 180bpm)
    ⑤ 봉우리 간격 → 심박수 (bpm = 60 / 간격)

사용법:
    python tools/ppg_hr.py data/ppg_rest01.csv --truth 72
    (--truth: 손목 맥박을 15초 세서 ×4 한 값)
"""
import argparse

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

parser = argparse.ArgumentParser()
parser.add_argument("csv", help="ppg_logger.py로 저장한 CSV")
parser.add_argument("--truth", type=float, default=None, help="직접 센 심박수 (bpm)")
parser.add_argument("--min-interval", type=float, default=0.33, help="박동 사이 최소 간격 (초)")
parser.add_argument("--height", type=float, default=0.5, help="봉우리 최소 크기 (신호 표준편차의 몇 배)")
parser.add_argument("--skip", type=float, default=3.0, help="앞부분 버릴 시간 (초)")
args = parser.parse_args()


def moving_average(x, n):
    return np.convolve(x, np.ones(n) / n, mode="same")


def find_beats(t, x, height, min_interval):
    """봉우리 찾기: height 이상이고, 직전과 min_interval 이상 떨어진 꼭대기. 가까우면 큰 쪽."""
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
    return beats


# ===== 데이터 읽기 =====
df = pd.read_csv(args.csv)
df = df[(df["t_ms"] - df["t_ms"].iloc[0]) / 1000.0 >= args.skip].reset_index(drop=True)
t = ((df["t_ms"] - df["t_ms"].iloc[0]) / 1000.0).to_numpy()
ir = df["ir"].to_numpy(dtype=float)
fs = 1000.0 / df["t_ms"].diff().mean()

# ===== ①②③ 박동 신호 만들기 =====
pulse = -(ir - moving_average(ir, int(fs)))              # 느린 변화 제거 + 뒤집기
pulse = moving_average(pulse, max(1, int(fs * 0.2)))     # 잔잡음 다듬기
edge = int(fs)                                           # 앞뒤 1초는 이동평균 왜곡 → 제외
t_k, p_k = t[edge:-edge], pulse[edge:-edge]

# ===== ④ 봉우리 찾기 =====
height = args.height * np.std(p_k)
beats = find_beats(t_k, p_k, height, args.min_interval)

# ===== ⑤ 심박수 =====
print(f"파일: {args.csv}  ({t[-1]:.1f}초, {fs:.0f}Hz)")
if ir.mean() < 10000:
    print("※ IR 평균이 낮음: 손가락이 센서에서 떨어졌을 수 있음")

if len(beats) < 3:
    print("박동을 3개 이상 찾지 못함. 그래프를 확인하세요.")
    iv, hr = np.array([]), None
else:
    iv = np.diff(t_k[beats])
    hr = 60 / np.median(iv)
    print(f"\n박동 {len(beats)}개, 간격 중앙값 {np.median(iv):.3f}초")
    print(f"심박수: {hr:.0f} bpm", end="")
    if args.truth:
        print(f"  (직접 센 값 {args.truth:.0f}, 차이 {hr - args.truth:+.0f})")
    else:
        print()
    print(f"박동 간격 범위: {iv.min():.2f}~{iv.max():.2f}초 "
          f"(= {60 / iv.max():.0f}~{60 / iv.min():.0f} bpm)")

# ===== 그래프 =====
fig, axes = plt.subplots(3, 1, figsize=(12, 9), sharex=True,
                         gridspec_kw={"height_ratios": [2, 3, 2]})

axes[0].plot(t, ir, color="purple", linewidth=0.8)
axes[0].set_ylabel("IR (raw)")
axes[0].set_title("Raw IR")

axes[1].plot(t_k, p_k, color="black", linewidth=0.9)
axes[1].plot(t_k[beats], p_k[beats], "o", color="red", markersize=6,
             label=f"beat ({len(beats)})")
axes[1].axhline(height, color="red", linestyle="--", linewidth=0.8, label="min height")
axes[1].axhline(0, color="gray", linewidth=0.6)
axes[1].set_ylabel("pulse (inverted)")
axes[1].set_title("Pulse wave and detected beats")
axes[1].legend(loc="upper right")

if len(iv):
    axes[2].plot(t_k[beats][1:], 60 / iv, "o-", color="darkred", markersize=5)
    axes[2].axhline(hr, color="gray", linestyle="--", linewidth=0.8, label=f"median {hr:.0f} bpm")
    if args.truth:
        axes[2].axhline(args.truth, color="green", linestyle=":", linewidth=1.2,
                        label=f"manual {args.truth:.0f} bpm")
    axes[2].legend(loc="upper right")
axes[2].set_ylabel("heart rate (bpm)")
axes[2].set_xlabel("time (s)")
axes[2].set_title("Beat-to-beat heart rate")

for ax in axes:
    ax.grid(alpha=0.3)
plt.tight_layout()
out_png = args.csv.rsplit(".", 1)[0] + "_hr.png"
plt.savefig(out_png, dpi=120)
print(f"\n그래프 저장: {out_png}")
plt.show()