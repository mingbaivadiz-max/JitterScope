# Сторонние компоненты

Приложение использует Python, PyQt6 / Qt6, PyQt6-sip, icmplib и psutil. Тексты лицензий, найденные в установленных дистрибутивах, включены в папку `licenses`; точные версии и пути перечислены в `licenses/manifest.json`.

Собственный код JitterScope: Copyright (C) 2026 SanyLok, GPL-3.0-only (см. `LICENSE`). Исходники точных версий сторонних библиотек доступны по ссылкам в `DEPENDENCY_SOURCES.md`.

| Компонент | Версия сборки | Документ из дистрибутива |
|---|---|---|
| Python | 3.12.14 | licenses/PYTHON-LICENSE.txt |
| PyQt6 | 6.11.0 | licenses/PyQt6/…/LICENSE — GNU GPL v3 |
| Qt6 | 6.11.2 | licenses/PyQt6-Qt6/…/LICENSE — GNU LGPL v3 |
| PyQt6-sip | 13.13.0 | licenses/PyQt6-sip/…/LICENSE — BSD-style text |
| icmplib | 3.0.4 | licenses/icmplib/…/LICENSE — GNU LGPL v3 |
| psutil | 7.2.2 | licenses/psutil/…/LICENSE — BSD 3-Clause |

Авторские уведомления сохранены в оригинальных текстах. Qt включает собственные сторонние компоненты; перед публичным выпуском нужно завершить проверку их уведомлений, соответствующих исходников и условий выбранного способа распространения. Этот перечень не объявляет всю будущую коммерческую поставку проверенной на соблюдение лицензий.

Официальные источники:

- [Riverbank: введение и лицензия PyQt](https://www.riverbankcomputing.com/software/pyqt/intro)
- [Riverbank: FAQ по лицензированию](https://www.riverbankcomputing.com/commercial/license-faq)
- [Qt: обязательства GPL/LGPL](https://www.qt.io/development/open-source-lgpl-obligations)
- [Qt: сторонние лицензии](https://doc.qt.io/qt-6/licenses-used-in-qt.html)
- [icmplib](https://github.com/ValentinBELYN/icmplib)
- [psutil](https://github.com/giampaolo/psutil)

PyInstaller используется как инструмент сборки и не входит в зависимости исходного приложения. Сведения о его загрузчике: [PyInstaller license](https://pyinstaller.org/en/stable/license.html).
