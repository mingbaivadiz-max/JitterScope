# Corresponding third-party sources

JitterScope source code is distributed with this release. Its build recipe is `JitterScope.spec` and pinned runtime dependencies are in `requirements.txt`. No changes were made to the third-party libraries listed below.

The following designated upstream locations provide the corresponding source archives for the versions used in the Windows build. Downloads from these locations are free of charge. The PyQt6 wheel bundles Qt separately; both source archives are listed. Preserve the source access and third-party notices when redistributing a binary release.

- **PyQt6 6.11.0:** [pyqt6-6.11.0.tar.gz](https://files.pythonhosted.org/packages/8b/47/b25c13eca5bebc6505394d0223e46d7ebf0c57dcac2ed908d7d19b18ab6b/pyqt6-6.11.0.tar.gz) — SHA-256 `45dd60aa69976de1918b5ced6b4e7b6a25abd2a919ecef5fd5826ecc76718889`.
- **PyQt6-sip 13.13.0:** [pyqt6_sip-13.13.0.tar.gz](https://files.pythonhosted.org/packages/78/35/bed43ff7cf040ced6b62a17b272abecb94914755284b54e8d06844e1ed23/pyqt6_sip-13.13.0.tar.gz) — SHA-256 `2cd55f575cde208c398d6cfdecc5a13394ed2afb54226210c50e3a6df7c3a997`.
- **icmplib 3.0.4:** [icmplib-3.0.4.tar.gz](https://files.pythonhosted.org/packages/6d/78/ca07444be85ec718d4a7617f43fdb5b4eaae40bc15a04a5c888b64f3e35f/icmplib-3.0.4.tar.gz) — SHA-256 `57868f2cdb011418c0e1d5586b16d1fabd206569fe9652654c27b6b2d6a316de`.
- **psutil 7.2.2:** [psutil-7.2.2.tar.gz](https://files.pythonhosted.org/packages/aa/c6/d1ddf4abb55e93cebc4f2ed8b5d6dbad109ecb8d63748dd2b20ab5e57ebe/psutil-7.2.2.tar.gz) — SHA-256 `0746f5f8d406af344fd547f1c8daa5f5c33dbc293bb8d6a16d80b4bb88f59372`.
- **PyInstaller 6.22.3:** [pyinstaller-6.22.3.tar.gz](https://files.pythonhosted.org/packages/63/41/f90302845945abd4ed647933ff5ee7c6ac93983187be67f897b6cb613331/pyinstaller-6.22.3.tar.gz) — SHA-256 `05eb2f5615503e72939a7224d68b4aff572c6b0438ee4a17d0a4b481f399362d`.
- **Qt 6.11.2:** [source archive](https://download.qt.io/archive/qt/6.11/6.11.2/single/qt-everywhere-src-6.11.2.tar.xz).
- **Python 3.12.14:** [source archive](https://www.python.org/ftp/python/3.12.14/Python-3.12.14.tar.xz).

Qt third-party licensing information: [Qt 6 licensing](https://doc.qt.io/qt-6/licensing.html) and the LICENSES/REUSE information in the corresponding Qt source archive. Python license notices are also provided in `licenses/PYTHON-LICENSE.txt`. PyInstaller uses GPL with its bootloader exception; see its source distribution for the complete terms.

For rebuilding, use Windows x64 with Python 3.12, install requirements and PyInstaller 6.22.3, then run `python -m PyInstaller JitterScope.spec`. A developer certificate is not needed to build an unsigned EXE.
