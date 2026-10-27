# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 SanyLok
from __future__ import annotations
import os
import psutil
from datetime import datetime
from PyQt6.QtCore import QPoint, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QDialogButtonBox, QMessageBox, QWidget)
from .model import WINDOW
PROCESS_NAMES = {'onedrive.exe', 'qbittorrent.exe', 'dropbox.exe', 'googledrivefs.exe', 'eadesktop.exe', 'utorrent.exe', 'yandexdisk2.exe', 'epicgameslauncher.exe', 'battle.net.exe'}
class TimelineGraph(QWidget):
    def __init__(self):
        super().__init__()
        self.points = []
        self.setMinimumHeight(160)
        self.setToolTip('История выбранной цели за всю сессию. До 600 интервалов; в каждом показана максимальная задержка. Красная риска — тайм-аут, жёлтая — ошибка.')

    def set_points(self, points):
        self.points = points
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(QFont('Segoe UI',8))
        painter.setPen(QColor('#b5b0c8'))
        if not self.points:
            painter.drawText(self.rect(),Qt.AlignmentFlag.AlignCenter,'Выберите сессию: здесь появится история задержки')
            return
        area = QRectF(42,12,max(1,self.width()-54),self.height()-62)
        ceiling = max(100,max((p['rtt'] or 0 for p in self.points),default=0)*1.15)
        first,last = self.points[0]['timestamp'],self.points[-1]['timestamp']
        duration = max(.001,last-first)
        for fraction in (0,.5,1):
            y = area.bottom()-fraction*area.height()
            painter.setPen(QPen(QColor('#39344d'),1))
            painter.drawLine(QPoint(int(area.left()),int(y)),QPoint(int(area.right()),int(y)))
            painter.setPen(QColor('#b5b0c8'))
            painter.drawText(QRectF(0,y-8,36,16),Qt.AlignmentFlag.AlignRight,f'{ceiling*fraction:.0f}')
        path = QPainterPath()
        connected = False
        for point in self.points:
            x = area.left()+(point['timestamp']-first)/duration*area.width()
            if point['loss'] or point['error']:
                painter.setPen(QPen(QColor('#ff6289' if point['loss'] else '#ffc857'),2))
                painter.drawLine(QPoint(int(x),int(area.bottom()-7)),QPoint(int(x),int(area.bottom())))
                connected = False
            if point['rtt'] is not None:
                y = area.bottom()-point['rtt']/ceiling*area.height()
                path.lineTo(x,y) if connected else path.moveTo(x,y)
                connected = True
            else:
                connected = False
        painter.setPen(QPen(QColor('#44e6c3'),1.5))
        painter.drawPath(path)
        painter.setPen(QColor('#b5b0c8'))
        painter.drawText(QRectF(area.left(),area.bottom()+8,area.width(),18),Qt.AlignmentFlag.AlignLeft,
                         datetime.fromtimestamp(first).strftime('%m-%d %H:%M'))
        painter.drawText(QRectF(area.left(),area.bottom()+8,area.width(),18),Qt.AlignmentFlag.AlignRight,
                         datetime.fromtimestamp(last).strftime('%m-%d %H:%M'))
        painter.drawText(QRectF(area.left(),area.bottom()+27,area.width(),18),Qt.AlignmentFlag.AlignCenter,
                         'Пиковая задержка по интервалам, мс')


