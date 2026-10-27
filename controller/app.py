# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 SanyLok
from __future__ import annotations
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
from PyQt6.QtCore import QLockFile, QStandardPaths
from PyQt6.QtWidgets import QApplication, QMessageBox
from .model import VERSION


def data_directory():
    override = os.environ.get('JITTERSCOPE_DATA_DIR') or os.environ.get('USB_NET_DATA_DIR')
    return Path(override) if override else Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))


def setup_logging(directory):
    directory = Path(directory) / 'logs'
    directory.mkdir(parents=True,exist_ok=True)
    handler = RotatingFileHandler(directory/'controller.log',maxBytes=2_000_000,backupCount=3,encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s'))
    logger = logging.getLogger('usb_net')
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    def exception_hook(kind, value, traceback):
        logger.critical('Unhandled exception',exc_info=(kind,value,traceback))
        sys.__excepthook__(kind,value,traceback)
    sys.excepthook = exception_hook
    logger.info('Starting JitterScope %s',VERSION)
    return handler


def main():
    app = QApplication(sys.argv)
    app.setOrganizationName('USBNetController')
    app.setApplicationName('DesktopWidget')
    app.setApplicationVersion(VERSION)
    directory = data_directory()
    try:
        directory.mkdir(parents=True,exist_ok=True)
        log_handler = setup_logging(directory)
    except OSError as exc:
        QMessageBox.critical(None,'Не удалось запустить',f'Нет доступа к папке данных:\n{directory}\n{exc}')
        return 1
    lock = QLockFile(str(directory/'instance.lock'))
    if not lock.tryLock(100):
        QMessageBox.information(None,'Программа уже запущена','Проверьте открытое окно или значок JitterScope в трее.')
        return 0
    from .ui import PingControllerWidget
    window = PingControllerWidget(data_dir=directory)
    window.show()
    result = app.exec()
    lock.unlock()
    log_handler.close()
    return result
