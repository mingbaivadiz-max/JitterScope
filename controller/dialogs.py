# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 SanyLok
from __future__ import annotations
import json
from datetime import datetime
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout)
from server_catalog import PRESETS, BY_HOST
from .widgets import TimelineGraph


def number(value):
    return '—' if value is None else f'{value:.1f}'


class ReportJob(QThread):
    completed = pyqtSignal(object)

    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation = operation

    def run(self):
        try:
            self.completed.emit({'value':self.operation()})
        except Exception as exc:
            self.completed.emit({'error':str(exc)})


class ComparisonDialog(QDialog):
    selection_changed = pyqtSignal(list)

    def __init__(self, selected, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Сравнение игровых регионов')
        self.resize(820, 700)
        layout = QVBoxLayout(self)
        info = QLabel('Выберите до пяти дополнительных адресов. Они проверяются по ICMP одновременно с основной целью.\n'
                      'Результат зависит от маршрута; UDP/SDR и фактический сервер матча могут отличаться.')
        info.setWordWrap(True)
        layout.addWidget(info)
        self.list = QListWidget()
        self.list.setMaximumHeight(200)
        for preset in PRESETS:
            item = QListWidgetItem(preset['name'])
            item.setData(Qt.ItemDataRole.UserRole, preset['host'])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if preset['host'] in selected else Qt.CheckState.Unchecked)
            item.setToolTip(preset['note'])
            self.list.addItem(item)
        layout.addWidget(self.list)
        row = QHBoxLayout()
        start = QPushButton('Применить выбор')
        start.clicked.connect(self.apply)
        row.addWidget(start)
        stop = QPushButton('Остановить дополнительные проверки')
        stop.clicked.connect(self.stop)
        row.addWidget(stop)
        layout.addLayout(row)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(['Узел', 'Сейчас, мс', 'Среднее', 'P95', 'Потери / ТА, %', 'n', 'Режим'])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setWordWrap(False)
        layout.addWidget(self.table, 1)
        self.status = QLabel('Для сравнения накопите хотя бы пять успешных ответов каждой выбранной точки.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.button(QDialogButtonBox.StandardButton.Close).setText('Закрыть')
        close.rejected.connect(self.close)
        layout.addWidget(close)

    def apply(self):
        hosts = [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())
                 if self.list.item(i).checkState() == Qt.CheckState.Checked]
        if len(hosts) > 5:
            self.status.setText('Допустимо до пяти дополнительных узлов. Снимите лишние отметки.')
            return
        self.selection_changed.emit(hosts)

    def stop(self):
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(Qt.CheckState.Unchecked)
        self.selection_changed.emit([])

    def update_data(self, data):
        nodes = data.get('nodes', {})
        self.table.setRowCount(len(nodes))
        candidates = []
        for row, (role, node) in enumerate(nodes.items()):
            host = role.removeprefix('compare:')
            title = BY_HOST.get(host, {}).get('name', host) if role.startswith('compare:') else {'target':'Выбранная цель','gateway':'Шлюз','control':'Контроль'}.get(role, role)
            sample = node['sample']
            values = [title, number(sample.rtt) if not sample.error else 'Ошибка', number(node['avg']),
                      number(node['p95']), number(node['loss']), str(node['count']), node.get('mode','icmp').upper()]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(sample.error or f"{node['address']} · Успешных ответов: {node['received']}")
                self.table.setItem(row, column, item)
            if role.startswith('compare:') and node.get('mode') == 'icmp' and node['received'] >= 5 and not sample.error and sample.rtt is not None:
                candidates.append((node['loss'] or 0, node['avg'], title))
        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(0, min(300, self.table.columnWidth(0)))
        if candidates:
            candidates.sort()
            self.status.setText(f'Среди дополнительных узлов с ≥5 ответами сейчас меньше потерь/средней задержки: {candidates[0][2]}. '
                                'Это сравнение диагностических точек за скользящее окно, не гарантия пинга матча.')


