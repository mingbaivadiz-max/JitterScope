# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 SanyLok
"""Safe local tests: no real DNS flush or application termination."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys
import tempfile
import threading
import time
import unittest
from collections import namedtuple
from unittest.mock import patch, Mock

from PyQt6.QtCore import QPoint, QProcess, QSettings, Qt
from PyQt6.QtGui import QFontDatabase
from PyQt6.QtNetwork import QHostAddress, QHostInfo
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMessageBox
import usb_net_controller as c
import controller.network as net


APP = QApplication.instance() or QApplication([])
APP.setQuitOnLastWindowClosed(False)
if sys.platform == "win32":
    for font in ("segoeui.ttf", "segoeuib.ttf"):
        QFontDatabase.addApplicationFont(os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Fonts", font))


def until(condition, seconds=4):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        APP.processEvents()
        if condition():
            return True
        time.sleep(.005)
    return False


class MetricsTests(unittest.TestCase):
    def test_loss_and_jitter_use_same_window_and_preserve_precision(self):
        data = c.summarize([c.Sample(10.2), c.Sample(10.7), c.Sample(None), c.Sample(50.1)])
        self.assertAlmostEqual(data["jitter"], .5)
        self.assertEqual(data["loss"], 25)
        self.assertEqual(data["count"], 4)

    def test_local_error_is_not_packet_loss_or_jitter_pair(self):
        data = c.summarize([c.Sample(10), c.Sample(None, "access"), c.Sample(90)])
        self.assertEqual(data["loss"], 0)
        self.assertIsNone(data["jitter"])
        self.assertEqual(data["count"], 2)

    def test_empty_and_all_timeout(self):
        self.assertIsNone(c.summarize([])["loss"])
        self.assertIsNone(c.summarize([c.Sample(None, "error")])["loss"])
        self.assertEqual(c.summarize([c.Sample(None)] * 60)["loss"], 100)

    def test_counter_reset_and_rate(self):
        Net = namedtuple("Net", "bytes_recv bytes_sent")
        self.assertEqual(c.traffic_delta(Net(100, 100), Net(2148, 1124), 2), (1, .5))
        self.assertIsNone(c.traffic_delta(Net(100, 100), Net(0, 0), 1))
        self.assertIsNone(c.traffic_delta(None, Net(1, 1), 1))

    def test_permission_falls_back_on_windows(self):
        with patch.object(net, "ping", side_effect=c.SocketPermissionError(privileged=False)), \
             patch.object(net, "windows_echo", return_value=c.Sample(12.5)) as fallback, \
             patch.object(c.sys, "platform", "win32"):
            self.assertEqual(c.probe("1.1.1.1", "192.168.1.2").rtt, 12.5)
            fallback.assert_called_once_with("1.1.1.1", "192.168.1.2")

    def test_probe_error_not_timeout(self):
        with patch.object(net, "ping", side_effect=RuntimeError("no socket")):
            self.assertIn("no socket", c.probe("1.1.1.1").error)

    def test_disconnected_adapter(self):
        with patch.object(c.psutil, "net_if_stats", return_value={}):
            with self.assertRaisesRegex(RuntimeError, "отключён"):
                c.adapter_source("phone")


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.gateway_patch = patch.object(net, "find_gateway", return_value="192.0.2.1")
        self.gateway_patch.start()

    def tearDown(self):
        self.gateway_patch.stop()

    def test_three_probes_really_overlap_and_histories_are_independent(self):
        barrier = threading.Barrier(3, timeout=2)
        received = []
        modes = []
        values = {"127.0.0.1": 80, "192.0.2.1": 2, "1.1.1.1": 40}
        def parallel(address, source, mode="icmp", port=443):
            modes.append((address, mode, port))
            barrier.wait()
            return c.Sample(values[address])
        worker = c.NetworkWorker()
        worker.configure("127.0.0.1", None, "tcp", 8080)
        worker.updated.connect(received.append)
        try:
            with patch.object(net, "probe", side_effect=parallel):
                worker.start()
                self.assertTrue(until(lambda: bool(received)))
                worker.request_stop()
                self.assertTrue(worker.wait(3000))
            data = received[0]
            self.assertEqual(set(data["nodes"]), {"target", "gateway", "control"})
            self.assertEqual({r: n["sample"].rtt for r, n in data["nodes"].items()},
                             {"target": 80, "gateway": 2, "control": 40})
            self.assertIn(("127.0.0.1", "tcp", 8080), modes)
            self.assertIn(("192.0.2.1", "icmp", 443), modes)
            self.assertIn(("1.1.1.1", "icmp", 443), modes)
        finally:
            worker.request_stop()
            worker.wait(3000)

    def test_missing_gateway_does_not_prevent_other_probes(self):
        worker = c.NetworkWorker()
        received = []
        worker.updated.connect(received.append)
        try:
            with patch.object(net, "find_gateway", side_effect=RuntimeError("no gateway")), \
                 patch.object(net, "probe", return_value=c.Sample(20)):
                worker.start()
                self.assertTrue(until(lambda: bool(received)))
                worker.request_stop()
                self.assertTrue(worker.wait(2000))
            self.assertIn("no gateway", received[0]["nodes"]["gateway"]["sample"].error)
            self.assertEqual(received[0]["nodes"]["control"]["sample"].rtt, 20)
        finally:
            worker.request_stop()
            worker.wait(3000)

    def test_mode_switch_during_probe_discards_old_result(self):
        entered, release = threading.Event(), threading.Event()
        received = []

        def delayed(address, source, mode="icmp", port=443):
            if mode == "icmp":
                entered.set()
                release.wait(2)
                return c.Sample(999)
            self.assertEqual(port, 8080)
            return c.Sample(15)

        worker = c.NetworkWorker()
        worker.updated.connect(received.append)
        try:
            with patch.object(net, "probe", side_effect=delayed), patch.object(net, "INTERVAL", .03):
                worker.start()
                self.assertTrue(entered.wait(2))
                generation = worker.configure("127.0.0.1", None, "tcp", 8080)
                release.set()
                self.assertTrue(until(lambda: len(received) >= 2))
                self.assertTrue(all(d["generation"] == generation and d["mode"] == "tcp" for d in received))
                self.assertEqual(received[0]["samples"], (c.Sample(15),))
                worker.request_stop()
                self.assertTrue(worker.wait(2000))
        finally:
            release.set()
            worker.request_stop()
            worker.wait(3000)

    def test_switch_during_probe_discards_old_result(self):
        entered, release = threading.Event(), threading.Event()
        received = []

        def delayed(address, source, **kwargs):
            if address == "1.1.1.1":
                entered.set()
                release.wait(2)
                return c.Sample(999)
            return c.Sample(15.25)

        worker = c.NetworkWorker()
        worker.updated.connect(received.append)
        try:
            with patch.object(net, "probe", side_effect=delayed), \
                 patch.object(net, "INTERVAL", .03):
                worker.start()
                self.assertTrue(entered.wait(2))
                generation = worker.configure("127.0.0.1", None)
                release.set()
                self.assertTrue(until(lambda: len(received) >= 2))
                self.assertTrue(all(d["generation"] == generation for d in received))
                self.assertTrue(all(s.rtt != 999 for d in received for s in d["samples"]))
                self.assertEqual(received[0]["count"], 1)
                worker.request_stop()
                self.assertTrue(worker.wait(2000))
        finally:
            release.set()
            worker.request_stop()
            worker.wait(3000)


class WidgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="usb-net-test-")
        self.settings_file = os.path.join(self.temp.name, "settings.ini")
        self.probe_patch = patch.object(net, "probe", return_value=c.Sample(35.5))
        self.probe_patch.start()
        self.widget = c.PingControllerWidget(QSettings(self.settings_file, QSettings.Format.IniFormat))
        self.widget.show()
        self.assertTrue(until(lambda: self.widget.ping_label.text() == "35.5 мс"))

    def tearDown(self):
        self.widget.close()
        self.assertTrue(until(lambda: not self.widget.worker.isRunning() and not self.widget.isVisible()))
        self.widget.deleteLater()
        APP.processEvents()
        self.probe_patch.stop()
        self.temp.cleanup()

    def reopen(self):
        self.widget.close()
        self.assertTrue(until(lambda: not self.widget.worker.isRunning() and not self.widget.isVisible()))
        self.widget.deleteLater()
        APP.processEvents()
        self.widget = c.PingControllerWidget(QSettings(self.settings_file, QSettings.Format.IniFormat))
        self.widget.show()
        self.assertTrue(until(lambda: self.widget.ping_label.text() == "35.5 мс"))

    def test_settings_round_trip(self):
        self.widget.address.setText("127.0.0.1")
        self.widget.mode.setCurrentIndex(1)
        self.widget.port.setValue(8080)
        self.widget.opacity.setValue(72)
        self.widget.pin.setChecked(False)
        area = APP.primaryScreen().availableGeometry()
        position = area.topLeft() + QPoint(5, 0)
        self.widget.move(position)
        self.reopen()
        self.assertEqual(self.widget.address.text(), "127.0.0.1")
        self.assertEqual(self.widget.servers.currentText(), "Свой адрес")
        self.assertEqual(self.widget.mode.currentData(), "tcp")
        self.assertEqual(self.widget.port.value(), 8080)
        self.assertEqual(self.widget.opacity.value(), 72)
        self.assertAlmostEqual(self.widget.windowOpacity(), .72, places=2)
        self.assertFalse(self.widget.pin.isChecked())
        self.assertEqual(self.widget.pos(), position)
        self.assertIn("Тайм-ауты", self.widget.metrics.text())

    def test_header_double_click_toggles_compact_and_preserves_monitoring(self):
        generation = self.widget.generation
        QTest.mouseDClick(self.widget.header, Qt.MouseButton.LeftButton)
        APP.processEvents()
        self.assertTrue(self.widget.compact)
        self.assertFalse(self.widget.details.isVisible())
        self.assertFalse(self.widget.graph.isVisible())
        self.assertTrue(self.widget.mini.isVisible())
        self.assertLessEqual(self.widget.height(), 180)
        self.assertIn("35.5", self.widget.mini_ping.text())
        self.assertEqual(self.widget.generation, generation)
        QTest.mouseDClick(self.widget.header, Qt.MouseButton.LeftButton)
        APP.processEvents()
        self.assertFalse(self.widget.compact)
        self.assertTrue(self.widget.graph.isVisible())
        self.assertEqual(self.widget.generation, generation)

    def test_compact_state_survives_restart(self):
        self.widget.set_compact(True)
        self.reopen()
        self.assertTrue(self.widget.compact)
        self.assertFalse(self.widget.graph.isVisible())
        self.assertLessEqual(self.widget.height(), 180)
        self.widget.set_compact(False)
        self.assertGreater(self.widget.height(), 320)

    def test_hostname_resolves_asynchronously_and_stale_dns_is_ignored(self):
        callbacks = []
        info = QHostInfo()
        info.setAddresses([QHostAddress("203.0.113.10")])
        with patch.object(c.QHostInfo, "lookupHost", side_effect=lambda host, callback: callbacks.append(callback) or 123), \
             patch.object(c.QHostInfo, "abortHostLookup") as abort:
            self.widget.address.setText("first.example.com")
            self.widget.apply_target()
            first_generation = self.widget.generation
            self.widget.address.setText("second.example.com")
            self.widget.apply_target()
            second_generation = self.widget.generation
            callbacks[0](info)
            self.assertEqual(self.widget.generation, second_generation)
            self.assertNotEqual(first_generation, second_generation)
            callbacks[1](info)
            self.assertEqual(self.widget._active_address, "second.example.com")
            self.assertEqual(self.widget.worker._config[1], "203.0.113.10")
            abort.assert_called_with(123)

    def test_dns_lookup_timeout_does_not_resume_old_goal(self):
        callbacks = []
        with patch.object(c.QHostInfo, "lookupHost", side_effect=lambda host, callback: callbacks.append(callback) or 123), \
             patch.object(c.QHostInfo, "abortHostLookup"):
            self.widget.address.setText("slow.example.com")
            self.widget.apply_target()
            self.widget.lookup_timeout()
            info = QHostInfo()
            info.setAddresses([QHostAddress("203.0.113.10")])
            callbacks[0](info)
            self.assertIn("4 секунды", self.widget.monitor_status.text())
            self.assertIsNone(self.widget.worker._config[1])

    def test_close_cancels_pending_hostname_lookup(self):
        with patch.object(c.QHostInfo, "lookupHost", return_value=123), \
             patch.object(c.QHostInfo, "abortHostLookup") as abort:
            self.widget.address.setText("slow.example.com")
            self.widget.apply_target()
            self.widget.close()
            self.assertTrue(until(lambda: not self.widget.isVisible()))
            abort.assert_called_with(123)

    def test_dns_name_is_saved_instead_of_resolved_ip(self):
        info = QHostInfo()
        info.setAddresses([QHostAddress("203.0.113.10")])
        callbacks = []
        with patch.object(c.QHostInfo, "lookupHost", side_effect=lambda host, callback: callbacks.append(callback) or 123):
            self.widget.address.setText("ping-de.ds.on.epicgames.com")
            self.widget.apply_target()
            callbacks[0](info)
            self.widget.save_settings()
            self.assertEqual(self.widget.settings.value("monitor/address"), "ping-de.ds.on.epicgames.com")

    def test_corrupt_settings_and_missing_adapter_recover(self):
        self.widget.close()
        self.assertTrue(until(lambda: not self.widget.isVisible()))
        settings = QSettings(self.settings_file, QSettings.Format.IniFormat)
        for key, value in {"monitor/address": "not an ip", "monitor/port": "oops",
                           "monitor/mode": "unknown", "monitor/adapter": "MISSING-TEST-ADAPTER",
                           "window/opacity": 999, "window/position": QPoint(-90000, 90000)}.items():
            settings.setValue(key, value)
        settings.sync()
        # The closed widget must not save over the deliberately corrupted file again.
        self.widget.deleteLater()
        APP.processEvents()
        self.widget = c.PingControllerWidget(QSettings(self.settings_file, QSettings.Format.IniFormat))
        self.widget.show()
        self.assertTrue(until(lambda: self.widget.ping_label.text() == "35.5 мс"))
        self.assertEqual(self.widget.address.text(), "1.1.1.1")
        self.assertEqual(self.widget.port.value(), 443)
        self.assertEqual(self.widget.mode.currentData(), "icmp")
        self.assertEqual(self.widget.opacity.value(), 100)
        self.assertIsNone(self.widget.adapters.currentData())
        self.assertIn("недоступен", self.widget.action_status.text())
        self.assertTrue(APP.primaryScreen().availableGeometry().contains(self.widget.pos()))

    def test_saved_adapter_is_restored_by_name(self):
        original_source = c.adapter_source
        def source(name):
            return "192.168.42.2" if name == "Test phone" else original_source(name)
        fake_stats = {"Test phone": Mock(isup=True)}
        fake_addrs = {"Test phone": [Mock(family=c.socket.AF_INET, address="192.168.42.2")]}
        with patch.object(c.psutil, "net_if_stats", return_value=fake_stats), \
             patch.object(c.psutil, "net_if_addrs", return_value=fake_addrs), \
             patch.object(net, "adapter_source", side_effect=source):
            self.widget.refresh_adapters()
            self.widget.adapters.setCurrentIndex(self.widget.adapters.findData("Test phone"))
            self.reopen()
            self.assertEqual(self.widget.adapters.currentData(), "Test phone")

    def test_mode_switch_clears_history_and_changes_labels(self):
        previous = self.widget.generation
        self.widget.mode.setCurrentIndex(1)
        self.assertGreater(self.widget.generation, previous)
        self.assertTrue(self.widget.port.isEnabled())
        self.assertEqual(self.widget.graph.samples, ())
        self.assertIn("TCP", self.widget.graph.caption)
        self.assertIn("Тайм-ауты", self.widget.metrics.text())
        self.widget.mode.setCurrentIndex(0)
        self.assertFalse(self.widget.port.isEnabled())
        self.assertIn("Потери", self.widget.metrics.text())

    def test_invalid_edit_does_not_replace_saved_target(self):
        self.widget.address.setText("invalid")
        self.widget.apply_target()
        self.reopen()
        self.assertEqual(self.widget.address.text(), "1.1.1.1")

    def test_stale_signal_is_ignored_and_invalid_ip_keeps_target(self):
        self.widget.update_dashboard({"generation": -1})
        self.assertEqual(self.widget.ping_label.text(), "35.5 мс")
        previous = self.widget.generation
        self.widget.address.setText("bad; command")
        self.widget.apply_target()
        self.assertEqual(self.widget.generation, previous)
        self.assertIn("IPv4", self.widget.action_status.text())

    def test_graph_draws_loss_error_and_zero_latency(self):
        self.widget.graph.set_samples((c.Sample(0), c.Sample(50), c.Sample(None),
                                       c.Sample(None, "error"), c.Sample(150)))
        image = self.widget.grab().toImage()
        self.assertFalse(image.isNull())
        self.assertGreater(image.width(), 400)
        self.assertGreater(self.widget.graph.height(), 100)
        self.assertGreaterEqual(self.widget.ping_label.height(), 74)

    def fake_dns(self, code):
        real_start = self.widget.dns.start
        with patch.object(self.widget.dns, "start", side_effect=lambda *args: real_start(
                sys.executable, ["-c", f"import sys; sys.exit({code})"])):
            self.widget.flush_dns()
        self.assertTrue(until(lambda: self.widget.flush_button.isEnabled()))

    def test_dns_failure_is_not_success(self):
        self.fake_dns(5)
        self.assertIn("не очищен", self.widget.action_status.text())
        self.assertIn("5", self.widget.action_status.text())

    def test_dns_success(self):
        self.fake_dns(0)
        self.assertIn("DNS-кэш очищен", self.widget.action_status.text())

    def test_dns_timeout_stops_only_own_child_process(self):
        real_start = self.widget.dns.start
        with patch.object(self.widget.dns, "start", side_effect=lambda *args: real_start(
                sys.executable, ["-c", "import time; time.sleep(30)"])):
            self.widget.flush_dns()
        self.assertTrue(until(lambda: self.widget.dns.state() == QProcess.ProcessState.Running))
        self.widget.dns_timeout()
        self.assertTrue(until(lambda: self.widget.flush_button.isEnabled()))
        self.assertIn("остановлена", self.widget.action_status.text())

    def test_failed_dns_start(self):
        real_start = self.widget.dns.start
        with patch.object(self.widget.dns, "start", side_effect=lambda *args: real_start(
                "Z:/nonexistent-program-for-test.exe", [])):
            self.widget.flush_dns()
        self.assertTrue(until(lambda: self.widget.flush_button.isEnabled()))
        self.assertIn("Не удалось запустить", self.widget.action_status.text())

    def test_close_waits_for_worker_without_blocking_gui(self):
        start = time.monotonic()
        self.widget.close()
        self.assertLess(time.monotonic() - start, .2)
        self.assertTrue(until(lambda: not self.widget.isVisible()))


class TcpTests(unittest.TestCase):
    def test_connection_is_closed_and_bound_without_sending_payload(self):
        connection = Mock()
        context = Mock()
        context.__enter__ = Mock(return_value=connection)
        context.__exit__ = Mock(return_value=False)
        with patch.object(c.socket, "create_connection", return_value=context) as connect, \
             patch.object(c.time, "perf_counter", side_effect=[1, 1.0125]):
            sample = c.probe("127.0.0.1", "192.168.42.2", "tcp", 8080)
        self.assertAlmostEqual(sample.rtt, 12.5)
        connect.assert_called_once_with(("127.0.0.1", 8080), timeout=c.TIMEOUT,
                                        source_address=("192.168.42.2", 0))
        context.__exit__.assert_called_once()
        connection.send.assert_not_called()
        connection.sendall.assert_not_called()

    def test_timeout_and_refused_port_are_different(self):
        with patch.object(c.socket, "create_connection", side_effect=TimeoutError()):
            timeout = c.tcp_probe("127.0.0.1")
        with patch.object(c.socket, "create_connection", side_effect=ConnectionRefusedError()):
            refused = c.tcp_probe("127.0.0.1")
        self.assertEqual(timeout, c.Sample(None))
        self.assertIn("отклонено", refused.error)
        self.assertEqual(c.summarize([timeout, refused])["loss"], 100)
        self.assertEqual(c.summarize([timeout, refused])["count"], 1)

    def test_invalid_port_never_connects(self):
        with patch.object(c.socket, "create_connection") as connect:
            self.assertTrue(c.tcp_probe("127.0.0.1", port=0).error)
            connect.assert_not_called()

    def test_actual_loopback_connection(self):
        # Listen only on loopback; no remote service is touched.
        with c.socket.socket(c.socket.AF_INET, c.socket.SOCK_STREAM) as server:
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            server.settimeout(2)
            sample = c.tcp_probe("127.0.0.1", port=server.getsockname()[1])
            self.assertEqual(sample.error, "")
            self.assertIsNotNone(sample.rtt)
            connection, _ = server.accept()
            with connection:
                connection.settimeout(2)
                self.assertEqual(connection.recv(1), b"")


class IcmpCacheTests(unittest.TestCase):
    def test_api_initialized_once_even_for_concurrent_callers(self):
        original = net._icmp_api
        dll = Mock()
        results = []
        try:
            net._icmp_api = None
            with patch.object(c.ctypes, "WinDLL", return_value=dll, create=True) as load:
                threads = [threading.Thread(target=lambda: results.append(c.get_icmp_api())) for _ in range(8)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(2)
                self.assertEqual(len(results), 8)
                self.assertTrue(all(result is dll for result in results))
                load.assert_called_once_with("iphlpapi", use_last_error=True)
        finally:
            net._icmp_api = original


class DiagnosticTests(unittest.TestCase):
    def nodes(self, now):
        return {role: {"sample": c.Sample(value), "samples": (c.Sample(10),) * 5 + (c.Sample(value),)}
                for role, value in zip(("gateway", "control", "target"), now)}

    def test_only_target_slows(self):
        self.assertIn("только выбранный", c.diagnostic_hint(self.nodes((10, 10, 80))))

    def test_both_external_nodes_slow(self):
        self.assertIn("обе внешние", c.diagnostic_hint(self.nodes((10, 80, 90))))

    def test_gateway_slows(self):
        self.assertIn("уже до шлюза", c.diagnostic_hint(self.nodes((80, 80, 90))))

    def test_timeout_is_not_a_definitive_diagnosis(self):
        nodes = self.nodes((10, 10, None))
        self.assertIn("не доказывает", c.diagnostic_hint(nodes))

    def test_target_validation(self):
        self.assertEqual(c.validate_target("PING-DE.ds.on.epicgames.com."), "ping-de.ds.on.epicgames.com")
        for bad in ("0.0.0.0", "999.1.1.1", "224.0.0.1", "https://test.com/", "1.1.1.1;cmd", "::1"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                c.validate_target(bad)


class ProcessTests(unittest.TestCase):
    def test_no_process_is_selected_by_default(self):
        process = Mock(pid=4444)
        process.info = {"pid": 4444, "name": "OneDrive.exe", "create_time": 10}
        with patch.object(c.psutil, "process_iter", return_value=[process]):
            dialog = c.ProcessDialog(None)
            self.assertEqual(dialog.items.item(0).checkState(), Qt.CheckState.Unchecked)
            dialog.finish_selected()
            process.kill.assert_not_called()
            dialog.close()

    def test_reused_pid_not_killed(self):
        process = Mock(pid=4444)
        process.info = {"pid": 4444, "name": "OneDrive.exe", "create_time": 10}
        replacement = Mock()
        replacement.create_time.return_value = 20
        with patch.object(c.psutil, "process_iter", return_value=[process]), \
             patch.object(c.psutil, "Process", return_value=replacement), \
             patch.object(c.QMessageBox, "warning", return_value=QMessageBox.StandardButton.Yes):
            dialog = c.ProcessDialog(None)
            dialog.items.item(0).setCheckState(Qt.CheckState.Checked)
            dialog.finish_selected()
            replacement.kill.assert_not_called()
            self.assertIn("изменился", dialog.result_label.text())
            dialog.close()


if __name__ == "__main__":
    unittest.main()
