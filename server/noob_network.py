"""
Faster internet connections for NOOB.

Some networks (phone hotspots especially) hand out IPv6 addresses that do not actually work. Browsers try IPv6 and
IPv4 at the same time, but Python tries the addresses one after another and waits for each dead IPv6 address to time
out first (Google's Gemini alone lists 8 of them), so a single connection could take a minute before it tried IPv4.

prefer_ipv4() makes every connection in the NOOB server try the IPv4 addresses first. IPv6 is still used when
there is no IPv4 address, so nothing stops working on an IPv6-only network.
"""

import socket

_original_getaddrinfo = socket.getaddrinfo


def _ipv4_first(*args, **kwargs):
    results = _original_getaddrinfo(*args, **kwargs)
    return sorted(results, key=lambda info: info[0] != socket.AF_INET)      # stable: keeps each family's order


def prefer_ipv4():
    if socket.getaddrinfo is not _ipv4_first:                               # only once
        socket.getaddrinfo = _ipv4_first