class HistoryDialog(QDialog):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.job = None
        self._close_requested = False
        self.chart_job = None
        self._chart_serial = 0
        self._pending_chart = None
        self.setWindowTitle('История и отчёты')
        self.resize(950, 650)
        layout = QVBoxLayout(self)
        self.info = QLabel('Выберите сессию для отчёта или две сессии для сравнения. Время показано в часовом поясе Windows.')
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(['Начало', 'Профиль', 'Цель', 'Режим', 'Измерений цели', 'Состояние'])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self.select_session)
        layout.addWidget(self.table, 1)
        self.chart = TimelineGraph()
        layout.addWidget(self.chart)
        row = QHBoxLayout()
        for title, callback in [('Обновить', self.refresh), ('Сравнить две сессии', self.compare), ('Экспорт CSV + HTML…', self.export)]:
            button = QPushButton(title)
            button.clicked.connect(callback)
            row.addWidget(button)
        layout.addLayout(row)
        self.summary = QTableWidget(0, 7)
        self.summary.setHorizontalHeaderLabels(['Сессия / точка','Среднее','P50','P95','Потери / ТА, %','Ошибки','n'])
        self.summary.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.summary.setMaximumHeight(200)
        layout.addWidget(self.summary)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.button(QDialogButtonBox.StandardButton.Close).setText('Закрыть')
        close.rejected.connect(self.close)
        layout.addWidget(close)
        self.refresh()

    def refresh(self):
        try:
            self.store.flush()
            self.sessions = self.store.list_sessions()
            self.table.setRowCount(len(self.sessions))
            for row, session in enumerate(self.sessions):
                settings = json.loads(session['metadata'])
                values = [datetime.fromtimestamp(session['started']).strftime('%Y-%m-%d %H:%M:%S'),
                          settings.get('profile') or 'Без профиля', settings.get('host',''), settings.get('mode','icmp').upper(),
                          str(session['attempts']), {'complete':'Завершена','interrupted':'Прервана','active':'Активна'}.get(session.get('status'),'Неизвестно')]
                for column, value in enumerate(values):
                    self.table.setItem(row,column,QTableWidgetItem(value))
            self.table.resizeColumnsToContents()
        except Exception as exc:
            self.info.setText(str(exc))

    def chosen(self):
        return [self.sessions[index.row()] for index in self.table.selectionModel().selectedRows()]

    def select_session(self):
        chosen = self.chosen()
        self._chart_serial += 1
        if len(chosen) != 1:
            self.chart.set_points([])
            self._pending_chart = None
            return
        self._pending_chart = (chosen[0]['id'],self._chart_serial)
        self.start_chart_job()

    def start_chart_job(self):
        if self._pending_chart is None or self._close_requested or (self.chart_job is not None and self.chart_job.isRunning()):
            return
        session,serial = self._pending_chart
        self._pending_chart = None
        self.chart_job = ReportJob(lambda:self.store.chart_points(session),self)
        self.chart_job.completed.connect(lambda result:self.chart_ready(result,serial))
        self.chart_job.finished.connect(self.chart_finished)
        self.chart_job.start()

    def chart_ready(self, result, serial):
        if serial != self._chart_serial:
            return
        if 'value' in result:
            self.chart.set_points(result['value'])
        else:
            self.info.setText('Ошибка чтения графика: '+result['error'])

    def chart_finished(self):
        job,self.chart_job = self.chart_job,None
        if job is not None:
            job.deleteLater()
        self.start_chart_job()
        self.after_job()

    def compare(self):
        if self.job is not None and self.job.isRunning():
            return
        chosen = self.chosen()
        if len(chosen) != 2:
            self.info.setText('Выберите ровно две строки с помощью Ctrl + клик.')
            return
        first,second = chosen[0]['id'],chosen[1]['id']
        self.info.setText('Расчёт статистики двух сессий…')
        def operation():
            self.store.flush()
            return self.store.compare_sessions(first,second)
        self.job = ReportJob(operation,self)
        self.job.completed.connect(self.comparison_finished)
        self.job.finished.connect(self.export_job_stopped)
        self.job.start()

    def comparison_finished(self, result):
        try:
            if 'error' in result:
                raise OSError(result['error'])
            comparison = result['value']
            self.summary.setRowCount(2)
            for row, item in enumerate(comparison):
                stats = item['stats']
                values = [item['settings'].get('profile') or item['settings'].get('host',''), number(stats['avg']),
                          number(stats['p50']), number(stats['p95']), number(stats['loss']), str(stats['errors']), str(stats['count'])]
                for column, value in enumerate(values):
                    self.summary.setItem(row,column,QTableWidgetItem(value))
            self.summary.resizeColumnsToContents()
            self.info.setText('Сравнение сохранённых измерений цели. Учитывайте разные адреса, протоколы, время и условия подключения.')
        except Exception as exc:
            self.info.setText(str(exc))

    def export(self):
        if self.job is not None and self.job.isRunning():
            return
        chosen = self.chosen()
        if len(chosen) != 1:
            self.info.setText('Выберите одну сессию для экспорта.')
            return
        directory = QFileDialog.getExistingDirectory(self, 'Куда сохранить отчёт')
        if not directory:
            return
        self.info.setText('Подготовка CSV и HTML в фоновом потоке…')
        session_id = chosen[0]['id']
        self.job = ReportJob(lambda:self.store.export_session(session_id,directory),self)
        self.job.completed.connect(self.export_finished)
        self.job.finished.connect(self.export_job_stopped)
        self.job.start()

    def export_finished(self, result):
        if 'error' in result:
            self.info.setText('Не удалось сохранить отчёт: '+result['error'])
        else:
            csv_path,html_path = result['value']
            self.info.setText(f'Сохранены:\n{csv_path}\n{html_path}')

    def after_job(self):
        if self._close_requested:
            self.close()

    def export_job_stopped(self):
        job,self.job = self.job,None
        if job is not None:
            job.deleteLater()
        self.after_job()

    def closeEvent(self, event):
        if (self.job is not None and self.job.isRunning()) or (self.chart_job is not None and self.chart_job.isRunning()):
            self._close_requested = True
            self.info.setText('Отчёт ещё сохраняется. Окно закроется после завершения.')
            event.ignore()
        else:
            event.accept()


