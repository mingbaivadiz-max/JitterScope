# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 SanyLok
from __future__ import annotations
import ipaddress
import logging
import os
import sys
import json
import time
from pathlib import Path
import psutil
import socket
from PyQt6.QtCore import QEvent, QPoint, QProcess, QRectF, QSettings, QSize, Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QDesktopServices, QFont, QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PyQt6.QtNetwork import QHostInfo
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel,
    QDialog, QInputDialog, QLineEdit, QMenu, QMessageBox, QPushButton, QScrollArea, QSlider, QSpinBox,
    QSystemTrayIcon, QVBoxLayout, QWidget)
from .model import VERSION, Sample, validate_target, summarize, quality, QUALITY_COLORS, AlertTracker
from .network import NetworkWorker
from .widgets import HistoryGraph, ProcessDialog
from .storage import HistoryStore
from .profiles import Profiles
from .dialogs import ComparisonDialog, HistoryDialog, PreferencesDialog
from server_catalog import BY_HOST, CHECKED, SERVERS
LOG = logging.getLogger('usb_net.ui')
STYLE = "\nQWidget { color: #eeeaf7; font-family: 'Segoe UI'; font-size: 12px; }\nQFrame#panel { background: rgba(22, 18, 35, 239); border: 1px solid #7862b0; border-radius: 16px; }\nQDialog { background: #211b30; }\nQComboBox, QLineEdit, QSpinBox, QListWidget { background: #30283f; border: 1px solid #625276; border-radius: 6px; padding: 6px; }\nQComboBox QAbstractItemView { background: #30283f; color: #eeeaf7; selection-background-color: #67508e; }\nQPushButton { background: #382b4f; border: 1px solid #7862b0; border-radius: 7px; padding: 8px; }\nQPushButton:hover { background: #554071; }\nQPushButton:disabled { color: #9b90a7; background: #30283f; }\nQLabel#muted { color: #b8afca; font-size: 11px; }\n"
STYLE += '''
QDoubleSpinBox { background: #30283f; color: #eeeaf7; border: 1px solid #625276; border-radius: 6px; padding: 6px; }
QTableWidget, QListWidget { background: #241d33; color: #eeeaf7; gridline-color: #514360; selection-background-color: #665084; }
QHeaderView::section { background: #382c4c; color: #eeeaf7; padding: 6px; border: 1px solid #645077; }
QHeaderView { background: #382c4c; }
QTableCornerButton::section { background: #382c4c; border: 1px solid #645077; }
QToolTip { background: #292036; color: #eeeaf7; border: 1px solid #7862b0; padding: 5px; }
QScrollBar:vertical { background: #20192e; width: 12px; }
QScrollBar::handle:vertical { background: #77618e; min-height: 25px; border-radius: 5px; }
QScrollBar:horizontal { background: #20192e; height: 12px; }
QScrollBar::handle:horizontal { background: #77618e; min-width: 25px; border-radius: 5px; }
'''


class StorageCloser(QThread):
    def __init__(self, store, session, parent):
        super().__init__(parent)
        self.store, self.session = store, session
        self.error = ''

    def run(self):
        try:
            self.store.end_session(self.session)
            self.store.close()
        except Exception as exc:
            self.error = str(exc)
            LOG.exception('Could not finish history')


