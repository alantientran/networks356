# mm-throughput logging and visualization

This README explains how the receiver stores throughput logs and how to visualize them with `mm-throughput-graph`.

What I changed
- The receiver (`CCA/transport.py`) now appends timestamped cumulative bytes to `mm_throughput.log` in the current working directory.
- Each line in `mm_throughput.log` has the format:

  <unix_time_seconds> <cumulative_bytes>

  Example:
  1600000000.123456 1024

How to run (CloudLab / two nodes)
1. On the receiver node, run:

```zsh
python3 CCA/transport.py receiver --ip 0.0.0.0 --port 9000
```

This creates/updates `mm_throughput.log` in the current directory.

2. On the sender node, run (example):

```zsh
python3 CCA/transport.py sender --ip <receiver-ip> --port 9000 --sendfile file_to_send.txt
```

3. After or while the transfer runs, convert the cumulative log to per-interval throughput samples using the helper script (below) which outputs `mm_throughput_samples.txt`.

```zsh
python3 CCA/convert_mm_log.py mm_throughput.log mm_throughput_samples.txt
```

The output file has lines: `<time_seconds> <throughput_Mbps>` (time is the center/time of the interval used to compute throughput).

4. Visualize with `mm-throughput-graph` (if installed). Many versions of `mm-throughput-graph` accept a two-column whitespace-separated file with time and throughput in Mbps. Example invocation:

```zsh
mm-throughput-graph mm_throughput_samples.txt
```

If `mm-throughput-graph` expects a different column order or units, the helper script can be adapted.

Notes and next steps
- I only added receiver-side logging (cumulative bytes). If you'd like sender-side cwnd/rtt logging, I can add that too.
- If you have an expected input format for `mm-throughput-graph`, tell me and I'll adapt the converter to match it exactly.
