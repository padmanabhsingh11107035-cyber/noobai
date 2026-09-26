"""
"Connect to nearby devices": finds and pairs NOOB devices on the same Wi-Fi.

Only devices running the NOOB firmware answer, because they speak this small
text protocol over UDP (port 4210 on the device, 4211 on this PC):

  PC -> device   NOOB?DISCOVER                         device replies NOOB!DEVICE|name|mac|paired(0/1)|version
  PC -> device   NOOB?PAIRSTART                        device shows a 4-digit code on its screen, replies NOOB!CODE
  PC -> device   NOOB?PAIR|code|server_url|device_key  device replies NOOB!PAIRED|name|mac  or  NOOB!BADCODE
  PC -> device   NOOB?UNPAIR|device_key                device forgets this PC, replies NOOB!UNPAIRED
  device -> PC   NOOB?SERVER  (broadcast)              this PC replies NOOB!SERVER|http://<pc-ip>:5000/ask
"""

import socket
import threading
import time

DEVICE_PORT = 4210
SERVER_PORT = 4211


def local_ip(towards="8.8.8.8"):
    """This PC's address on the network that leads to `towards` (no data is actually sent)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((towards, 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def _udp_socket(timeout):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.settimeout(timeout)
    s.bind(("", 0))
    return s


def scan(seconds=2.5):
    """Broadcasts NOOB?DISCOVER and returns the NOOB devices that answer."""
    found = {}
    s = _udp_socket(0.3)
    ip = local_ip()
    targets = {"255.255.255.255", ip.rsplit(".", 1)[0] + ".255"}
    end = time.time() + seconds
    next_send = 0
    try:
        while time.time() < end:
            if time.time() >= next_send:                      # send 3 times: Wi-Fi can drop UDP packets
                for t in targets:
                    try:
                        s.sendto(b"NOOB?DISCOVER", (t, DEVICE_PORT))
                    except OSError:
                        pass
                next_send = time.time() + 0.8
            try:
                data, (addr, _) = s.recvfrom(512)
            except socket.timeout:
                continue
            parts = data.decode("utf-8", "replace").strip().split("|")
            if parts[0] == "NOOB!DEVICE" and len(parts) >= 5:
                found[parts[2]] = {"name": parts[1], "mac": parts[2], "ip": addr,
                                   "paired": parts[3] == "1", "version": parts[4]}
    finally:
        s.close()
    return list(found.values())


def send(ip, message, expect, seconds=3.0):
    """Sends one command to a device and waits for a reply starting with one of `expect`."""
    s = _udp_socket(0.5)
    end = time.time() + seconds
    try:
        while time.time() < end:
            s.sendto(message.encode("utf-8"), (ip, DEVICE_PORT))
            try:
                data, _ = s.recvfrom(512)
            except socket.timeout:
                continue
            reply = data.decode("utf-8", "replace").strip()
            if reply.split("|")[0] in expect:
                return reply
    finally:
        s.close()
    return None


def start_server_responder(port, log):
    """Answers NOOB devices that are looking for this PC (e.g. after its IP address changed)."""
    def run():
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("", SERVER_PORT))
        except OSError as e:
            log(f"!! Device finder not started (UDP {SERVER_PORT} busy: {e})")
            return
        while True:
            try:
                data, (addr, their_port) = s.recvfrom(512)
                if data.strip() == b"NOOB?SERVER":
                    url = f"http://{local_ip(addr)}:{port}/ask"
                    s.sendto(f"NOOB!SERVER|{url}".encode(), (addr, their_port))
            except OSError:
                time.sleep(0.5)
    threading.Thread(target=run, daemon=True).start()
