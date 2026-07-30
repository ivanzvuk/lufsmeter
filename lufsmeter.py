import sys
import platform
import numpy as np
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QGroupBox, QCheckBox, QComboBox, QDoubleSpinBox, QLabel, QPushButton,
                             QScrollArea, QGridLayout, QSpinBox, QSizePolicy, QSplitter,
                             QMessageBox, QAction, QMenu, QMenuBar, QDialog, QLineEdit, 
                              QDialogButtonBox, QFileDialog, QProgressBar, QProgressDialog,
                              QListWidget, QListWidgetItem)
from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal, QPointF, QRectF, QObject
from PyQt5.QtGui import QPainter, QColor, QPen, QFont, QFontMetrics, QPolygonF
from scipy import signal
from collections import deque
import time
import subprocess
import threading
import queue
import os
import json
from urllib.parse import urlparse, parse_qs
from datetime import datetime
import math
import urllib.request
import zipfile
import shutil
import importlib.util
import socket
import struct

# ─── Platform detection ─────────────────────────────────────────────
IS_WINDOWS = sys.platform == 'win32'
IS_MACOS = sys.platform == 'darwin'

# ─── Audio backend selection ───────────────────────────────────────
# sounddevice is used on both platforms (SoloPlayer, macOS capture)
import sounddevice as sd

if IS_WINDOWS:
    import pyaudio
    import audioop
else:
    # On macOS, capture is done via sounddevice; pyaudio not required
    audioop = None  # not used on macOS path

# ─── Application directory (for bundled apps) ──────────────────────
if getattr(sys, 'frozen', False):
    _app_dir = sys._MEIPASS
else:
    _app_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _app_dir)

# ─── Windows-only: ASIO support via NAudio (pythonnet) ────────────
if IS_WINDOWS:
    import ctypes
    from ctypes import c_int, byref, windll
    import sys as _sys

HAS_ASIO = False
if IS_WINDOWS:
    try:
        import clr
        _naudio_path = os.path.join(_app_dir, 'NAudio.dll')
        clr.AddReference(_naudio_path)
        import NAudio
        from NAudio.Wave import AsioOut
        from System.Threading import Thread, ApartmentState, ThreadStart
        HAS_ASIO = True
        print(f"[OK] ASIO support (NAudio) loaded from {_naudio_path}")
    except Exception as _asio_err:
        print(f"[FAIL] ASIO support unavailable: {_asio_err}")
else:
    print("[INFO] ASIO not available on this platform")

# Константы для аудио
FORMAT = pyaudio.paInt16
RATE = 44100
CHUNK = 1024

# Константы для R128 EBU
PRE_FILTER_A = [1.0, -1.69065929318241, 0.73248077421585]
PRE_FILTER_B = [1.53512485958697, -2.69169618940638, 1.19839281085285]

RLB_FILTER_A = [1.0, -1.99004745483398, 0.99007225036621]
RLB_FILTER_B = [1.0, -2.0, 1.0]

# ─── Auto-setup: tools directory ──────────────────────────────────
TOOLS_DIR = os.path.join(os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else _app_dir, 'tools')

def find_ffmpeg():
    """Ищет ffmpeg в PATH и в tools/"""
    exe = 'ffmpeg.exe' if IS_WINDOWS else 'ffmpeg'
    which = shutil.which(exe)
    if which:
        return which
    local = os.path.join(TOOLS_DIR, exe)
    if os.path.isfile(local):
        return local
    return None

def ensure_ffmpeg(parent_widget=None):
    """Авто-установка ffmpeg если не найден"""
    if find_ffmpeg():
        return True
    os.makedirs(TOOLS_DIR, exist_ok=True)
    print("[SETUP] ffmpeg не найден, загружаю...")
    if IS_WINDOWS:
        url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
        zip_path = os.path.join(TOOLS_DIR, 'ffmpeg.zip')
        exe_name = 'ffmpeg.exe'
    else:
        url = "https://evermeet.cx/ffmpeg/ffmpeg.zip"
        zip_path = os.path.join(TOOLS_DIR, 'ffmpeg.zip')
        exe_name = 'ffmpeg'
    progress = None
    if parent_widget:
        progress = QProgressDialog("Загрузка ffmpeg...", None, 0, 0, parent_widget)
        progress.setWindowTitle("Первый запуск")
        progress.setModal(True)
        progress.show()
    try:
        urllib.request.urlretrieve(url, zip_path)
        with zipfile.ZipFile(zip_path, 'r') as zf:
            for name in zf.namelist():
                if name.endswith('/' + exe_name) or name.endswith(exe_name):
                    parts = name.split('/')
                    zf.extract(name, TOOLS_DIR)
                    os.rename(os.path.join(TOOLS_DIR, name),
                              os.path.join(TOOLS_DIR, exe_name))
                    break
        os.remove(zip_path)
        os.chmod(os.path.join(TOOLS_DIR, exe_name), 0o755)
        print(f"[SETUP] ffmpeg загружен в {TOOLS_DIR}")
        return True
    except Exception as e:
        print(f"[SETUP] Ошибка загрузки ffmpeg: {e}")
        return False
    finally:
        if progress:
            progress.close()

def ensure_packages():
    """Авто-установка Python пакетов (только при запуске из скрипта)"""
    if getattr(sys, 'frozen', False):
        return True
    required = {
        'numpy': 'numpy',
        'PyQt5': 'PyQt5',
        'scipy': 'scipy',
        'zeroconf': 'zeroconf',
    }
    if IS_WINDOWS:
        required['pyaudio'] = 'pyaudio'
    else:
        required['sounddevice'] = 'sounddevice'
    missing = []
    for name, pip_name in required.items():
        if importlib.util.find_spec(name) is None:
            missing.append(pip_name)
    if missing:
        print(f"[SETUP] Устанавливаю пакеты: {', '.join(missing)}...")
        try:
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--upgrade'] + missing,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("[SETUP] Пакеты установлены")
        except Exception as e:
            print(f"[SETUP] Ошибка установки пакетов: {e}")
            try:
                subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--user', '--upgrade'] + missing,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print("[SETUP] Пакеты установлены (--user)")
            except Exception as e2:
                print(f"[SETUP] Ошибка установки пакетов (--user): {e2}")
    return True

def first_run_setup(parent_widget=None):
    """Проверка и установка всего необходимого при первом запуске"""
    print("[SETUP] Проверка окружения...")
    ensure_packages()
    ensure_ffmpeg(parent_widget)
    print("[SETUP] Готово")

