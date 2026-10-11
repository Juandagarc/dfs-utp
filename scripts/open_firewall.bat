@echo off
REM Run ONCE from a CMD opened as Administrator. Allows ports 8000-8001, 8080 and ping.
netsh advfirewall firewall add rule name="DFS-UTP 8000-8001" dir=in action=allow protocol=TCP localport=8000-8001
netsh advfirewall firewall add rule name="DFS-UTP 8080" dir=in action=allow protocol=TCP localport=8080
netsh advfirewall firewall add rule name="DFS-UTP ping" dir=in action=allow protocol=icmpv4:8,any
echo Firewall rules added.
