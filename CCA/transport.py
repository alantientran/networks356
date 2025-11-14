import argparse
import json
from typing import Any, Dict, List, Optional, Tuple
import random
import socket
import time
import os

# Note: In this starter code, we annotate types where
# appropriate. While it is optional, both in python and for this
# course, we recommend it since it makes programming easier.

# The maximum size of the data contained within one packet
payload_size = 1200
# The maximum size of a packet including all the JSON formatting
packet_size = 1500

# Optional fixed cwnd in units of PACKETS (if set, overrides AIMD)
FIXED_CWND_PACKETS: Optional[float] = None


class Receiver:
    def __init__(self):
        # TODO: Initialize any variables you want here, like the receive buffer
        self.received_ranges = []
        self.rcv_buffer = {} # seq_num_start -> ending seq_num, data
        self.next_seq = 0

    def data_packet(self, seq_range: Tuple[int, int], data: str) -> Tuple[List[Tuple[int, int]], str]:
        '''This function is called whenever a data packet is
        received. `seq_range` is the range of sequence numbers
        received: It contains two numbers: the starting sequence
        number (inclusive) and ending sequence number (exclusive) of
        the data received. `data` is a binary string of length
        `seq_range[1] - seq_range[0]` representing the data.

        It should output the list of sequence number ranges to
        acknowledge and any data that is ready to be sent to the
        application. Note, data must be sent to the application
        _reliably_ and _in order_ of the sequence numbers. This means
        that if bytes in sequence numbers 0-10000 and 11000-15000 have
        been received, only 0-10000 must be sent to the application,
        since if we send the latter bytes, we will not be able to send
        bytes 10000-11000 in order when they arrive. The solution
        layer must hide hide all packet reordering and loss.

        The ultimate behavior of the program should be that the data
        sent by the sender should be stored exactly in the same order
        at the receiver in a file in the same directory. No gaps, no
        reordering. You may assume that our test cases only ever send
        printable ASCII characters (letters, numbers, punctuation,
        newline etc), so that terminal output can be used to debug the
        program.

        '''
        # TODO
        self.received_ranges = self.merge_range(self.received_ranges, seq_range)
        data_for_app = ""
        if seq_range[0] == self.next_seq:
            data_for_app += data
            self.next_seq = seq_range[1]
            
            # loop through rcv_buffer to find contiguous ranges that can be delivered
            while self.next_seq in self.rcv_buffer:
                next_packet = self.rcv_buffer[self.next_seq]
                data_for_app += next_packet[1]

                # remove packet from rcv_buffer b/c gets sent to app right after
                del self.rcv_buffer[self.next_seq]

                # set next_seq to the end of this current packet
                self.next_seq = next_packet[0]
        else:
            # when we have a gap and can't send anything
            self.rcv_buffer[seq_range[0]] = (seq_range[1], data)
        return (self.received_ranges, data_for_app)

    def merge_range(self, existing_ranges, new_range):
        '''
        Helper to merge a new range into the list of all existing ranges
        that the receiver has received.
        '''
        new_start, new_end = new_range
        merged = []
        i = 0
        # add all existing_ranges that end before [new_start,new_end)
        while i < len(existing_ranges) and existing_ranges[i][1] < new_start:
            merged.append(existing_ranges[i])
            i += 1
        # merge overlaps with [new_start,new_end)
        merged_start, merged_end = new_start, new_end
        while i < len(existing_ranges) and existing_ranges[i][0] <= merged_end:
            merged_start = min(merged_start, existing_ranges[i][0])
            merged_end = max(merged_end, existing_ranges[i][1])
            i += 1
        merged.append((merged_start, merged_end))
        # append the rest
        while i < len(existing_ranges):
            merged.append(existing_ranges[i])
            i += 1
        return merged

    def finish(self):
        '''Called when the sender sends the `fin` packet. You don't need to do
        anything in particular here. You can use it to check that all
        data has already been sent to the application at this
        point. If not, there is a bug in the code. A real solution
        stack will deallocate the receive buffer. Note, this may not
        be called if the fin packet from the sender is locked. You can
        read up on "TCP connection termination" to know more about how
        TCP handles this.

        '''
        print("Finished")


