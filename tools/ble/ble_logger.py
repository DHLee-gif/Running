"""
RunBand BLE 수신 테스트 (firmware/runband_ble 3단계용)

PC 블루투스로 보드에 연결 → START → --sec초 기록 → STOP → CSV 저장
  - <out>.csv      : t_ms,red,ir,ax,ay,az,gx,gy,gz  (hr_logger.py와 같은 열)
  - <out>_temp.csv : t_ms,temp
끝나면 빠진 패킷(seq 건너뜀), 실제 샘플 속도, 전송량을 출력

준비:   pip install bleak
사용법: python tools/ble/ble_logger.py --sec 60 --out data/ble_test01.csv
"""
import argparse
import asyncio
import csv
import os
import struct
import time

from bleak import BleakClient, BleakScanner

parser = argparse.ArgumentParser()
parser.add_argument("--name", default="RunBand")
parser.add_argument("--sec", type=float, default=30, help="기록 시간(초)")
parser.add_argument("--out", default="data/ble_test.csv")
args = parser.parse_args()

NUS_RX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"   # PC → 보드 (명령)
NUS_TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"   # 보드 → PC (텍스트)
DATA = "7a1e0002-5c3b-4f0e-9d2a-6b8f1c2e3d40"     # 보드 → PC (바이너리)

SAMPLE = struct.Struct("<I3s3s6h")                 # t, red, ir, ax ay az gx gy gz = 22바이트
A_SCALE, G_SCALE = 0.000244, 0.0175                # ±8g, ±500dps

rows, temps = [], []
stat = {"pkts": 0, "bytes": 0, "gaps": 0, "last_seq": None}
text_buf = ""
stop_done = asyncio.Event()


def on_text(_, data: bytearray):
    """NUS 텍스트: 줄 단위로 출력, TEMP는 저장"""
    global text_buf
    text_buf += data.decode("utf-8", errors="ignore")
    while "\n" in text_buf:
        line, text_buf = text_buf.split("\n", 1)
        line = line.strip()
        if not line:
            continue
        print("  [board]", line)
        if line.startswith("TEMP"):
            kv = dict(p.split("=") for p in line.split()[1:])
            temps.append((int(kv["t_ms"]), kv["c"]))
        elif line.startswith("OK STOP"):
            stop_done.set()


def on_data(_, data: bytearray):
    """바이너리 패킷: [0x01][n][seq 2B] + n × 22B"""
    if len(data) < 4 or data[0] != 0x01:
        print("  [경고] 모르는 패킷", data[:8].hex())
        return
    n, seq = data[1], struct.unpack_from("<H", data, 2)[0]
    if len(data) != 4 + n * SAMPLE.size:
        print(f"  [경고] 길이 이상: {len(data)}바이트, n={n}")
        return
    if stat["last_seq"] is not None and seq != (stat["last_seq"] + 1) & 0xFFFF:
        stat["gaps"] += (seq - stat["last_seq"] - 1) & 0xFFFF
    stat["last_seq"] = seq
    stat["pkts"] += 1
    stat["bytes"] += len(data)
    for i in range(n):
        t, red, ir, *imu = SAMPLE.unpack_from(data, 4 + i * SAMPLE.size)
        rows.append((t, int.from_bytes(red, "little"), int.from_bytes(ir, "little"), *imu))


async def send(client, cmd):
    await client.write_gatt_char(NUS_RX, (cmd + "\n").encode(), response=True)


async def main():
    print(f"'{args.name}' 찾는 중...")
    dev = await BleakScanner.find_device_by_name(args.name, timeout=15)
    if dev is None:
        print("보드를 찾지 못함 (폰 nRF Connect 연결을 먼저 끊었는지 확인)")
        return
    async with BleakClient(dev) as client:
        print(f"연결됨: {dev.address}, MTU={client.mtu_size}")
        await client.start_notify(NUS_TX, on_text)
        await client.start_notify(DATA, on_data)
        await send(client, "STATUS")
        await asyncio.sleep(0.5)

        await send(client, "START")
        t0 = time.time()
        while time.time() - t0 < args.sec:
            await asyncio.sleep(5)
            el = time.time() - t0
            print(f"  {el:4.0f}초  샘플 {len(rows)}개 ({len(rows) / el:.1f}/s), "
                  f"패킷 {stat['pkts']}, 빠짐 {stat['gaps']}")

        await send(client, "STOP")
        try:
            await asyncio.wait_for(stop_done.wait(), 5)
        except asyncio.TimeoutError:
            print("  [경고] OK STOP 응답 없음")
        await asyncio.sleep(0.5)                 # 늦게 온 패킷 받기

    save()


def save():
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t_ms", "red", "ir", "ax", "ay", "az", "gx", "gy", "gz"])
        for t, red, ir, ax, ay, az, gx, gy, gz in rows:
            w.writerow([t, red, ir,
                        f"{ax * A_SCALE:.3f}", f"{ay * A_SCALE:.3f}", f"{az * A_SCALE:.3f}",
                        f"{gx * G_SCALE:.2f}", f"{gy * G_SCALE:.2f}", f"{gz * G_SCALE:.2f}"])
    temp_out = os.path.splitext(args.out)[0] + "_temp.csv"
    with open(temp_out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t_ms", "temp"])
        w.writerows(temps)

    # 요약
    print("\n===== 결과 =====")
    if len(rows) >= 2:
        dur = (rows[-1][0] - rows[0][0]) / 1000
        dts = [b[0] - a[0] for a, b in zip(rows, rows[1:])]
        print(f"샘플 {len(rows)}개, {dur:.1f}초 → {(len(rows) - 1) / dur:.1f} Hz")
        print(f"샘플 간격 최대 {max(dts)} ms (100ms 넘으면 중간에 빠진 구간)")
        print(f"전송량 {stat['bytes'] / dur:.0f} B/s, 패킷 {stat['pkts']}개, 빠진 패킷 {stat['gaps']}개")
    print(f"온도 {len(temps)}개")
    print(f"저장: {args.out}, {temp_out}")


asyncio.run(main())
