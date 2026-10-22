"""
PPG + IMU 통합 로거 (firmware/hr_imu 펌웨어용)

보드 출력: t_ms,red,ir,ax,ay,az,gx,gy,gz
사용법: python tools/hr_logger.py --port COM7 --sec 60 --out data/hr_A80.csv
"""
import argparse
import csv
import math
import time

import serial

parser = argparse.ArgumentParser()
parser.add_argument("--port", default="COM7")
parser.add_argument("--baud", type=int, default=115200)
parser.add_argument("--sec", type=float, default=60, help="기록 시간(초)")
parser.add_argument("--out", default="data/hr_log.csv")
args = parser.parse_args()

HEADER = ["t_ms", "red", "ir", "ax", "ay", "az", "gx", "gy", "gz"]

with serial.Serial(args.port, args.baud, timeout=1) as ser, \
        open(args.out, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(HEADER)
    print(f"[{args.port}] 연결됨. 센서 준비를 기다리는 중...")

    start, rows, last_report = None, 0, time.time()
    while True:
        line = ser.readline().decode("utf-8", errors="ignore").strip()
        if not line:
            continue

        parts = line.split(",")
        if len(parts) != len(HEADER):           # 숫자 9개짜리 줄만 저장
            print("  [board]", line)
            continue
        try:
            ir = int(parts[2])
            ax, ay, az = float(parts[3]), float(parts[4]), float(parts[5])
        except ValueError:
            print("  [board]", line)            # 헤더 줄 등
            continue

        if start is None:
            start = time.time()
            print(f"기록 시작! ({time.strftime('%H:%M:%S')})")

        writer.writerow(parts)
        rows += 1

        now = time.time()
        if now - last_report >= 1.0:
            mag = math.sqrt(ax * ax + ay * ay + az * az)
            hint = "  ← 손가락이 떨어진 것 같음" if ir < 50000 else ""
            print(f"  {now - start:5.1f}s  {rows}행  ir={ir}  |a|={mag:.2f}g{hint}")
            last_report = now
        if now - start >= args.sec:
            break

print(f"완료: {rows}행 → {args.out}")