class Sender:
    def __init__(self, data_len: int):
        '''`data_len` is the length of the data we want to send. A real
        solution will not force the application to pre-commit to the
        length of data, but we are ok with it.'''
        self.data_len = data_len
        self.next_seq = 0
        self.sent_packets = {} # packet_id -> (start, end) for sent packets that have not yet been acknowledged
        self.acked_intervals = []
        self.sent_times = {} # packet_id -> last send time in seconds
        # RTT estimation (EWMA). None until first measurement.
        self.rtt_avg = None
        self.rtt_var = None
        # EWMA alpha/beta values (RFC-style defaults)
        self.rtt_alpha = 1.0 / 8.0
        self.rtt_beta = 1.0 / 4.0
        self.cwnd = float(payload_size) # Keep as float for fractional additive increments

    def timeout(self):
        '''Called when the sender times out.'''
        # On timeout we assume in-flight packets may have been lost.
        # Clear sent_packets so bytes will be re-allocated for sending starting from the first unacked byte.
        self.sent_packets = {}
        # Multiplicative decrease (half) on timeout/loss
        try:
            self.cwnd = max(float(payload_size), self.cwnd / 2.0)
        except Exception:
            self.cwnd = float(payload_size)
        if not self._is_all_acked():
            self.next_seq = self._first_unacked()

    def ack_packet(self, sacks: List[Tuple[int, int]], packet_id: int) -> int:
        '''Called every time we get an acknowledgment. The argument is a list
        of ranges of bytes that have been ACKed. Returns the number of
        payload bytes new that are no longer in flight, either because
        the packet has been acked (measured by the unique ID) or it
        has been assumed to be lost because of dupACKs. Note, this
        number is incremental. For example, if one 100-byte packet is
        ACKed and another 500-byte is assumed lost, we will return
        600, even if 1000s of bytes have been ACKed before this.'''
        newly_acked = 0
        # If we have a send timestamp for this packet id, use it to update RTT estimates
        send_ts = None
        if packet_id in self.sent_times:
            send_ts = self.sent_times.pop(packet_id)
        if send_ts is not None:
            now = time.time()
            measured_rtt = now - send_ts
            if measured_rtt < 0:
                measured_rtt = 0.0
            # Initialize EWMA on first measurement
            if self.rtt_avg is None:
                self.rtt_avg = measured_rtt
                # initialize variance to a reasonable value (half the RTT)
                self.rtt_var = measured_rtt / 2.0
            else:
                rtt_diff = abs(measured_rtt - self.rtt_avg)
                self.rtt_var = (1.0 - self.rtt_beta) * self.rtt_var + self.rtt_beta * rtt_diff
                self.rtt_avg = (1.0 - self.rtt_alpha) * self.rtt_avg + self.rtt_alpha * measured_rtt
        for s in sacks:
            start, end = s
            if start >= end:
                continue
            # Compute bytes in [start,end) that are not yet acked
            remaining = self._subtract_acked((start, end))
            for r in remaining:
                newly_acked += r[1] - r[0]
                self._insert_acked(r)

        # Remove any sent_packets that are fully ACKed
        for pid, rng in list(self.sent_packets.items()):
            if self._range_fully_acked(rng):
                del self.sent_packets[pid]

        # Additive increase: increase cwnd by 1 packet per RTT.
        # We implement per-ACK fractional increments so that across an RTT
        # the total increase is approximately `payload_size` bytes.
        if newly_acked > 0:
            try:
                # fraction of cwnd freed by this ACKs
                frac = float(newly_acked) / max(self.cwnd, 1.0)
                inc = payload_size * frac
                self.cwnd += inc
            except Exception:
                # keep cwnd same on unexpected errors
                self.cwnd = max(float(payload_size), getattr(self, 'cwnd', float(payload_size)))

        return newly_acked

    def send(self, packet_id: int) -> Optional[Tuple[int, int]]:
        '''Called just before we are going to send a data packet. Should
        return the range of sequence numbers we should send. If there
        are no more bytes to send, returns a zero range (i.e. the two
        elements of the tuple are equal). Returns None if there are no
        more bytes to send, and _all_ bytes have been
        acknowledged. Note: The range should not be larger than
        `payload_size` or contain any bytes that have already been
        acknowledged
        '''
        # If everything has been acknowledged, return None to indicate we're done
        if self._is_all_acked():
            return None

        # Advance next_seq past any already-acked bytes
        if self.next_seq < self.data_len and self._byte_acked(self.next_seq):
            self.next_seq = self._first_unacked()

        # If there are no bytes currently available to send (all allocated
        # but not yet acked), return a zero-range to indicate caller should
        # wait for ACKs or timeout.
        if self.next_seq >= self.data_len:
            return (0, 0)

        start = self.next_seq
        end = min(self.data_len, start + payload_size)

        self.sent_packets[packet_id] = (start, end)
        self.next_seq = end

        return (start, end)

    def record_send_time(self, packet_id: int) -> None:
        """Record timestamp when a packet (by id) was actually transmitted on the socket."""
        self.sent_times[packet_id] = time.time()

    def get_cwnd(self) -> int:
        # Return current congestion window in bytes (int).
        # If a fixed cwnd (in PACKETS) is set at module level, use it.
        # This allows external sweep scripts to evaluate constant cwnd values
        # without implementing a full CCA.
        global FIXED_CWND_PACKETS
        try:
            if FIXED_CWND_PACKETS is not None:
                # allow fractional packet counts, but return bytes
                return int(max(payload_size, int(FIXED_CWND_PACKETS * payload_size)))
        except Exception:
            pass
        return int(max(payload_size, int(self.cwnd)))
    
    def get_rto(self) -> float:
        # Conservative default until we have measured RTTs
        if self.rtt_avg is None or self.rtt_var is None:
            return 1.0
        rto = self.rtt_avg + 4.0 * self.rtt_var
        # enforce a small lower bound
        return max(0.01, rto)

    # Interval helper methods 
    def _insert_acked(self, interval: Tuple[int, int]) -> None:
        # Insert and merge into acked_intervals to keep list sorted and non-overlapping
        start, end = interval
        if start >= end:
            return
        new = []
        placed = False
        for a, b in self.acked_intervals:
            if b < start:
                new.append((a, b))
            elif end < a:
                if not placed:
                    new.append((start, end))
                    placed = True
                new.append((a, b))
            else:
                # Overlaps, merge
                start = min(start, a)
                end = max(end, b)
        if not placed:
            new.append((start, end))
        # sort just in case and assign
        new.sort()
        self.acked_intervals = new

    def _subtract_acked(self, interval: Tuple[int, int]) -> List[Tuple[int, int]]:
        # Return list of sub-intervals of `interval` that are not already acked
        start, end = interval
        if start >= end:
            return []
        remaining = []
        cur = start
        for a, b in self.acked_intervals:
            if b <= cur:
                continue
            if a >= end:
                break
            if a > cur:
                remaining.append((cur, min(a, end)))
            cur = max(cur, b)
            if cur >= end:
                break
        if cur < end:
            remaining.append((cur, end))
        return remaining

    def _range_fully_acked(self, interval: Tuple[int, int]) -> bool:
        start, end = interval
        # Check if [start,end) is fully covered by acked_intervals
        cur = start
        for a, b in self.acked_intervals:
            if b <= cur:
                continue
            if a > cur:
                return False
            cur = max(cur, b)
        return cur >= end

    def _byte_acked(self, b: int) -> bool:
        for a, c in self.acked_intervals:
            if a <= b < c:
                return True
            if a > b:
                return False
        return False

    def _first_unacked(self) -> int:
        # Find the first byte index that is not acked (0...data_len) (find first gap)
        cur = 0
        for a, b in self.acked_intervals:
            if cur < a:
                return cur
            cur = max(cur, b)
        return min(cur, self.data_len)

    def _is_all_acked(self) -> bool:
        # len(self.acked_intervals) == 1 means there is only one continuous interval
        # self.acked_intervals[0][0] == 0 means it starts from byte 0
        # self.acked_intervals[0][1] >= self.data_len means it covers all bytes
        return len(self.acked_intervals) == 1 and self.acked_intervals[0][0] == 0 and self.acked_intervals[0][1] >= self.data_len