class SRTStreamDialog(QDialog):
    """Диалог для добавления SRT потока с авто-сканированием и ручным вводом"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Добавить SRT поток")
        self.setModal(True)
        self.resize(520, 420)
        self._selected_host = None
        self._selected_port = None
        self._selected_name = None
        self._selected_stream_id = None
        self._selected_passphrase = None
        self._selected_mode = "caller"
        self._scanner = None
        self.setup_ui()
        self.start_scan()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        # Раздел: обнаруженные потоки
        layout.addWidget(QLabel("Обнаруженные SRT источники (UDP beacon 239.255.255.250:54321):"))
        self.list_widget = QListWidget()
        self.list_widget.setAlternatingRowColors(True)
        self.list_widget.itemClicked.connect(self._on_list_selected)
        layout.addWidget(self.list_widget)

        scan_layout = QHBoxLayout()
        self.status_label = QLabel("Сканирование...")
        scan_layout.addWidget(self.status_label)
        scan_layout.addStretch()
        self.refresh_btn = QPushButton("Обновить")
        self.refresh_btn.clicked.connect(self.start_scan)
        scan_layout.addWidget(self.refresh_btn)
        layout.addLayout(scan_layout)

        # Разделитель
        layout.addWidget(QLabel("─" * 50))

        # Раздел: ручной ввод
        layout.addWidget(QLabel("Или введите вручную:"))
        grid = QGridLayout()
        grid.addWidget(QLabel("Адрес (IP/хост):"), 0, 0)
        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText("192.168.1.100")
        grid.addWidget(self.host_edit, 0, 1)
        grid.addWidget(QLabel("Порт:"), 1, 0)
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(5000)
        grid.addWidget(self.port_spin, 1, 1)
        grid.addWidget(QLabel("Stream ID:"), 2, 0)
        self.stream_id_edit = QLineEdit()
        self.stream_id_edit.setPlaceholderText("(необязательно)")
        grid.addWidget(self.stream_id_edit, 2, 1)
        grid.addWidget(QLabel("Пароль (Passphrase):"), 3, 0)
        self.passphrase_edit = QLineEdit()
        self.passphrase_edit.setPlaceholderText("(необязательно)")
        self.passphrase_edit.setEchoMode(QLineEdit.Password)
        grid.addWidget(self.passphrase_edit, 3, 1)
        grid.addWidget(QLabel("Тип (Mode):"), 4, 0)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["caller", "listener", "rendezvous"])
        self.mode_combo.setCurrentText("caller")
        grid.addWidget(self.mode_combo, 4, 1)
        grid.addWidget(QLabel("Имя:"), 5, 0)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Мой SRT поток")
        grid.addWidget(self.name_edit, 5, 1)
        layout.addLayout(grid)

        # Кнопки
        btn_layout = QHBoxLayout()
        self.add_btn = QPushButton("Добавить")
        self.add_btn.clicked.connect(self._on_add)
        btn_layout.addWidget(self.add_btn)
        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def start_scan(self):
        self.list_widget.clear()
        self.status_label.setText("Сканирование...")
        self._discovered = []
        if self._scanner:
            self._scanner.stop()
            self._scanner.wait(500)
        self._scanner = SRTScannerThread(timeout=3.0)
        self._scanner.discovered.connect(self._on_discovered)
        self._scanner.start()

    def _on_discovered(self, results):
        self._discovered = results
        self.list_widget.clear()
        if results:
            for host, port, stream_id, passphrase, mode, display_name in results:
                item_text = f"{display_name}  ({host}:{port}, {mode})"
                item = QListWidgetItem(item_text)
                item.setData(Qt.UserRole, (host, port, stream_id, passphrase, mode, display_name))
                self.list_widget.addItem(item)
            self.status_label.setText(f"Найдено {len(results)} источников")
        else:
            self.status_label.setText("Не найдено SRT источников в сети.")

    def _on_list_selected(self, item):
        data = item.data(Qt.UserRole)
        if data:
            host, port, stream_id, passphrase, mode, display_name = data
            self._selected_host = host
            self._selected_port = port
            self._selected_stream_id = stream_id
            self._selected_passphrase = passphrase
            self._selected_mode = mode
            self.host_edit.setText(host)
            self.port_spin.setValue(port)
            self.stream_id_edit.setText(stream_id)
            self.passphrase_edit.setText(passphrase)
            idx = self.mode_combo.findText(mode)
            if idx >= 0:
                self.mode_combo.setCurrentIndex(idx)
            self.name_edit.setText(display_name)

    def _on_add(self):
        host = self.host_edit.text().strip()
        port = self.port_spin.value()
        name = self.name_edit.text().strip()
        stream_id = self.stream_id_edit.text().strip()
        passphrase = self.passphrase_edit.text()
        mode = self.mode_combo.currentText()
        if not host:
            QMessageBox.warning(self, "Ошибка", "Введите адрес SRT источника")
            return
        if not name:
            name = f"{host}:{port}"
        self._selected_host = host
        self._selected_port = port
        self._selected_name = name
        self._selected_stream_id = stream_id
        self._selected_passphrase = passphrase
        self._selected_mode = mode
        self.accept()

    def get_srt_data(self):
        return self._selected_host, self._selected_port, self._selected_stream_id, self._selected_passphrase, self._selected_mode, self._selected_name

    def closeEvent(self, event):
        if self._scanner:
            self._scanner.stop()
            self._scanner.wait(500)
        event.accept()

class R128EBUProcessor:
    """Процессор для расчета LUFS по стандарту R128 EBU"""
    
    def __init__(self, sample_rate=44100, calibration_offset=0.0):
        self.sample_rate = sample_rate
        self.calibration_offset = calibration_offset
        
        self.pre_filter_b, self.pre_filter_a = PRE_FILTER_B, PRE_FILTER_A
        self.rlb_filter_b, self.rlb_filter_a = RLB_FILTER_B, RLB_FILTER_A
        
        self.pre_filter_state = signal.lfilter_zi(self.pre_filter_b, self.pre_filter_a)
        self.rlb_filter_state = signal.lfilter_zi(self.rlb_filter_b, self.rlb_filter_a)
        
        self.momentary_window = 0.4
        self.momentary_samples = int(self.momentary_window * self.sample_rate)
        self.momentary_buffer = deque(maxlen=self.momentary_samples)
        
        self.short_term_window = 3.0
        self.short_term_samples = int(self.short_term_window * self.sample_rate)
        self.short_term_buffer = deque(maxlen=self.short_term_samples)
        
        self.integrated_started = False
        self.integrated_values = []
        self._integrated_sum = 0.0
        self._integrated_count = 0
        
    def set_calibration_offset(self, offset):
        """Установить смещение калибровки"""
        self.calibration_offset = offset
        
    def reset(self):
        self.momentary_buffer.clear()
        self.short_term_buffer.clear()
        self.integrated_started = False
        self.integrated_values = []
        self._integrated_sum = 0.0
        self._integrated_count = 0
        self.pre_filter_state = signal.lfilter_zi(self.pre_filter_b, self.pre_filter_a)
        self.rlb_filter_state = signal.lfilter_zi(self.rlb_filter_b, self.rlb_filter_a)
        
    def process_audio(self, audio_data):
        """Обработка аудиоданных и расчет LUFS"""
        # Конвертируем в float32
        audio_float = audio_data.astype(np.float32) / 32768.0
        
        # Применяем pre-filter (high-pass at 38 Hz)
        filtered_audio, self.pre_filter_state = signal.lfilter(
            self.pre_filter_b, self.pre_filter_a, audio_float, zi=self.pre_filter_state
        )
        
        # Применяем RLB (Revised Low Frequency B-weighting) filter
        weighted_audio, self.rlb_filter_state = signal.lfilter(
            self.rlb_filter_b, self.rlb_filter_a, filtered_audio, zi=self.rlb_filter_state
        )
        
        # Возводим в квадрат для получения мощности
        squared_audio = weighted_audio ** 2
        
        for sample in squared_audio:
            self.momentary_buffer.append(sample)
            self.short_term_buffer.append(sample)
            self.integrated_values.append(sample)
            self._integrated_sum += sample
            self._integrated_count += 1

        momentary_lufs = self._calculate_lufs(self.momentary_buffer)
        short_term_lufs = self._calculate_lufs(self.short_term_buffer)
        if self._integrated_count >= self.momentary_samples and not self.integrated_started:
            self.integrated_started = True
        if self.integrated_started and self._integrated_count > 0:
            mean_square = self._integrated_sum / self._integrated_count
            db = 10 * np.log10(mean_square)
            integrated_lufs = db - 0.691 + self.calibration_offset
        else:
            integrated_lufs = momentary_lufs

        return momentary_lufs, short_term_lufs, integrated_lufs
    
    def _calculate_lufs(self, buffer):
        if not buffer:
            return -70.0
        mean_square = np.mean(buffer)
        if mean_square <= 0:
            return -70.0
        db = 10 * np.log10(mean_square)
        lufs = db - 0.691 + self.calibration_offset
        return max(-70.0, min(0.0, lufs))

class SRTStreamProcessor(QThread):
    """Поток для обработки SRT потока и извлечения аудио"""
    data_ready = pyqtSignal(int, float, float, float)  # channel_idx, momentary, short_term, integrated
    rms_ready = pyqtSignal(int, float, float)  # channel_idx, peak_db_l, peak_db_r
    
    def __init__(self, srt_url, channel_idx, channel_mode, calibration_offset=0.0, parent=None):
        super().__init__(parent)
        self.srt_url = srt_url
        self.channel_idx = channel_idx
        self.channel_mode = channel_mode
        self.calibration_offset = calibration_offset
        self.running = False
        self.processor = R128EBUProcessor(calibration_offset=calibration_offset)
        self.ffmpeg_process = None
        self.recorder = None
        self.solo_queue = None
        
    def run(self):
        self.running = True
        
        try:
            print(f"Подключаемся к SRT потоку: {self.srt_url}")
            
            # Определяем количество каналов из режима
            if self.channel_mode == '1+2':
                channels = 2  # стерео
            else:
                # Для моно режимов берем 16 каналов, чтобы получить доступ ко всем
                channels = 16
            
            # Команда ffmpeg для извлечения аудио из SRT потока
            ffmpeg_bin = find_ffmpeg() or 'ffmpeg'
            command = [
                ffmpeg_bin,
                '-i', self.srt_url,
                '-f', 's16le',        # 16-bit little-endian PCM
                '-ac', str(channels), # количество каналов
                '-ar', str(RATE),     # частота дискретизации
                '-loglevel', 'quiet', # отключить логи
                '-vn',                # отключить видео
                '-fflags', 'nobuffer', # минимизировать буферизацию
                '-flags', 'low_delay', # низкая задержка
                'pipe:1'              # вывод в stdout
            ]
            
            print(f"Запускаем ffmpeg: {' '.join(command)}")
            
            startupinfo = None
            if IS_WINDOWS:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0
            
            self.ffmpeg_process = subprocess.Popen(
                command, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE,
                bufsize=CHUNK*4,
                startupinfo=startupinfo
            )
            
            print("[OK] SRT поток подключен")
            
            # Основной цикл обработки аудио
            while self.running and self.ffmpeg_process.poll() is None:
                # Читаем аудио данные
                raw_data = self.ffmpeg_process.stdout.read(CHUNK * channels * 2)  # каналы * 2 байта на сэмпл
                
                if not raw_data:
                    # Если данных нет, ждем немного и продолжаем
                    time.sleep(0.01)
                    continue
                
                # Проверяем что получили достаточно данных
                if len(raw_data) < CHUNK * channels * 2:
                    continue
                    
                audio_data = np.frombuffer(raw_data, dtype=np.int16)
                
                is_srt_stereo = self.channel_mode == '1+2'
                if is_srt_stereo:
                    left_raw = audio_data[0::channels].astype(np.float32)
                    right_raw = audio_data[1::channels].astype(np.float32)
                
                processed_data = self._process_audio_channels(audio_data, self.channel_mode, channels)
                
                momentary, short_term, integrated = self.processor.process_audio(processed_data)
                
                peak_db = 20.0 * math.log10(max(float(np.max(np.abs(processed_data))), 1e-10))
                self.rms_ready.emit(self.channel_idx, peak_db, peak_db)
                
                self.data_ready.emit(self.channel_idx, momentary, short_term, integrated)
                if self.recorder:
                    if is_srt_stereo:
                        stereo = np.empty(len(left_raw) * 2, dtype=np.float32)
                        stereo[0::2] = left_raw
                        stereo[1::2] = right_raw
                        self.recorder.feed_audio(self.channel_idx, stereo, self.processor.sample_rate)
                    else:
                        self.recorder.feed_audio(self.channel_idx, processed_data, self.processor.sample_rate)
                if self.solo_queue is not None:
                    try:
                        if is_srt_stereo:
                            stereo = np.empty(len(left_raw) * 2, dtype=np.float32)
                            stereo[0::2] = left_raw
                            stereo[1::2] = right_raw
                            self.solo_queue.put_nowait((stereo / 32768.0).astype(np.float32))
                        else:
                            self.solo_queue.put_nowait((processed_data / 32768.0).astype(np.float32))
                    except queue.Full:
                        pass
                    
        except Exception as e:
            print(f"[ERR] Ошибка обработки SRT потока: {e}")
            import traceback
            traceback.print_exc()
        finally:
            # Завершаем ffmpeg процесс при остановке
            if self.ffmpeg_process and self.ffmpeg_process.poll() is None:
                self.ffmpeg_process.terminate()
                self.ffmpeg_process.wait()
    
    def _process_audio_channels(self, audio_data, channel_mode, total_channels):
        """Обработка аудио каналов в зависимости от режима"""
        if channel_mode == '1+2':
            # Стерео: используем оба канала как один (среднее)
            return self._process_stereo(audio_data, total_channels)
        else:
            # Моно: используем конкретный канал
            # Извлекаем номер канала из формата "1+1", "2+2" и т.д.
            channel_num = int(channel_mode.split('+')[0]) - 1  # преобразуем в 0-based индекс
            return self._process_mono(audio_data, channel_num, total_channels)
    
    def _process_stereo(self, audio_data, total_channels):
        """Обработка стерео сигнала (объединение каналов)"""
        if len(audio_data) >= total_channels * 2:
            # Разделяем на каналы
            left_channel = audio_data[0::total_channels]
            right_channel = audio_data[1::total_channels]
            
            # Объединяем каналы (среднее значение)
            return (left_channel.astype(np.float32) + right_channel.astype(np.float32)) / 2
        return audio_data.astype(np.float32)
    
    def _process_mono(self, audio_data, channel_num, total_channels):
        """Обработка моно сигнала (выбор конкретного канала)"""
        if len(audio_data) >= total_channels and channel_num < total_channels:
            # Выбираем нужный канал
            return audio_data[channel_num::total_channels].astype(np.float32)
        elif len(audio_data) > 0:
            # Если канал недоступен, берем первый
            return audio_data[0::total_channels].astype(np.float32)
        return audio_data.astype(np.float32)
    
    def stop(self):
        """Остановка потока"""
        self.running = False
        if self.ffmpeg_process and self.ffmpeg_process.poll() is None:
            self.ffmpeg_process.terminate()
        self.wait()

class AudioStreamThread(QThread):
    """Поток для захвата аудио с устройства (pyaudio на Windows, sounddevice на macOS)"""
    data_ready = pyqtSignal(int, float, float, float)
    rms_ready = pyqtSignal(int, float, float)

    def __init__(self, device_index, channel_idx, channel_mode, device_type, calibration_offset=0.0, parent=None):
        super().__init__(parent)
        self.device_index = device_index
        self.channel_idx = channel_idx
        self.channel_mode = channel_mode
        self.device_type = device_type
        self.calibration_offset = calibration_offset
        self.running = False
        self.processor = R128EBUProcessor(calibration_offset=calibration_offset)
        self.recorder = None
        self.solo_queue = None
        if IS_WINDOWS:
            self.audio = pyaudio.PyAudio()

    def run(self):
        self.running = True
        stream = None
        channels = 2

        try:
            if IS_WINDOWS:
                self._run_windows(stream, channels)
            else:
                self._run_macos(channels)
        except Exception as e:
            print(f"Ошибка открытия аудиоустройства {self.device_type}: {e}")
        finally:
            if stream is not None:
                try:
                    stream.stop_stream()
                    stream.close()
                except:
                    pass

    def _run_windows(self, stream, channels):
        if self.device_type in ('WDM Output', 'Output'):
            try:
                stream = self.audio.open(
                    format=pyaudio.paInt16, channels=channels, rate=RATE,
                    input=True, input_device_index=self.device_index,
                    frames_per_buffer=CHUNK, as_loopback=True)
            except:
                stream = self.audio.open(
                    format=pyaudio.paInt16, channels=channels, rate=RATE,
                    input=True, input_device_index=self.device_index,
                    frames_per_buffer=CHUNK)
        else:
            stream = self.audio.open(
                format=pyaudio.paInt16, channels=channels, rate=RATE,
                input=True, input_device_index=self.device_index,
                frames_per_buffer=CHUNK)

        while self.running:
            try:
                data = stream.read(CHUNK, exception_on_overflow=False)
                audio_data = np.frombuffer(data, dtype=np.int16)
                self._process_chunk(audio_data, audio_data.astype(np.float32))
            except Exception as e:
                print(f"Ошибка чтения аудио: {e}")
                break

    def _run_macos(self, channels):
        # macOS: use sounddevice InputStream (non-callback blocking reads)
        stream = sd.InputStream(
            device=self.device_index if self.device_index >= 0 else None,
            channels=channels, samplerate=RATE, blocksize=CHUNK, dtype='float32')
        stream.start()

        while self.running:
            try:
                chunk, _ = stream.read(CHUNK)
                if chunk.shape[0] == 0:
                    time.sleep(0.001)
                    continue
                # Convert float32 [-1..1] to int16 to match Windows code path
                audio_int16 = np.clip(chunk * 32767, -32768, 32767).astype(np.int16).flatten()
                raw_float = audio_int16.astype(np.float32)
                self._process_chunk(audio_int16, raw_float)
            except Exception as e:
                print(f"Ошибка чтения аудио: {e}")
                break

    def _process_chunk(self, audio_data, raw_float):
        is_stereo = self.channel_mode == '1+2'
        if is_stereo:
            processed_data = self._process_stereo(audio_data)
        elif self.channel_mode in ['1+1', '2+2']:
            ch = int(self.channel_mode.split('+')[0]) - 1
            processed_data = self._process_mono(audio_data, min(ch, 1))
        else:
            processed_data = self._process_mono(audio_data, 0)

        momentary, short_term, integrated = self.processor.process_audio(processed_data)
        peak_db = 20.0 * math.log10(max(float(np.max(np.abs(processed_data))), 1e-10))
        self.rms_ready.emit(self.channel_idx, peak_db, peak_db)
        self.data_ready.emit(self.channel_idx, momentary, short_term, integrated)

        if self.recorder:
            if is_stereo:
                self.recorder.feed_audio(self.channel_idx, raw_float, self.processor.sample_rate)
            else:
                self.recorder.feed_audio(self.channel_idx, processed_data, self.processor.sample_rate)
        if self.solo_queue is not None:
            try:
                if is_stereo:
                    self.solo_queue.put_nowait((raw_float / 32768.0).astype(np.float32))
                else:
                    self.solo_queue.put_nowait((processed_data / 32768.0).astype(np.float32))
            except queue.Full:
                pass

    def _process_stereo(self, audio_data):
        if len(audio_data) >= 2:
            l = audio_data[::2]
            r = audio_data[1::2]
            return (l.astype(np.float32) + r.astype(np.float32)) / 2
        return audio_data.astype(np.float32)

    def _process_mono(self, audio_data, channel=0):
        if len(audio_data) >= 2:
            return audio_data[::2].astype(np.float32) if channel == 0 else audio_data[1::2].astype(np.float32)
        return audio_data.astype(np.float32)

    def stop(self):
        self.running = False
        self.wait()

class VirtualOutputDeviceThread(QThread):
    """Виртуальный поток для эмуляции выходных устройств"""
    data_ready = pyqtSignal(int, float, float, float)
    rms_ready = pyqtSignal(int, float, float)  # channel_idx, peak_db_l, peak_db_r
    
    def __init__(self, channel_idx, channel_mode, calibration_offset=0.0, parent=None):
        super().__init__(parent)
        self.channel_idx = channel_idx
        self.channel_mode = channel_mode
        self.calibration_offset = calibration_offset
        self.running = False
        self.processor = R128EBUProcessor(calibration_offset=calibration_offset)
        self.recorder = None
        self.solo_queue = None
        
    def run(self):
        self.running = True
        
        # Эмуляция выходного устройства - генерируем тестовый сигнал
        import math
        sample_count = 0
        
        while self.running:
            try:
                # Генерируем тестовый синусоидальный сигнал
                frequency = 440  # Hz
                amplitude = 0.5
                
                # Создаем буфер с тестовым сигналом
                samples = np.zeros(CHUNK, dtype=np.float32)
                for i in range(CHUNK):
                    sample = amplitude * math.sin(2 * math.pi * frequency * (sample_count + i) / RATE)
                    samples[i] = sample
                
                sample_count += CHUNK
                
                # Обрабатываем аудио по стандарту R128 EBU
                momentary, short_term, integrated = self.processor.process_audio(samples)
                
                # True peak для быстрого VU
                peak_db = 20.0 * math.log10(max(amplitude, 1e-10))
                self.rms_ready.emit(self.channel_idx, peak_db, peak_db)
                
                # Отправляем данные в измеритель и рекордер
                self.data_ready.emit(self.channel_idx, momentary, short_term, integrated)
                if self.recorder:
                    self.recorder.feed_audio(self.channel_idx, samples * 32768.0, self.processor.sample_rate)
                # Соло-мониторинг
                if self.solo_queue is not None:
                    try:
                        self.solo_queue.put_nowait(samples.astype(np.float32))
                    except queue.Full:
                        pass
                
                time.sleep(CHUNK / RATE)  # Имитируем реальное время
                
            except Exception as e:
                print(f"Ошибка виртуального устройства: {e}")
                break
    
    def stop(self):
        self.running = False
        self.wait()


class OMTStreamDialog(QDialog):
    """Диалог для добавления OMT потока с авто-сканированием и ручным вводом"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Добавить OMT поток")
        self.setModal(True)
        self.resize(520, 420)
        self._selected_host = None
        self._selected_port = None
        self._selected_name = None
        self._scanner = None
        self.setup_ui()
        self.start_scan()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        # Раздел: обнаруженные потоки
        layout.addWidget(QLabel("Обнаруженные OMT источники (_omt._tcp.local):"))
        self.list_widget = QListWidget()
        self.list_widget.setAlternatingRowColors(True)
        self.list_widget.itemClicked.connect(self._on_list_selected)
        layout.addWidget(self.list_widget)

        scan_layout = QHBoxLayout()
        self.status_label = QLabel("Сканирование...")
        scan_layout.addWidget(self.status_label)
        scan_layout.addStretch()
        self.refresh_btn = QPushButton("Обновить")
        self.refresh_btn.clicked.connect(self.start_scan)
        scan_layout.addWidget(self.refresh_btn)
        layout.addLayout(scan_layout)

        # Разделитель
        layout.addWidget(QLabel("─" * 50))

        # Раздел: ручной ввод
        layout.addWidget(QLabel("Или введите вручную:"))
        grid = QGridLayout()
        grid.addWidget(QLabel("Адрес (IP/хост):"), 0, 0)
        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText("192.168.1.100")
        grid.addWidget(self.host_edit, 0, 1)
        grid.addWidget(QLabel("Порт:"), 1, 0)
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(6400)
        grid.addWidget(self.port_spin, 1, 1)
        grid.addWidget(QLabel("Имя:"), 2, 0)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Мой OMT поток")
        grid.addWidget(self.name_edit, 2, 1)
        layout.addLayout(grid)

        # Кнопки
        btn_layout = QHBoxLayout()
        self.add_btn = QPushButton("Добавить")
        self.add_btn.clicked.connect(self._on_add)
        btn_layout.addWidget(self.add_btn)
        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def start_scan(self):
        self.list_widget.clear()
        self.status_label.setText("Сканирование...")
        self._discovered = []
        if self._scanner:
            self._scanner.stop()
            self._scanner.wait(500)
        self._scanner = OMTScannerThread(timeout=3.0)
        self._scanner.discovered.connect(self._on_discovered)
        self._scanner.start()

    def _on_discovered(self, results):
        self._discovered = results
        self.list_widget.clear()
        if results:
            for host, port, display_name, server_name in results:
                item_text = f"{display_name}  ({host}:{port})"
                item = QListWidgetItem(item_text)
                item.setData(Qt.UserRole, (host, port, display_name))
                self.list_widget.addItem(item)
            self.status_label.setText(f"Найдено {len(results)} источников")
        else:
            self.status_label.setText("Не найдено. Убедитесь что OMT включён на источнике и Bonjour/zeroconf работает.")

    def _on_list_selected(self, item):
        data = item.data(Qt.UserRole)
        if data:
            self._selected_host, self._selected_port, self._selected_name = data
            self.host_edit.setText(self._selected_host)
            self.port_spin.setValue(self._selected_port)
            self.name_edit.setText(self._selected_name)

    def _on_add(self):
        host = self.host_edit.text().strip()
        port = self.port_spin.value()
        name = self.name_edit.text().strip()
        if not host:
            QMessageBox.warning(self, "Ошибка", "Введите адрес OMT источника")
            return
        if not name:
            name = f"{host}:{port}"
        self._selected_host = host
        self._selected_port = port
        self._selected_name = name
        self.accept()

    def get_omt_data(self):
        return self._selected_host, self._selected_port, self._selected_name

    def closeEvent(self, event):
        if self._scanner:
            self._scanner.stop()
            self._scanner.wait(500)
        event.accept()


