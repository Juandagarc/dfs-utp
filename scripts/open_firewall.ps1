# Run ONCE as Administrator on each Windows host so other hosts can connect.
# Coordinator uses 8000, nodes use 8001. Also allows ping (ICMP).
New-NetFirewallRule -DisplayName "DFS-UTP 8000-8001" -Direction Inbound -Protocol TCP -LocalPort 8000-8001 -Action Allow
New-NetFirewallRule -DisplayName "DFS-UTP ping" -Direction Inbound -Protocol ICMPv4 -IcmpType 8 -Action Allow