def start_receiver(ip: str, port: int):
    '''Starts a receiver thread. For each source address, we start a new
    `Receiver` class. When a `fin` packet is received, we call the
    `finish` function of that class.

    We start listening on the given IP address and port. By setting
    the IP address to be `0.0.0.0`, you can make it listen on all
    available interfaces. A network interface is typically a device
    connected to a computer that interfaces with the physical world to
    send/receive packets. The WiFi and ethernet cards on personal
    computers are examples of physical interfaces.

    Sometimes, when you start listening on a port and the program
    terminates incorrectly, it might not release the port
    immediately. It might take some time for the port to become
    available again, and you might get an error message saying that it
    could not bind to the desired port. In this case, just pick a
    different port. The old port will become available soon. Also,
    picking a port number below 1024 usually requires special
    permission from the OS. Pick a larger number. Numbers in the
    8000-9000 range are conventional.

    Virtual interfaces also exist. The most common one is `localhost',
    which has the default IP address of `127.0.0.1` (a universal
    constant across most machines). The Mahimahi network emulator also
    creates virtual interfaces that behave like real interfaces, but
    really only emulate a network link in software that shuttles
    packets between different virtual interfaces. Use `ifconfig` in a
    terminal to find out what interfaces exist in your machine or
    inside a Mahimahi shell

    '''
    receivers: Dict[str, Receiver] = {}
    received_data = ''
    # Log file used by mm-throughput-graph: each line contains
    # <unix_time_seconds> <cumulative_bytes_received>
    # Allow overriding via environment variable so sweep scripts can
    # write separate logs per run.
    log_path = os.environ.get('MM_THROUGHPUT_LOG', 'mm_throughput.log')
    cumulative_bytes = 0
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server_socket:
        server_socket.bind((ip, port))
        log_file = open(log_path, 'a')

        while True:
            data, addr = server_socket.recvfrom(packet_size)
            if addr not in receivers:
                receivers[addr] = Receiver()

            received = json.loads(data.decode())
            if received["type"] == "data":
                # Format check. Real code will have much more
                # carefully designed checks to defend against
                # attacks. Can you think of ways to exploit this
                # transport layer and cause problems at the receiver?
                # This is just for fun. It is not required as part of
                # the assignment.
                assert type(received["seq"]) is list
                assert type(received["seq"][0]) is int and type(received["seq"][1]) is int
                assert type(received["payload"]) is str
                assert len(received["payload"]) <= payload_size

                # Deserialize the packet. Real transport layers use
                # more efficient and standardized ways of packing the
                # data. One option is to use protobufs (look it up)
                # instead of json. Protobufs can automatically design
                # a byte structure given the data structure. However,
                # for an internet standard, we usually want something
                # more custom and hand-designed.
                sacks, app_data = receivers[addr].data_packet(tuple(received["seq"]), received["payload"])
                # Note: we immediately write the data to file
                # receivers[addr][1].write(app_data)
                print(f"Received seq: {received['seq']}, id: {received['id']}, sending sacks: {sacks}")
                received_data += app_data # p3
                # Update cumulative bytes and write a timestamped sample for plotting
                if app_data:
                    try:
                        # app_data is a str of printable ASCII per assignment notes
                        cumulative_bytes += len(app_data)
                        log_file.write(f"{time.time():.6f} {cumulative_bytes}\n")
                        log_file.flush()
                    except Exception:
                        # If logging fails, continue without crashing the receiver
                        pass

                # Send the ACK
                server_socket.sendto(json.dumps({"type": "ack", "sacks": sacks, "id": received["id"]}).encode(), addr)
            elif received["type"] == "fin":
                receivers[addr].finish()

                try:
                    # attempt to close but guard in case already closed
                    if not log_file.closed:
                        log_file.close()
                except Exception:
                    pass
            else:
                assert False
        # Ensure log file is closed on normal exit as well
        try:
            if not log_file.closed:
                log_file.close()
        except Exception:
            pass