class OMTStreamProcessor(QThread):
    """Поток для приёма аудио из OMT потока (Open Media Transport)"""
    data_ready = pyqtSignal(int, float, float, float)
    rms_ready = pyqtSignal(int, float, float)

    OMT_VERSION = 1
    OMT_FRAME_METADATA = 1
    OMT_FRAME_VIDEO = 2
    OMT_FRAME_AUDIO = 4
    OMT_AUDIO_CODEC_FPA1 = 0x31415046  # 'FPA1'

    def __init__(self, host, port, channel_idx, channel_mode, calibration_offset=0.0, parent=None):
        super().__init__(parent)
        self.host = host
        self.port = port
        self.channel_idx = channel_idx
        self.channel_mode = channel_mode
        self.calibration_offset = calibration_offset
        self.running = False
        self.processor = R128EBUProcessor(calibration_offset=calibration_offset)
        self.sock = None
        self.recorder = None
        self.solo_queue = None
        self.ch_rate = None

    def run(self):
        self.running = True
        try:
            print(f"[OMT] Connecting to {self.host}:{self.port}")
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 262144)
            self.sock.settimeout(10.0)
            self.sock.connect((self.host, self.port))
            self.sock.settimeout(5.0)
            print(f"[OMT] Connected to {self.host}:{self.port}")

            self._send_subscribe_audio()
            print(f"[OMT] Subscribe sent, waiting for frames...")

            _frame_count = 0
            while self.running:
                try:
                    header = self._recv_all(16)
                    if not header:
                        break

                    version, frame_type, timestamp, metadata_len, data_len = struct.unpack('<BBqHi', header)
                    if version != self.OMT_VERSION:
                        continue

                    _frame_count += 1
                    if _frame_count <= 5 or _frame_count % 100 == 0:
                        ft_name = {1:'META', 2:'VIDEO', 4:'AUDIO'}.get(frame_type, f'UNKN({frame_type})')
                        print(f"[OMT] Frame #{_frame_count}: type={ft_name} data_len={data_len} meta_len={metadata_len}")

                    if frame_type == self.OMT_FRAME_AUDIO:
                        audio_ext = self._recv_all(24)
                        if not audio_ext:
                            break

                        codec, sample_rate, samples_per_ch, total_channels, active_ch, reserved = struct.unpack('<iiiiIi', audio_ext)
                        print(f"[OMT] Audio frame: codec=0x{codec:08X} sr={sample_rate} spc={samples_per_ch} ch={total_channels} active=0x{active_ch:X}")
                        self.ch_rate = sample_rate

                        if self.processor.sample_rate != sample_rate:
                            self.processor = R128EBUProcessor(sample_rate=sample_rate, calibration_offset=self.calibration_offset)

                        audio_data_len = data_len - 24 - metadata_len
                        if audio_data_len > 0:
                            audio_raw = self._recv_all(audio_data_len)
                            if not audio_raw:
                                break

                            channel_data = self._parse_audio(audio_raw, codec, samples_per_ch, total_channels, active_ch)
                            if channel_data is not None and channel_data.shape[0] > 0:
                                processed = self._process_audio_channels(channel_data, self.channel_mode, total_channels)
                                if len(processed) > 0:
                                    momentary, short_term, integrated = self.processor.process_audio(processed * 32768.0)
                                    peak_db = 20.0 * math.log10(max(float(np.max(np.abs(processed))), 1e-10))
                                    self.rms_ready.emit(self.channel_idx, peak_db, peak_db)
                                    self.data_ready.emit(self.channel_idx, momentary, short_term, integrated)
                                    if self.recorder:
                                        try:
                                            left_ch, right_ch, need_ch, is_stereo = parse_mode(self.channel_mode)
                                        except:
                                            left_ch, right_ch = 1, 2
                                            is_stereo = True
                                        if is_stereo and left_ch != right_ch:
                                            l = channel_data[:, left_ch - 1].astype(np.float32)
                                            r = channel_data[:, right_ch - 1].astype(np.float32)
                                            stereo = np.empty(len(l) * 2, dtype=np.float32)
                                            stereo[0::2] = l
                                            stereo[1::2] = r
                                            self.recorder.feed_audio(self.channel_idx, stereo * 32768.0, self.processor.sample_rate)
                                        else:
                                            self.recorder.feed_audio(self.channel_idx, processed * 32768.0, self.processor.sample_rate)
                                    if self.solo_queue is not None:
                                        try:
                                            left_ch, right_ch, need_ch, is_stereo = parse_mode(self.channel_mode)
                                        except:
                                            left_ch, right_ch = 1, 2
                                            is_stereo = True
                                        if is_stereo and left_ch != right_ch:
                                            l = channel_data[:, left_ch - 1].astype(np.float32)
                                            r = channel_data[:, right_ch - 1].astype(np.float32)
                                            stereo = np.empty(len(l) * 2, dtype=np.float32)
                                            stereo[0::2] = l
                                            stereo[1::2] = r
                                            try:
                                                self.solo_queue.put_nowait(stereo)
                                            except queue.Full:
                                                pass
                                        else:
                                            try:
                                                self.solo_queue.put_nowait(processed.astype(np.float32))
                                            except queue.Full:
                                                pass


                        # Остаток фрейма — пер-фреймовая мета, если есть
                        if metadata_len > 0:
                            self._recv_all(metadata_len)

                    elif frame_type == self.OMT_FRAME_VIDEO:
                        skip_len = data_len
                        if skip_len > 0:
                            self._recv_all(skip_len)

                    elif frame_type == self.OMT_FRAME_METADATA:
                        if data_len > 0:
                            meta_xml = self._recv_all(data_len)
                            if meta_xml and _frame_count <= 5:
                                print(f"[OMT] Metadata: {meta_xml[:200]}")

                except socket.timeout:
                    print(f"[OMT] Read timeout (no data for 5s), frames received: {_frame_count}")
                    continue
                except Exception as e:
                    print(f"[OMT] Read error: {e}")
                    import traceback
                    traceback.print_exc()
                    break

        except Exception as e:
            print(f"[OMT] Error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            if self.sock:
                try:
                    self.sock.close()
                except:
                    pass
            print(f"[OMT] Disconnected from {self.host}:{self.port}")

    def _recv_all(self, n):
        if n <= 0:
            return b''
        data = b''
        while len(data) < n and self.running:
            try:
                chunk = self.sock.recv(n - len(data))
                if not chunk:
                    return None
                data += chunk
            except socket.timeout:
                if not self.running:
                    return None
                continue
        return data

    def _send_subscribe(self, type_name, value):
        xml = f'<OMTSubscribe {type_name}="{value}" />'.encode('utf-8')
        # Metadata frame: no per-frame metadata (MetadataLength=0),
        # DataLength = length of XML payload (no trailing null for subscribe frames)
        header = struct.pack('<BBqHi', self.OMT_VERSION, self.OMT_FRAME_METADATA, 0, 0, len(xml))
        self.sock.sendall(header + xml)
        print(f"[OMT] Subscribe sent: {type_name}={value}")

    def _send_subscribe_audio(self):
        self._send_subscribe("Audio", "true")

    def _parse_audio(self, raw_data, codec, samples_per_ch, total_channels, active_ch_mask):
        if codec != self.OMT_AUDIO_CODEC_FPA1:
            return None
        active_channels = []
        for ch in range(total_channels):
            if active_ch_mask & (1 << ch):
                active_channels.append(ch)
        if not active_channels:
            return np.zeros((samples_per_ch, total_channels), dtype=np.float32)
        ch_data = {}
        offset = 0
        for ch in active_channels:
            ch_size = samples_per_ch * 4
            if offset + ch_size > len(raw_data):
                break
            ch_samples = np.frombuffer(raw_data[offset:offset+ch_size], dtype=np.float32)
            ch_data[ch] = ch_samples
            offset += ch_size
        result = np.zeros((samples_per_ch, total_channels), dtype=np.float32)
        for ch, samples in ch_data.items():
            result[:, ch] = samples
        return result

    def _process_audio_channels(self, channel_data, channel_mode, total_channels):
        try:
            left, right, need_ch, is_stereo = parse_mode(channel_mode)
        except:
            left, right = 1, 2
            is_stereo = True
        if is_stereo and left != right:
            return self._process_stereo(channel_data, left - 1, right - 1, total_channels)
        else:
            return self._process_mono(channel_data, left - 1, total_channels)

    def _process_stereo(self, channel_data, left_idx, right_idx, total_channels):
        if channel_data.ndim >= 2 and left_idx < channel_data.shape[1] and right_idx < channel_data.shape[1]:
            left = channel_data[:, left_idx]
            right = channel_data[:, right_idx]
            return (left.astype(np.float32) + right.astype(np.float32)) / 2
        elif channel_data.ndim >= 2 and channel_data.shape[1] > 0:
            return channel_data[:, 0].astype(np.float32)
        return channel_data.astype(np.float32)

    def _process_mono(self, channel_data, ch_idx, total_channels):
        if channel_data.ndim >= 2 and ch_idx < channel_data.shape[1]:
            return channel_data[:, ch_idx].astype(np.float32)
        elif channel_data.ndim >= 2 and channel_data.shape[1] > 0:
            return channel_data[:, 0].astype(np.float32)
        return channel_data.astype(np.float32)

    def stop(self):
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
        self.wait()


class OMTScannerThread(QThread):
    """Поток для сканирования OMT источников через DNS-SD"""
    discovered = pyqtSignal(list)

    def __init__(self, timeout=3.0, parent=None):
        super().__init__(parent)
        self.timeout = timeout
        self._zc = None
        self._browser = None

    def run(self):
        results = []
        try:
            from zeroconf import Zeroconf, ServiceBrowser, ServiceStateChange
            self._zc = Zeroconf()
            discovered_services = {}
            discovered_event = threading.Event()

            def on_change(zeroconf, service_type, name, state_change):
                if state_change == ServiceStateChange.Added:
                    info = zeroconf.get_service_info(service_type, name)
                    if info:
                        if hasattr(info, 'parsed_scoped_addresses'):
                            addresses = info.parsed_scoped_addresses()
                        elif hasattr(info, 'parsed_addresses'):
                            addresses = info.parsed_addresses()
                        else:
                            addresses = [socket.inet_ntoa(info.address)] if info.address else []
                        host = addresses[0] if addresses else 'unknown'
                        port = info.port
                        display_name = name
                        for suffix in ['._omt._tcp.local.', '._omt._tcp']:
                            if display_name.endswith(suffix):
                                display_name = display_name[:-len(suffix)]
                                break
                        server_str = str(info.server) if info.server else host
                        discovered_services[display_name] = (host, port, display_name, server_str)
                        discovered_event.set()

            self._browser = ServiceBrowser(self._zc, "_omt._tcp.local.", handlers=[on_change])
            discovered_event.wait(self.timeout)
            results = list(discovered_services.values())
            if results:
                print(f"[OMT] Discovered {len(results)} sources via DNS-SD")
                for r in results:
                    print(f"  [OMT] {r[2]} -> {r[0]}:{r[1]}")
            else:
                print("[OMT] No OMT sources discovered via DNS-SD")
        except ImportError:
            print("[OMT] zeroconf not installed, cannot scan DNS-SD")
        except Exception as e:
            print(f"[OMT] DNS-SD scan error: {e}")
        finally:
            if self._zc:
                self._zc.close()
                self._zc = None

        self.discovered.emit(results)

    def stop(self):
        if self._zc:
            try:
                self._zc.close()
            except:
                pass
            self._zc = None


class SRTScannerThread(QThread):
    """Поток для сканирования SRT источников через UDP multicast beacon"""
    discovered = pyqtSignal(list)

    def __init__(self, timeout=3.0, parent=None):
        super().__init__(parent)
        self.timeout = timeout
        self._running = False

    def run(self):
        self._running = True
        results = []
        sock = None
        try:
            MCAST_GRP = '239.255.255.250'
            MCAST_PORT = 54321
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.settimeout(self.timeout)
            if os.name == 'nt':
                sock.bind(('0.0.0.0', MCAST_PORT))
            else:
                sock.bind((MCAST_GRP, MCAST_PORT))
            mreq = struct.pack("4sl", socket.inet_aton(MCAST_GRP), socket.INADDR_ANY)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

            start = time.time()
            while self._running and time.time() - start < self.timeout:
                try:
                    data, addr = sock.recvfrom(4096)
                    msg = json.loads(data.decode('utf-8'))
                    host = msg.get('host', addr[0])
                    port = msg.get('port', 5000)
                    stream_id = msg.get('stream_id', '')
                    passphrase = msg.get('passphrase', '')
                    mode = msg.get('mode', 'caller')
                    display_name = msg.get('name', f"SRT {host}:{port}")
                    results.append((host, port, stream_id, passphrase, mode, display_name))
                except (json.JSONDecodeError, UnicodeDecodeError, socket.timeout):
                    pass
            if results:
                print(f"[SRT] Discovered {len(results)} sources via UDP beacon")
                for r in results:
                    print(f"  [SRT] {r[5]} -> {r[0]}:{r[1]} mode={r[4]}")
        except Exception as e:
            print(f"[SRT] UDP beacon scan error: {e}")
        finally:
            if sock:
                try:
                    sock.close()
                except:
                    pass
        self.discovered.emit(results)

    def stop(self):
        self._running = False


def parse_mode(mode):
    """Парсит строку режима канала, возвращает (left_ch, right_ch, need_channels, is_stereo)"""
    if '+' in mode:
        left_str, right_str = mode.split('+')
        left_ch = int(left_str.strip())
        right_ch = int(right_str.strip())
        need_channels = max(left_ch, right_ch)
        is_stereo = True
    else:
        ch = int(mode.strip())
        need_channels = ch
        left_ch = ch
        right_ch = ch
        is_stereo = False
    return left_ch, right_ch, need_channels, is_stereo


class ASIOStreamThread(QThread):
    """Поток для захвата аудио с ASIO устройства через NAudio.
    Поддерживает несколько каналов (слотов) на одном драйвере."""
    data_ready = pyqtSignal(int, float, float, float)
    rms_ready = pyqtSignal(int, float, float)  # channel_idx, rms_db_l, rms_db_r
    
    def __init__(self, driver_name, channel_slots, sample_rate=RATE, calibration_offset=0.0, parent=None):
        """
        channel_slots: список словарей с ключами 'channel_idx', 'channel_mode'
                       например [{'channel_idx': 0, 'channel_mode': '1+2'},
                                 {'channel_idx': 1, 'channel_mode': '3+4'}]
        """
        super().__init__(parent)
        self.driver_name = driver_name
        self.channel_slots = channel_slots
        self.sample_rate = sample_rate
        self.calibration_offset = calibration_offset
        self.running = False
        self._asio = None
        self._sta_thread = None
        self.recorder = None
        self._init_event = threading.Event()
        # Последние данные на канал для LUFS (только 1 снимок, без накопления)
        self._latest_data = {}  # idx -> (raw_data, peaks_l, peaks_r, processor)
        self._latest_lock = threading.Lock()
        self._diag_msgs = deque()
        self._diag_msgs_lock = threading.Lock()
        
    def process_queue(self):
        """Обработка данных с каждого канала (вызывается из таймера Qt, 40 мс)."""
        with self._latest_lock:
            snap = dict(self._latest_data)
            self._latest_data.clear()
        
        for idx, (raw_data, rms_db_l, rms_db_r, processor) in snap.items():
            try:
                momentary, short_term, integrated = processor.process_audio(raw_data * 32768.0)
                self.data_ready.emit(idx, momentary, short_term, integrated)
                self.rms_ready.emit(idx, rms_db_l, rms_db_r)
            except Exception as e:
                print(f"[ASIO] LUFS error ch{idx}: {e}")
        
        # Диагностика: выводим накопленные сообщения из callback (без блокировки callback)
        with self._diag_msgs_lock:
            while self._diag_msgs:
                print(self._diag_msgs.popleft())
    
    def run(self):
        self.running = True
        try:
            self._run_asio_on_sta()
        except Exception as e:
            print(f"[ERR] ASIO ошибка: {e}")
            import traceback
            traceback.print_exc()
    
    def _run_asio_on_sta(self):
        """Запуск ASIO на STA потоке (требуется для COM-интерфейса ASIO)"""
        
        # Предварительно парсим все слоты
        parsed_slots = []
        max_ch = 0
        for slot in self.channel_slots:
            left, right, need, stereo = parse_mode(slot['channel_mode'])
            cal = slot.get('calibration_offset', self.calibration_offset)
            parsed_slots.append({
                'channel_idx': slot['channel_idx'],
                'left': left, 'right': right, 'is_stereo': stereo,
                'processor': R128EBUProcessor(sample_rate=self.sample_rate, calibration_offset=cal),
                'recorder': slot.get('recorder', self.recorder),
                'local_rec_idx': slot.get('local_rec_idx', slot['channel_idx']),
            })
            max_ch = max(max_ch, need)
        self._parsed_slots = parsed_slots
        need_channels = max_ch
        
        def asio_worker():
            try:
                modes_str = ', '.join(s['channel_mode'] for s in self.channel_slots)
                print(f"[ASIO] Starting driver: {self.driver_name}, slots: {modes_str}")
                
                self._asio = AsioOut(self.driver_name)
                self._asio.InitRecordAndPlayback(None, need_channels, self.sample_rate)
                fpb = self._asio.FramesPerBuffer
                self._fpb = fpb
                print(f"[ASIO] Driver initialized: sr={self.sample_rate} Hz, FramesPerBuffer={fpb}")
                self._init_event.set()
                
                _cb_count = [0]
                _first = [True]
                _recorder = self.recorder
                _rec_sample_rate = self.sample_rate
                _latest_lock = self._latest_lock
                _latest = self._latest_data
                _need_channels = need_channels
                _fed_counter = {ps['channel_idx']: 0 for ps in parsed_slots}  # frames fed to recorder
                _t0 = [time.time()]  # для измерения реальной частоты
                _perf_t0 = [0.0]    # perf_counter_ns начала callback (для измерения времени в callback)
                _cb_times = []       # длительность каждой callback в мкс
                
                def on_audio(sender, args):
                    if not self.running:
                        return
                    try:
                        cb_start = time.perf_counter_ns()
                        prev_start = _perf_t0[0]
                        _perf_t0[0] = cb_start
                        cb_interval_us = (cb_start - prev_start) / 1000.0 if prev_start > 0 else 0
                        _cb_count[0] += 1
                        samples = args.GetAsInterleavedSamples()
                        samples_none = samples is None or len(samples) == 0
                        if samples_none:
                            audio_data = np.zeros(fpb * _need_channels, dtype=np.float32)
                            driver_ch = 0
                        else:
                            audio_data = np.array(samples, dtype=np.float32)
                            driver_ch = len(audio_data) // fpb
                            if driver_ch != _need_channels:
                                # Драйвер отдаёт другое количество каналов — приводим к _need_channels
                                try:
                                    td = audio_data.reshape(-1, driver_ch)
                                except:
                                    td = np.zeros((fpb, driver_ch), dtype=np.float32) if driver_ch > 0 else np.zeros((fpb, 0), dtype=np.float32)
                                padded = np.zeros((fpb, _need_channels), dtype=np.float32)
                                cols = min(td.shape[1], _need_channels)
                                padded[:, :cols] = td[:, :cols]
                                audio_data = padded.ravel()
                        actual_ch = _need_channels
                        frames_this_cb = len(audio_data) // actual_ch
                        
                        for ps in parsed_slots:
                            left, right = ps['left'], ps['right']
                            is_stereo = ps['is_stereo']
                            processor = ps['processor']
                            idx = ps['channel_idx']
                            
                            # Извлекаем raw сигнал с правильным stride
                            if is_stereo and left != right:
                                raw_l = audio_data[left - 1::actual_ch]
                                raw_r = audio_data[right - 1::actual_ch]
                            else:
                                raw = audio_data[left - 1::actual_ch]
                            
                            # True peak для VU (быстро)
                            if is_stereo and left != right:
                                peak_l = float(np.max(np.abs(raw_l)))
                                peak_r = float(np.max(np.abs(raw_r)))
                            else:
                                peak_l = float(np.max(np.abs(raw)))
                                peak_r = peak_l
                            peak_db_l = 20.0 * math.log10(max(peak_l, 1e-10)) if peak_l > 1e-10 else -100.0
                            peak_db_r = 20.0 * math.log10(max(peak_r, 1e-10)) if peak_r > 1e-10 else -100.0
                            
                            # Сохраняем данные для LUFS (только последний снимок — без накопления)
                            with _latest_lock:
                                if is_stereo and left != right:
                                    raw_mono = (raw_l + raw_r) / 2
                                    _latest[idx] = (raw_mono.copy(), peak_db_l, peak_db_r, processor)
                                else:
                                    _latest[idx] = (raw.copy(), peak_db_l, peak_db_r, processor)
                            
                             # Рекордер: быстрый буфер в RAM
                            rec = ps.get('recorder', _recorder)
                            if rec:
                                local_rec_idx = ps.get('local_rec_idx', idx)
                                if is_stereo and left != right:
                                    rec.feed_audio_stereo(local_rec_idx, raw_l, raw_r, _rec_sample_rate)
                                    _fed_counter[idx] = _fed_counter.get(idx, 0) + len(raw_l)
                                else:
                                    rec.feed_audio(local_rec_idx, raw * 32768.0, _rec_sample_rate)
                                    _fed_counter[idx] = _fed_counter.get(idx, 0) + len(raw)
                            
                             # Соло-мониторинг напрямую в queue (без лишних копий)
                            solo_q = ps.get('solo_queue')
                            if solo_q is not None:
                                try:
                                    if is_stereo and left != right:
                                        stereo = np.empty(len(raw_l) * 2, dtype=np.float32)
                                        stereo[0::2] = raw_l
                                        stereo[1::2] = raw_r
                                        solo_q.put_nowait(stereo)
                                    else:
                                        solo_q.put_nowait(raw)
                                except queue.Full:
                                    pass
                        
                        if _first[0]:
                            _first[0] = False
                            _t0[0] = time.time()
                            first_samples = 0 if samples_none else len(samples)
                            print(f"[ASIO] First callback #{_cb_count[0]}: raw_samples={first_samples} driver_ch={driver_ch} need_ch={_need_channels} actual_ch={actual_ch} fpb={fpb} sr={self.sample_rate}Hz frames_this_cb={frames_this_cb} slots={len(parsed_slots)} peak={peak_db_l:.1f} dB")
                        elif _cb_count[0] % 100 == 0:
                            elapsed = time.time() - _t0[0]
                            tot_frames = frames_this_cb * _cb_count[0]
                            est_rate = tot_frames / elapsed if elapsed > 0 else 0
                            fed_str = ', '.join(f'ch{k}={v}' for k, v in sorted(_fed_counter.items()))
                            if _cb_times:
                                avg_us = sum(_cb_times) / len(_cb_times)
                                max_us = max(_cb_times)
                                min_us = min(_cb_times)
                                _cb_times.clear()
                                diag = f"[ASIO] {_cb_count[0]} callbacks, {elapsed:.1f}s, ~{est_rate:.0f}Hz, cb: {avg_us:.1f}±{max_us-min_us:.1f}us, fed: {fed_str}"
                            else:
                                diag = f"[ASIO] {_cb_count[0]} callbacks, {elapsed:.1f}s, ~{est_rate:.0f}Hz, fed: {fed_str}"
                            with self._diag_msgs_lock:
                                self._diag_msgs.append(diag)
                        
                    except Exception as ex:
                        print(f"ASIO callback error #{_cb_count[0]}: {ex}")
                    
                    # Время выполнения тела callback (после обработки, до следующего вызова)
                    cb_end = time.perf_counter_ns()
                    _cb_times.append((cb_end - cb_start) / 1000.0)
                
                def on_stopped(sender, args):
                    print(f"[ASIO] PlaybackStopped event! sender={sender}")
                
                self._asio.AudioAvailable += on_audio
                self._asio.PlaybackStopped += on_stopped
                self._asio.Play()
                
                print(f"[ASIO] Stream started, keeping alive...")
                while self.running:
                    time.sleep(0.1)
                
                print(f"[ASIO] Worker loop exited after {_cb_count[0]} callbacks")
                if _fed_counter:
                    fed_str = ', '.join(f'ch{k}={v}' for k, v in sorted(_fed_counter.items()))
                    print(f"[ASIO]  Total frames fed: {fed_str}")
                    
            except Exception as e:
                print(f"[ASIO] STA thread error: {e}")
                import traceback
                traceback.print_exc()
            finally:
                if self._asio:
                    try:
                        self._asio.Stop()
                        self._asio.Dispose()
                        print(f"[ASIO] Driver {self.driver_name} stopped")
                    except Exception as e:
                        print(f"ASIO cleanup error: {e}")
        
        self._sta_thread = Thread(ThreadStart(asio_worker))
        self._sta_thread.SetApartmentState(ApartmentState.STA)
        self._sta_thread.Start()
        self._sta_thread.Join()
    
    def stop(self):
        self.running = False
        self.wait()
    
    def set_solo_queue(self, channel_idx, q):
        """Установить queue для соло-мониторинга слота."""
        for ps in getattr(self, '_parsed_slots', []):
            if ps['channel_idx'] == channel_idx:
                ps['solo_queue'] = q
                return True
        return False
    
    def clear_solo_queue(self, channel_idx):
        """Убрать queue соло-мониторинга слота."""
        for ps in getattr(self, '_parsed_slots', []):
            if ps['channel_idx'] == channel_idx:
                ps.pop('solo_queue', None)
                return True
        return False


class SharedASIOController(QObject):
    """Управляет одним ASIO драйвером для всех окон.
    Создаёт один ASIOStreamThread на драйвер и распределяет данные по всем окнам."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._groups = {}
        self._routing = {}
        self._process_timer = None
        self._ch_rates = {}
    
    def add_slot(self, driver_name, mode, window, local_vm_idx,
                 local_rec_idx, recorder, calibration_offset, ch_name, color):
        left, right, need_ch, is_stereo = parse_mode(mode)
        g = self._groups.setdefault(driver_name, {
            'need_channels': 0, 'slots': [], 'thread': None, 'rate': None,
        })
        global_idx = len(self._routing)
        g['need_channels'] = max(g['need_channels'], need_ch)
        g['slots'].append({
            'channel_idx': global_idx,
            'channel_mode': mode,
            'left': left, 'right': right,
            'is_stereo': is_stereo,
            'recorder': recorder,
            'local_rec_idx': local_rec_idx,
            'calibration_offset': calibration_offset,
            'color': color,
            'name': ch_name,
        })
        self._routing[global_idx] = (window, local_vm_idx)
        return global_idx
    
    def start(self, audio_manager):
        for driver_name, g in self._groups.items():
            rate = audio_manager.get_asio_sample_rate(driver_name)
            g['rate'] = rate
            thread = ASIOStreamThread(driver_name, g['slots'], sample_rate=rate)
            thread.data_ready.connect(self._route_data)
            thread.rms_ready.connect(self._route_rms)
            thread.start()
            g['thread'] = thread
            print(f"  [ASIO] Shared driver '{driver_name}': {len(g['slots'])} slots across all windows")
        # Ждём инициализации всех потоков (таймаут 10 с на каждый)
        for g in self._groups.values():
            thread = g['thread']
            if not thread._init_event.wait(10.0):
                print(f"[ASIO] WARNING: thread not initialized after 10s")
            g['rate'] = thread.sample_rate  # обновляем фактической частотой
        self._process_timer = QTimer(self)
        self._process_timer.timeout.connect(self._process_queues)
        self._process_timer.start(40)
    
    def _process_queues(self):
        for g in self._groups.values():
            if g['thread']:
                g['thread'].process_queue()
    
    def stop(self):
        if self._process_timer:
            self._process_timer.stop()
            self._process_timer = None
        for g in self._groups.values():
            if g['thread']:
                g['thread'].stop()
        self._groups.clear()
        self._routing.clear()
    
    def _route_data(self, global_idx, M, S, I):
        win, local = self._routing.get(global_idx, (None, None))
        if win:
            win.volume_meter.buffer_data(local, M, S, I)
    
    def _route_rms(self, global_idx, peak_l, peak_r):
        win, local = self._routing.get(global_idx, (None, None))
        if win:
            win.volume_meter.set_rms(local, peak_l, peak_r)
    
    def get_ch_rates(self):
        rates = {}
        for g in self._groups.values():
            for slot in g['slots']:
                rates[slot['channel_idx']] = g['rate']
        return rates
    
    def get_thread_for_global(self, global_idx):
        """Найти поток ASIO по глобальному индексу слота."""
        for g in self._groups.values():
            for slot in g['slots']:
                if slot['channel_idx'] == global_idx:
                    return g.get('thread')
        return None


class SoloPlayer:
    """Плеер для мониторинга канала (соло) через системное устройство вывода."""
    def __init__(self, sample_rate, channels=1, frames_per_buffer=8192):
        self.queue = queue.Queue(maxsize=2000)
        self._running = True
        self._accum = np.array([], dtype=np.float32)
        self._max_accum = 262144
        self.channels = channels
        bs = max(min(frames_per_buffer, 32768), 4096)
        self.stream = sd.OutputStream(
            samplerate=sample_rate,
            channels=channels,
            callback=self._callback,
            blocksize=bs,
            dtype='float32',
        )
        self.stream.start()
    
    def feed(self, audio_data):
        if self._running:
            try:
                self.queue.put_nowait(audio_data.copy())
            except queue.Full:
                pass
    
    def _callback(self, outdata, frames, time_info, status):
        need = frames * self.channels
        # Ограничиваем аккумулятор, чтобы не рос бесконечно
        if len(self._accum) > self._max_accum:
            self._accum = self._accum[-self._max_accum:]
        while len(self._accum) < need and not self.queue.empty():
            try:
                self._accum = np.concatenate([self._accum, self.queue.get_nowait()])
            except queue.Empty:
                break
        if len(self._accum) >= need:
            data = self._accum[:need]
            self._accum = self._accum[need:]
        else:
            data = np.concatenate([self._accum, np.zeros(need - len(self._accum), dtype=np.float32)])
            self._accum = self._accum[:0]
        outdata[:] = data.reshape(-1, self.channels)
    
    def stop(self):
        self._running = False
        self.stream.abort()
        self.stream.close()


# ─── Recorder ────────────────────────────────────────────────────
import wave as _wave

REC_FORMATS = [
    ('WAV 44.1 кГц / 16 бит', 44100, 2, 'wav'),
    ('WAV 44.1 кГц / 24 бит', 44100, 3, 'wav'),
    ('WAV 48 кГц / 16 бит',   48000, 2, 'wav'),
    ('WAV 48 кГц / 24 бит',   48000, 3, 'wav'),
    ('WAV 96 кГц / 16 бит',   96000, 2, 'wav'),
    ('WAV 96 кГц / 24 бит',   96000, 3, 'wav'),
]

class RecorderManager(QObject):
    """Многодорожечный рекордер"""
    recording_started = pyqtSignal()
    recording_stopped = pyqtSignal()
    timecode_updated = pyqtSignal(str)
    
    def __init__(self, parent=None, emit_signals=True):
        super().__init__(parent)
        self.recording = False
        self.emit_signals = emit_signals
        self.format_idx = 1
        self._base_dir_override = None
        self.armed = set()
        self._writers = {}       # ch_idx -> _wave.Writer
        self._wav_paths = {}     # ch_idx -> str (для диагностики)
        self._frame_count = {}   # ch_idx -> int
        self._ch_nchannels = {}  # ch_idx -> 1 (mono) or 2 (stereo)
        self._buf = {}
        self._buf_lock = threading.Lock()
        self._start_time = None
        self._base_dir = None
        self._flush_timer = None
        self._ch_rate = {}  # ch_idx -> реальная частота дискретизации устройства
        
    @property
    def fmt(self):
        return REC_FORMATS[self.format_idx]
    
    def arm(self, ch_idx):
        self.armed.add(ch_idx)
    def disarm(self, ch_idx):
        self.armed.discard(ch_idx)
    def is_armed(self, ch_idx):
        return ch_idx in self.armed
    
    def feed_audio(self, channel_idx, audio_data, sample_rate):
        if not self.recording:
            return
        with self._buf_lock:
            if channel_idx not in self.armed:
                return
            norm = audio_data.astype(np.float64) / 32768.0
            self._buf.setdefault(channel_idx, []).append(norm)
    
    def feed_audio_stereo(self, channel_idx, left_data, right_data, sample_rate):
        """Запись стерео (L и R интерливингом)."""
        if not self.recording:
            return
        with self._buf_lock:
            if channel_idx not in self.armed:
                return
            # left_data/right_data = float32 [-1, 1] — raw from ASIO, не scaled
            l = left_data.astype(np.float64)
            r = right_data.astype(np.float64)
            interleaved = np.empty(len(l) * 2, dtype=np.float64)
            interleaved[0::2] = l
            interleaved[1::2] = r
            self._buf.setdefault(channel_idx, []).append(interleaved)
    
    def start_recording(self, window_title, channel_names, channel_nchannels=None, channel_rates=None, subdir=None):
        """
        channel_names: dict ch_idx -> name
        channel_nchannels: dict ch_idx -> 1|2 (mono/stereo, default 1)
        channel_rates: dict ch_idx -> sample_rate (реальная частота устройства, если None — из формата)
        subdir: поддиректория для записи (напр. имя драйвера), None — корень сессии
        """
        if self.recording:
            return
        
        width = self.fmt[2]
        fmt_rate = self.fmt[1]
        if channel_nchannels is None:
            channel_nchannels = {}
        if channel_rates is None:
            channel_rates = {}
        
        # Активируем запись ДО создания директорий — ASIO callback сразу начнёт
        # буферизовать данные в _buf, даже если _writers ещё нет.
        with self._buf_lock:
            self.recording = True
            self._start_time = time.time()
            self._writers.clear()
            self._wav_paths.clear()
            self._frame_count.clear()
            self._ch_nchannels.clear()
            self._ch_rate.clear()
            self._buf.clear()
        
        # Медленные операции (создание директорий на сетевом диске)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        safe_win = ''.join(c if c.isalnum() or c in ' _-' else '_' for c in window_title).strip()
        root = self._base_dir_override if self._base_dir_override else 'recordings'
        base = os.path.join(root, ts, safe_win)
        if subdir:
            self._base_dir = os.path.join(base, subdir)
        else:
            self._base_dir = base
        os.makedirs(self._base_dir, exist_ok=True)
        
        # Создаём writers для всех вооружённых каналов (БЕЗ блокировки — это медленная операция с файловой системой)
        pre_buf_size = 0
        new_writers = {}
        new_wav_paths = {}
        for ch_idx in self.armed:
            nch = channel_nchannels.get(ch_idx, 1)
            rate = channel_rates.get(ch_idx, fmt_rate)
            safe_name = ''.join(c if c.isalnum() or c in ' _-' else '_' for c in channel_names.get(ch_idx, f'ch{ch_idx}')).strip()
            fpath = os.path.join(self._base_dir, f'{safe_name}.wav')
            wf = _wave.open(fpath, 'wb')
            wf.setnchannels(nch)
            wf.setsampwidth(width)
            wf.setframerate(rate)
            new_writers[ch_idx] = wf
            new_wav_paths[ch_idx] = fpath
        # Быстрая операция под блокировкой — только назначение writer'ов и сброс _buf
        with self._buf_lock:
            for ch_idx in self.armed:
                self._writers[ch_idx] = new_writers[ch_idx]
                self._wav_paths[ch_idx] = new_wav_paths[ch_idx]
                self._frame_count[ch_idx] = 0
                self._ch_nchannels[ch_idx] = channel_nchannels.get(ch_idx, 1)
                self._ch_rate[ch_idx] = channel_rates.get(ch_idx, fmt_rate)
            # Сброс данных, накопленных до создания writer'ов
            for ch_idx, chunks in list(self._buf.items()):
                if ch_idx in self._writers and chunks:
                    pre_buf_size += sum(len(c) for c in chunks)
                    self._write_chunks(ch_idx, chunks)
        
        if pre_buf_size > 0:
            print(f"  [REC] Flushed {pre_buf_size} pre-writer samples from _buf")
        
        self._flush_timer = QTimer(self)
        self._flush_timer.timeout.connect(self.flush_all)
        self._flush_timer.start(500)
        if self.emit_signals:
            self.recording_started.emit()
        n_armed = len(self.armed)
        print(f"[REC] Recording started -> {self._base_dir} ({n_armed} ch, {self.fmt[1]}Hz/{'%dbit' % (self.fmt[2]*8)})")
    
    def stop_recording(self):
        if not self.recording:
            return
        elapsed = time.time() - self._start_time
        self.recording = False
        if self._flush_timer:
            self._flush_timer.stop()
            self._flush_timer = None
        # Финальный сброс + закрытие под одной блокировкой
        with self._buf_lock:
            for ch_idx, chunks in list(self._buf.items()):
                if chunks:
                    self._write_chunks(ch_idx, chunks)
            # Дополняем тишиной, если записанных фреймов меньше ожидаемых
            for ch_idx in list(self._writers.keys()):
                rate = self._ch_rate.get(ch_idx, self.fmt[1])
                expected = int(elapsed * rate)
                actual = self._frame_count.get(ch_idx, 0)
                if actual < expected:
                    gap = expected - actual
                    nch = self._ch_nchannels.get(ch_idx, 1)
                    silence = np.zeros(gap * nch, dtype=np.float64)
                    self._write_chunks(ch_idx, [silence])
                    print(f"  [REC] ch{ch_idx}: padded {gap} silence frames ({gap/rate:.2f}s)")
            for wf in self._writers.values():
                try: wf.close()
                except: pass
            self._writers.clear()
            self._buf.clear()
        if self.emit_signals:
            self.recording_stopped.emit()
        elapsed_str = f"{elapsed:.1f}s" if elapsed else "?"
        total_frames = sum(self._frame_count.values()) if self._frame_count else 0
        for ch_idx, nf in sorted(self._frame_count.items()):
            sr = self._ch_rate.get(ch_idx, self.fmt[1])
            dur = nf / sr if sr else 0
            print(f"  [REC] ch{ch_idx}: {nf} frames @ {sr} Hz = {dur:.2f}s ({elapsed_str} wall)")
        print(f"[REC] Recording stopped ({elapsed_str}, {total_frames} frames total)")
    
    def flush_all(self):
        """Сброс буферов на диск (вызывается по таймеру из потока Qt)."""
        with self._buf_lock:
            snap = self._buf
            self._buf = {}
            writers = dict(self._writers)
        for ch_idx, chunks in snap.items():
            if chunks:
                self._write_chunks(ch_idx, chunks)
    
    def _write_chunks(self, ch_idx, chunks):
        """Запись на диск (без блокировок — вызывается снаружи)."""
        try:
            cat = np.concatenate(chunks)
            wf = self._writers.get(ch_idx)
            if wf is None:
                return
            nch = wf.getnchannels()
            width = self.fmt[2]
            frames = len(cat) // nch
            
            if nch == 2:
                cat_2d = np.ascontiguousarray(cat.reshape(-1, 2))
                if width == 2:
                    pcm = np.clip(np.round(cat_2d * 32767.0), -32768, 32767).astype('<i2').ravel()
                elif width == 3:
                    scaled = np.clip(np.round(cat_2d * 8388607.0), -8388608, 8388607).astype('<i4')
                    l_3 = scaled[:, 0].copy().view('<u1').reshape(-1, 4)[:, :3]
                    r_3 = scaled[:, 1].copy().view('<u1').reshape(-1, 4)[:, :3]
                    pcm = np.column_stack([l_3, r_3]).ravel()
            else:
                if width == 2:
                    pcm = np.clip(np.round(cat * 32767.0), -32768, 32767).astype('<i2')
                elif width == 3:
                    scaled = np.clip(np.round(cat * 8388607.0), -8388608, 8388607).astype('<i4')
                    pcm = scaled.view('<u1').reshape(-1, 4)[:, :3].ravel()
            
            wf.writeframes(pcm.tobytes())
            self._frame_count[ch_idx] = self._frame_count.get(ch_idx, 0) + frames
        except Exception as e:
            print(f"[REC] Write error ch{ch_idx}: {e}")
    
    def get_current_timecode(self):
        if not self._start_time:
            return "00:00:00:00"
        elapsed = time.time() - self._start_time
        h = int(elapsed // 3600)
        m = int((elapsed % 3600) // 60)
        s = int(elapsed % 60)
        f = int((elapsed % 1) * 25)
        return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"

class VolumeMeterWidget(QWidget):
    def __init__(self, target_lufs=-10.0, display_time=10, parent=None):
        super().__init__(parent)
        self.target_lufs = target_lufs
        self.display_time = display_time
        self.values = []
        self.history = []   # list[list[float]] — значения, размер = display_time * 10
        self.colors = []
        self.labels = []
        self.fill_enabled = False
        
        self.setMinimumSize(300, 200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        self.current_momentary = -70.0
        self.current_short_term = -70.0
        self.current_integrated = -70.0
        
        self._draw_order = []
        
        self._vu_bars = {}
        self._vu_peak = {}   # ch_idx -> {'l': peak_db, 'r': peak_db}
        self._vu_timestamp = {}  # ch_idx -> time.time()
        self._data_buffer = []
        self._buffer_lock = threading.Lock()
        self._sync_timer = QTimer(self)
        self._sync_timer.timeout.connect(self._flush_buffer)
        self._sync_timer.start(40)
        
        # Диапазон отображения по Y
        self.level_bottom = -70.0
        self.level_top = 0.0
        
        # Рабочий диапазон (полупрозрачная полоса)
        self.working_range_enabled = False
        self.working_range_fill_enabled = True
        self.working_range_width = 6.0  # dB, ширина полосы
        
    def buffer_data(self, channel_idx, momentary, short_term, integrated):
        with self._buffer_lock:
            self._data_buffer.append((channel_idx, momentary, short_term, integrated))
    
    def set_rms(self, channel_idx, peak_db_l, peak_db_r):
        """True Peak VU с ballistic: атака 0.15s, спад 1s, шкала -60..0 dBFS."""
        now = time.time()
        prev = self._vu_peak.get(channel_idx, {'l': -100.0, 'r': -100.0})
        t_last = self._vu_timestamp.get(channel_idx, now)
        dt = max(now - t_last, 0.0001)
        
        new_l = self._ballistic(prev['l'], peak_db_l, dt, 0.15, 0.3)
        new_r = self._ballistic(prev['r'], peak_db_r, dt, 0.15, 0.3)
        
        self._vu_peak[channel_idx] = {'l': new_l, 'r': new_r}
        self._vu_timestamp[channel_idx] = now
        
        bars = self._vu_bars.get(channel_idx)
        if bars is not None:
            vu_l = max(0, min(100, (new_l + 60) * 1.6667))
            bars['l'].setValue(int(vu_l))
            if bars['r'] is not None:
                vu_r = max(0, min(100, (new_r + 60) * 1.6667))
                bars['r'].setValue(int(vu_r))
    
    def _ballistic(self, prev, target, dt, attack_tc, decay_tc):
        """Экспоненциальный ballistic: prev -> target за dt секунд."""
        tc = attack_tc if target > prev else decay_tc
        return prev + (target - prev) * (1.0 - math.exp(-dt / tc))
    
    def _flush_buffer(self):
        with self._buffer_lock:
            if not self._data_buffer:
                return
            items = self._data_buffer[:]
            self._data_buffer.clear()
        
        per_channel = {}
        for channel_idx, momentary, short_term, integrated in items:
            if 0 <= channel_idx < len(self.values):
                self.values[channel_idx] = (momentary, short_term, integrated)
                per_channel.setdefault(channel_idx, []).append(momentary)
                self.current_momentary = momentary
                self.current_short_term = short_term
                self.current_integrated = integrated
        
        if not per_channel:
            return
        
        ch_indices = sorted(per_channel.keys())
        counts = [len(per_channel[ch]) for ch in ch_indices]
        n = max(counts)
        
        target = int(self.display_time * 10)
        for ch_idx in ch_indices:
            buf = per_channel[ch_idx]
            if len(buf) < n:
                last = buf[-1] if buf else self.level_bottom
                buf.extend([last] * (n - len(buf)))
            # Дополняем историю слева до target, чтобы график сразу был полной ширины
            while len(self.history[ch_idx]) < target:
                self.history[ch_idx].append(self.level_bottom)
            self.history[ch_idx].extend(buf)
            if len(self.history[ch_idx]) > target:
                self.history[ch_idx] = self.history[ch_idx][-target:]
        
        self.update()
        
    def set_target(self, target_lufs):
        self.target_lufs = target_lufs
        self.update()
    
    def set_level_range(self, bottom, top):
        self.level_bottom = bottom
        self.level_top = top
        self.update()
    
    def set_working_range(self, enabled, width, fill_enabled):
        self.working_range_enabled = enabled
        self.working_range_width = width
        self.working_range_fill_enabled = fill_enabled
        self.update()
    
    def set_display_time(self, display_time):
        self.display_time = display_time
        target = int(display_time * 10)
        for i in range(len(self.history)):
            if len(self.history[i]) > target:
                self.history[i] = self.history[i][-target:]
        self.update()
        
    def set_fill_enabled(self, enabled):
        self.fill_enabled = enabled
        self.update()
        
    def set_vu_bar(self, channel_idx, bar_l, bar_r=None):
        if bar_l is None:
            self._vu_bars.pop(channel_idx, None)
        else:
            self._vu_bars[channel_idx] = {'l': bar_l, 'r': bar_r}
    
    def add_channel(self, color, label):
        self.colors.append(QColor(color))
        self.labels.append(label)
        self.values.append((-70.0, -70.0, -70.0))
        target = int(self.display_time * 10)
        self.history.append([self.level_bottom] * target)
        
    def set_sort_order(self, order):
        self._draw_order = order
        
    def update_value(self, channel_idx, momentary, short_term, integrated):
        if 0 <= channel_idx < len(self.values):
            self.values[channel_idx] = (momentary, short_term, integrated)
            self.current_momentary = momentary
            self.current_short_term = short_term
            self.current_integrated = integrated
            target = int(self.display_time * 10)
            if len(self.history[channel_idx]) < target:
                self.history[channel_idx] = [self.level_bottom] * target
            self.history[channel_idx].append(momentary)
            if len(self.history[channel_idx]) > target:
                self.history[channel_idx] = self.history[channel_idx][-target:]
            self.update()
            
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        
        if hasattr(self.window(), 'is_dark_mode') and self.window().is_dark_mode:
            bg, grid, text, fill = QColor(30,30,30), QColor(80,80,80), QColor(220,220,220), QColor(60,60,60,100)
        else:
            bg, grid, text, fill = QColor(240,240,240), QColor(180,180,180), QColor(40,40,40), QColor(200,200,200,100)
        
        painter.fillRect(0, 0, w, h, bg)
        self._draw_grid(painter, w, h, grid, text)
        self._draw_working_range(painter, w, h)
        if self.fill_enabled:
            self._draw_fill(painter, w, h)
        self._draw_target_level(painter, w, h)
        self._draw_graphs(painter, w, h)
        self._draw_current_values(painter, w, h, text)
        
    def _draw_grid(self, painter, w, h, grid_color, text_color):
        painter.setPen(QPen(grid_color, 1))
        bot = self.level_bottom
        top = self.level_top
        span = top - bot
        step = 10 if span > 40 else 5
        for db in range(int(bot // step * step), int(top) + 1, step):
            if db < bot:
                continue
            y = self._db_to_y(db, h)
            painter.drawLine(50, y, w - 10, y)
            painter.setPen(text_color)
            painter.drawText(10, y + 5, f"{db}")
            painter.setPen(QPen(grid_color, 1))
        
        gw = w - 60
        dt = max(1, self.display_time)
        n_ticks = max(1, min(10, int(dt / 5)))
        step_t = dt / n_ticks
        for i in range(n_ticks + 1):
            sec = i * step_t
            x = 50 + int(sec * gw / dt)
            painter.drawLine(x, 20, x, h - 20)
            painter.setPen(text_color)
            painter.drawText(x - 15, h - 5, f"{sec:.0f}")
            painter.setPen(QPen(grid_color, 1))
        
        painter.setPen(text_color)
        painter.drawText(w // 2 - 20, h - 5, "Время (с)")
        painter.drawText(5, h // 2, "dBFS")
    
    def _db_to_y(self, db, h):
        """Преобразует dB в Y-координату на графике."""
        bot = self.level_bottom
        top = self.level_top
        span = top - bot
        return h - 20 - int((db - bot) * (h - 40) / span)
        
    def _draw_fill(self, painter, w, h):
        if not self.history:
            return
        gw, gh = w - 60, h - 40
        mx = max(1, gw)
        target = int(self.display_time * 10)
        order = self._draw_order if self._draw_order else list(range(len(self.history)))
        for draw_idx, vm_idx in enumerate(order):
            if vm_idx >= len(self.history) or vm_idx >= len(self.colors):
                continue
            hist = self.history[vm_idx]
            if not hist:
                continue
            pts = hist[-target:]
            pad = target - len(pts)
            s = max(1, target - 1)
            poly = QPolygonF()
            poly.append(QPointF(50, h - 20))
            for j in range(target):
                v = pts[j - len(pts)] if j >= pad else self.level_bottom
                poly.append(QPointF(50 + j * gw / s, self._db_to_y(v, h)))
            poly.append(QPointF(w - 10, h - 20))
            c = self.colors[vm_idx]
            fill_color = QColor(c.red(), c.green(), c.blue(), 60)
            painter.setBrush(fill_color)
            painter.setPen(Qt.NoPen)
            painter.drawPolygon(poly)
        
    def _draw_target_level(self, painter, w, h):
        y = self._db_to_y(self.target_lufs, h)
        painter.setPen(QPen(QColor(255, 0, 0), 2, Qt.DashLine))
        painter.drawLine(50, y, w - 10, y)
        c = QColor(255, 150, 150) if (hasattr(self.window(), 'is_dark_mode') and self.window().is_dark_mode) else QColor(200, 0, 0)
        painter.setPen(c)
        painter.drawText(w - 40, y - 5, f"{self.target_lufs:.1f}")
        
    def _downsample(self, data, max_points):
        if len(data) <= max_points:
            return data
        step = len(data) / max_points
        return [data[int(i * step)] for i in range(max_points)]
    
    def _draw_working_range(self, painter, w, h):
        if not self.working_range_enabled:
            return
        half = self.working_range_width / 2.0
        y_top = self._db_to_y(self.target_lufs + half, h)
        y_bot = self._db_to_y(self.target_lufs - half, h)
        rect = QRectF(50, y_top, w - 60, y_bot - y_top)
        if self.working_range_fill_enabled:
            painter.fillRect(rect, QColor(144, 238, 144, 25))
        painter.setPen(QPen(QColor(144, 238, 144, 160), 1, Qt.DashLine))
        painter.drawLine(int(rect.left()), y_top, int(rect.right()), y_top)
        painter.drawLine(int(rect.left()), y_bot, int(rect.right()), y_bot)
    
    def _draw_graphs(self, painter, w, h):
        if not self.history:
            return
        gw = w - 60
        target = int(self.display_time * 10)
        order = self._draw_order if self._draw_order else list(range(len(self.history)))
        for draw_idx, vm_idx in enumerate(order):
            if vm_idx >= len(self.history) or vm_idx >= len(self.colors):
                continue
            hist = self.history[vm_idx]
            if not hist:
                continue
            painter.setPen(QPen(self.colors[vm_idx], 2))
            pts = hist[-target:]
            pad = target - len(pts)
            s = max(1, target - 1)
            poly = QPolygonF()
            for j in range(target):
                v = pts[j - len(pts)] if j >= pad else self.level_bottom
                poly.append(QPointF(50 + j * gw / s, self._db_to_y(v, h)))
            painter.drawPolyline(poly)
            
            lx = 60 + draw_idx * 100
            if lx < w - 50:
                painter.drawLine(lx, 15, lx + 30, 15)
                c = QColor(220, 220, 220) if (hasattr(self.window(), 'is_dark_mode') and self.window().is_dark_mode) else QColor(40, 40, 40)
                painter.setPen(c)
                painter.drawText(lx + 35, 20, self.labels[vm_idx])
    
    def _draw_current_values(self, painter, w, h, text_color):
        painter.setPen(text_color)
        f = QFont("Arial", 8)
        painter.setFont(f)
        text = f"M:{self.current_momentary:.1f} S:{self.current_short_term:.1f} I:{self.current_integrated:.1f} T:{self.target_lufs:.1f}"
        if QFontMetrics(f).width(text) < w - 20:
            painter.drawText(10, 15, text)
        else:
            painter.drawText(10, 15, f"M:{self.current_momentary:.1f} T:{self.target_lufs:.1f}")

class AudioDeviceManager:
    """Менеджер аудиоустройств и SRT/OMT потоков (Windows pyaudio, macOS sounddevice)"""
    def __init__(self):
        self.asio_drivers = []
        if IS_WINDOWS:
            self.audio = pyaudio.PyAudio()
            self.asio_drivers = self._enumerate_asio_drivers()
        else:
            self.audio = None
        self.devices = self.get_all_audio_devices()
        self.srt_streams = []
        self.omt_streams = []

    def _enumerate_asio_drivers(self):
        if not HAS_ASIO or not IS_WINDOWS:
            return []
        try:
            from System.Threading import Thread, ApartmentState, ThreadStart
            result = []
            def enum_asio():
                try:
                    for name in list(AsioOut.GetDriverNames()):
                        result.append((name, f"[ASIO] {name}"))
                except Exception as e:
                    print(f"ASIO enum error: {e}")
            t = Thread(ThreadStart(enum_asio))
            t.SetApartmentState(ApartmentState.STA)
            t.Start()
            t.Join()
            return result
        except Exception as e:
            print(f"ASIO enumeration failed: {e}")
            return []

    def get_all_audio_devices(self):
        devices = []

        if IS_WINDOWS:
            for i in range(self.audio.get_device_count()):
                info = self.audio.get_device_info_by_index(i)
                if info['maxInputChannels'] > 0:
                    devices.append((i, f"[Input] {info['name']}", info['maxInputChannels'], 'WDM Input'))
            for i in range(self.audio.get_device_count()):
                info = self.audio.get_device_info_by_index(i)
                if info['maxOutputChannels'] > 0 and info['maxInputChannels'] > 0 and 'output' in info['name'].lower():
                    devices.append((i, f"[Output] {info['name']}", info['maxOutputChannels'], 'WDM Output'))
            for driver_name, display_name in self.asio_drivers:
                devices.append((-3, display_name, 16, 'ASIO'))
            devices.append((-1, "[Virtual] System Output", 2, 'WDM Output'))
        else:
            # macOS: enumerate via sounddevice
            try:
                dev_list = sd.query_devices()
                for i, dev in enumerate(dev_list):
                    if dev['max_input_channels'] > 0:
                        devices.append((i, f"[Input] {dev['name']}", dev['max_input_channels'], 'Input'))
                for i, dev in enumerate(dev_list):
                    if dev['max_output_channels'] > 0 and dev['max_input_channels'] > 0:
                        devices.append((i, f"[Output] {dev['name']}", dev['max_output_channels'], 'Output'))
                devices.append((-1, "[Virtual] System Output", 2, 'Output'))
            except Exception as e:
                print(f"[ERR] Sounddevice device enumeration failed: {e}")

        return devices

    def build_srt_url(self, host, port, stream_id, passphrase, mode):
        url = f"srt://{host}:{port}?mode={mode}"
        if stream_id:
            url += f"&streamid={stream_id}"
        if passphrase:
            url += f"&passphrase={passphrase}"
        return url

    def add_srt_stream(self, host, port, stream_id, passphrase, mode, name):
        self.srt_streams.append((host, port, stream_id, passphrase, mode, name))
        print(f"Добавлен SRT поток: {name} -> {self.build_srt_url(host, port, stream_id, passphrase, mode)}")

    def add_omt_stream(self, host, port, name):
        self.omt_streams.append((host, port, name))
        print(f"Добавлен OMT поток: {name} -> {host}:{port}")

    def get_all_devices(self):
        all_devices = self.devices.copy()
        for host, port, stream_id, passphrase, mode, name in self.srt_streams:
            all_devices.append((-2, f"[SRT] {name}", 2, 'SRT Stream'))
        for host, port, name in self.omt_streams:
            all_devices.append((-4, f"[OMT] {name}", 32, 'OMT Stream'))
        return all_devices

    def get_device_index_by_name(self, name):
        for idx, device_name, _, _ in self.get_all_devices():
            if device_name == name:
                return idx
        return None

    def get_device_type(self, name):
        for idx, device_name, _, device_type in self.get_all_devices():
            if device_name == name:
                return device_type
        return 'WDM Input' if IS_WINDOWS else 'Input'

    # ─── Windows-only: ASIO helpers ────────────────────────────────
    def get_asio_driver_name(self, display_name):
        if not IS_WINDOWS:
            return display_name
        for driver_name, disp in self.asio_drivers:
            if disp == display_name:
                return driver_name
        return display_name[7:] if display_name.startswith("[ASIO] ") else display_name

    def get_asio_sample_rate(self, driver_name):
        if not HAS_ASIO or not IS_WINDOWS:
            return RATE
        try:
            result = [RATE]
            def query():
                try:
                    import System
                    from NAudio.Wave.Asio import AsioDriver
                    driver = AsioDriver.GetAsioDriverByName(driver_name)
                    driver.Init(System.IntPtr.Zero)
                    result[0] = int(driver.GetSampleRate())
                    driver.ReleaseComAsioDriver()
                    print(f"[ASIO] {driver_name} sample rate: {result[0]} Hz")
                except Exception as e:
                    print(f"[ASIO] Sample rate query error: {e}")
            from System.Threading import Thread, ApartmentState, ThreadStart
            t = Thread(ThreadStart(query))
            t.SetApartmentState(ApartmentState.STA)
            t.Start()
            t.Join()
            return result[0] if result[0] > 0 else RATE
        except Exception as e:
            print(f"ASIO sample rate failed: {e}")
            return RATE

    def get_asio_channel_count(self, driver_name):
        if not HAS_ASIO or not IS_WINDOWS:
            return 256
        try:
            result = [0]
            def query():
                try:
                    import System
                    from NAudio.Wave.Asio import AsioDriver
                    driver = AsioDriver.GetAsioDriverByName(driver_name)
                    driver.Init(System.IntPtr.Zero)
                    in_ch, out_ch = driver.GetChannels()
                    result[0] = int(in_ch)
                    driver.ReleaseComAsioDriver()
                except Exception as e:
                    print(f"[ASIO] Channel count query error: {e}")
            from System.Threading import Thread, ApartmentState, ThreadStart
            t = Thread(ThreadStart(query))
            t.SetApartmentState(ApartmentState.STA)
            t.Start()
            t.Join()
            return result[0] if result[0] > 0 else 256
        except Exception as e:
            print(f"ASIO channel count failed: {e}")
            return 256

class ChannelConfigWidget(QWidget):
    """Виджет для настройки канала"""
    remove_requested = pyqtSignal(object)  # emit self
    
    def __init__(self, channel_idx, audio_manager, parent=None):
        super().__init__(parent)
        self.channel_idx = channel_idx
        self.audio_manager = audio_manager
        self.setup_ui()
        
    def setup_ui(self):
        layout = QHBoxLayout(self)
        
        self.enabled_checkbox = QCheckBox(f"Канал {self.channel_idx + 1}")
        self.enabled_checkbox.setChecked(True)
        
        self.name_edit = QLineEdit(f"Канал {self.channel_idx + 1}")
        self.name_edit.setMaximumWidth(150)
        self.name_edit.textChanged.connect(self.on_name_changed)
        
        self.device_combo = QComboBox()
        self.channel_mode_combo = QComboBox()
        self._populate_default_modes()
        
        self._current_device_type = 'WDM Input' if IS_WINDOWS else 'Input'
        
        # При смене устройства обновляем список режимов (для ASIO)
        self.device_combo.currentIndexChanged.connect(self._on_device_changed)
        
        # Заполняем список устройств (должен быть после создания channel_mode_combo)
        self.refresh_devices()
        
        self.color_combo = QComboBox()
        self.color_combo.addItems(["Серый", "Зеленый", "Красный", "Синий", "Желтый", "Пурпурный", "Голубой"])
        self.color_combo.setCurrentIndex(self.channel_idx % 7)
        
        layout.addWidget(self.enabled_checkbox)
        layout.addWidget(QLabel("Имя:"))
        layout.addWidget(self.name_edit)
        layout.addWidget(QLabel("Устройство:"))
        layout.addWidget(self.device_combo)
        layout.addWidget(QLabel("Режим:"))
        layout.addWidget(self.channel_mode_combo)
        layout.addWidget(QLabel("Цвет:"))
        layout.addWidget(self.color_combo)
        
        # Arm button for recording
        self.arm_btn = QPushButton("R")
        self.arm_btn.setFixedSize(22, 22)
        self.arm_btn.setCheckable(True)
        self.arm_btn.setToolTip("Вооружить канал для записи")
        self.arm_btn.setStyleSheet("QPushButton { font-weight: bold; color: #666; border: 1px solid #888; border-radius: 3px; } QPushButton:checked { color: red; border: 2px solid red; background: #440000; }")
        layout.addWidget(self.arm_btn)
        
        # VU meter bars (L и R)
        self.vu_bar_l = QProgressBar()
        self.vu_bar_l.setFixedWidth(28)
        self.vu_bar_l.setFixedHeight(14)
        self.vu_bar_l.setRange(0, 100)
        self.vu_bar_l.setValue(0)
        self.vu_bar_l.setTextVisible(False)
        self.vu_bar_l.setStyleSheet("QProgressBar { border: 1px solid #555; border-radius: 2px; background: #222; } QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 green, stop:0.6 yellow, stop:0.8 orange, stop:1 red); }")
        layout.addWidget(self.vu_bar_l)
        
        self.vu_bar_r = QProgressBar()
        self.vu_bar_r.setFixedWidth(28)
        self.vu_bar_r.setFixedHeight(14)
        self.vu_bar_r.setRange(0, 100)
        self.vu_bar_r.setValue(0)
        self.vu_bar_r.setTextVisible(False)
        self.vu_bar_r.setStyleSheet("QProgressBar { border: 1px solid #555; border-radius: 2px; background: #222; } QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 green, stop:0.6 yellow, stop:0.8 orange, stop:1 red); }")
        self.vu_bar_r.setVisible(False)  # скрыт для моно
        layout.addWidget(self.vu_bar_r)
        
        # Кнопка удаления канала
        self.remove_btn = QPushButton("✕")
        self.remove_btn.setFixedSize(20, 20)
        self.remove_btn.setToolTip("Удалить канал")
        self.remove_btn.clicked.connect(lambda: self.remove_requested.emit(self))
        layout.addWidget(self.remove_btn)
        
        self.apply_theme()
        
    def on_name_changed(self, text):
        self.enabled_checkbox.setText(text)
        
    def refresh_devices(self):
        """Обновить список устройств"""
        self.device_combo.clear()
        for _, name, _, _ in self.audio_manager.get_all_devices():
            self.device_combo.addItem(name)
        # Обновляем режим каналов после смены списка устройств
        self._on_device_changed()
        
    def _get_selected_device_type(self):
        """Определить тип выбранного устройства"""
        name = self.device_combo.currentText()
        return self.audio_manager.get_device_type(name)
    
    def _on_device_changed(self):
        device_type = self._get_selected_device_type()
        self._current_device_type = device_type

        if IS_WINDOWS and device_type == 'ASIO':
            device_name = self.device_combo.currentText()
            driver_name = self.audio_manager.get_asio_driver_name(device_name)
            ch_count = self.audio_manager.get_asio_channel_count(driver_name)
            self._populate_asio_modes(ch_count)
        elif device_type == 'OMT Stream':
            self._populate_asio_modes(32)
        else:
            self._populate_default_modes()
    
    def _populate_default_modes(self):
        """Стандартные режимы для WDM/SRT устройств (2 канала)"""
        self.channel_mode_combo.blockSignals(True)
        self.channel_mode_combo.clear()
        self.channel_mode_combo.addItems(["1+2 (Стерео)", "1+1 (Моно L)", "2+2 (Моно R)"])
        self.channel_mode_combo.setCurrentIndex(0)
        self.channel_mode_combo.blockSignals(False)
    
    def _populate_asio_modes(self, channel_count):
        """Заполнить список режимов каналами ASIO драйвера"""
        self.channel_mode_combo.blockSignals(True)
        self.channel_mode_combo.clear()
        
        if channel_count <= 0:
            channel_count = 256  # запасной вариант для неизвестных ASIO драйверов
        
        # Пары каналов: 1+2, 3+4, 5+6, ...
        for i in range(1, channel_count, 2):
            if i + 1 <= channel_count:
                self.channel_mode_combo.addItem(f"{i}+{i+1}")
        
        # Отдельные каналы: 1, 2, 3, ... (моно)
        for i in range(1, channel_count + 1):
            self.channel_mode_combo.addItem(str(i))
        
        self.channel_mode_combo.setCurrentIndex(0)
        self.channel_mode_combo.blockSignals(False)
        
    def apply_theme(self):
        """Применяем тему к виджету"""
        if hasattr(self.window(), 'is_dark_mode') and self.window().is_dark_mode:
            self.setStyleSheet("""
                QCheckBox, QLabel { color: white; }
                QComboBox, QLineEdit { 
                    background-color: #333; 
                    color: white; 
                    border: 1px solid #555;
                }
                QComboBox::drop-down { border: 0px; }
                QComboBox::down-arrow { image: none; border: 0px; }
            """)
        else:
            self.setStyleSheet("")
        
    def get_color(self):
        color_map = {
            "Серый": "gray",
            "Зеленый": "green",
            "Красный": "red",
            "Синий": "blue",
            "Желтый": "yellow",
            "Пурпурный": "magenta",
            "Голубой": "cyan"
        }
        return color_map[self.color_combo.currentText()]
    
    def is_enabled(self):
        return self.enabled_checkbox.isChecked()
    
    def get_device_name(self):
        return self.device_combo.currentText()
    
    def get_channel_mode(self):
        asio_like = IS_WINDOWS and self._current_device_type in ('ASIO', 'OMT Stream')
        if asio_like or self._current_device_type == 'OMT Stream':
            return self.channel_mode_combo.currentText()
        else:
            mode_text = self.channel_mode_combo.currentText()
            if "Стерео" in mode_text:
                return "1+2"
            elif "Моно L" in mode_text:
                return "1+1"
            else:
                return "2+2"
    
    def get_channel_name(self):
        return self.name_edit.text()
    
    @property
    def vu_bar(self):
        return self.vu_bar_l

class MeterWindow(QWidget):
    """Окно с измерителем громкости"""
    def __init__(self, window_idx, audio_manager, calibration_offset=0.0, parent=None):
        super().__init__(parent)
        self.window_idx = window_idx
        self.audio_manager = audio_manager
        self.calibration_offset = calibration_offset
        self.channels = []
        self.audio_threads = []
        self.custom_title = f"Окно {window_idx + 1}"  # Название окна
        self.recorder = None
        self._vm_to_ch_name = {}
        self._vm_to_color = {}
        self._vm_to_order = {}
        self._vm_to_global = {}  # local_vm_idx → global_idx (для соло)
        self._vm_to_thread = {}  # local_vm_idx → thread (для не-ASIO соло)
        self._recording = False
        self._asio_ch_rates = {}  # channel_idx -> sample_rate
        self._driver_recorders = {}  # driver_name → RecorderManager (инициализируется рано для stop_measurement)
        self._vm_to_driver = {}      # local_vm_idx → driver_name
        self._solo_players = {}   # local_vm_idx → SoloPlayer
        self._solo_active = {}    # local_vm_idx → bool
        
        self.setup_ui()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Заголовок окна с редактируемым названием
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        
        self.title_edit = QLineEdit(self.custom_title)
        self.title_edit.setStyleSheet("font-weight: bold; font-size: 14px; border: 1px solid #ccc; padding: 2px;")
        self.title_edit.textChanged.connect(self.update_title)
        
        self.toggle_button = QPushButton("▲")
        self.toggle_button.setFixedSize(20, 20)
        self.toggle_button.clicked.connect(self.toggle_config)
        
        # Рекордер
        self.recorder = RecorderManager(self)
        self.rec_btn = QPushButton("● Запись")
        self.rec_btn.setFixedHeight(22)
        self.rec_btn.setStyleSheet("QPushButton { color: #888; } QPushButton:hover { color: red; }")
        self.rec_btn.setToolTip("Начать запись")
        self.rec_btn.clicked.connect(self.toggle_recording)
        self.rec_btn.setEnabled(True)
        
        self.smpte_label = QLabel("00:00:00:00")
        self.smpte_label.setStyleSheet("font-family: monospace; font-size: 12px; color: #aaa;")
        self.smpte_label.setVisible(False)
        
        self.smpte_timer = QTimer(self)
        self.smpte_timer.timeout.connect(self.update_smpte)
        
        self.recorder.recording_started.connect(self.on_recording_started)
        self.recorder.recording_stopped.connect(self.on_recording_stopped)
        
        header_layout.addWidget(self.title_edit)
        header_layout.addWidget(self.toggle_button)
        header_layout.addWidget(self.rec_btn)
        header_layout.addWidget(self.smpte_label)
        header_layout.addStretch()
        
        layout.addWidget(header_widget)
        
        # Конфигурация каналов
        self.config_widget = QWidget()
        self.config_layout = QVBoxLayout(self.config_widget)
        
        self.channel_layout = QVBoxLayout()
        for i in range(2):  # 2 канала по умолчанию
            channel_config = ChannelConfigWidget(i, self.audio_manager)
            channel_config.remove_requested.connect(self.remove_channel)
            self.channels.append(channel_config)
            self.channel_layout.addWidget(channel_config)
        
        self.config_layout.addLayout(self.channel_layout)
        
        # Кнопка добавления канала
        btn_layout = QHBoxLayout()
        self.add_channel_btn = QPushButton("+ Добавить канал")
        self.add_channel_btn.clicked.connect(self.add_channel)
        btn_layout.addWidget(self.add_channel_btn)
        btn_layout.addStretch()
        self.config_layout.addLayout(btn_layout)
        
        layout.addWidget(self.config_widget)
        
        # Легенда каналов (цвет + имя + кнопка соло)
        self.legend_widget = QWidget()
        self.legend_layout = QHBoxLayout(self.legend_widget)
        self.legend_layout.setContentsMargins(5, 0, 5, 0)
        self.legend_layout.setSpacing(8)
        self.legend_items = []  # список dict с label, solo_btn, idx
        layout.addWidget(self.legend_widget)
        
        # Измеритель громкости
        self.volume_meter = VolumeMeterWidget()
        layout.addWidget(self.volume_meter)
        
        # Изначально показываем конфигурацию
        self.config_visible = True
        
    def update_title(self, text):
        """Обновить название окна"""
        self.custom_title = text
        self.update()
        
    def toggle_config(self):
        self.config_visible = not self.config_visible
        self.config_widget.setVisible(self.config_visible)
        self.toggle_button.setText("▼" if self.config_visible else "▲")
        
    def add_channel(self):
        new_idx = len(self.channels)
        channel_config = ChannelConfigWidget(new_idx, self.audio_manager)
        channel_config.remove_requested.connect(self.remove_channel)
        self.channels.append(channel_config)
        self.channel_layout.addWidget(channel_config)
        
    def remove_channel(self, channel_widget):
        if len(self.channels) <= 1:
            return
        idx = self.channels.index(channel_widget)
        if idx < 0:
            return
        channel = self.channels.pop(idx)
        self.channel_layout.removeWidget(channel)
        channel.setParent(None)
        channel.deleteLater()
        
    def set_calibration_offset(self, offset):
        """Установить смещение калибровки"""
        self.calibration_offset = offset
    
    def toggle_recording(self):
        mw = self.window()
        if not self._recording:
            # Собираем вооружённые каналы, группируя по рекордеру (per-драйвер для ASIO, window для остальных)
            armed_by_rec = {}  # recorder -> {seq_idx: info}
            seq_idx = 0
            for ch in self.channels:
                if ch.is_enabled():
                    if ch.arm_btn.isChecked():
                        mode = ch.get_channel_mode()
                        is_stereo = '+' in mode or 'Стерео' in mode
                        # Какой рекордер использует этот канал?
                        driver_name = getattr(self, '_vm_to_driver', {}).get(seq_idx)
                        driver_recorders = getattr(self, '_driver_recorders', {})
                        if driver_name and driver_name in driver_recorders:
                            rec = driver_recorders[driver_name]
                        else:
                            rec = self.recorder
                        armed_by_rec.setdefault(rec, {})[seq_idx] = {
                            'name': ch.get_channel_name(),
                            'nch': 2 if is_stereo else 1,
                            'stereo': is_stereo,
                        }
                    seq_idx += 1
            
            if not armed_by_rec:
                print("[REC] Нет вооружённых каналов")
                return
            
            # Очищаем все armed set'ы (фикс phantom-каналов)
            self.recorder.armed.clear()
            for dr in getattr(self, '_driver_recorders', {}).values():
                dr.armed.clear()
            
            # Формат из MainWindow
            fmt_rate = self.recorder.fmt[1]
            fmt_width = self.recorder.fmt[2]
            if hasattr(mw, 'rec_format_combo'):
                fmt_idx = mw.rec_format_combo.currentIndex()
                self.recorder.format_idx = fmt_idx
                for dr in getattr(self, '_driver_recorders', {}).values():
                    dr.format_idx = fmt_idx
            if hasattr(mw, 'rec_base_dir') and mw.rec_base_dir:
                self.recorder._base_dir_override = mw.rec_base_dir
                for dr in getattr(self, '_driver_recorders', {}).values():
                    dr._base_dir_override = mw.rec_base_dir
            
            # Запускаем каждый рекордер
            for rec, channels in armed_by_rec.items():
                for idx in channels:
                    rec.arm(idx)
                names = {idx: info['name'] for idx, info in channels.items()}
                nchannels = {idx: info['nch'] for idx, info in channels.items()}
                ch_rates = {}
                default_rate = rec.fmt[1]
                for idx in channels:
                    thread = self._vm_to_thread.get(idx)
                    rate = default_rate
                    if thread is not None:
                        if hasattr(thread, 'ch_rate') and thread.ch_rate:
                            rate = thread.ch_rate
                        elif hasattr(thread, 'processor') and hasattr(thread.processor, 'sample_rate'):
                            rate = thread.processor.sample_rate
                    if rate == default_rate:
                        rate = self._asio_ch_rates.get(idx, default_rate) if hasattr(self, '_asio_ch_rates') else default_rate
                    ch_rates[idx] = rate
                # Для per-драйверных рекордеров пишем в поддиректорию с именем драйвера
                subdir = None
                if rec is not self.recorder:
                    # Находим имя драйвера для этого рекордера
                    for dname, dr in getattr(self, '_driver_recorders', {}).items():
                        if dr is rec:
                            safe_driver = ''.join(c if c.isalnum() or c in ' _-' else '_' for c in dname).strip()
                            subdir = safe_driver
                            break
                rec.start_recording(self.custom_title, names, nchannels, ch_rates, subdir=subdir)
            # UI сигнал и таймер
            # Если главный рекордер не был запущен — устанавливаем _start_time для timecode
            if not self.recorder.recording:
                self.recorder._start_time = time.time()
            self.on_recording_started()
            if self.recorder.recording:
                self.recorder.recording_started.emit()
        else:
            self.recorder.stop_recording()
            for dr in getattr(self, '_driver_recorders', {}).values():
                if dr.recording:
                    dr.stop_recording()
            if self._recording:
                self.on_recording_stopped()
                if not self.recorder.recording:
                    self.recorder.recording_stopped.emit()
    
    def on_recording_started(self):
        self._recording = True
        self.rec_btn.setText("■ Стоп")
        self.rec_btn.setStyleSheet("QPushButton { color: red; }")
        self.smpte_label.setVisible(True)
        self.smpte_timer.start(40)
    
    def on_recording_stopped(self):
        self._recording = False
        self.rec_btn.setText("● Запись")
        self.rec_btn.setStyleSheet("QPushButton { color: #888; } QPushButton:hover { color: red; }")
        self.smpte_label.setVisible(False)
        self.smpte_timer.stop()
    
    def update_smpte(self):
        self.smpte_label.setText(self.recorder.get_current_timecode())
    
    def start_measurement(self):
        """Начать измерение"""
        # Останавливаем предыдущие потоки
        self.stop_measurement()
        
        # Сбрасываем измеритель
        self.volume_meter.values = []
        self.volume_meter.history = []
        self.volume_meter.colors = []
        self.volume_meter.labels = []
        
        # Clear old state
        self._vm_to_ch_name.clear()
        self._vm_to_color.clear()
        self._vm_to_order.clear()
        self._vm_to_global.clear()
        self._vm_to_thread.clear()
        self._ch_vm_map = {}
        self._ch_stereo = {}
        self._asio_ch_rates.clear()
        self._asio_threads = []
        self._driver_recorders = {}  # driver_name → RecorderManager (per-ASIO-driver)
        self._vm_to_driver = {}     # local_vm_idx → driver_name (для ASIO каналов)
        # Stop all solo players
        for p in self._solo_players.values():
            p.stop()
        self._solo_players.clear()
        self._solo_active.clear()
        
        print(f"Запуск измерения для окна {self.custom_title} (калибровка: {self.calibration_offset} dB)")
        
        controller = getattr(self, '_asio_controller', None)
        non_asio_channels = []
        local_idx = [0]  # счётчик локальных индексов volume_meter для этого окна
        self._vm_to_global = {}  # local_vm_idx → global_idx
        
        for i, channel in enumerate(self.channels):
            self._ch_vm_map[id(channel)] = -1
            if not channel.is_enabled():
                continue
            device_type = self.audio_manager.get_device_type(channel.get_device_name())
            if device_type == 'ASIO' and HAS_ASIO and controller is not None:
                driver_name = self.audio_manager.get_asio_driver_name(channel.get_device_name())
                mode = channel.get_channel_mode()
                is_stereo = '+' in mode
                vm_idx = local_idx[0]
                # Создаём per-драйверный рекордер (первый слот драйвера создаёт, остальные используют)
                if driver_name not in self._driver_recorders:
                    dr = RecorderManager(emit_signals=False)
                    dr.format_idx = self.recorder.format_idx
                    dr._base_dir_override = self.recorder._base_dir_override
                    self._driver_recorders[driver_name] = dr
                driver_rec = self._driver_recorders[driver_name]
                self._vm_to_driver[vm_idx] = driver_name
                # Регистрируем слот в общем контроллере (получаем global_idx)
                global_idx = controller.add_slot(
                    driver_name, mode, self, vm_idx,
                    vm_idx, driver_rec,
                    self.calibration_offset,
                    channel.get_channel_name(),
                    channel.get_color()
                )
                self._ch_stereo[vm_idx] = is_stereo
                self._ch_vm_map[id(channel)] = vm_idx
                self._vm_to_ch_name[vm_idx] = channel.get_channel_name()
                self._vm_to_color[vm_idx] = QColor(channel.get_color())
                self._vm_to_order[vm_idx] = i
                self._vm_to_global[vm_idx] = global_idx
                bar_r = channel.vu_bar_r if is_stereo else None
                self.volume_meter.add_channel(channel.get_color(), channel.get_channel_name())
                self.volume_meter.set_vu_bar(vm_idx, channel.vu_bar, bar_r)
                channel.vu_bar_r.setVisible(is_stereo)
                local_idx[0] += 1
            else:
                non_asio_channels.append(i)
        
        # Таймер обработки очередей ASIO (для не-ASIO потоков)
        self._lufs_timer = QTimer(self)
        self._lufs_timer.timeout.connect(self._flush_asio_queues)
        self._lufs_timer.start(40)
        
        # Запускаем остальные (не-ASIO) потоки по одному на канал
        for i in non_asio_channels:
            channel = self.channels[i]
            device_name = channel.get_device_name()
            device_index = self.audio_manager.get_device_index_by_name(device_name)
            device_type = self.audio_manager.get_device_type(device_name)
            channel_mode = channel.get_channel_mode()
            
            ch_idx = local_idx[0]
            print(f"  Канал {i+1}: {device_name} (режим: {channel_mode})")
            self.volume_meter.add_channel(channel.get_color(), channel.get_channel_name())
            self._ch_vm_map[id(channel)] = ch_idx
            self._vm_to_ch_name[ch_idx] = channel.get_channel_name()
            self._vm_to_color[ch_idx] = QColor(channel.get_color())
            self._vm_to_order[ch_idx] = i
            self._ch_stereo[ch_idx] = '+' in channel_mode
            is_stereo = self._ch_stereo[ch_idx]
            bar_r = channel.vu_bar_r if is_stereo else None
            self.volume_meter.set_vu_bar(ch_idx, channel.vu_bar, bar_r)
            channel.vu_bar_r.setVisible(is_stereo)
            local_idx[0] += 1
            
            if device_type == 'SRT Stream':
                srt_info = None
                for s in self.audio_manager.srt_streams:
                    if f"[SRT] {s[5]}" == device_name:
                        srt_info = s
                        break
                if srt_info:
                    host, port, stream_id, passphrase, mode, name = srt_info
                    url = self.audio_manager.build_srt_url(host, port, stream_id, passphrase, mode)
                    print(f"    Запуск SRT процессора: {url}")
                    thread = SRTStreamProcessor(url, ch_idx, channel_mode, self.calibration_offset)
                    thread.data_ready.connect(self.volume_meter.buffer_data)
                    thread.rms_ready.connect(self.volume_meter.set_rms)
                    thread.recorder = self.recorder
                    thread.start()
                    self.audio_threads.append(thread)
                    self._vm_to_thread[ch_idx] = thread
                else:
                    print(f"    [ERR] Не найден URL для SRT потока: {device_name}")
            elif device_type == 'OMT Stream':
                host, port, name = None, None, None
                for omt_host, omt_port, omt_name in self.audio_manager.omt_streams:
                    if f"[OMT] {omt_name}" == device_name:
                        host, port, name = omt_host, omt_port, omt_name
                        break
                if host and port:
                    print(f"    Запуск OMT процессора: {name} -> {host}:{port}")
                    thread = OMTStreamProcessor(host, port, ch_idx, channel_mode, self.calibration_offset)
                    thread.data_ready.connect(self.volume_meter.buffer_data)
                    thread.rms_ready.connect(self.volume_meter.set_rms)
                    thread.recorder = self.recorder
                    thread.start()
                    self.audio_threads.append(thread)
                    self._vm_to_thread[ch_idx] = thread
                else:
                    print(f"    [ERR] Не найден адрес для OMT потока: {device_name}")
            elif device_index == -1:
                print(f"    Запуск виртуального устройства")
                thread = VirtualOutputDeviceThread(ch_idx, channel_mode, self.calibration_offset)
                thread.data_ready.connect(self.volume_meter.buffer_data)
                thread.rms_ready.connect(self.volume_meter.set_rms)
                thread.recorder = self.recorder
                thread.start()
                self.audio_threads.append(thread)
                self._vm_to_thread[ch_idx] = thread
            else:
                print(f"    Запуск аудиоустройства: {device_name}")
                thread = AudioStreamThread(device_index, ch_idx, channel_mode, device_type, self.calibration_offset)
                thread.data_ready.connect(self.volume_meter.buffer_data)
                thread.rms_ready.connect(self.volume_meter.set_rms)
                thread.recorder = self.recorder
                thread.start()
                self.audio_threads.append(thread)
                self._vm_to_thread[ch_idx] = thread
        
        # Enable record button
        self.rec_btn.setEnabled(True)
        
        # Set volume_meter draw order to match channel order
        if self._vm_to_order:
            order = sorted(range(len(self._vm_to_order)), key=lambda k: self._vm_to_order[k])
            self.volume_meter.set_sort_order(order)
        
        # Rebuild legend bar
        self._rebuild_legend()
        
        print(f"Измерение запущено для {local_idx[0]} каналов")
    
    def _rebuild_legend(self):
        """Перестроить легенду с кнопками соло."""
        # Clear existing legend items
        for item in self.legend_items:
            self.legend_layout.removeWidget(item['label'])
            item['label'].deleteLater()
            if item.get('solo_btn'):
                self.legend_layout.removeWidget(item['solo_btn'])
                item['solo_btn'].deleteLater()
        self.legend_items.clear()
        
        sorted_vm = sorted(self._vm_to_order.keys(), key=lambda k: self._vm_to_order[k])
        for vm_idx in sorted_vm:
            color = self._vm_to_color.get(vm_idx)
            name = self._vm_to_ch_name.get(vm_idx, f"Ch{vm_idx}")
            if color is None:
                color = QColor("#aaa")
            # Color swatch + label
            label = QLabel(f"■ {name}")
            label.setStyleSheet(f"color: {color.name()}; font-size: 11px;")
            self.legend_layout.addWidget(label)
            # Solo button (всегда показываем)
            solo_btn = QPushButton("S")
            solo_btn.setFixedSize(20, 18)
            solo_btn.setCheckable(True)
            solo_btn.setToolTip("Прослушать канал (соло)")
            solo_btn.setStyleSheet(
                "QPushButton { font-weight: bold; font-size: 9px; border: 1px solid #888; border-radius: 2px; } "
                "QPushButton:checked { color: #ff0; border: 2px solid #ff0; background: #442200; }"
            )
            solo_btn.clicked.connect(lambda checked, idx=vm_idx: self.toggle_solo(idx))
            self.legend_layout.addWidget(solo_btn)
            self.legend_items.append({'label': label, 'solo_btn': solo_btn, 'idx': vm_idx})
        
        self.legend_layout.addStretch()
        self.legend_widget.setVisible(len(self.legend_items) > 0)
    
    def toggle_solo(self, local_vm_idx):
        """Включить/выключить соло-мониторинг канала (ASIO или не-ASIO)."""
        global_idx = self._vm_to_global.get(local_vm_idx)
        controller = getattr(self, '_asio_controller', None)
        thread = None
        if global_idx is not None and controller is not None:
            thread = controller.get_thread_for_global(global_idx)
        if thread is None:
            thread = self._vm_to_thread.get(local_vm_idx)
        if thread is None:
            return
        
        if self._solo_active.get(local_vm_idx, False):
            # Выключаем соло
            if global_idx is not None and hasattr(thread, 'clear_solo_queue'):
                thread.clear_solo_queue(global_idx)
            else:
                thread.solo_queue = None
            if local_vm_idx in self._solo_players:
                self._solo_players[local_vm_idx].stop()
                del self._solo_players[local_vm_idx]
            self._solo_active[local_vm_idx] = False
            print(f"[SOLO] Ch{local_vm_idx} off")
        else:
            # Включаем соло
            rate = self._asio_ch_rates.get(local_vm_idx)
            if rate is None or rate <= 0:
                thread = self._vm_to_thread.get(local_vm_idx)
                if thread is not None:
                    if hasattr(thread, 'ch_rate') and thread.ch_rate:
                        rate = thread.ch_rate
                    elif hasattr(thread, 'processor') and hasattr(thread.processor, 'sample_rate'):
                        rate = thread.processor.sample_rate
                    elif hasattr(thread, 'sample_rate'):
                        rate = thread.sample_rate
                    else:
                        rate = 48000
                else:
                    rate = 48000
            if rate <= 0 or rate is None:
                rate = 48000
            nch = 2 if self._ch_stereo.get(local_vm_idx, False) else 1
            fpb = getattr(thread, '_fpb', 256)
            solo_buf = max(fpb * 32, 8192)
            try:
                player = SoloPlayer(rate, channels=nch, frames_per_buffer=solo_buf)
            except Exception as e:
                print(f"[SOLO] Ch{local_vm_idx}: failed to create player: {e}")
                return
            if global_idx is not None and hasattr(thread, 'set_solo_queue'):
                thread.set_solo_queue(global_idx, player.queue)
            else:
                thread.solo_queue = player.queue
            self._solo_players[local_vm_idx] = player
            self._solo_active[local_vm_idx] = True
            print(f"[SOLO] Ch{local_vm_idx} on ({nch}ch @ {rate}Hz buf={solo_buf})")
    
    def _flush_asio_queues(self):
        """Обработка очередей ASIO для LUFS и VU (по таймеру, ~40 мс).
        При shared ASIO контроллере здесь обрабатываются только не-ASIO потоки (их нет)."""
        for t in getattr(self, '_asio_threads', []):
            t.process_queue()
    
    def stop_measurement(self):
        """Остановить измерение"""
        # Stop the LUFS processing timer
        if hasattr(self, '_lufs_timer') and self._lufs_timer:
            self._lufs_timer.stop()
            self._lufs_timer = None
        # Stop audio threads first — no more feed_audio calls
        for thread in self.audio_threads:
            thread.stop()
        self.audio_threads.clear()
        self._asio_threads = []
        # Stop solo players
        for p in self._solo_players.values():
            p.stop()
        self._solo_players.clear()
        self._solo_active.clear()
        # Then stop recorder (queue is now quiescent)
        if self._recording:
            self.recorder.stop_recording()
        for dr in getattr(self, '_driver_recorders', {}).values():
            if dr.recording:
                dr.stop_recording()
        self._driver_recorders.clear()
        self._vm_to_driver.clear()
        self.rec_btn.setEnabled(False)
    
    def refresh_devices(self):
        """Обновить список устройств во всех каналах"""
        for channel in self.channels:
            channel.refresh_devices()
    
    def apply_theme(self):
        """Применить тему ко всем элементам"""
        for channel in self.channels:
            channel.apply_theme()
    
    def set_target(self, target_lufs):
        """Установить целевой уровень LUFS"""
        self.volume_meter.set_target(target_lufs)
    
    def set_display_time(self, display_time):
        """Установить время отображения"""
        self.volume_meter.set_display_time(display_time)
        
    def set_fill_enabled(self, enabled):
        """Включить/выключить заливку под графиками"""
        self.volume_meter.set_fill_enabled(enabled)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.audio_manager = AudioDeviceManager()
        self.meter_windows = []
        self.is_dark_mode = False
        self.measuring = False
        self._asio_controller = None
        self.fill_enabled = False  # Флаг заливки под графиками
        self.calibration_offset = 0.0  # Смещение калибровки по умолчанию
        self._recording_all = False  # Флаг "Запись на всех окнах"
        self.rec_base_dir = None
         
        self.setup_ui()
        self.load_settings(silent=True)
        
    def setup_ui(self):
        self.setWindowTitle("Анализатор громкости R128 EBU v11")
        self.setGeometry(100, 100, 1200, 800)
        
        # Центральный виджет и основной layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # Создаем меню
        self.create_menu()
        
        # Панель управления с кнопкой сворачивания
        self.control_panel = QGroupBox("Настройки")
        self.control_panel.setCheckable(True)
        self.control_panel.setChecked(True)
        self.control_panel.toggled.connect(self.toggle_control_panel)
        
        control_layout = QGridLayout(self.control_panel)
        
        # Первая строка настроек
        control_layout.addWidget(QLabel("Целевой уровень LUFS:"), 0, 0)
        self.target_spin = QDoubleSpinBox()
        self.target_spin.setRange(-50, 0)
        self.target_spin.setValue(-10.0)
        self.target_spin.setSingleStep(0.5)
        self.target_spin.valueChanged.connect(self.update_all_targets)
        control_layout.addWidget(self.target_spin, 0, 1)
        
        control_layout.addWidget(QLabel("Время отображения (сек):"), 0, 2)
        self.display_time_spin = QSpinBox()
        self.display_time_spin.setRange(1, 3600)
        self.display_time_spin.setSingleStep(5)
        self.display_time_spin.setValue(10)
        self.display_time_spin.valueChanged.connect(self.update_display_time)
        control_layout.addWidget(self.display_time_spin, 0, 3)
        
        # Вторая строка настроек
        control_layout.addWidget(QLabel("Количество окон:"), 1, 0)
        self.window_count_spin = QSpinBox()
        self.window_count_spin.setRange(1, 24)
        self.window_count_spin.setValue(1)
        self.window_count_spin.valueChanged.connect(self.update_window_count)
        control_layout.addWidget(self.window_count_spin, 1, 1)
        
        control_layout.addWidget(QLabel("Калибровка LUFS (dB):"), 1, 2)
        self.calibration_spin = QDoubleSpinBox()
        self.calibration_spin.setRange(-10.0, 10.0)
        self.calibration_spin.setValue(0.0)
        self.calibration_spin.setSingleStep(0.1)
        self.calibration_spin.setDecimals(1)
        self.calibration_spin.valueChanged.connect(self.update_calibration_offset)
        control_layout.addWidget(self.calibration_spin, 1, 3)
        
        # Третья строка настроек — диапазон графика
        control_layout.addWidget(QLabel("Нижний уровень (dBFS):"), 2, 0)
        self.level_bottom_spin = QDoubleSpinBox()
        self.level_bottom_spin.setRange(-120, 0)
        self.level_bottom_spin.setValue(-70.0)
        self.level_bottom_spin.setSingleStep(5)
        self.level_bottom_spin.valueChanged.connect(self.update_level_range)
        control_layout.addWidget(self.level_bottom_spin, 2, 1)
        
        control_layout.addWidget(QLabel("Верхний уровень (dBFS):"), 2, 2)
        self.level_top_spin = QDoubleSpinBox()
        self.level_top_spin.setRange(-120, 20)
        self.level_top_spin.setValue(0.0)
        self.level_top_spin.setSingleStep(5)
        self.level_top_spin.valueChanged.connect(self.update_level_range)
        control_layout.addWidget(self.level_top_spin, 2, 3)
        
        # Четвёртая строка — рабочий диапазон
        self.wr_checkbox = QCheckBox("Рабочий диапазон")
        self.wr_checkbox.setChecked(False)
        self.wr_checkbox.stateChanged.connect(self.update_working_range)
        control_layout.addWidget(self.wr_checkbox, 3, 0)
        
        control_layout.addWidget(QLabel("Ширина (dB):"), 3, 1)
        self.wr_width_spin = QDoubleSpinBox()
        self.wr_width_spin.setRange(0, 60)
        self.wr_width_spin.setValue(6.0)
        self.wr_width_spin.setSingleStep(1)
        self.wr_width_spin.valueChanged.connect(self.update_working_range)
        control_layout.addWidget(self.wr_width_spin, 3, 2)
        
        self.wr_fill_checkbox = QCheckBox("Заливка диапазона")
        self.wr_fill_checkbox.setChecked(True)
        self.wr_fill_checkbox.stateChanged.connect(self.update_working_range)
        control_layout.addWidget(self.wr_fill_checkbox, 3, 3)
        
        # Пятая строка
        self.fill_checkbox = QCheckBox("Заливка под графиками")
        self.fill_checkbox.setChecked(self.fill_enabled)
        self.fill_checkbox.stateChanged.connect(self.toggle_fill)
        control_layout.addWidget(self.fill_checkbox, 4, 0)
        
        self.start_btn = QPushButton("Старт")
        self.start_btn.clicked.connect(self.toggle_measurement)
        control_layout.addWidget(self.start_btn, 4, 1)
        
        self.rec_all_btn = QPushButton("Записать всё")
        self.rec_all_btn.setToolTip("Запустить запись на всех каналах всех окон")
        self.rec_all_btn.clicked.connect(self.record_all)
        control_layout.addWidget(self.rec_all_btn, 4, 2, 1, 2)
        
        # Шестая строка — настройки записи
        control_layout.addWidget(QLabel("Формат записи:"), 5, 0)
        self.rec_format_combo = QComboBox()
        for fmt_name, _, _, _ in REC_FORMATS:
            self.rec_format_combo.addItem(fmt_name)
        self.rec_format_combo.setCurrentIndex(1)  # WAV 44.1/24
        control_layout.addWidget(self.rec_format_combo, 5, 1)
        self.rec_folder_btn = QPushButton("Папка...")
        self.rec_folder_btn.setToolTip("Выбрать папку для записей (по умолчанию: recordings/)")
        self.rec_folder_btn.clicked.connect(self.select_recording_folder)
        control_layout.addWidget(self.rec_folder_btn, 5, 2)
        self.rec_folder_label = QLabel("recording/")
        self.rec_folder_label.setStyleSheet("color: #888; font-size: 10px;")
        control_layout.addWidget(self.rec_folder_label, 5, 3)
        
        asio_count = len(self.audio_manager.asio_drivers) if IS_WINDOWS else 0
        extra = f"ASIO:{asio_count}" if IS_WINDOWS else "SoundDevice"
        info_text = f"Доступно устройств: {len(self.audio_manager.get_all_devices())} (Input/Output/SRT/Virtual/{extra})"
        info_label = QLabel(info_text)
        info_label.setStyleSheet("color: #888; font-size: 10px;")
        control_layout.addWidget(info_label, 6, 0, 1, 4)
        
        main_layout.addWidget(self.control_panel)
        
        # Область с окнами измерителей в виде сетки
        self.graphs_container = QWidget()
        self.graphs_layout = QGridLayout(self.graphs_container)
        self.graphs_layout.setSpacing(5)
        
        self.meter_windows = []
        
        # Добавляем контейнер в скролл область
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.graphs_container)
        
        main_layout.addWidget(self.scroll_area)
        
        # Добавляем первое окно по умолчанию
        self.add_meter_window()
        
        # Применяем начальную тему
        self.apply_theme()
        
    def create_menu(self):
        """Создаем меню приложения"""
        menubar = self.menuBar()
        
        # Меню "Файл"
        file_menu = menubar.addMenu('Файл')
        
        add_srt_action = QAction('Добавить SRT поток...', self)
        add_srt_action.triggered.connect(self.add_srt_stream)
        file_menu.addAction(add_srt_action)
        
        add_omt_action = QAction('Добавить OMT поток...', self)
        add_omt_action.triggered.connect(self.add_omt_stream)
        file_menu.addAction(add_omt_action)
        
        refresh_action = QAction('Обновить устройства', self)
        refresh_action.triggered.connect(self.refresh_all_devices)
        file_menu.addAction(refresh_action)
        
        file_menu.addSeparator()
        
        save_action = QAction('Сохранить настройки...', self)
        save_action.triggered.connect(self.on_save_preset)
        file_menu.addAction(save_action)
        
        load_action = QAction('Загрузить настройки...', self)
        load_action.triggered.connect(self.on_load_preset)
        file_menu.addAction(load_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction('Выход', self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Меню "Вид"
        view_menu = menubar.addMenu('Вид')
        
        self.toggle_theme_action = QAction('Тёмный режим', self)
        self.toggle_theme_action.setCheckable(True)
        self.toggle_theme_action.setChecked(False)
        self.toggle_theme_action.triggered.connect(self.toggle_theme)
        view_menu.addAction(self.toggle_theme_action)
        
    def toggle_theme(self):
        """Переключение между светлой и тёмной темой"""
        self.is_dark_mode = not self.is_dark_mode
        self.toggle_theme_action.setChecked(self.is_dark_mode)
        self.apply_theme()
        
    def toggle_fill(self, state):
        """Переключение заливки под графиками"""
        self.fill_enabled = state == Qt.Checked
        for window in self.meter_windows:
            window.set_fill_enabled(self.fill_enabled)
            
    def update_calibration_offset(self):
        """Обновить смещение калибровки для всех окон"""
        self.calibration_offset = self.calibration_spin.value()
        for window in self.meter_windows:
            window.set_calibration_offset(self.calibration_offset)
        
        # Перезапускаем измерения если они активны
        if self.measuring:
            self.stop_all_measurements()
            self.start_all_measurements()
        
    def _apply_dark_titlebar(self, dark):
        if not IS_WINDOWS:
            return
        try:
            hwnd = int(self.winId())
            DWMWA_USE_IMMERSIVE_DARK_MODE = 20
            value = c_int(1 if dark else 0)
            windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, byref(value), ctypes.sizeof(value))
        except:
            try:
                DWMWA_USE_IMMERSIVE_DARK_MODE_OLD = 19
                value = c_int(1 if dark else 0)
                windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE_OLD, byref(value), ctypes.sizeof(value))
            except:
                pass
    
    def apply_theme(self):
        self._apply_dark_titlebar(self.is_dark_mode)
        if self.is_dark_mode:
            dark_bg = "#2b2b2b"
            dark_widget = "#333333"
            dark_surface = "#404040"
            dark_border = "#555555"
            text_color = "white"
            
            self.setStyleSheet(f"""
                QMainWindow {{
                    background-color: {dark_bg};
                    color: {text_color};
                }}
                QMainWindow > QWidget {{
                    background-color: {dark_bg};
                    color: {text_color};
                }}
                QWidget {{
                    background-color: {dark_bg};
                    color: {text_color};
                }}
                QGroupBox {{
                    background-color: {dark_surface};
                    color: {text_color};
                    border: 1px solid {dark_border};
                    border-radius: 5px;
                    margin-top: 1ex;
                    padding-top: 10px;
                }}
                QGroupBox::title {{
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 5px 0 5px;
                }}
                QPushButton {{
                    background-color: {dark_surface};
                    color: {text_color};
                    border: 1px solid {dark_border};
                    padding: 5px;
                    border-radius: 3px;
                }}
                QPushButton:hover {{
                    background-color: #505050;
                }}
                QPushButton:pressed {{
                    background-color: #606060;
                }}
                QLabel {{
                    color: {text_color};
                    background-color: transparent;
                }}
                QDoubleSpinBox, QSpinBox {{
                    background-color: {dark_widget};
                    color: {text_color};
                    border: 1px solid {dark_border};
                    padding: 2px;
                }}
                QLineEdit {{
                    background-color: {dark_widget};
                    color: {text_color};
                    border: 1px solid {dark_border};
                    padding: 2px;
                }}
                QScrollArea {{
                    background-color: {dark_bg};
                    border: none;
                }}
                QScrollArea > QWidget > QWidget {{
                    background-color: {dark_bg};
                }}
                QScrollBar:vertical {{
                    background: {dark_widget};
                    width: 12px;
                    border: none;
                }}
                QScrollBar::handle:vertical {{
                    background: {dark_border};
                    min-height: 20px;
                    border-radius: 3px;
                }}
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                    height: 0px;
                }}
                QCheckBox {{
                    color: {text_color};
                }}
                QCheckBox::indicator {{
                    width: 13px;
                    height: 13px;
                }}
                QCheckBox::indicator:unchecked {{
                    border: 1px solid {dark_border};
                    background-color: {dark_widget};
                }}
                QCheckBox::indicator:checked {{
                    border: 1px solid {dark_border};
                    background-color: #0078d7;
                }}
                QComboBox {{
                    background-color: {dark_widget};
                    color: {text_color};
                    border: 1px solid {dark_border};
                    padding: 2px;
                }}
                QComboBox::drop-down {{
                    border: 0px;
                }}
                QComboBox::down-arrow {{
                    image: none;
                    border: 0px;
                }}
                QMenuBar {{
                    background-color: {dark_surface};
                    color: {text_color};
                }}
                QMenuBar::item {{
                    background-color: transparent;
                    padding: 4px 10px;
                }}
                QMenuBar::item:selected {{
                    background-color: #505050;
                }}
                QMenu {{
                    background-color: {dark_surface};
                    color: {text_color};
                    border: 1px solid {dark_border};
                }}
                QMenu::item {{
                    padding: 5px 20px;
                }}
                QMenu::item:selected {{
                    background-color: #505050;
                }}
                QSplitter::handle {{
                    background-color: {dark_border};
                }}
            """)
            
            app = QApplication.instance()
            if app:
                app.setStyleSheet("QToolTip { background-color: #333; color: white; border: 1px solid #555; }")
            
            central_widget = self.centralWidget()
            if central_widget:
                central_widget.setAttribute(Qt.WA_StyledBackground, True)
        else:
            self.setStyleSheet("")
            
        for window in self.meter_windows:
            window.apply_theme()
            for channel in window.channels:
                channel.apply_theme()
                
        self.update()
        
    def toggle_control_panel(self, visible):
        """Сворачивание/разворачивание панели управления"""
        if visible:
            self.control_panel.setTitle("Настройки")
            self.control_panel.setMaximumHeight(16777215)
        else:
            self.control_panel.setTitle("Настройки (развернуть)")
            self.control_panel.setMaximumHeight(30)
        
    def add_meter_window(self):
        new_window = MeterWindow(len(self.meter_windows), self.audio_manager, self.calibration_offset)
        self.meter_windows.append(new_window)
        self.update_graphs_layout()
        
    def update_graphs_layout(self):
        """Обновляем layout графиков в зависимости от количества"""
        # Очищаем текущий layout
        for i in reversed(range(self.graphs_layout.count())): 
            self.graphs_layout.itemAt(i).widget().setParent(None)
        
        # Определяем оптимальное количество колонок
        num_windows = len(self.meter_windows)
        if num_windows == 0:
            return
            
        # Вычисляем оптимальное количество колонок (максимум 6)
        cols = min(6, int(np.ceil(np.sqrt(num_windows))))
        rows = int(np.ceil(num_windows / cols))
        
        # Добавляем окна в сетку
        for i, window in enumerate(self.meter_windows):
            row = i // cols
            col = i % cols
            self.graphs_layout.addWidget(window, row, col)
        
    def update_window_count(self):
        count = self.window_count_spin.value()
        while len(self.meter_windows) < count:
            self.add_meter_window()
        while len(self.meter_windows) > count:
            window_to_remove = self.meter_windows.pop()
            window_to_remove.setParent(None)
            window_to_remove.deleteLater()
        
        self.update_graphs_layout()
        # Применяем все текущие настройки к новым окнам (и заодно ко всем)
        if hasattr(self, 'target_spin'):
            self.update_all_targets()
            self.update_display_time()
            self.update_level_range()
            self.update_working_range()
            for window in self.meter_windows:
                window.set_fill_enabled(self.fill_checkbox.isChecked())
                window.apply_theme()
            
    def update_all_targets(self):
        target = self.target_spin.value()
        for window in self.meter_windows:
            window.set_target(target)
            
    def update_display_time(self):
        display_time = self.display_time_spin.value()
        for window in self.meter_windows:
            window.set_display_time(display_time)
    
    def update_level_range(self):
        bot = self.level_bottom_spin.value()
        top = self.level_top_spin.value()
        if bot >= top:
            top = bot + 10
            self.level_top_spin.setValue(top)
        for window in self.meter_windows:
            window.volume_meter.set_level_range(bot, top)
    
    def update_working_range(self):
        enabled = self.wr_checkbox.isChecked()
        width = self.wr_width_spin.value()
        fill = self.wr_fill_checkbox.isChecked()
        for window in self.meter_windows:
            window.volume_meter.set_working_range(enabled, width, fill)
            
    def toggle_measurement(self):
        if self.measuring:
            self.stop_all_measurements()
            self.start_btn.setText("Старт")
        else:
            self.start_all_measurements()
            self.start_btn.setText("Стоп")
            
        self.measuring = not self.measuring
        
    def start_all_measurements(self):
        if self.measuring:
            return
        if IS_WINDOWS and self.audio_manager.asio_drivers:
            controller = SharedASIOController(self)
            self._asio_controller = controller
            for window in self.meter_windows:
                window._asio_controller = controller
                window.stop_measurement()
        for window in self.meter_windows:
            window.start_measurement()
        if IS_WINDOWS and self.audio_manager.asio_drivers:
            self._asio_controller.start(self.audio_manager)
            ch_rates = self._asio_controller.get_ch_rates()
            for window in self.meter_windows:
                window._asio_ch_rates.update(ch_rates)
            
    def stop_all_measurements(self):
        for window in self.meter_windows:
            window.stop_measurement()
        if IS_WINDOWS and hasattr(self, '_asio_controller') and self._asio_controller is not None:
            self._asio_controller.stop()
            self._asio_controller = None
    
    def record_all(self):
        """Запустить/остановить запись на всех каналах всех окон"""
        if not self._recording_all:
            # Запускаем запись на всех окнах
            for window in self.meter_windows:
                for ch in window.channels:
                    if ch.is_enabled():
                        ch.arm_btn.setChecked(True)
                if not window._recording:
                    window.toggle_recording()
            self._recording_all = True
            self.rec_all_btn.setText("Остановить запись")
            print("[REC] Запись запущена на всех окнах")
        else:
            # Останавливаем запись на всех окнах
            for window in self.meter_windows:
                if window._recording:
                    window.toggle_recording()
            self._recording_all = False
            self.rec_all_btn.setText("Записать всё")
            print("[REC] Запись остановлена на всех окнах")
    
    def select_recording_folder(self):
        dlg = QFileDialog.getExistingDirectory(self, "Выбрать папку для записей",
                                                 self.rec_base_dir or "recordings")
        if dlg:
            self.rec_base_dir = dlg
            self.rec_folder_label.setText(os.path.basename(dlg) + "/")
            
    def add_srt_stream(self):
        """Добавить SRT поток"""
        dialog = SRTStreamDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            host, port, stream_id, passphrase, mode, name = dialog.get_srt_data()
            if host:
                self.audio_manager.add_srt_stream(host, port, stream_id, passphrase, mode, name)
                self.refresh_all_devices()
                QMessageBox.information(self, "Успех", f"SRT поток '{name}' добавлен!")

    def add_omt_stream(self):
        """Добавить OMT поток (сканирование + ручной ввод в одном окне)"""
        dialog = OMTStreamDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            host, port, name = dialog.get_omt_data()
            if host:
                self.audio_manager.add_omt_stream(host, port, name)
                self.refresh_all_devices()
                QMessageBox.information(self, "Успех", f"OMT поток '{name}' добавлен!")

    def refresh_all_devices(self):
        """Обновить все устройства"""
        for window in self.meter_windows:
            window.refresh_devices()
    
    def _default_settings_dir(self):
        if getattr(sys, 'frozen', False):
            base = os.path.join(os.path.dirname(sys.executable), 'settings')
        elif os.name == 'nt':
            appdata = os.environ.get('APPDATA')
            if appdata:
                base = os.path.join(appdata, 'R128Analyzer')
            else:
                base = os.path.dirname(os.path.abspath(__file__))
        else:
            base = os.path.join(os.path.expanduser('~'), '.config', 'lufsmeter')
        os.makedirs(base, exist_ok=True)
        return base
    
    def _default_preset_path(self):
        return os.path.join(self._default_settings_dir(), 'default_preset.json')
    
    def _build_settings_dict(self):
        settings = {
            "is_dark_mode": self.is_dark_mode,
            "target_lufs": self.target_spin.value(),
            "display_time": self.display_time_spin.value(),
            "window_count": self.window_count_spin.value(),
            "calibration_offset": self.calibration_spin.value(),
            "fill_enabled": self.fill_enabled,
            "level_bottom": self.level_bottom_spin.value(),
            "level_top": self.level_top_spin.value(),
            "wr_enabled": self.wr_checkbox.isChecked(),
            "wr_width": self.wr_width_spin.value(),
            "wr_fill": self.wr_fill_checkbox.isChecked(),
            "control_panel_visible": self.control_panel.isChecked(),
            "srt_streams": [
                {"host": host, "port": port, "stream_id": stream_id,
                 "passphrase": passphrase, "mode": mode, "name": name}
                for host, port, stream_id, passphrase, mode, name in self.audio_manager.srt_streams
            ],
            "omt_streams": [
                {"host": host, "port": port, "name": name}
                for host, port, name in self.audio_manager.omt_streams
            ],
            "windows": []
        }
        for win in self.meter_windows:
            win_data = {"title": win.title_edit.text(), "channels": []}
            for ch in win.channels:
                ch_data = {
                    "enabled": ch.enabled_checkbox.isChecked(),
                    "device_name": ch.device_combo.currentText(),
                    "channel_mode_index": ch.channel_mode_combo.currentIndex(),
                    "color_index": ch.color_combo.currentIndex(),
                    "name": ch.name_edit.text()
                }
                win_data["channels"].append(ch_data)
            settings["windows"].append(win_data)
        return settings
    
    def save_settings(self, path=None, silent=False):
        if path is None:
            path = self._default_preset_path()
        settings = self._build_settings_dict()
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)
            if not silent:
                QMessageBox.information(self, "Настройки", f"Пресет сохранён:\n{path}")
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось сохранить настройки:\n{e}")
    
    def load_settings(self, path=None, silent=False):
        if path is None:
            path = self._default_preset_path()
        if not os.path.exists(path):
            if not silent:
                QMessageBox.information(self, "Настройки", "Файл пресета не найден")
            return
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                settings = json.load(f)
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось загрузить настройки:\n{e}")
            return
        
        if self.measuring:
            self.toggle_measurement()
        
        self.audio_manager.srt_streams.clear()
        for s in settings.get("srt_streams", []):
            url = s.get("url", "")
            if url:
                parsed = urlparse(url)
                host = parsed.hostname or ""
                port = parsed.port or 5000
                qs = parse_qs(parsed.query)
                mode = (qs.get('mode') or ['caller'])[0]
                stream_id = (qs.get('streamid') or [''])[0]
                passphrase = (qs.get('passphrase') or [''])[0]
                name = s.get("name", host)
            else:
                host = s.get("host", "")
                port = s.get("port", 5000)
                stream_id = s.get("stream_id", "")
                passphrase = s.get("passphrase", "")
                mode = s.get("mode", "caller")
                name = s.get("name", host)
            if host:
                self.audio_manager.add_srt_stream(host, port, stream_id, passphrase, mode, name)
        
        self.audio_manager.omt_streams.clear()
        for o in settings.get("omt_streams", []):
            host = o.get("host") or o.get("url", "")
            port = o.get("port", 6400)
            name = o.get("name", host)
            if host:
                self.audio_manager.add_omt_stream(host, port, name)
        
        self.window_count_spin.setValue(settings.get("window_count", 1))
        
        # Обновляем списки устройств во всех окнах (чтобы SRT потоки появились в комбобоксах)
        self.refresh_all_devices()
        
        for i, win_data in enumerate(settings.get("windows", [])):
            if i >= len(self.meter_windows):
                break
            win = self.meter_windows[i]
            win.title_edit.setText(win_data.get("title", f"Окно {i+1}"))
            
            saved_channels = win_data.get("channels", [])
            while len(win.channels) < len(saved_channels):
                win.add_channel()
            
            for j, ch_data in enumerate(saved_channels):
                if j >= len(win.channels):
                    break
                ch = win.channels[j]
                ch.name_edit.setText(ch_data.get("name", f"Канал {j+1}"))
                ch.enabled_checkbox.setChecked(ch_data.get("enabled", True))
                
                device_name = ch_data.get("device_name", "")
                idx = ch.device_combo.findText(device_name)
                if idx >= 0:
                    ch.device_combo.setCurrentIndex(idx)
                
                mode_idx = ch_data.get("channel_mode_index", 0)
                if 0 <= mode_idx < ch.channel_mode_combo.count():
                    ch.channel_mode_combo.setCurrentIndex(mode_idx)
                
                color_idx = ch_data.get("color_index", j % 7)
                if 0 <= color_idx < ch.color_combo.count():
                    ch.color_combo.setCurrentIndex(color_idx)
        
        if settings.get("is_dark_mode", False) != self.is_dark_mode:
            self.toggle_theme()
        
        self.target_spin.setValue(settings.get("target_lufs", -10.0))
        self.display_time_spin.setValue(settings.get("display_time", 10))
        self.calibration_spin.setValue(settings.get("calibration_offset", 0.0))
        self.fill_enabled = settings.get("fill_enabled", False)
        self.fill_checkbox.setChecked(self.fill_enabled)
        
        self.level_bottom_spin.setValue(settings.get("level_bottom", -70.0))
        self.level_top_spin.setValue(settings.get("level_top", 0.0))
        self.wr_checkbox.setChecked(settings.get("wr_enabled", False))
        self.wr_width_spin.setValue(settings.get("wr_width", 6.0))
        self.wr_fill_checkbox.setChecked(settings.get("wr_fill", True))
        
        cp_visible = settings.get("control_panel_visible", True)
        self.control_panel.setChecked(cp_visible)
        
        if not silent:
            QMessageBox.information(self, "Настройки", "Пресет загружен")
    
    def on_save_preset(self):
        default_dir = self._default_settings_dir()
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить пресет",
            os.path.join(default_dir, "preset.json"),
            "JSON файлы (*.json);;Все файлы (*.*)")
        if path:
            self.save_settings(path=path, silent=False)
    
    def on_load_preset(self):
        default_dir = self._default_settings_dir()
        path, _ = QFileDialog.getOpenFileName(
            self, "Загрузить пресет", default_dir,
            "JSON файлы (*.json);;Все файлы (*.*)")
        if path:
            self.load_settings(path=path, silent=False)
    
    def closeEvent(self, event):
        self.save_settings(silent=True)
        self.stop_all_measurements()
        event.accept()

def _set_high_priority():
    if not IS_WINDOWS:
        return
    try:
        kernel32 = ctypes.windll.kernel32
        GetCurrentProcess = kernel32.GetCurrentProcess
        GetCurrentProcess.restype = ctypes.c_void_p
        SetPriorityClass = kernel32.SetPriorityClass
        SetPriorityClass.restype = ctypes.c_bool
        SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        ok = SetPriorityClass(GetCurrentProcess(), 0x80)
        if ok:
            print("[PRIO] Process priority set to HIGH")
    except:
        pass

if __name__ == "__main__":
    _set_high_priority()
    app = QApplication(sys.argv)

    if IS_MACOS:
        print("Запуск на macOS. Для захвата системного аудио установите BlackHole:")
        print("  brew install blackhole-2ch")
        print("  Затем выберите BlackHole как устройство ввода в Audio MIDI Setup")

    first_run_setup()

    window = MainWindow()
    window.show()

    sys.exit(app.exec_())