class PreferencesDialog(QDialog):
    def __init__(self, preferences, parent=None):
        super().__init__(parent)
        self.setWindowTitle('История и уведомления')
        self.resize(490, 340)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.retention = QComboBox()
        for days in (1,7,30):
            self.retention.addItem(f'{days} дней', days)
        self.retention.setCurrentIndex(max(0,self.retention.findData(preferences['retention'])))
        form.addRow('Хранить историю', self.retention)
        self.enabled = QCheckBox('Уведомлять об ухудшении и восстановлении')
        self.enabled.setChecked(preferences['alerts'])
        form.addRow(self.enabled)
        self.rtt = QSpinBox()
        self.rtt.setRange(20,2000)
        self.rtt.setValue(preferences['rtt'])
        form.addRow('Порог задержки, мс', self.rtt)
        self.loss = QDoubleSpinBox()
        self.loss.setRange(.1,100)
        self.loss.setValue(preferences['loss'])
        form.addRow('Порог потерь / тайм-аутов, %', self.loss)
        self.jitter = QSpinBox()
        self.jitter.setRange(1,1000)
        self.jitter.setValue(preferences['jitter'])
        form.addRow('Порог разброса, мс', self.jitter)
        layout.addLayout(form)
        note = QLabel('Ухудшение: 3 последовательных плохих оценки после накопления ≥5 попыток. '
                      'Восстановление: 5 хороших оценок. Повторные предупреждения ограничены интервалом 2 минуты. '
                      'Уведомления относятся к выбранной цели. История локальная; при 30 днях база может занимать сотни мегабайт и больше.')
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Сохранить')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('Отмена')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self):
        return {'retention':self.retention.currentData(), 'alerts':self.enabled.isChecked(),
                'rtt':self.rtt.value(),'loss':self.loss.value(),'jitter':self.jitter.value()}