class HistoryGraph(QWidget):
    def __init__(self):
        super().__init__()
        self.samples = ()
        self.caption = "ICMP RTT, мс"
        self.setMinimumHeight(150)
        self.setToolTip("Линия — задержка. Красная риска — тайм-аут. Жёлтая — ошибка измерения.\n"
                        "Джиттер ниже: средняя разность соседних успешных RTT; разрывы не соединяются.")

    def set_mode(self, mode):
        self.caption = "Время TCP-подключения, мс" if mode == "tcp" else "ICMP RTT, мс"
        self.update()

    def set_samples(self, samples):
        self.samples = samples
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = QRectF(42, 15, max(1, self.width() - 54), self.height() - 60)
        values = [s.rtt for s in self.samples if s.rtt is not None]
        ceiling = max(100, max(values, default=0) * 1.2)
        painter.setFont(QFont("Segoe UI", 8))
        for fraction in (0, .5, 1):
            y = area.bottom() - fraction * area.height()
            painter.setPen(QPen(QColor("#39344d"), 1))
            painter.drawLine(QPoint(int(area.left()), int(y)), QPoint(int(area.right()), int(y)))
            painter.setPen(QColor("#b5b0c8"))
            painter.drawText(QRectF(0, y - 8, 37, 16), Qt.AlignmentFlag.AlignRight,
                             f"{ceiling * fraction:.0f}")
        path = QPainterPath()
        connected = False
        points = []
        for index, sample in enumerate(self.samples):
            x = area.right() - (len(self.samples) - 1 - index) * area.width() / (WINDOW - 1)
            if sample.rtt is None:
                connected = False
                painter.setPen(QPen(QColor("#ffc857" if sample.error else "#ff6289"), 2))
                painter.drawLine(QPoint(int(x), int(area.bottom() - 8)), QPoint(int(x), int(area.bottom())))
            else:
                y = area.bottom() - sample.rtt / ceiling * area.height()
                if connected:
                    path.lineTo(x, y)
                else:
                    path.moveTo(x, y)
                points.append((x, y))
                connected = True
        painter.setPen(QPen(QColor("#44e6c3"), 2))
        painter.drawPath(path)
        painter.setBrush(QColor("#44e6c3"))
        for x, y in points:
            painter.drawEllipse(QRectF(x - 2, y - 2, 4, 4))
        painter.setPen(QColor("#b5b0c8"))
        painter.drawText(QRectF(area.left(), area.bottom() + 8, area.width(), 20),
                         Qt.AlignmentFlag.AlignCenter, f"{self.caption} · окно 60")



class ProcessDialog(QDialog):
    """User-selected candidates. Does not claim to measure per-process bandwidth."""
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Выберите приложения для завершения")
        self.resize(520, 380)
        layout = QVBoxLayout(self)
        label = QLabel("Это известные загрузчики и клиенты синхронизации.\n"
                       "Их реальный сетевой трафик здесь не измеряется.\n"
                       "Завершение принудительное: сохраните работу и отметьте нужные.")
        label.setWordWrap(True)
        layout.addWidget(label)
        self.items = QListWidget()
        layout.addWidget(self.items)
        self.populate()
        self.result_label = QLabel("")
        self.result_label.setWordWrap(True)
        layout.addWidget(self.result_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText('Закрыть')
        buttons.rejected.connect(self.reject)
        self.kill_button = buttons.addButton("Завершить выбранные", QDialogButtonBox.ButtonRole.ActionRole)
        self.kill_button.clicked.connect(self.finish_selected)
        layout.addWidget(buttons)

    def populate(self):
        self.items.clear()
        for proc in psutil.process_iter(["pid", "name", "create_time"]):
            try:
                name = proc.info["name"] or ""
                if name.casefold() not in PROCESS_NAMES or proc.pid == os.getpid():
                    continue
                item = QListWidgetItem(f"{name}   ·   PID {proc.pid}")
                item.setData(Qt.ItemDataRole.UserRole, (proc.pid, proc.info["create_time"], name))
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked)
                self.items.addItem(item)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        if not self.items.count():
            self.items.addItem("Приложения из списка не найдены.")

    def finish_selected(self):
        selected = [self.items.item(i).data(Qt.ItemDataRole.UserRole)
                    for i in range(self.items.count())
                    if self.items.item(i).checkState() == Qt.CheckState.Checked]
        if not selected:
            self.result_label.setText("Сначала отметьте приложения.")
            return
        if QMessageBox.warning(self, "Принудительное завершение",
                               f"Завершить выбранные процессы ({len(selected)})?\n"
                               "Несохранённые данные могут быть потеряны.",
                               QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                               QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        completed, gone, failed = 0, 0, []
        for pid, created, name in selected:
            try:
                proc = psutil.Process(pid)
                if created is None or proc.create_time() != created or proc.name().casefold() != name.casefold():
                    failed.append(f"PID {pid}: процесс изменился")
                    continue
                proc.kill()
                completed += 1
            except psutil.NoSuchProcess:
                gone += 1
            except psutil.AccessDenied:
                failed.append(f"{name}: нет доступа")
            except OSError as exc:
                failed.append(f"{name}: {exc}")
        self.populate()
        self.result_label.setText(f"Команда завершения отправлена: {completed}. Уже закрыты: {gone}.\n"
                                  + "\n".join(failed))

