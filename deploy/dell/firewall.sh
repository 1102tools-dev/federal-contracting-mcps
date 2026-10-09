#!/usr/bin/env bash
# Lets the MCP containers (compose network 172.31.250.0/24) reach the
# internet but not the LAN (cameras, router, NAS), other Docker networks, or
# services on govnode itself. Idempotent; mcp-origin-firewall.service reruns
# it whenever Docker starts.
set -euo pipefail
NET=172.31.250.0/24

iptables -N MCP-ORIGIN 2>/dev/null || iptables -F MCP-ORIGIN
iptables -A MCP-ORIGIN -d "$NET" -j RETURN
iptables -A MCP-ORIGIN -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
for private in 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 100.64.0.0/10 169.254.0.0/16 224.0.0.0/4; do
  iptables -A MCP-ORIGIN -d "$private" -j DROP
done
# Routed traffic (LAN, other bridges, internet) passes DOCKER-USER.
iptables -C DOCKER-USER -s "$NET" -j MCP-ORIGIN 2>/dev/null || iptables -I DOCKER-USER -s "$NET" -j MCP-ORIGIN
# Traffic to any of govnode's own addresses is INPUT, not FORWARD.
iptables -C INPUT -s "$NET" -m conntrack --ctstate NEW -j DROP 2>/dev/null \
  || iptables -I INPUT -s "$NET" -m conntrack --ctstate NEW -j DROP
