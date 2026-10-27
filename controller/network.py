# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 SanyLok
from __future__ import annotations
import ctypes
import logging
import socket
import struct
import sys
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import psutil
from icmplib import ping, SocketPermissionError
from PyQt6.QtCore import QThread, pyqtSignal
from .model import Sample, summarize, diagnostic_hint, WINDOW, CONTROL_ADDRESS
LOG = logging.getLogger('usb_net.network')
TIMEOUT = .9
INTERVAL = 1.0
_icmp_api = None
_icmp_api_lock = threading.Lock()
def get_icmp_api():
    """Lazy module cache: configure signatures once, including across workers."""
    global _icmp_api
    with _icmp_api_lock:
        if _icmp_api is None:
            dll = ctypes.WinDLL("iphlpapi", use_last_error=True)
            dll.IcmpCreateFile.argtypes = []
            dll.IcmpCreateFile.restype = ctypes.c_void_p
            dll.IcmpCloseHandle.argtypes = [ctypes.c_void_p]
            dll.IcmpCloseHandle.restype = ctypes.c_int
            dll.IcmpSendEcho2Ex.argtypes = [
                ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_ushort,
                ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
            ]
            dll.IcmpSendEcho2Ex.restype = ctypes.c_uint32
            dll.GetBestRoute.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)]
            dll.GetBestRoute.restype = ctypes.c_uint32
            dll.GetIpAddrTable.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32), ctypes.c_int]
            dll.GetIpAddrTable.restype = ctypes.c_uint32
            _icmp_api = dll
        return _icmp_api



def find_gateway(source=None, destination=CONTROL_ADDRESS):
    """Next hop toward the control host; never substitute an unrelated NIC."""
    if sys.platform != "win32":
        raise RuntimeError("Автоопределение шлюза доступно в Windows")
    dll = get_icmp_api()
    src = struct.unpack("=I", socket.inet_aton(source))[0] if source else 0
    dst = struct.unpack("=I", socket.inet_aton(destination))[0]
    row = (ctypes.c_uint32 * 14)()  # MIB_IPFORWARDROW
    code = dll.GetBestRoute(dst, src, row)
    if code:
        raise OSError(code, "Нет маршрута к контрольному узлу")
    if source:
        size = ctypes.c_uint32(0)
        code = dll.GetIpAddrTable(None, ctypes.byref(size), False)
        if code not in (0, 122) or not size.value:
            raise OSError(code, "Не удалось определить индекс адаптера")
        buf = ctypes.create_string_buffer(size.value)
        code = dll.GetIpAddrTable(buf, ctypes.byref(size), False)
        if code:
            raise OSError(code, "Не удалось прочитать адреса адаптеров")
        count = struct.unpack_from("=I", buf.raw)[0]
        indexes = [struct.unpack_from("=II", buf.raw, 4 + i * 24)[1]
                   for i in range(count) if struct.unpack_from("=I", buf.raw, 4 + i * 24)[0] == src]
        if row[4] not in indexes:
            raise RuntimeError("Лучший маршрут Windows использует другой адаптер; шлюз не подменяется")
    if row[3] == 0:
        raise RuntimeError("У маршрута нет отдельного шлюза (прямое подключение или VPN)")
    return socket.inet_ntoa(struct.pack("=I", row[3]))



def windows_echo(address, source=None, timeout=TIMEOUT):
    """Windows fallback; each probe owns and closes its own handle/buffers.

    Read only the initial DWORDs shared by ICMP_ECHO_REPLY/REPLY32.
    """
    dll = get_icmp_api()
    handle = dll.IcmpCreateFile()
    if handle == ctypes.c_void_p(-1).value or handle is None:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        data = ctypes.create_string_buffer(b"usb-net-monitor")
        reply = ctypes.create_string_buffer(512)
        src = struct.unpack("=I", socket.inet_aton(source))[0] if source else 0
        dst = struct.unpack("=I", socket.inet_aton(address))[0]
        count = dll.IcmpSendEcho2Ex(handle, None, None, None, src, dst, data, len(data) - 1,
                                   None, reply, len(reply), int(timeout * 1000))
        status = struct.unpack_from("=I", reply.raw, 4)[0] if count else ctypes.get_last_error()
        if status == 11010:  # IP_REQ_TIMED_OUT
            return Sample(None)
        if status:
            raise OSError(status, f"Windows ICMP: код {status} (маршрут, адаптер или доступ)")
        if not count:
            raise OSError("Windows ICMP не вернул ответ")
        return Sample(float(struct.unpack_from("=I", reply.raw, 8)[0]))
    finally:
        dll.IcmpCloseHandle(handle)



