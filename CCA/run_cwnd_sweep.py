#!/usr/bin/env python3
"""
Generate a shell script (`run_sweep.sh`) that runs Mahimahi mm-link/mm-delay
for cwnd values from 1 packet to 10*BDP (in packets).

This script DOES NOT run Mahimahi itself. It writes a bash script you can run
in a terminal that has mahimahi installed.

Usage example:
    python3 run_cwnd_sweep.py --rate-mbps 12 --delay-ms 10 --sendfile CCA/test_file.txt

Generated `run_sweep.sh` will contain one mm-delay/mm-link invocation per cwnd.
Each invocation runs `transport.py` receiver and sender inside the same mahimahi
namespace. Receiver will append a JSON line with goodput to the logfile you
specify via --out-dir (default: ./cwnd_logs).

Adjust the generated command if you prefer separate namespaces or different
mm-link options.
"""

import argparse
import math
import os
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--rate-mbps', type=float, default=12.0, help='Link rate in Mbps (per direction)')
parser.add_argument('--delay-ms', type=float, default=10.0, help='Base one-way delay in ms')
parser.add_argument('--payload', type=int, default=1200, help='Payload size in bytes (packet payload)')
parser.add_argument('--sendfile', type=str, default='CCA/test_file.txt', help='File to send from sender')
parser.add_argument('--ip', type=str, default='10.0.0.1', help='IP used by receiver (inside mahimahi)')
parser.add_argument('--port', type=int, default=9000, help='Port used for transport')
parser.add_argument('--out-dir', type=str, default='cwnd_logs', help='Directory to store generated logs and script')
parser.add_argument('--max-multiplier', type=float, default=10.0, help='Multiply BDP by this to get max cwnd (in packets)')
args = parser.parse_args()

rate_bps = args.rate_mbps * 1e6
rate_Bps = rate_bps / 8.0
base_delay_s = args.delay_ms / 1000.0
bdp_bytes = rate_Bps * base_delay_s
bdp_pkts = max(1, int(math.ceil(bdp_bytes / args.payload)))
max_pkts = max(1, int(math.ceil(bdp_pkts * args.max_multiplier)))

out_dir = Path(args.out_dir)
out_dir.mkdir(parents=True, exist_ok=True)
script_path = out_dir / 'run_sweep.sh'

with open(script_path, 'w') as sh:
    sh.write('#!/usr/bin/env bash\n')
    sh.write('# Generated mahimahi run script: each invocation runs receiver+sender in a mahimahi namespace\n')
    sh.write('# Edit mm-link options (queues, meter flags) below if needed.\n')
    sh.write('\n')

    for cwnd in range(1, max_pkts + 1):
        logfile = out_dir / f'rcv_log_cwnd_{cwnd}.jsonl'
        snd_log = out_dir / f'snd_log_cwnd_{cwnd}.txt'
        mm_out = out_dir / f'mm_out_cwnd_{cwnd}.txt'
        # Example mm-link options; keep similar to the provided example in the prompt
        cmd = (
            f'mm-delay {int(args.delay_ms)} mm-link --meter-uplink --meter-uplink-delay '
            f'--downlink-queue=infinite --uplink-queue=droptail --uplink-queue-args=bytes=30000 '
            f'{args.rate_mbps}mbps {args.rate_mbps}mbps -- '
            f'sh -c "python3 CCA/transport.py receiver --ip {args.ip} --port {args.port} --logfile {logfile} & sleep 0.3; '
            f'python3 CCA/transport.py sender --ip {args.ip} --port {args.port} --sendfile {args.sendfile} '
            f'--fixed-cwnd-pkts {cwnd} > {snd_log} 2>&1" > {mm_out} 2>&1'
        )
        sh.write(cmd + '\n')

print(f'Wrote {script_path} with cwnd=1..{max_pkts} (BDP ~ {bdp_pkts} pkts).')
print('Run the script in a shell with mahimahi installed, e.g.:')
print(f'  bash {script_path}')
print('After runs finish, check the JSONL receiver logs in the output directory, and use mm-throughput-graph or your own plotting tool.')