def start_sender(ip: str, port: int, data: str, recv_window: int, simloss: float):
    sender = Sender(len(data))

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client_socket:
        # So we can receive messages
        client_socket.connect((ip, port))

        # Number of bytes that we think are inflight. We are only
        # including payload bytes here, which is different from how
        # TCP does things
        inflight = 0
        packet_id = 0
        wait = False
        send_buf = [] # p3 code

        while True:
            # Ask sender for current congestion window (bytes)
            cwnd = sender.get_cwnd()
            # Do we have enough room in recv_window to send an entire
            # packet? Use payload_size (bytes of data) for inflight accounting
            # since `inflight` counts payload bytes.
            if inflight + payload_size <= min(recv_window, cwnd) and not wait:
                seq = sender.send(packet_id)
                got_fin_ack = False
                if seq is None:
                    # We are done sending
                    # print("#######send_buf#########: ", len(send_buf))
                    if send_buf:
                        random.shuffle(send_buf)
                        for p in send_buf:
                            client_socket.send(p)
                        send_buf = []
                    client_socket.send('{"type": "fin"}'.encode())
                    break

                elif seq[1] == seq[0]:
                    # No more packets to send until loss happens. Wait
                    wait = True
                    continue

                assert seq[1] - seq[0] <= payload_size
                assert seq[1] <= len(data)
                print(f"Sending seq: {seq}, id: {packet_id}")

                # Simulate random loss before sending packets
                if random.random() < simloss:
                    pass
                else:
                    # Send the packet
                    client_socket.send(
                        json.dumps(
                            {"type": "data", "seq": seq, "id": packet_id, "payload": data[seq[0]:seq[1]]}
                        ).encode()
                    )
                    # record the actual send time for RTT measurement
                    sender.record_send_time(packet_id)

                inflight += seq[1] - seq[0]
                packet_id += 1

            else:
                wait = False
                # Wait for ACKs
                try:
                    rto = sender.get_rto()
                    client_socket.settimeout(rto)
                    received_bytes = client_socket.recv(packet_size)
                    received = json.loads(received_bytes.decode())
                    assert received["type"] == "ack"

                    print(f"Got ACK sacks: {received['sacks']}, id: {received['id']}")
                    if random.random() < simloss:
                        print("Dropped ack!")
                        continue


                    inflight = max(0, inflight - sender.ack_packet(received["sacks"], received["id"]))
                    assert inflight >= 0
                except socket.timeout:
                    inflight = 0
                    print("Timeout")
                    sender.timeout()