def tcp_probe(address, source=None, port=443):
    """Connect and immediately close; no TLS, HTTP, or game payload is sent."""
    try:
        if not 1 <= port <= 65535:
            raise ValueError("TCP-порт должен быть от 1 до 65535")
        started = time.perf_counter()
        with socket.create_connection((address, port), timeout=TIMEOUT,
                                      source_address=(source, 0) if source else None):
            elapsed = (time.perf_counter() - started) * 1000
        return Sample(elapsed)
    except TimeoutError:
        return Sample(None)
    except ConnectionRefusedError:
        return Sample(None, f"TCP {port}: соединение отклонено. Порт закрыт или блокируется.")
    except Exception as exc:
        LOG.debug("TCP probe failed", exc_info=True)
        return Sample(None, f"TCP {port}: {type(exc).__name__}: {exc}")



def probe(address, source=None, mode="icmp", port=443):
    if mode == "tcp":
        return tcp_probe(address, source, port)
    if mode != "icmp":
        return Sample(None, "Неизвестный режим измерения")
    try:
        try:
            host = ping(address, count=1, timeout=TIMEOUT, source=source, privileged=False)
            return Sample(host.rtts[0] if host.is_alive else None)
        except SocketPermissionError:
            if sys.platform == "win32":
                return windows_echo(address, source)
            raise
    except Exception as exc:
        LOG.debug("Probe failed", exc_info=True)
        return Sample(None, f"{type(exc).__name__}: {exc}")



def adapter_source(adapter):
    if not adapter:
        return None
    stats = psutil.net_if_stats().get(adapter)
    if not stats or not stats.isup:
        raise RuntimeError("Выбранный адаптер отключён. Обновите список или выберите другой.")
    for addr in psutil.net_if_addrs().get(adapter, []):
        if addr.family == socket.AF_INET and not addr.address.startswith("169.254."):
            return addr.address
    raise RuntimeError("У выбранного адаптера нет рабочего IPv4-адреса.")



def traffic_delta(before, after, elapsed):
    if before is None or after is None or elapsed <= 0:
        return None
    received = after.bytes_recv - before.bytes_recv
    sent = after.bytes_sent - before.bytes_sent
    if received < 0 or sent < 0:
        return None
    return received / elapsed / 1024, sent / elapsed / 1024



