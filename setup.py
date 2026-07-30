"""
Сборка macOS .app бандла.

ВАЖНО: Рекомендуется использовать PyInstaller вместо py2app.
Выполните build_mac.sh или напрямую:

  pip install pyinstaller numpy scipy PyQt5 sounddevice zeroconf
  python create_icon_mac.py
  pyinstaller --windowed --onedir --name "LUFS Meter" --icon icon.icns \
    --osx-bundle-identifier com.lufsmeter.app \
    --collect-all PyQt5 --collect-all scipy --collect-all numpy \
    --hidden-import scipy.signal --hidden-import scipy.special \
    --hidden-import scipy.sparse --hidden-import scipy.fft \
    --hidden-import scipy.linalg --hidden-import scipy.optimize \
    --hidden-import scipy._lib --hidden-import sounddevice \
    --hidden-import zeroconf \
    --exclude-module tkinter --exclude-module matplotlib \
    lufsmeter.py

py2app (legacy, не рекомендуется для Apple Silicon):
  pip install py2app
  python setup.py py2app
"""
from setuptools import setup

APP = ['lufsmeter.py']
APP_NAME = "LUFS Meter"

OPTIONS = {
    'argv_emulation': False,
    'packages': [
        'numpy', 'scipy', 'PyQt5', 'sounddevice', 'zeroconf',
    ],
    'includes': [
        'scipy.signal', 'scipy.special', 'scipy.sparse',
        'scipy.fft', 'scipy.linalg', 'scipy.optimize',
        'scipy._lib', 'scipy._lib._ccallback_c',
        'sounddevice', 'zeroconf',
    ],
    'excludes': ['tkinter', 'matplotlib', 'PIL', 'cv2'],
    'plist': {
        'CFBundleName': APP_NAME,
        'CFBundleDisplayName': APP_NAME,
        'CFBundleIdentifier': 'com.lufsmeter.app',
        'CFBundleVersion': '11.0.0',
        'CFBundleShortVersionString': '11.0.0',
        'NSHighResolutionCapable': True,
        'NSMicrophoneUsageDescription': 'Доступ к микрофону для измерения громкости.',
    },
}

setup(
    name=APP_NAME,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