def main():
    parser = argparse.ArgumentParser(description="Transport assignment")
    parser.add_argument("role", choices=["sender", "receiver"], help="Role to play: 'sender' or 'receiver'")
    parser.add_argument("--ip", type=str, required=True, help="IP address to bind/connect to")
    parser.add_argument("--port", type=int, required=True, help="Port number to bind/connect to")
    parser.add_argument("--sendfile", type=str, required=False, help="If role=sender, the file that contains data to send")

    parser.add_argument("--recv_window", type=int, default=15000000, help="Receive window size in bytes")

    parser.add_argument("--simloss", type=float, default=0.0, help="Simulate packet loss. Provide the fraction of packets (0-1) that should be randomly dropped")
    parser.add_argument("--fixed_cwnd_packets", type=float, default=None, help="If set, override congestion control and use a fixed cwnd (in packets) for the sender")
    args = parser.parse_args()

    if args.role == "receiver":
        start_receiver(args.ip, args.port)
    else:
        # If the user provided a fixed cwnd, set the module-level variable.
        global FIXED_CWND_PACKETS
        if args.fixed_cwnd_packets is not None:
            try:
                FIXED_CWND_PACKETS = float(args.fixed_cwnd_packets)
            except Exception:
                FIXED_CWND_PACKETS = None

        if args.sendfile is None:
            print("No file to send")
            return

        with open(args.sendfile, 'r') as f:
            data = f.read()
            start_sender(args.ip, args.port, data, args.recv_window, args.simloss)


if __name__ == "__main__":
    main()
