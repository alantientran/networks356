#!/usr/bin/env python3
"""
Plot cwnd (assumed 1..N) vs goodput from a JSONL logfile produced by
`transport.py` receiver (`--logfile`).

Assumptions:
- Each line in the JSONL file corresponds to a single run (one cwnd value)
  in the order you executed the sender loop (e.g., cwnd=1,2,3...).
- Each JSON line contains the key `goodput_Bps` (bytes/sec).

Usage:
    pip install matplotlib numpy
    python3 CCA/plot_cwnd_goodput.py --input cwnd_logs/rcv.jsonl --out cwnd_goodput.png

Options:
    --input: path to the JSONL file (default: cwnd_logs/rcv.jsonl)
    --out: path to save PNG output (default: cwnd_goodput.png)
    --title: optional title for the plot
    --start-cwnd: integer cwnd for the first line (default 1)
    --dpi: output image DPI (default 150)

If you instead used per-cwnd files, you can aggregate them manually and pass a file
containing JSON lines as well.
"""

import argparse
import json
import matplotlib.pyplot as plt
import numpy as np

parser = argparse.ArgumentParser()
parser.add_argument('--input', '-i', default='cwnd_logs/rcv.jsonl')
parser.add_argument('--out', '-o', default='cwnd_goodput.png')
parser.add_argument('--title', default='cwnd vs goodput')
parser.add_argument('--start-cwnd', type=int, default=1)
parser.add_argument('--dpi', type=int, default=150)
args = parser.parse_args()

goods = []
with open(args.input) as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        try:
            j = json.loads(line)
        except json.JSONDecodeError:
            print('Skipping non-json line:', line[:200])
            continue
        # Accept either 'goodput_Bps' or 'goodput' as key
        if 'goodput_Bps' in j:
            g = float(j['goodput_Bps'])
        elif 'goodput' in j:
            g = float(j['goodput'])
        else:
            print('Line missing goodput fields, skipping:', j)
            continue
        goods.append(g)

if not goods:
    print('No goodput data found in', args.input)
    raise SystemExit(1)

n = len(goods)
cwnds = np.arange(args.start_cwnd, args.start_cwnd + n)
# Convert bytes/sec to Mbps
goodput_mbps = np.array(goods) * 8.0 / 1e6

plt.figure(figsize=(6,4))
plt.plot(cwnds, goodput_mbps, marker='o')
positions = cwnds
labels = [str(float(p/25)) for p in [1, 25, 50, 75, 100, 125, 150, 175, 200, 225, 250]]  # ['1','2',...,'10']
plt.xticks(positions, labels)
plt.xlabel('BPD')
plt.ylabel('Goodput (Mbps)')
plt.title(args.title)
plt.grid(alpha=0.3)
plt.xticks(cwnds)
plt.tight_layout()
plt.savefig(args.out, dpi=args.dpi)
print(f'Saved plot to {args.out} (showing {n} points).')

# also show interactive if running in terminal with display
try:
    plt.show()
except Exception:
    pass
