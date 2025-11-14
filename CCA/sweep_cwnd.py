#!/usr/bin/env python3
"""
Sweep cwnd (in packets) from 1..max_factor*BDP and run experiments collecting goodput
This script assumes there is an executable/script `CCA/run_experiments.py` in the repo
that accepts the same flags shown below. It will call that script repeatedly, setting
--fixed_cwnd_packets for each run and setting MM_THROUGHPUT_LOG so each run writes
its own log file.

By default it attempts to plot results with matplotlib; if matplotlib is missing it
writes `results.csv` with columns: cwnd_packets, throughput_mbps, total_unique_bytes.

Assumptions:
- payload_size is 1200 bytes (the transport uses this value internally). BDP is
  computed as: BDP_bytes = (link_rate_mbps * 1e6 / 8) * (base_delay_ms/1000). This
  uses base_delay_ms as the RTT in ms; if your emulator uses one-way delay, multiply
  accordingly when invoking this script.

"""
import argparse
import math
import os
import subprocess
import sys
import time

PAYLOAD_SIZE = 1200


def parse_mm_log(path):
    # mm_throughput.log format: '<unix_time_seconds> <cumulative_bytes>' per line
    times = []
    bytes_vals = []
    try:
        with open(path, 'r') as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) < 2:
                    continue
                t = float(parts[0])
                b = int(float(parts[1]))
                times.append(t)
                bytes_vals.append(b)
    except FileNotFoundError:
        return None
    if not times:
        return None
    return times, bytes_vals


def compute_throughput(times, bytes_vals):
    # compute throughput (Mbps) from first to last sample
    if len(times) < 2:
        return 0.0, bytes_vals[-1] if bytes_vals else 0
    dt = times[-1] - times[0]
    if dt <= 0:
        return 0.0, bytes_vals[-1]
    dbytes = bytes_vals[-1] - bytes_vals[0]
    mbps = (dbytes * 8.0) / dt / 1e6
    return mbps, dbytes


def main():
    parser = argparse.ArgumentParser(description="Sweep cwnd (in packets) and collect goodput")
    parser.add_argument('--link_rate_mbps', type=float, required=True)
    parser.add_argument('--base_delay_ms', type=float, required=True)
    parser.add_argument('--sendfile', type=str, required=True)
    parser.add_argument('--simloss', type=float, default=0.0)
    parser.add_argument('--max_factor', type=float, default=10.0,
                        help='Max multiple of BDP to sweep up to (default 10)')
    parser.add_argument('--out_dir', type=str, default='sweep_logs', help='Directory for logs/outputs')
    parser.add_argument('--run_cmd', type=str, default='python3 run_experiments.py',
                        help='Command to run the experiment (should accept the same flags).')
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    # compute BDP in bytes (assumes base_delay_ms is RTT in ms)
    bdp_bytes = (args.link_rate_mbps * 1e6 / 8.0) * (args.base_delay_ms / 1000.0)
    bdp_packets = max(1, int(math.ceil(bdp_bytes / PAYLOAD_SIZE)))
    max_packets = max(1, int(math.ceil(args.max_factor * bdp_packets)))

    print(f"BDP ~ {bdp_bytes:.1f} bytes = {bdp_packets} packets; sweeping 1..{max_packets}")

    results = []
    # Use transport.py directly: start receiver (writes mm log) then run sender with fixed cwnd
    parser_ip = '127.0.0.1'
    parser_port = 9000
    for cwnd_p in range(1, max_packets + 1):
        log_path = os.path.join(args.out_dir, f"mm_throughput_{cwnd_p}.log")
        # Ensure old log removed
        try:
            if os.path.exists(log_path):
                os.remove(log_path)
        except Exception:
            pass

        env = os.environ.copy()
        env['MM_THROUGHPUT_LOG'] = log_path

        # Start receiver as a separate process which will write the mm log
        recv_cmd = [sys.executable, 'transport.py', 'receiver', '--ip', parser_ip, '--port', str(parser_port)]
        print(f"Starting receiver -> {' '.join(recv_cmd)} (log -> {log_path})")
        try:
            recv_proc = subprocess.Popen(recv_cmd, env=env)
        except Exception as e:
            print(f"Failed to start receiver: {e}")
            break

        # Give receiver a moment to bind
        time.sleep(0.2)

        # Run sender in the foreground; it will connect to the receiver and exit when done
        send_cmd = [sys.executable, 'transport.py', 'sender', '--ip', parser_ip, '--port', str(parser_port), '--sendfile', args.sendfile, '--simloss', str(args.simloss), '--fixed_cwnd_packets', str(cwnd_p)]
        print(f"Running sender -> {' '.join(send_cmd)}")
        try:
            ret = subprocess.run(send_cmd, env=env)
            if ret.returncode != 0:
                print(f"Sender failed for cwnd={cwnd_p} (exit {ret.returncode}).")
        except KeyboardInterrupt:
            print('Interrupted by user')
            # Try to clean up receiver
            try:
                recv_proc.terminate()
            except Exception:
                pass
            break

        # Wait for receiver to exit (it should exit after receiving fin). Give it a short timeout
        try:
            recv_proc.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            # If receiver didn't exit, terminate it
            try:
                recv_proc.terminate()
            except Exception:
                pass

        # Wait briefly for receiver to flush logfile
        time.sleep(0.1)

        parsed = parse_mm_log(log_path)
        if parsed is None:
            print(f"No log produced for cwnd={cwnd_p} at {log_path}")
            continue
        times, bytes_vals = parsed
        mbps, unique_bytes = compute_throughput(times, bytes_vals)
        print(f"cwnd={cwnd_p} pkts -> {mbps:.3f} Mbps over {len(times)} samples ({unique_bytes} unique bytes)")
        results.append((cwnd_p, mbps, unique_bytes))

    # Write CSV
    csv_path = os.path.join(args.out_dir, 'results.csv')
    with open(csv_path, 'w') as f:
        f.write('cwnd_packets,throughput_mbps,unique_bytes\n')
        for r in results:
            f.write(f"{r[0]},{r[1]:.6f},{r[2]}\n")

    print(f"Wrote results to {csv_path}")

    # Try to plot using matplotlib if available
    try:
        import matplotlib.pyplot as plt
        xs = [r[0] for r in results]
        ys = [r[1] for r in results]
        plt.figure(figsize=(8,4))
        plt.plot(xs, ys, marker='o')
        plt.xlabel('cwnd (packets)')
        plt.ylabel('Goodput (Mbps)')
        plt.title(f'Goodput vs cwnd (link {args.link_rate_mbps} Mbps, delay {args.base_delay_ms} ms)')
        plt.grid(True)
        out_png = os.path.join(args.out_dir, 'cwnd_vs_goodput.png')
        plt.savefig(out_png, dpi=150)
        print(f"Saved plot to {out_png}")
    except Exception:
        print('matplotlib not available; results.csv can be plotted with your preferred tool (or mm-throughput-graph if you adapt logs).')


if __name__ == '__main__':
    main()