class PingControllerWidget(QWidget):
    alert_emitted = pyqtSignal(str,str)
    def __init__(self, settings=None, data_dir=None):
        super().__init__()
        self.settings = settings if settings is not None else QSettings("USBNetController", "DesktopWidget")
        self.settings.setFallbacksEnabled(False)
        if data_dir is None:
            if settings is not None and str(settings.fileName()).endswith('.ini'):
                data_dir = Path(settings.fileName()).parent
            else:
                from .app import data_directory
                data_dir = data_directory()
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True,exist_ok=True)
        self.store = None
        self.session = None
        self._session_key = None
        self._storage_closer = None
        self._storage_closed = False
        self.comparison_dialog = None
        self.comparison_hosts = []
        self._extra_results = {}
        self._extra_lookups = {}
        self._extra_token = 0
        self.profile_name = ''
        self.profiles = Profiles(self.settings)
        self.preferences = self.read_preferences()
        self.alert_tracker = AlertTracker(self.preferences['rtt'],self.preferences['loss'],self.preferences['jitter'])
        try:
            self.store = HistoryStore(self.data_dir/'history.sqlite',self.preferences['retention'])
        except Exception as exc:
            LOG.exception('History initialization failed')
            self._history_init_error = str(exc)
        self._restoring = True
        self._active_address = "1.1.1.1"
        self._active_mode = "icmp"
        self._active_port = 443
        self._active_adapter = None
        self._closing = False
        self._drag_pos = None
        self.compact = False
        self._full_size = QSize(500, 900)
        self._lookup_id = None
        self._lookup_token = 0
        self._last_data = None
        self.generation = 0
        self.dns_timed_out = False
        self.worker = NetworkWorker()
        self.worker.updated.connect(self.update_dashboard)
        self.worker.finished.connect(self.worker_finished)
        self.dns = QProcess(self)
        self.dns.finished.connect(self.dns_finished)
        self.dns.errorOccurred.connect(self.dns_error)
        self.dns_timer = QTimer(self)
        self.dns_timer.setSingleShot(True)
        self.dns_timer.timeout.connect(self.dns_timeout)
        self.lookup_timer = QTimer(self)
        self.lookup_timer.setSingleShot(True)
        self.lookup_timer.timeout.connect(self.lookup_timeout)
        self.retry_timer = QTimer(self)
        self.retry_timer.setSingleShot(True)
        self.retry_timer.timeout.connect(self.retry_dns)
        self.comparison_retry_timer = QTimer(self)
        self.comparison_retry_timer.timeout.connect(self.retry_comparison_dns)
        self.comparison_retry_timer.start(60000)
        self.build_ui()
        self.refresh_adapters()
        self.restore_settings()
        self._restoring = False
        self.init_tray()
        self.apply_target()
        self.worker.start()
        try:
            selected = json.loads(self.settings.value('monitor/compare','[]'))
            if isinstance(selected,list):
                self.configure_comparison(selected[:5])
        except (ValueError,TypeError):
            pass
        for key, callback in [('Ctrl+M',lambda: self.set_compact(not self.compact)),
                              ('Ctrl+H',self.show_history),('Ctrl+E',self.show_history)]:
            shortcut = QShortcut(QKeySequence(key),self)
            shortcut.activated.connect(callback)
        if self.store is None:
            self.action_status.setText('История недоступна: ' + self._history_init_error)

    def build_ui(self):
        self.setWindowTitle(f"JitterScope {VERSION}")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(self._full_size)
        self.setMinimumWidth(440)
        self.setStyleSheet(STYLE)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        panel = QFrame()
        panel.setObjectName("panel")
        outer.addWidget(panel)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)
        self.header = QWidget()
        self.header.setToolTip("Двойной клик: мини-панель / полное окно. Перетаскивание: переместить.")
        self.header.installEventFilter(self)
        header = QHBoxLayout(self.header)
        header.setContentsMargins(0, 0, 0, 0)
        title = QLabel(f"JITTERSCOPE {VERSION}")
        title.setStyleSheet("color: #d0b5ff; font-weight: 700; font-size: 14px;")
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        header.addWidget(title)
        header.addStretch()
        minimize = QPushButton('−')
        minimize.setFixedSize(30,30)
        minimize.setToolTip('Свернуть в трей')
        minimize.clicked.connect(self.minimize_to_tray)
        header.addWidget(minimize)
        close = QPushButton("×")
        close.setFixedSize(30, 30)
        close.clicked.connect(self.close)
        header.addWidget(close)
        layout.addWidget(self.header)
        self.details = QScrollArea()
        self.details.setFrameShape(QFrame.Shape.NoFrame)
        self.details.setWidgetResizable(True)
        self.details.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        self.body = QWidget()
        self.details.setWidget(self.body)
        layout.addWidget(self.details, 1)
        self.mini = QWidget()
        mini_layout = QVBoxLayout(self.mini)
        mini_layout.setContentsMargins(0, 0, 0, 0)
        mini_layout.setSpacing(6)
        self.mini_ping = QLabel("Цель —   Шлюз —   Сеть — мс")
        self.mini_ping.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mini_ping.setStyleSheet("color: #44e6c3; font-size: 14px; font-weight: bold;")
        self.mini_traffic = QLabel("↓ —   ↑ — КиБ/с")
        self.mini_traffic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mini_layout.addWidget(self.mini_ping)
        mini_layout.addWidget(self.mini_traffic)
        layout.addWidget(self.mini)
        self.mini.hide()
        layout = QVBoxLayout(self.body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        profiles_row = QHBoxLayout()
        self.profile_combo = QComboBox()
        self.refresh_profiles()
        self.profile_combo.currentIndexChanged.connect(self.load_profile)
        profiles_row.addWidget(self.profile_combo,1)
        save_profile = QPushButton('Сохранить профиль…')
        save_profile.clicked.connect(self.save_profile)
        profiles_row.addWidget(save_profile)
        remove_profile = QPushButton('Удалить')
        remove_profile.clicked.connect(self.remove_profile)
        profiles_row.addWidget(remove_profile)
        layout.addLayout(profiles_row)
        row = QHBoxLayout()
        self.servers = QComboBox()
        for name, address in SERVERS.items():
            self.servers.addItem(name, address)
        self.servers.currentIndexChanged.connect(self.select_preset)
        row.addWidget(self.servers)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.address = QLineEdit("1.1.1.1")
        self.address.setPlaceholderText("IPv4 или имя узла")
        self.address.returnPressed.connect(self.apply_target)
        row.addWidget(self.address)
        apply_button = QPushButton("Применить")
        apply_button.clicked.connect(self.apply_target)
        row.addWidget(apply_button)
        layout.addLayout(row)
        self.preset_hint = QLabel("Диагностические узлы. Замер может отличаться от пинга в игре.")
        self.preset_hint.setObjectName("muted")
        self.preset_hint.setWordWrap(True)
        self.preset_hint.setOpenExternalLinks(True)
        layout.addWidget(self.preset_hint)
        row = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItem("ICMP Echo", "icmp")
        self.mode.addItem("TCP-подключение", "tcp")
        self.mode.currentIndexChanged.connect(self.mode_changed)
        row.addWidget(self.mode, 1)
        row.addWidget(QLabel("Порт"))
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(443)
        self.port.setEnabled(False)
        self.port.setKeyboardTracking(False)
        self.port.valueChanged.connect(self.apply_target)
        self.port.setToolTip("Укажите открытый TCP-порт, например 443 или 80. UDP-порт игры не подходит.")
        row.addWidget(self.port)
        layout.addLayout(row)
        self.mode_hint = QLabel("ICMP: время до эхо-ответа выбранного узла.")
        self.mode_hint.setObjectName("muted")
        self.mode_hint.setWordWrap(True)
        layout.addWidget(self.mode_hint)
        row = QHBoxLayout()
        self.adapters = QComboBox()
        self.adapters.setMinimumWidth(0)
        self.adapters.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.adapters.currentIndexChanged.connect(self.apply_target)
        row.addWidget(self.adapters, 1)
        refresh = QPushButton("Обновить")
        refresh.clicked.connect(self.refresh_adapters)
        row.addWidget(refresh)
        layout.addLayout(row)
        self.ping_label = QLabel("— мс")
        self.ping_label.setMinimumHeight(74)
        self.ping_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ping_label.setFont(QFont("Segoe UI", 34, QFont.Weight.Bold))
        layout.addWidget(self.ping_label)
        self.graph = HistoryGraph()
        layout.addWidget(self.graph, 1)
        self.metrics = QLabel("Джиттер —   |   Потери —")
        self.metrics.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.metrics)
        self.node_labels = {}
        for role, name in (("gateway", "Шлюз"), ("control", "Интернет")):
            label = QLabel(f"{name}: —")
            label.setObjectName("muted")
            label.setWordWrap(True)
            self.node_labels[role] = label
            layout.addWidget(label)
        self.diagnosis = QLabel("Накопление сравнительных измерений…")
        self.diagnosis.setWordWrap(True)
        self.diagnosis.setObjectName("muted")
        layout.addWidget(self.diagnosis)
        self.traffic = QLabel("↓ —   ↑ — КиБ/с")
        self.traffic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.traffic)
        self.monitor_status = QLabel("Подготовка…")
        self.monitor_status.setObjectName("muted")
        self.monitor_status.setWordWrap(True)
        self.monitor_status.setMinimumHeight(38)
        layout.addWidget(self.monitor_status)
        tools_row = QHBoxLayout()
        for title, callback in [('Регионы…',self.show_comparison),('История / отчёты…',self.show_history),('Настройки…',self.show_preferences)]:
            button = QPushButton(title)
            button.clicked.connect(callback)
            tools_row.addWidget(button)
        layout.addLayout(tools_row)
        self.history_status = QLabel('История: локальная запись')
        self.history_status.setObjectName('muted')
        self.history_status.setWordWrap(True)
        layout.addWidget(self.history_status)
        processes = QPushButton("Выбрать фоновые приложения…")
        processes.clicked.connect(self.show_processes)
        layout.addWidget(processes)
        self.flush_button = QPushButton("Очистить DNS-кэш")
        self.flush_button.setEnabled(sys.platform == "win32")
        self.flush_button.setToolTip("Очистка кэша имён. Не снижает RTT до числового IP.")
        self.flush_button.clicked.connect(self.flush_dns)
        layout.addWidget(self.flush_button)
        self.action_status = QLabel("Изменения сети выполняются только по нажатию кнопки.")
        self.action_status.setWordWrap(True)
        self.action_status.setObjectName("muted")
        self.action_status.setMinimumHeight(32)
        layout.addWidget(self.action_status)
        row = QHBoxLayout()
        self.pin = QCheckBox("Поверх окон")
        self.pin.setChecked(True)
        self.pin.toggled.connect(self.set_pinned)
        row.addWidget(self.pin)
        row.addStretch()
        row.addWidget(QLabel("Прозрачность"))
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(55, 100)
        self.opacity.setValue(100)
        self.opacity.setMaximumWidth(90)
        self.opacity.valueChanged.connect(lambda value: self.setWindowOpacity(value / 100))
        row.addWidget(self.opacity)
        layout.addLayout(row)

    def restore_settings(self):
        """Validate persisted values and keep the title on an attached screen."""
        def number(key, default, low, high):
            try:
                return max(low, min(high, int(self.settings.value(key, default))))
            except (ValueError, TypeError, OverflowError):
                return default

        address = str(self.settings.value("monitor/address", "1.1.1.1"))
        try:
            address = validate_target(address)
        except ValueError:
            address = "1.1.1.1"
        preset = self.servers.findData(address)
        if preset < 0:
            self.servers.addItem("Свой адрес", address)
            preset = self.servers.count() - 1
        self.servers.setCurrentIndex(preset)
        self.address.setText(address)
        adapter = self.settings.value("monitor/adapter", "") or None
        index = self.adapters.findData(adapter)
        self.adapters.setCurrentIndex(max(0, index))
        if adapter and index < 0:
            self.action_status.setText("Сохранённый адаптер недоступен: выбран общий режим.")
        self.port.setValue(number("monitor/port", 443, 1, 65535))
        mode = self.settings.value("monitor/mode", "icmp")
        self.mode.setCurrentIndex(1 if mode == "tcp" else 0)
        self.mode_changed()
        self.opacity.setValue(number("window/opacity", 100, 55, 100))
        pinned = self.settings.value("window/pinned", True)
        self.pin.setChecked(str(pinned).casefold() in ("true", "1"))
        # setWindowFlag can hide/recreate a native window, so do this before show().
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.pin.isChecked())
        saved_profile = self.settings.value('profiles/active','')
        if any(item['name'] == saved_profile for item in self.profiles.items):
            self.profile_name = saved_profile
            self.refresh_profiles()
        full_size = self.settings.value("window/fullSize")
        if isinstance(full_size, QSize) and 440 <= full_size.width() <= 1400 and 400 <= full_size.height() <= 1800:
            self._full_size = full_size
        self.resize(self._full_size)
        compact = str(self.settings.value("window/compact", False)).casefold() in ("true", "1")
        self.set_compact(compact)
        position = self.settings.value("window/position")
        if isinstance(position, QPoint):
            self.move(position)
        self.fit_on_screen()

    def save_settings(self):
        for key, value in {
            "monitor/address": self._active_address,
            "monitor/adapter": self._active_adapter or "",
            "monitor/mode": self._active_mode,
            "monitor/port": self._active_port,
            "window/position": self.pos(),
            "window/opacity": self.opacity.value(),
            "window/pinned": self.pin.isChecked(),
            "window/compact": self.compact,
            "window/fullSize": self._full_size if self.compact else self.size(),
            'monitor/compare': json.dumps(self.comparison_hosts),
            'profiles/active': self.profile_name,
        }.items():
            self.settings.setValue(key, value)
        self.settings.sync()
        if self.settings.status() != QSettings.Status.NoError:
            LOG.warning("Не удалось сохранить настройки: %s", self.settings.status())

    def mode_changed(self):
        tcp = self.mode.currentData() == "tcp"
        self.port.setEnabled(tcp)
        self.mode_hint.setText(
            "TCP: время подключения к открытому порту. Без TLS и данных игры; UDP не проверяется."
            if tcp else "ICMP: время до эхо-ответа выбранного узла.")
        self.apply_target()

    def refresh_adapters(self):
        previous = self.adapters.currentData()
        self.adapters.blockSignals(True)
        self.adapters.clear()
        self.adapters.addItem("Все адаптеры · маршрут Windows", None)
        try:
            stats = psutil.net_if_stats()
            for name, addrs in psutil.net_if_addrs().items():
                ips = [a.address for a in addrs if a.family == socket.AF_INET
                       and not a.address.startswith(("127.", "169.254."))]
                if name in stats and stats[name].isup and ips:
                    self.adapters.addItem(f"{name} · {ips[0]}", name)
        except Exception as exc:
            self.action_status.setText(f"Не удалось получить список адаптеров: {exc}")
        index = self.adapters.findData(previous)
        self.adapters.setCurrentIndex(max(0, index))
        self.adapters.blockSignals(False)
        if previous is not None and index < 0:
            self.action_status.setText("Адаптер исчез: выбран общий режим. Выберите новое подключение.")
        self.apply_target()

    def select_preset(self):
        self.address.setText(self.servers.currentData())
        # Published addresses are ICMP/trace diagnostics, not advertised TCP services.
        self.mode.blockSignals(True)
        self.mode.setCurrentIndex(0)
        self.mode.blockSignals(False)
        self.mode_changed()

    def cancel_lookup(self):
        self._lookup_token += 1
        self.lookup_timer.stop()
        self.retry_timer.stop()
        if self._lookup_id is not None:
            QHostInfo.abortHostLookup(self._lookup_id)
            self._lookup_id = None

    def lookup_timeout(self):
        self.cancel_lookup()
        message = 'DNS: имя не определилось за 4 секунды. Шлюз, контроль и трафик продолжают измеряться.'
        self.generation = self.worker.set_target_error(message)
        self.monitor_status.setText(message)
        self.retry_timer.start(30000)

    def finish_lookup(self, info, token, host, mode, port, adapter):
        if self._closing or token != self._lookup_token:
            return
        self._lookup_id = None
        self.lookup_timer.stop()
        addresses = [str(a.toString()) for a in info.addresses() if a.protocol().value == 0]
        if info.error() != QHostInfo.HostInfoError.NoError or not addresses:
            message = 'DNS: нет IPv4 для ' + host + '. ' + info.errorString()
            self.generation = self.worker.set_target_error(message)
            self.monitor_status.setText(message)
            self.retry_timer.start(30000)
            return
        self.activate_target(host, addresses[0], mode, port, adapter)

    def activate_target(self, host, ip, mode, port, adapter):
        self.retry_timer.stop()
        self._pending_host = None
        self._active_address, self._active_adapter = host, adapter
        self._active_mode, self._active_port = mode, port
        self.generation = self.worker.configure(ip, adapter, mode, port)
        self.monitor_status.setText(f"{host} → {ip}" + (f":{port} · TCP" if mode == "tcp" else " · ICMP"))

    def retry_dns(self):
        if self._closing or not getattr(self,'_pending_host',None):
            return
        try:
            if validate_target(self.address.text()) == self._pending_host:
                self.apply_target()
        except ValueError:
            pass

    def retry_comparison_dns(self):
        if not self._closing and any(ip is None for ip,error in self._extra_results.values()):
            self.configure_comparison(self.comparison_hosts)

    def apply_target(self):
        if self._restoring or self._closing:
            return
        address = self.address.text().strip()
        try:
            host = validate_target(address)
        except ValueError:
            self.action_status.setText("Введите IPv4 или полное имя узла. Предыдущая цель продолжает проверяться.")
            return
        self.cancel_lookup()
        mode, port = self.mode.currentData(), self.port.value()
        adapter = self.adapters.currentData()
        self.start_session(host, mode, port, adapter)
        index = self.servers.findData(host)
        self.servers.blockSignals(True)
        if index < 0:
            index = self.servers.findText("Свой адрес")
            if index < 0:
                self.servers.addItem("Свой адрес", host)
                index = self.servers.count() - 1
            else:
                self.servers.setItemData(index, host)
        self.servers.setCurrentIndex(index)
        self.servers.blockSignals(False)
        self._last_data = None
        preset = BY_HOST.get(host)
        if preset:
            self.preset_hint.setText(preset["note"] + f' <a style="color:#cfb0ff" href="{preset["source"]}">Источник</a> · {CHECKED}')
        else:
            self.preset_hint.setText("Свой адрес. Его назначение и поддержка ICMP/TCP определяются владельцем.")
        self.graph.set_mode(mode)
        self.graph.set_samples(())
        self.ping_label.setText("— мс")
        self.metrics.setText("Разброс —   |   Тайм-ауты —" if mode == "tcp" else "Джиттер —   |   Потери —")
        self.traffic.setText("↓ —   ↑ — КиБ/с")
        self.mini_ping.setText("Цель —   Шлюз —   Сеть — мс")
        self.mini_traffic.setText("↓ —   ↑ — КиБ/с")
        for label in self.node_labels.values():
            label.setText("Подготовка…")
        self.diagnosis.setText("Накопление сравнительных измерений…")
        try:
            ipaddress.IPv4Address(host)
        except ipaddress.AddressValueError:
            self._pending_host = host
            self.generation = self.worker.configure(None, adapter, mode, port)
            self.monitor_status.setText(f"Определение IPv4 для {host}…")
            token = self._lookup_token
            self._lookup_id = QHostInfo.lookupHost(host, lambda info: self.finish_lookup(
                info, token, host, mode, port, adapter))
            self.lookup_timer.start(4000)
        else:
            self.activate_target(host, host, mode, port, adapter)

    def update_dashboard(self, data):
        if self._closing or data["generation"] != self.generation:
            return
        sample = data["sample"]
        self._last_data = data
        tcp = data.get('mode',self._active_mode) == 'tcp'
        self.graph.set_samples(data["samples"])
        if sample.error:
            text, color = "ОШИБКА", "#ffc857"
            status = sample.error
        elif sample.rtt is None:
            text, color = "НЕТ ОТВЕТА", "#ff6289"
            status = (f"TCP {self._active_port}: тайм-аут подключения. Проверьте адрес и открытый порт."
                      if tcp else "Нет ICMP-ответа: узел может фильтровать ICMP. Это не доказывает обрыв интернета.")
        else:
            text = f"{sample.rtt:.1f} мс"
            status = (f"TCP {self._active_port}: соединение установлено и закрыто."
                      if tcp else "ICMP: ответ получен. Окно статистики — до 60 последних измерений.")
        color = QUALITY_COLORS[quality(sample,data)]
        self.ping_label.setText(text)
        self.ping_label.setStyleSheet(f"color: {color}; font-size: {'24' if sample.rtt is None else '34'}pt; font-weight: 700;")
        jitter = f"{data['jitter']:.1f} мс" if data["jitter"] is not None else "—"
        loss = f"{data['loss']:.1f}%" if data["loss"] is not None else "—"
        self.metrics.setText(f"Разброс {jitter}   |   Тайм-ауты {loss}   ·   n={data['count']}" if tcp else
                             f"Джиттер {jitter}   |   Потери {loss}   ·   n={data['count']}")
        traffic = data["traffic"]
        self.traffic.setText(f"↓ {traffic[0]:.1f}   ↑ {traffic[1]:.1f} КиБ/с" if traffic else "↓ —   ↑ — КиБ/с")
        self.mini_traffic.setText(self.traffic.text())
        nodes = data.get("nodes", {})
        numbers = {}
        for role, name in (("target", "Цель"), ("gateway", "Шлюз"), ("control", "Сеть")):
            node = nodes.get(role)
            point = node["sample"] if node else sample if role == "target" else None
            numbers[role] = f"{point.rtt:.1f}" if point and point.rtt is not None else "!" if point and point.error else "—"
            if role in self.node_labels and node:
                loss_text = f"{node['loss']:.1f}%" if node["loss"] is not None else "—"
                self.node_labels[role].setText(f"{name} · {node['address']} · {numbers[role]} мс · потери {loss_text}")
                self.node_labels[role].setToolTip(point.error or f"ICMP, n={node['count']}. Независимая история этой точки.")
        self.mini_ping.setText(f"Цель {numbers['target']}   Шлюз {numbers['gateway']}   Сеть {numbers['control']} мс")
        self.mini_ping.setToolTip(f"Цель: {getattr(self,'_pending_host',None) or self._active_address} · {data.get('mode',self._active_mode).upper()}\n"
                                  "Шлюз и сеть: ICMP. ! — ошибка, — — нет ответа.\n" + data.get("diagnosis", ""))
        self.diagnosis.setText(data.get("diagnosis", "Накопление сравнительных измерений…"))
        self.mini_ping.setStyleSheet(f'color: {color}; font-size: 14px; font-weight: bold;')
        status = f"{getattr(self,'_pending_host',None) or self._active_address} · " + status
        self.monitor_status.setText(status + ("\n" + data["traffic_error"] if data["traffic_error"] else ""))
        self.monitor_status.setToolTip(self.monitor_status.text())
        if self.store is not None:
            self.store.append(self.session,data)
            if self.store.last_error or self.store.dropped_rows:
                self.history_status.setText(self.store.last_error or f'История: не записано строк {self.store.dropped_rows}')
            else:
                self.history_status.setText(f"История: {self.preferences['retention']} дней · P95 {data.get('p95',0) or 0:.1f} мс")
        if self.comparison_dialog is not None and self.comparison_dialog.isVisible():
            self.comparison_dialog.update_data(data)
        if self.preferences['alerts']:
            alert = self.alert_tracker.update(sample,data,time.monotonic())
            if alert:
                self.notify('Связь ухудшилась' if alert == 'degraded' else 'Связь восстановилась',
                            f"{getattr(self,'_pending_host',None) or self._active_address}: " + self.metrics.text())

    def show_processes(self):
        ProcessDialog(self).exec()

    def read_preferences(self):
        defaults = {'retention':7,'alerts':False,'rtt':150,'loss':5.0,'jitter':30}
        try:
            values = json.loads(self.settings.value('preferences/json','{}'))
            if not isinstance(values,dict):
                return defaults
            return {'retention':int(values.get('retention',7)) if values.get('retention',7) in (1,7,30) else 7,
                    'alerts':values.get('alerts') is True,
                    'rtt':max(20,min(2000,int(values.get('rtt',150)))),
                    'loss':max(.1,min(100,float(values.get('loss',5)))),
                    'jitter':max(1,min(1000,int(values.get('jitter',30))))}
        except (ValueError,TypeError,OverflowError):
            return defaults

    def start_session(self, host, mode, port, adapter):
        key = (self.profile_name,host,mode,port,adapter)
        if key == self._session_key:
            return
        self.alert_tracker = AlertTracker(self.preferences['rtt'],self.preferences['loss'],self.preferences['jitter'])
        if self.store is not None:
            try:
                self.store.end_session(self.session)
                self.session = self.store.start_session({'profile':self.profile_name,'host':host,'mode':mode,
                                                          'port':port,'adapter':adapter,'version':VERSION})
                self._session_key = key
            except Exception as exc:
                LOG.exception('Could not start session')
                self.action_status.setText('История: ' + str(exc))

    def refresh_profiles(self):
        current = self.profile_name
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItem('Без профиля', '')
        for profile in self.profiles.items:
            self.profile_combo.addItem(profile['name'],profile['name'])
        self.profile_combo.setCurrentIndex(max(0,self.profile_combo.findData(current)))
        self.profile_combo.blockSignals(False)

    def save_profile(self):
        name, accepted = QInputDialog.getText(self,'Сохранить профиль','Имя профиля (например, «Телефон USB»):',text=self.profile_name)
        if not accepted:
            return
        try:
            if any(item['name'] == name.strip() for item in self.profiles.items):
                if QMessageBox.question(self,'Заменить профиль','Профиль с таким именем уже есть. Заменить?',
                                        QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
                                        QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                    return
            self.profiles.save({'name':name,'host':self.address.text(),'adapter':self.adapters.currentData(),
                                'mode':self.mode.currentData(),'port':self.port.value(),'compare':self.comparison_hosts})
            self.profile_name = name.strip()
            self.refresh_profiles()
            self.apply_target()
            self.action_status.setText('Профиль сохранён: ' + self.profile_name)
        except Exception as exc:
            self.action_status.setText(str(exc))

    def load_profile(self):
        name = self.profile_combo.currentData() or ''
        self.profile_name = name
        profile = next((item for item in self.profiles.items if item['name'] == name),None)
        if self._restoring:
            return
        if profile is None:
            self.apply_target()
            return
        self._restoring = True
        self.refresh_adapters()
        self.address.setText(profile['host'])
        index = self.adapters.findData(profile['adapter'] or None)
        self.adapters.setCurrentIndex(max(0,index))
        self.mode.setCurrentIndex(1 if profile['mode'] == 'tcp' else 0)
        self.port.setValue(profile['port'])
        self.mode_changed()
        self._restoring = False
        self.apply_target()
        self.configure_comparison(profile['compare'])
        self.action_status.setText('Профиль применён: '+name if index >= 0 else 'Адаптер профиля недоступен: выбран общий режим.')

    def remove_profile(self):
        if not self.profile_name:
            return
        if QMessageBox.question(self,'Удалить профиль',f'Удалить профиль «{self.profile_name}»? История сессий сохранится.',
                                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.profiles.remove(self.profile_name)
            self.profile_name = ''
            self.refresh_profiles()
            self.apply_target()

    def show_preferences(self):
        dialog = PreferencesDialog(self.preferences,self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.preferences = dialog.values()
            self.settings.setValue('preferences/json',json.dumps(self.preferences))
            self.settings.sync()
            self.alert_tracker = AlertTracker(self.preferences['rtt'],self.preferences['loss'],self.preferences['jitter'])
            if self.store is not None:
                self.store.set_retention(self.preferences['retention'])
            self.action_status.setText('Настройки истории и уведомлений сохранены.')

    def show_history(self):
        if self.store is None:
            self.action_status.setText('История недоступна. Проверьте журнал ошибок.')
            return
        HistoryDialog(self.store,self).exec()

    def cancel_extra_lookups(self):
        self._extra_token += 1
        for ident, timer in self._extra_lookups.values():
            QHostInfo.abortHostLookup(ident)
            timer.stop()
            timer.deleteLater()
        self._extra_lookups.clear()

    def publish_extras(self):
        extras = [(host,*self._extra_results[host]) for host in self.comparison_hosts]
        self.generation = self.worker.set_extras(extras)

    def configure_comparison(self, hosts):
        try:
            hosts = list(dict.fromkeys(validate_target(host) for host in hosts))
            if len(hosts) > 5:
                raise ValueError('Допустимо до пяти дополнительных адресов')
        except (ValueError,TypeError) as exc:
            self.action_status.setText(str(exc))
            return
        self.cancel_extra_lookups()
        self.comparison_hosts = hosts
        self._extra_results = {}
        token = self._extra_token
        for host in hosts:
            try:
                ipaddress.IPv4Address(host)
                self._extra_results[host] = (host,'')
            except ValueError:
                self._extra_results[host] = (None,'DNS: определение адреса…')
                timer = QTimer(self)
                timer.setSingleShot(True)
                ident = QHostInfo.lookupHost(host,lambda info,h=host,t=token:self.extra_resolved(h,info,t))
                timer.timeout.connect(lambda h=host,t=token:self.extra_timeout(h,t))
                self._extra_lookups[host] = (ident,timer)
                timer.start(4000)
        self.publish_extras()
        self.settings.setValue('monitor/compare',json.dumps(hosts))

    def extra_resolved(self, host, info, token):
        if self._closing or token != self._extra_token or host not in self._extra_results:
            return
        pending = self._extra_lookups.pop(host,None)
        if pending:
            pending[1].stop()
            pending[1].deleteLater()
        addresses = [a.toString() for a in info.addresses() if a.protocol().value == 0]
        self._extra_results[host] = (str(addresses[0]),'') if addresses and info.error() == QHostInfo.HostInfoError.NoError else (None,'DNS: '+info.errorString())
        self.publish_extras()

    def extra_timeout(self, host, token):
        if self._closing or token != self._extra_token or host not in self._extra_lookups:
            return
        ident,timer = self._extra_lookups.pop(host)
        QHostInfo.abortHostLookup(ident)
        timer.deleteLater()
        self._extra_results[host] = (None,'DNS: тайм-аут определения имени')
        self.publish_extras()

    def show_comparison(self):
        if self.comparison_dialog is not None:
            self.comparison_dialog.show()
            self.comparison_dialog.raise_()
            return
        self.comparison_dialog = ComparisonDialog(self.comparison_hosts,self)
        self.comparison_dialog.selection_changed.connect(self.configure_comparison)
        if self._last_data:
            self.comparison_dialog.update_data(self._last_data)
        self.comparison_dialog.show()

    def init_tray(self):
        pixmap = QPixmap(32,32)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor('#44e6c3'))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(3,3,26,26)
        painter.end()
        root = Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1]))
        icon = QIcon(str(root/'assets'/'app.png'))
        self.setWindowIcon(icon if not icon.isNull() else QIcon(pixmap))
        self.tray = QSystemTrayIcon(self.windowIcon(),self)
        self.tray.setToolTip('JitterScope '+VERSION)
        self.tray_menu = QMenu()
        for text, callback in [('Показать / скрыть',self.toggle_visibility),('Полное окно',self.show_full),
                               ('Мини-панель',self.show_mini),('История / отчёты',self.show_history),
                               ('Открыть папку данных',self.open_data_directory),('О программе',self.show_about),('Выход',self.close)]:
            action = QAction(text,self)
            action.triggered.connect(callback)
            self.tray_menu.addAction(action)
        self.tray.setContextMenu(self.tray_menu)
        self.tray.activated.connect(lambda reason:self.toggle_visibility() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

    def toggle_visibility(self):
        self.hide() if self.isVisible() else self.show_normal()

    def show_normal(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def show_full(self):
        self.set_compact(False)
        self.show_normal()

    def show_mini(self):
        self.set_compact(True)
        self.show_normal()

    def minimize_to_tray(self):
        self.hide() if self.tray.isVisible() else self.showMinimized()

    def notify(self, title, message):
        self.alert_emitted.emit(title,message)
        self.action_status.setText(title + ': ' + message)
        LOG.info('Notification: %s %s',title,message)
        if self.tray.isVisible() and QSystemTrayIcon.supportsMessages():
            self.tray.showMessage(title,message,QSystemTrayIcon.MessageIcon.Warning if 'ухудшилась' in title else QSystemTrayIcon.MessageIcon.Information,5000)

    def open_data_directory(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.data_dir.resolve())))

    def show_about(self):
        QMessageBox.information(self,'О программе',f'JitterScope {VERSION}\n'
                                '© 2026 SanyLok — автор JitterScope.\n'
                                'Полностью бесплатная программа.\n\n'
                                'Лицензия кода: GNU GPLv3 (GPL-3.0-only). Полный текст: LICENSE в архиве.\n\n'
                                'Локальный монитор качества подключения. ICMP/TCP до диагностических узлов могут отличаться от пинга игры.\n\n'
                                f'История и журналы: {self.data_dir}\n'
                                'Компоненты: Python, PyQt6 / Qt6, icmplib, psutil. Тексты лицензий и сведения находятся в папке licenses архива.\n'
                                'Авторская отметка — текстовое указание авторства. Цифровая подпись Windows отсутствует.')

    def flush_dns(self):
        if self.dns.state() != QProcess.ProcessState.NotRunning:
            return
        self.dns_timed_out = False
        self.flush_button.setEnabled(False)
        self.action_status.setText("Очистка DNS-кэша…")
        executable = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "ipconfig.exe")
        self.dns.start(executable, ["/flushdns"])
        self.dns_timer.start(8000)

    def dns_finished(self, code, status):
        self.dns_timer.stop()
        self.flush_button.setEnabled(not self._closing and sys.platform == "win32")
        if self._closing:
            self.try_finish_close()
            return
        if self.dns_timed_out:
            self.action_status.setText("Очистка DNS превысила 8 секунд и остановлена.")
        elif code == 0 and status == QProcess.ExitStatus.NormalExit:
            self.action_status.setText("DNS-кэш очищен. Задержка до IP от этого обычно не меняется.")
        else:
            self.action_status.setText(f"DNS не очищен (код {code}). Возможно, недостаточно прав.")

    def dns_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.dns_timer.stop()
            self.flush_button.setEnabled(not self._closing and sys.platform == "win32")
            self.action_status.setText("Не удалось запустить ipconfig: " + self.dns.errorString())
            if self._closing:
                self.try_finish_close()

    def dns_timeout(self):
        if self.dns.state() != QProcess.ProcessState.NotRunning:
            self.dns_timed_out = True
            self.dns.kill()

    def set_pinned(self, enabled):
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        if not self._restoring:
            self.show()

    def fit_on_screen(self):
        screen = next((s for s in QApplication.screens() if s.availableGeometry().contains(self.pos())),
                      QApplication.primaryScreen())
        if screen is None:
            return
        area = screen.availableGeometry()
        if not self.compact:
            self.resize(min(self.width(), area.width()), min(self.height(), max(320, area.height() - 16)))
        self.move(max(area.left(), min(self.x(), area.right() - self.width() + 1)),
                  max(area.top(), min(self.y(), area.bottom() - self.height() + 1)))

    def set_compact(self, enabled):
        if enabled == self.compact:
            return
        if enabled:
            self._full_size = self.size()
        self.compact = enabled
        self.details.setVisible(not enabled)
        self.mini.setVisible(enabled)
        self.setMinimumSize(360 if enabled else 440, 0 if enabled else 320)
        self.layout().activate()
        self.resize(QSize(420, 138) if enabled else self._full_size)
        self._drag_pos = None
        self.fit_on_screen()

    def eventFilter(self, obj, event):
        if obj is self.header and event.type() == QEvent.Type.MouseButtonDblClick and event.button() == Qt.MouseButton.LeftButton:
            self.set_compact(not self.compact)
            return True
        return super().eventFilter(obj, event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def closeEvent(self, event):
        self.comparison_retry_timer.stop()
        busy_reports = False
        for dialog in self.findChildren(HistoryDialog):
            dialog.close()
            busy_reports = busy_reports or any(job is not None and job.isRunning() for job in (dialog.job,dialog.chart_job))
        if busy_reports:
            event.ignore()
            self._closing = True
            self.worker.request_stop()
            self.cancel_lookup()
            self.cancel_extra_lookups()
            self.dns_timer.stop()
            if self.dns.state() != QProcess.ProcessState.NotRunning:
                self.dns.kill()
            QTimer.singleShot(50,self.try_finish_close)
            return
        if self.worker.isRunning() or self.dns.state() != QProcess.ProcessState.NotRunning:
            event.ignore()
            if not self._closing:
                self._closing = True
                self.cancel_lookup()
                self.cancel_extra_lookups()
                self.setEnabled(False)
                self.monitor_status.setText("Завершение измерения…")
                self.worker.request_stop()
                self.dns_timer.stop()
                if self.dns.state() != QProcess.ProcessState.NotRunning:
                    self.dns.kill()
            QTimer.singleShot(25, self.try_finish_close)
        elif self.store is not None and not self._storage_closed:
            event.ignore()
            self._closing = True
            self.cancel_lookup()
            self.cancel_extra_lookups()
            self.setEnabled(False)
            self.monitor_status.setText('Сохранение последних измерений…')
            if self._storage_closer is None:
                self._storage_closer = StorageCloser(self.store,self.session,self)
                self._storage_closer.finished.connect(self.history_closed)
                self._storage_closer.start()
        else:
            self.cancel_lookup()
            self.cancel_extra_lookups()
            self.save_settings()
            if hasattr(self,'tray'):
                self.tray.hide()
            if self.comparison_dialog is not None:
                self.comparison_dialog.close()
            event.accept()

    def history_closed(self):
        self._storage_closed = True
        if self._storage_closer.error:
            LOG.error('History shutdown: %s',self._storage_closer.error)
        self.close()

    def worker_finished(self):
        if self._closing:
            QTimer.singleShot(0, self.try_finish_close)

    def try_finish_close(self):
        if self._closing and not self.worker.isRunning() and self.dns.state() == QProcess.ProcessState.NotRunning:
            self.close()
        elif self._closing:
            QTimer.singleShot(50, self.try_finish_close)

