#!/usr/bin/env python3
"""subnet.py — VLSM addressing plans and subnet facts, with the ipaddress module.

    plan  Split a parent IPv4 network into subnets sized for host counts
          (largest first, each aligned on its own size).
    info  Everything about one address/prefix: network, mask, wildcard,
          broadcast, usable range and the kind of address (IPv4 or IPv6).

Usage:
    python3 subnet.py plan 192.168.10.0/24 100 50 20 2 --names users,servers,printers,wan
    python3 subnet.py plan 10.0.0.0/22 500 120 --json
    python3 subnet.py plan 10.0.0.0/30 2 1 --allow-31
    python3 subnet.py info 172.16.5.130/26
    python3 subnet.py info 2001:db8:abcd:12::1/64 --json

Host counts are the addresses a subnet needs: count the gateway, servers and
printers too, and add room for growth. A subnet of h hosts gets the smallest
prefix p with 2^(32-p) - 2 >= h, down to /30. With --allow-31, a request for
2 gets a /31 (point-to-point, RFC 3021) and a request for 1 a /32.

Exit codes: 0 ok, 1 the plan does not fit in the parent network, 2 bad input.
Standard library only; no network access; writes nothing.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import math
import sys


class InputError(ValueError):
    pass


def _prefix_for(hosts: int, allow_31: bool) -> int:
    if allow_31 and hosts == 1:
        return 32
    if allow_31 and hosts == 2:
        return 31
    for p in range(30, -1, -1):
        if 2 ** (32 - p) - 2 >= hosts:
            return p
    raise InputError(f"{hosts} hosts do not fit in any IPv4 subnet")


def _usable(net: ipaddress.IPv4Network) -> tuple[str, str, int, str]:
    """(first usable, last usable, count, broadcast) — RFC 3021 aware."""
    if net.prefixlen == 32:
        a = str(net.network_address)
        return a, a, 1, "none (/32)"
    if net.prefixlen == 31:
        return (str(net.network_address), str(net.broadcast_address), 2,
                "none (/31, RFC 3021)")
    return (str(net.network_address + 1), str(net.broadcast_address - 1),
            net.num_addresses - 2, str(net.broadcast_address))


def _kind(addr) -> str:
    if addr.is_unspecified:
        return "unspecified"
    if addr.is_loopback:
        return "loopback"
    if addr.is_link_local:
        return "link-local"
    if addr.is_multicast:
        return "multicast"
    if addr.version == 4:
        if addr in ipaddress.ip_network("100.64.0.0/10"):
            return "shared address space (RFC 6598, carrier-grade NAT)"
        for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"):
            if addr in ipaddress.ip_network(n):
                return f"private (RFC 1918, {n})"
        for n in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24"):
            if addr in ipaddress.ip_network(n):
                return "documentation (RFC 5737)"
    else:
        if addr in ipaddress.ip_network("fc00::/7"):
            return "unique local (ULA, fc00::/7)"
        if addr in ipaddress.ip_network("2001:db8::/32"):
            return "documentation (RFC 3849)"
    if addr.is_reserved:
        return "reserved"
    if addr.is_private:
        return "private / special-purpose"
    if addr.is_global:
        return "global (public)"
    return "special-purpose"


def plan(parent_text: str, hosts: list[int], names: list[str], allow_31: bool) -> dict:
    try:
        parent = ipaddress.ip_network(parent_text, strict=False)
    except ValueError as e:
        raise InputError(f"{parent_text!r} is not a network: {e}") from None
    if parent.version != 4:
        raise InputError("plan is for IPv4; in IPv6 give each LAN its own /64")
    notes = []
    if str(parent) != parent_text.strip():
        notes.append(f"{parent_text} has host bits set; using the network {parent}")
    if not hosts:
        raise InputError("give at least one host count")
    for h in hosts:
        if h < 1:
            raise InputError(f"host counts must be at least 1 (got {h})")
    if names and len(names) != len(hosts):
        raise InputError(f"{len(names)} names for {len(hosts)} host counts")
    names = names or [f"LAN{i + 1}" for i in range(len(hosts))]
    req = [{"index": i, "name": names[i], "hosts": h, "prefix": _prefix_for(h, allow_31)}
           for i, h in enumerate(hosts)]
    order = sorted(req, key=lambda r: (r["prefix"], r["index"]))   # largest first, stable
    start, end = int(parent.network_address), int(parent.broadcast_address)
    cursor = start
    subnets, need = [], 0
    for r in order:
        size = 2 ** (32 - r["prefix"])
        need += size
        cursor = -(-cursor // size) * size          # align up on the block size
        if cursor + size - 1 > end:
            total = sum(2 ** (32 - x["prefix"]) for x in req)
            fit = 32 - math.ceil(math.log2(total))
            raise OverflowError(f"the plan needs {total} addresses ({len(req)} subnets) and "
                                f"{parent} has {parent.num_addresses}: use at least a /{fit} "
                                f"parent, or fewer hosts")
        net = ipaddress.ip_network((cursor, r["prefix"]))
        first, last, usable, bcast = _usable(net)
        subnets.append({"name": r["name"], "requested_hosts": r["hosts"], "network": str(net),
                        "netmask": str(net.netmask), "first_usable": first, "last_usable": last,
                        "broadcast": bcast, "usable_hosts": usable, "waste": usable - r["hosts"]})
        cursor += size
    free = []
    if cursor <= end:
        free = [str(n) for n in ipaddress.summarize_address_range(
            ipaddress.ip_address(cursor), ipaddress.ip_address(end))]
    return {"parent": str(parent), "subnets": subnets, "used_addresses": need,
            "free_addresses": end - cursor + 1 if cursor <= end else 0, "free_blocks": free,
            "notes": notes}


def info(text: str) -> dict:
    try:
        iface = ipaddress.ip_interface(text.strip())
    except ValueError as e:
        raise InputError(f"{text!r} is not an address/prefix: {e}") from None
    net, addr = iface.network, iface.ip
    out = {"address": str(addr), "version": addr.version, "network": str(net),
           "prefix_length": net.prefixlen, "kind": _kind(addr), "addresses": net.num_addresses}
    if "/" not in text:
        out["note"] = f"no prefix given: /{net.prefixlen} assumed"
    if addr.version == 4:
        first, last, usable, bcast = _usable(net)
        out.update(netmask=str(net.netmask), wildcard=str(net.hostmask), broadcast=bcast,
                   first_usable=first, last_usable=last, usable_hosts=usable)
        if net.prefixlen < 31 and addr == net.broadcast_address:
            out["warning"] = f"{addr} is the broadcast address of {net}: it cannot be given to a host"
    else:
        out.update(first_address=str(net.network_address), last_address=str(net.broadcast_address),
                   note_ipv6="IPv6 has no broadcast; a LAN is normally a /64")
    return out


def _print_plan(r: dict) -> None:
    for n in r["notes"]:
        print(f"note: {n}")
    print(f"VLSM plan in {r['parent']}")
    cols = ("name", "requested_hosts", "network", "netmask", "first_usable", "last_usable",
            "broadcast", "usable_hosts", "waste")
    heads = ("Name", "Hosts", "Network", "Mask", "First", "Last", "Broadcast", "Usable", "Waste")
    rows = [[str(s[c]) for c in cols] for s in r["subnets"]]
    widths = [max(len(h), *(len(x[i]) for x in rows)) for i, h in enumerate(heads)]
    print("  ".join(h.ljust(w) for h, w in zip(heads, widths)))
    for x in rows:
        print("  ".join(v.ljust(w) for v, w in zip(x, widths)))
    free = ", ".join(r["free_blocks"]) or "none"
    print(f"Used {r['used_addresses']} addresses; free {r['free_addresses']}: {free}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="subnet.py", description="VLSM addressing plans and subnet facts.",
                                 epilog="Exit codes: 0 ok, 1 plan does not fit, 2 bad input.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="split an IPv4 network into subnets sized for host counts")
    p.add_argument("parent", help="parent network, e.g. 192.168.10.0/24")
    p.add_argument("hosts", nargs="+", type=int, help="addresses each subnet needs (gateway included)")
    p.add_argument("--names", default="", help="comma-separated subnet names, in the order of the counts")
    p.add_argument("--allow-31", action="store_true", help="2 hosts -> /31 (RFC 3021), 1 host -> /32")
    p.add_argument("--json", action="store_true", help="print one JSON object")
    i = sub.add_parser("info", help="facts about one address/prefix (IPv4 or IPv6)")
    i.add_argument("address", help="e.g. 172.16.5.130/26 or 2001:db8::1/64")
    i.add_argument("--json", action="store_true", help="print one JSON object")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "plan":
            names = [n.strip() for n in a.names.split(",")] if a.names.strip() else []
            r = plan(a.parent, a.hosts, names, a.allow_31)
            if a.json:
                print(json.dumps(r, indent=1))
            else:
                _print_plan(r)
            return 0
        r = info(a.address)
        if a.json:
            print(json.dumps(r, indent=1))
        else:
            for k, v in r.items():
                print(f"{k.replace('_', ' '):<16} {v}")
        return 0
    except OverflowError as e:
        if getattr(a, "json", False):
            print(json.dumps({"error": str(e), "fits": False}))
        print(f"subnet.py: does not fit: {e}", file=sys.stderr)
        return 1
    except InputError as e:
        print(f"subnet.py: error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
