"""
온도 샘플링 속도 비교 (실험 2)

10Hz로 기록한 온도 데이터를 솎아내서, 더 느리게 읽어도 같은 결론이 나오는지 본다.
(IMU 2편 downsample.py와 같은 방식: 같은 데이터에서 속도만 바꿈)

비교 항목
    - 최종 온도, 안정 시간: temp_settle.py와 같은 방법
    - 최대 오차: 느린 데이터를 점과 점 사이 직선으로 이어서 원본과 비교했을 때 가장 크게 벗어난 값
    - 1시간 샘플 수: BLE로 보낼 데이터 양 (적을수록 배터리 절약)

사용법: python tools/temp_rate.py data/temp_settle02.csv
결과:   data/temp_settle02_rate.csv, data/temp_settle02_rate.png
"""
import argparse

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

parser = argparse.ArgumentParser()
parser.add_argument("csv")
parser.add_argument("--periods", type=float, nargs="+", default=[0.1, 1, 5, 10, 30, 60],
                    help="비교할 읽기 간격 (초)")
parser.add_argument("--base", type=float, default=20)
parser.add_argument("--tail", type=float, default=60)
parser.add_argument("--tol", type=float, default=0.1)
args = parser.parse_args()

df = pd.read_csv(args.csv)
t_all = ((df["t_ms"] - df["t_ms"].iloc[0]) / 1000.0).to_numpy()
temp_all = df["temp"].to_numpy(float)
src_period = np.median(np.diff(t_all))


def settle(t, temp):
    """temp_settle.py와 같은 계산. (붙인 시점, 최종 온도, 안정 시간)"""
    base = temp[t <= args.base]
    start = base.mean() if len(base) else temp[0]
    idx = np.where((t > args.base) & (temp > start + 0.3))[0]
    t0 = t[idx[0]] if len(idx) else t[0]
    tail = temp[t >= t[-1] - args.tail]
    final = tail.mean() if len(tail) else temp[-1]
    out = np.where((t >= t0) & (np.abs(temp - final) > args.tol))[0]
    t_settle = (t[out[-1]] - t0) if len(out) else 0.0
    return t0, final, t_settle


t0_ref, _, _ = settle(t_all, temp_all)
rows, curves = [], {}
for p in args.periods:
    step = max(1, int(round(p / src_period)))
    t, temp = t_all[::step], temp_all[::step]
    t0, final, t_settle = settle(t, temp)

    # 점 사이를 직선으로 이어서 원본 시각에서 다시 계산 → 원본과의 차이
    recon = np.interp(t_all, t, temp)
    after = t_all >= t0_ref
    err_all = np.abs(recon - temp_all)[after].max()
    err_stable = np.abs(recon - temp_all)[t_all >= t0_ref + 600].max()   # 붙인 지 10분 이후

    rows.append({"period_s": p, "samples_per_hour": int(3600 / p),
                 "final": round(final, 2), "settle_min": round(t_settle / 60, 1),
                 "max_err_all": round(err_all, 2), "max_err_after10min": round(err_stable, 3)})
    curves[p] = (t, temp)

res = pd.DataFrame(rows)
out_csv = args.csv.rsplit(".", 1)[0] + "_rate.csv"
res.to_csv(out_csv, index=False)
print(res.to_string(index=False))
print("\nmax_err_all       : 붙인 뒤 전체 구간에서 원본과 가장 크게 벗어난 값 (°C)")
print("max_err_after10min: 안정된 뒤(붙인 지 10분 이후)에서 가장 크게 벗어난 값 (°C)")

# ===== 그래프: 전체 + 붙인 직후 2분 확대 =====
fig, axes = plt.subplots(1, 2, figsize=(14, 5))
show = [p for p in args.periods if p in (1, 10, 60)] or args.periods[:3]
for ax, (lo, hi) in zip(axes, [(t_all[0], t_all[-1]), (t0_ref - 10, t0_ref + 120)]):
    m = (t_all >= lo) & (t_all <= hi)
    ax.plot(t_all[m] - t0_ref, temp_all[m], color="lightgray", linewidth=3, label=f"original ({src_period:.1f}s)")
    for p, c in zip(show, ["tab:blue", "tab:orange", "tab:red"]):
        t, temp = curves[p]
        k = (t >= lo) & (t <= hi)
        ax.plot(t[k] - t0_ref, temp[k], "o-", color=c, markersize=3, linewidth=1, label=f"every {p:g}s")
    ax.set_xlabel("time since attached (s)")
    ax.set_ylabel("temperature (°C)")
    ax.grid(alpha=0.3)
    ax.legend(loc="lower right")
axes[0].set_title("Whole recording")
axes[1].set_title("Zoom: first 2 minutes after attaching")
plt.tight_layout()
out_png = args.csv.rsplit(".", 1)[0] + "_rate.png"
plt.savefig(out_png, dpi=120)
print(f"\n표 저장: {out_csv}\n그래프 저장: {out_png}")
plt.show()