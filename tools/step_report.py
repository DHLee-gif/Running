"""
전체 측정을 한 번에 정리하는 스크립트 (속도별 평균 표 + results.png)

trial.csv의 모든 측정을 걸음 검출 v1(처음)과 v2(개선)로 각각 분석해 비교한다.

trial.csv에 적힌 측정 파일을 하나씩 읽어서
    걸음 수 오차, 걸음 간격 CV를 v1/v2로 각각 계산하고
    BPM(속도)별로 평균 ± 표준편차를 정리한다.

CV 안정: 처음 N걸음(--skip)을 빼고, 튀는 간격(중앙값의 0.5배 미만, 1.5배 초과)도 뺀 CV

사용법:
    python tools/step_report.py
    python tools/step_report.py --skip 5
    python tools/step_report.py --trials data/trial_odr.csv --group odr   # 샘플링 속도별 비교
"""
import argparse
import os

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from step_detect import VERSIONS, cv, detect_steps, drop_outliers, step_intervals

parser = argparse.ArgumentParser()
parser.add_argument("--trials", default="data/trial.csv", help="측정 기록 파일")
parser.add_argument("--skip", type=int, default=5, help="CV 안정 계산 때 뺄 처음 걸음 수")
parser.add_argument("--group", default="bpm", help="묶어서 비교할 칸 (bpm 또는 odr)")
args = parser.parse_args()


def analyze(path, truth, p):
    df = pd.read_csv(path)
    t = ((df["t_ms"] - df["t_ms"].iloc[0]) / 1000.0).to_numpy()
    mag = np.sqrt(df["ax"] ** 2 + df["ay"] ** 2 + df["az"] ** 2).to_numpy()
    fs = 1000.0 / df["t_ms"].diff().mean()

    steps, _ = detect_steps(t, mag, fs, p)
    _, iv = step_intervals(t, steps, p["max_interval"])
    r = {"steps": len(steps),
         "median_s": np.median(iv) if len(iv) else np.nan,
         "cv_steady": cv(drop_outliers(iv[args.skip:])) if len(iv) > args.skip else np.nan}
    r["err_pct"] = (len(steps) - truth) / truth * 100 if not np.isnan(truth) else np.nan
    return r


# ===== 측정 기록 읽기 =====
trials = pd.read_csv(args.trials, skipinitialspace=True, encoding="utf-8-sig")
trials.columns = trials.columns.str.strip()
trials["file"] = trials["file"].astype(str).str.strip()
data_dir = os.path.dirname(args.trials)

rows = []
for _, tr in trials.iterrows():
    path = os.path.join(data_dir, tr["file"])
    if not os.path.exists(path):
        print(f"[건너뜀] 파일 없음: {path}")
        continue
    truth = float(tr["truth"]) if pd.notna(tr["truth"]) else np.nan
    row = {"file": tr["file"], "bpm": int(tr["bpm"]), "truth": truth}
    if args.group != "bpm":
        row[args.group] = int(tr[args.group])
    for ver, p in VERSIONS.items():
        for k, v in analyze(path, truth, p).items():
            row[f"{k}_{ver}"] = v
    rows.append(row)

res = pd.DataFrame(rows)
cols = ["file", "bpm"] + ([args.group] if args.group != "bpm" else []) + ["truth",
        "steps_v1", "steps_v2", "err_pct_v1", "err_pct_v2", "cv_steady_v1", "cv_steady_v2"]
res = res[cols + [c for c in res.columns if c not in cols]]

pd.set_option("display.width", 200)
print("\n===== 측정별 결과 (v1 → v2) =====")
print(res[cols].to_string(index=False, float_format=lambda v: f"{v:.1f}"))

# ===== BPM별 평균 ± 표준편차 =====
print(f"\n===== {args.group.upper()}별 평균 ± 표준편차 (CV 안정: 처음 {args.skip}걸음 제외) =====")
summary = []
for key, g in res.groupby(args.group):
    s = {args.group: key, "n": len(g)}
    for col in ["err_pct_v1", "err_pct_v2", "cv_steady_v1", "cv_steady_v2"]:
        s[col] = f"{g[col].mean():.1f} ± {g[col].std(ddof=1):.1f}"
    summary.append(s)
print(pd.DataFrame(summary).to_string(index=False))

name = os.path.splitext(os.path.basename(args.trials))[0].replace("trial", "results")
out_csv = os.path.join(data_dir, name + ".csv")
res.to_csv(out_csv, index=False, float_format="%.3f")
print(f"\n결과 저장: {out_csv}")

# ===== 그래프: BPM별 오차와 CV, v1(회색) vs v2(파랑) =====
bpms = sorted(res[args.group].unique())
unit = {"bpm": "BPM", "odr": "Hz"}.get(args.group, args.group)
style = {"v1": ("#9aa0a6", -0.18, "v1 (before)"), "v2": ("#2f6fe0", 0.18, "v2 (improved)")}
fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
panels = [("err_pct", "Step count error (%)", "Error vs video truth"),
          ("cv_steady", "CV (%)", f"Step rhythm CV (first {args.skip} steps skipped)")]

for ax, (col, ylabel, title) in zip(axes, panels):
    for ver, (color, dx, label) in style.items():
        for k, b in enumerate(bpms):
            vals = res.loc[res[args.group] == b, f"{col}_{ver}"].to_numpy()
            xi = k + dx + np.linspace(-0.05, 0.05, len(vals))
            ax.plot(xi, vals, "o", color=color, markersize=7, alpha=0.6)
            ax.errorbar(k + dx + 0.1, np.nanmean(vals), yerr=np.nanstd(vals, ddof=1),
                        fmt="s", color=color, markersize=7, capsize=5,
                        label=label if k == 0 else None)
    ax.axhline(0, color="gray", linewidth=0.8)
    ax.set_xticks(range(len(bpms)), [f"{b} {unit}" for b in bpms])
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(alpha=0.3, axis="y")
axes[0].legend(loc="best", title="circle: trial / square: mean ± SD", title_fontsize=8)

plt.tight_layout()
out_png = os.path.join(data_dir, name + ".png")
plt.savefig(out_png, dpi=120)
print(f"그래프 저장: {out_png}")
plt.show()