class NetworkWorker(QThread):
    updated = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._config = (0, "1.1.1.1", None, "icmp", 443, "", ())

    def configure(self, address, adapter, mode="icmp", port=443, target_error="", extras=None):
        with self._lock:
            generation = self._config[0] + 1
            extras = self._config[6] if extras is None else tuple(extras)
            self._config = generation, address, adapter, mode, port, target_error, extras
        self._wake.set()
        return generation

    def request_stop(self):
        self._stop.set()
        self._wake.set()

    def set_target_error(self, message):
        with self._lock:
            _, address, adapter, mode, port, _, extras = self._config
        return self.configure(address, adapter, mode, port, message, extras)

    def set_extras(self, extras):
        if len(extras) > 5:
            raise ValueError('Можно сравнивать до пяти дополнительных узлов')
        with self._lock:
            _, address, adapter, mode, port, error, _ = self._config
        return self.configure(address, adapter, mode, port, error, extras)

    def run(self):
        histories, history_keys, previous_errors = {}, {}, {}
        previous = None
        previous_time = None
        gateway = None
        gateway_error = ""
        route_checked = -100.0
        last_source = object()
        route_key = None
        # Numeric destinations only. UI resolves all hostnames asynchronously.
        with ThreadPoolExecutor(max_workers=8, thread_name_prefix="net-probe") as pool:
            while not self._stop.is_set():
                self._wake.clear()
                with self._lock:
                    generation, address, adapter, mode, port, target_error, extras = self._config
                control = '8.8.8.8' if address == CONTROL_ADDRESS else CONTROL_ADDRESS
                started = time.monotonic()
                futures, results = {}, {}
                destinations = {'target': address or '—', 'control': control}
                protocols = {'target': mode, 'control': 'icmp', 'gateway': 'icmp'}
                ports = {'target': port, 'control': None, 'gateway': None}
                try:
                    source = adapter_source(adapter)
                    if (source, adapter) != last_source:
                        histories.clear()
                        history_keys.clear()
                        previous = previous_time = None
                        route_checked = -100.0
                        last_source = (source, adapter)
                    if route_key != (source, control) or started - route_checked >= 10:
                        old_gateway = gateway
                        try:
                            gateway, gateway_error = find_gateway(source, destination=control), ""
                        except Exception as exc:
                            gateway, gateway_error = None, str(exc)
                        if old_gateway != gateway:
                            histories.clear()
                            history_keys.clear()
                        route_checked = started
                        route_key = (source, control)
                    if address is not None:
                        futures["target"] = pool.submit(probe, address, source, mode=mode, port=port)
                    else:
                        results['target'] = Sample(None, target_error or 'DNS: определение IPv4 выбранной цели…')
                    futures["control"] = pool.submit(probe, control, source, mode="icmp", port=443)
                    if gateway:
                        futures["gateway"] = pool.submit(probe, gateway, source, mode="icmp", port=443)
                    else:
                        results["gateway"] = Sample(None, gateway_error)
                    for host, ip, error in extras:
                        role = 'compare:' + host
                        destinations[role], protocols[role], ports[role] = ip or host, 'icmp', None
                        if ip:
                            futures[role] = pool.submit(probe, ip, source, mode='icmp', port=443)
                        else:
                            results[role] = Sample(None, error or 'DNS: определение адреса…')
                    for role, future in futures.items():
                        try:
                            results[role] = future.result()
                        except Exception as exc:
                            results[role] = Sample(None, str(exc))
                except Exception as exc:
                    results = {role: Sample(None, str(exc)) for role in ('target','gateway','control')}
                destinations['gateway'] = gateway or '—'
                traffic_error, current = "", None
                try:
                    current = psutil.net_io_counters(pernic=True).get(adapter) if adapter else psutil.net_io_counters()
                    if current is None:
                        traffic_error = "Нет счётчиков выбранного адаптера"
                except Exception as exc:
                    traffic_error = f"Ошибка счётчиков: {exc}"
                now = time.monotonic()
                traffic = traffic_delta(previous, current, now - previous_time) if previous_time else None
                previous, previous_time = current, now
                nodes = {}
                for role, sample in results.items():
                    key = (destinations.get(role), protocols.get(role), ports.get(role), adapter)
                    if history_keys.get(role) != key:
                        histories[role] = deque(maxlen=WINDOW)
                        history_keys[role] = key
                    histories[role].append(sample)
                    nodes[role] = {"sample": sample, "samples": tuple(histories[role]),
                                   'address': destinations.get(role, '—'), 'mode': protocols.get(role, 'icmp'),
                                   'port': ports.get(role), **summarize(histories[role])}
                    if previous_errors.get(role) != sample.error:
                        if sample.error:
                            LOG.warning('%s %s: %s', role, destinations.get(role), sample.error)
                        elif previous_errors.get(role):
                            LOG.info('%s recovered', role)
                        previous_errors[role] = sample.error
                for role in set(histories) - set(results):
                    del histories[role]
                    history_keys.pop(role, None)
                    previous_errors.pop(role, None)
                with self._lock:
                    still_current = generation == self._config[0]
                if still_current and not self._stop.is_set():
                    self.updated.emit({"generation": generation, "mode": mode, "port": port,
                                       **nodes["target"], "nodes": nodes,
                                       "diagnosis": diagnostic_hint({r: nodes[r] for r in ('target','gateway','control')}), "traffic": traffic,
                                       'timestamp': time.time(), 'adapter': adapter,
                                       "traffic_error": traffic_error})
                self._wake.wait(max(0, INTERVAL - (time.monotonic() - started)))

