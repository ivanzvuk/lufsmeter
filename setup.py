"""
Setup script для создания macOS .app бандла через py2app.

Использование:
  python setup.py py2app

Требования:
  pip install py2app

Перед сборкой установите зависимости:
  pip install numpy PyQt5 pyaudio scipy opencv-python
  brew install portaudio ffmpeg
"""
import sys
import os
from setuptools import setup

APP = ['lufsmeter_mac.py']
APP_NAME = "LUFS Meter"

OPTIONS = {
    'argv_emulation': True,
    'packages': [
        'numpy',
        'scipy',
        'PyQt5',
        'pyaudio',
    ],
    'includes': [
        'scipy.signal',
        'scipy.signal.signaltools',
        'scipy.signal.windows',
        'scipy.signal._spectral',
        'scipy._lib',
        'scipy._lib._ccallback_c',
        'scipy.sparse.linalg.isolve.iterative',
        'scipy.linalg',
        'scipy.linalg.cython_blas',
        'scipy.linalg.cython_lapack',
        'scipy.sparse',
        'scipy.special',
        'scipy.optimize',
        'scipy.fft',
    ],
    'excludes': [
        'tkinter',
        'matplotlib',
        'cv2',
        'audioop',
    ],
    'plist': {
        'CFBundleName': APP_NAME,
        'CFBundleDisplayName': APP_NAME,
        'CFBundleIdentifier': 'com.lufsmeter.app',
        'CFBundleVersion': '1.0.0',
        'CFBundleShortVersionString': '1.0.0',
        'NSHighResolutionCapable': True,
        'NSMicrophoneUsageDescription': 'Приложению нужен доступ к микрофону для измерения уровня громкости.',
    },
    'iconfile': 'icon.icns' if os.path.exists('icon.icns') else None,
}

setup(
    name=APP_NAME,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
