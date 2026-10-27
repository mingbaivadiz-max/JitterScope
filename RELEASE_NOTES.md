# JitterScope 2.0 beta

Free Windows network monitor for gamers by **SanyLok**.

- ICMP and optional TCP latency measurements.
- Parallel checks of the target, gateway, control address and selected diagnostic regions.
- Jitter, packet loss/timeouts, traffic and latency graphs.
- Compact panel: double-click the title or press Ctrl+M.
- Connection profiles, local session history, CSV/HTML reports and optional notifications.
- DNS cache clearing and confirmed termination of selected background applications.

## Download and run

Download `JitterScope-2.0.zip`, extract it and launch `JitterScope.exe`. Windows x64; Python is not needed for the packaged application. The interface is currently in Russian.

## Beta limitations

The EXE is unsigned. Local checks and 66 automated tests have passed; testing on additional computers and long sessions is still needed. Windows 10 compatibility has not been verified on a separate Windows 10 machine. ICMP/TCP measurements are diagnostic and may differ from in-game latency. Some diagnostic addresses block ICMP or may change. Per-process bandwidth is not measured. The app stores history locally and does not send it to the developer.

## License

Copyright (C) 2026 SanyLok. JitterScope source code: GPL-3.0-only; see LICENSE. Third-party components retain their own licenses. Source code and build instructions accompany this beta. No paid edition is planned.
