#!/usr/bin/env python3
"""
Simple converter from cumulative-byte log to per-interval throughput (Mbps).

Input format (mm_throughput.log):
  <unix_time_seconds> <cumulative_bytes>

Output format (samples file):
  <time_seconds> <throughput_Mbps>

The output time is the midpoint between two samples used to compute throughput.

Usage:
  python3 convert_mm_log.py mm_throughput.log mm_throughput_samples.txt

If the input has fewer than 2 samples, no output is produced.
"""

import sys


def convert(infile, outfile):
    lines = []
    with open(infile, 'r') as f:
        for l in f:
            l = l.strip()
            if not l:
                continue
            parts = l.split()
            if len(parts) < 2:
                continue
            try:
                t = float(parts[0])
                b = int(parts[1])
            except Exception:
                continue
            lines.append((t, b))

    if len(lines) < 2:
        print('Not enough samples to compute throughput')
        return

    samples = []
    for i in range(1, len(lines)):
        t0, b0 = lines[i-1]
        t1, b1 = lines[i]
        dt = t1 - t0
        if dt <= 0:
            continue
        db = b1 - b0
        # throughput in bits per second -> then convert to Mbps
        tp_mbps = (db * 8.0) / (dt * 1e6)
        mid_t = (t0 + t1) / 2.0
        samples.append((mid_t, tp_mbps))

    with open(outfile, 'w') as f:
        for t, tp in samples:
            f.write(f"{t:.6f} {tp:.6f}\n")

    print(f'Wrote {len(samples)} throughput samples to {outfile}')


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print('Usage: convert_mm_log.py <input_cumulative_log> <output_samples>')
        sys.exit(2)
    convert(sys.argv[1], sys.argv[2])
