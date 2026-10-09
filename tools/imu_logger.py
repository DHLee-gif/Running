"""
IMU 시리얼 데이터를 CSV로 저장하는 로거
사용법: python imu_logger.py --port COM7 --sec 30 --out walk01.csv
※ 실행 전에 Arduino IDE의 시리얼 모니터/플로터를 반드시 닫으세요 (포트 충돌)
"""
import argparse
import csv
import time

import serial

parser = argparse.ArgumentParser()
parser.add_argument("--port", default="COM7")
parser.add_argument("--baud", type=int, default=115200)
parser.add_argument("--sec", type=float, default=30, help="기록 시간(초)")
parser.add_argument("--out", default="imu_log.csv")
args = parser.parse_args()

HEADER = ["t_ms", "ax", "ay", "az", "gx", "gy", "gz"]

# 시리얼 연결 및 CSV 기록
# ser은 보드와 연결된 전화기(COM7), f는 저장할 빈 파일 walk01.csv 
with serial.Serial(args.port, args.baud, timeout=1) as ser, \
        open(args.out, "w", newline="") as f: # 실제 파일을 열어 둠. 글자를 받아서 디스크에 저장
    writer = csv.writer(f) # csv.writer는 리스트를 주면 쉼표로 이어서 한 줄로 써주는 도우미.
    writer.writerow(HEADER) # 실제 한줄을 적는 순간
    # 현재 시점 walk01.csv는 t_ms,ax,ay,az,gx,gy,gz

    print(f"[{args.port}] 연결됨. {args.sec}초 동안 기록합니다.")
    print("보드가 방금 리셋됐다면 처음 2초는 자이로 보정 중이니 가만히 두세요.")

    start = None # 기록 시작 시각
    rows = 0  # 저장할 줄 수
    last_report = time.time() # 마지막으로 진행상황 찍은 시각
    # time.time()은 지금 시각을 초 단위 숫자로 줌. 예를 들면 1000.0 같은 값.
    # 두 시각을 빼면 몇 초가 지났는지 알 수 있음. 1003.5 - 1000.0 = 3.5초인 식
    
    
    # 들어오는 줄을 하나씩 읽어서 CSV에 저장. WHO_AM_I, 보정 메시지, 헤더 등은 화면에만 표시
    while True: 
        line = ser.readline().decode("utf-8", errors="ignore").strip()
        # line = '2104,0.012,0.224,1.000,0.00,-0.05,0.01'
        if not line:
            continue

        parts = line.split(",") # 여기까지 parts = ["addr 0x6A -> WHO_AM_I 0x6A"
        # 숫자 7개짜리 줄만 저장 (WHO_AM_I, 보정 메시지, 헤더 등은 화면에만 표시)
        if len(parts) != 7:  # 로거에 걸러내는 코드, 센서값이 아닌 줄은 저장하지 않고 화면에만 표시
            print("  [board]", line) #  [board] addr 0x6A -> WHO_AM_I 0x6A
            continue
        try:
            values = [float(p) for p in parts]
        except ValueError:
            print("  [board]", line)
            continue

        if start is None:
            start = time.time() # start = 1003.0
            print("기록 시작!")

        writer.writerow(parts) # 파일에 한 줄 추가 --> 애가 센서값을 csv에 저장!! walk01.csv에 2104,0.012,0.224,1.000,0.00,-0.05,0.01 이런 식으로 한 줄씩 추가됨
        rows += 1  # rows = 1

        now = time.time()  # now = 1003.0
        if now - last_report >= 1.0:   # 1003.0 - 1000.0 = 3.0 ≥ 1 → 참
            print(f"  {now - start:5.1f}s  {rows}행")  # "    0.0s  1행"
            last_report = now   # last_report = 1003.0

        if now - start >= args.sec:  # 0.0 ≥ 30 → 거짓, 계속 반복
            break  # while 탈출 → with 블록 끝 → 포트·파일 자동으로 닫힘

print(f"완료: {rows}행 → {args.out}")