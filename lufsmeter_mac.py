import sys
import platform
import numpy as np
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QGroupBox, QCheckBox, QComboBox, QDoubleSpinBox, QLabel, QPushButton,
                             QScrollArea, QGridLayout, QSpinBox, QSizePolicy, QSplitter,
                             QMessageBox, QAction, QMenu, QMenuBar, QDialog, QLineEdit, QDialogButtonBox)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QPointF
from PyQt5.QtGui import QPainter, QColor, QPen, QFont, QFontMetrics, QPolygonF
import pyaudio
from scipy import signal
from collections import deque
import time
import subprocess
import threading
import queue
import os

IS_WINDOWS = sys.platform == 'win32'
IS_MACOS = sys.platform == 'darwin'

# Константы для аудио
FORMAT = pyaudio.paInt16
RATE = 44100
CHUNK = 1024

# Константы для R128 EBU
PRE_FILTER_A = [1.0, -1.69065929318241, 0.73248077421585]
PRE_FILTER_B = [1.53512485958697, -2.69169618940638, 1.19839281085285]

RLB_FILTER_A = [1.0, -1.99004745483398, 0.99007225036621]
RLB_FILTER_B = [1.0, -2.0, 1.0]


def create_process_no_window():
    """Создает startupinfo для скрытия окна процесса (Windows) или None (macOS/Linux)"""
    if IS_WINDOWS:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0  # SW_HIDE
        return startupinfo
    return None


class SRTStreamDialog(QDialog):
    """Диалог для добавления SRT потока"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Добавить SRT поток")
        self.setModal(True)
        self.setup_ui()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        layout.addWidget(QLabel("URL SRT потока:"))
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("srt://адрес:порт?параметры")
        self.url_edit.setText("srt://127.0.0.1:10000?mode=caller")
        layout.addWidget(self.url_edit)
        
        layout.addWidget(QLabel("Отображаемое имя:"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Мой SRT поток")
        self.name_edit.setText("SRT поток")
        layout.addWidget(self.name_edit)
        
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
        
    def get_srt_data(self):
        url = self.url_edit.text().strip()
        name = self.name_edit.text().strip()
        if not name:
            name = url
        return url, name


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
        
    def set_calibration_offset(self, offset):
        self.calibration_offset = offset
        
    def reset(self):
        self.momentary_buffer.clear()
        self.short_term_buffer.clear()
        self.integrated_started = False
        self.integrated_values = []
        self.pre_filter_state = signal.lfilter_zi(self.pre_filter_b, self.pre_filter_a)
        self.rlb_filter_state = signal.lfilter_zi(self.rlb_filter_b, self.rlb_filter_a)
        
    def process_audio(self, audio_data):
        audio_float = audio_data.astype(np.float32) / 32768.0
        
        filtered_audio, self.pre_filter_state = signal.lfilter(
            self.pre_filter_b, self.pre_filter_a, audio_float, zi=self.pre_filter_state
        )
        
        weighted_audio, self.rlb_filter_state = signal.lfilter(
            self.rlb_filter_b, self.rlb_filter_a, filtered_audio, zi=self.rlb_filter_state
        )
        
        squared_audio = weighted_audio ** 2
        
        for sample in squared_audio:
            self.momentary_buffer.append(sample)
            self.short_term_buffer.append(sample)
            self.integrated_values.append(sample)
            
        momentary_lufs = self._calculate_lufs(self.momentary_buffer)
        short_term_lufs = self._calculate_lufs(self.short_term_buffer)
        integrated_lufs = self._calculate_lufs(self.integrated_values) if self.integrated_started else momentary_lufs
        
        if len(self.integrated_values) >= self.momentary_samples and not self.integrated_started:
            self.integrated_started = True
            
        return momentary_lufs, short_term_lufs, integrated_lufs
    
    def _calculate_lufs(self, buffer):
        if not buffer:
            return -70.0
            
        mean_square = np.mean(list(buffer))
        if mean_square <= 0:
            return -70.0
            
        db = 10 * np.log10(mean_square)
        lufs = db - 0.691 + self.calibration_offset
        
        return max(-70.0, min(0.0, lufs))


class SRTStreamProcessor(QThread):
    """Поток для обработки SRT потока и извлечения аудио"""
    data_ready = pyqtSignal(int, float, float, float)
    
    def __init__(self, srt_url, channel_idx, channel_mode, calibration_offset=0.0, parent=None):
        super().__init__(parent)
        self.srt_url = srt_url
        self.channel_idx = channel_idx
        self.channel_mode = channel_mode
        self.calibration_offset = calibration_offset
        self.running = False
        self.processor = R128EBUProcessor(calibration_offset=calibration_offset)
        self.ffmpeg_process = None
        
    def run(self):
        self.running = True
        
        try:
            print(f"Подключаемся к SRT потоку: {self.srt_url}")
            
            if self.channel_mode == '1+2':
                channels = 2
            else:
                channels = 16
            
            command = [
                'ffmpeg',
                '-i', self.srt_url,
                '-f', 's16le',
                '-ac', str(channels),
                '-ar', str(RATE),
                '-loglevel', 'quiet',
                '-vn',
                '-fflags', 'nobuffer',
                '-flags', 'low_delay',
                'pipe:1'
            ]
            
            print(f"Запускаем ffmpeg: {' '.join(command)}")
            
            startupinfo = create_process_no_window()
            
            popen_kwargs = {
                'stdout': subprocess.PIPE,
                'stderr': subprocess.PIPE,
                'bufsize': CHUNK * 4,
            }
            if IS_WINDOWS:
                popen_kwargs['startupinfo'] = startupinfo
            
            self.ffmpeg_process = subprocess.Popen(command, **popen_kwargs)
            
            print("SRT поток подключен, извлекаем аудио...")
            
            while self.running and self.ffmpeg_process.poll() is None:
                raw_data = self.ffmpeg_process.stdout.read(CHUNK * channels * 2)
                
                if not raw_data:
                    time.sleep(0.01)
                    continue
                
                if len(raw_data) < CHUNK * channels * 2:
                    continue
                    
                audio_data = np.frombuffer(raw_data, dtype=np.int16)
                
                processed_data = self._process_audio_channels(audio_data, self.channel_mode, channels)
                
                momentary, short_term, integrated = self.processor.process_audio(processed_data)
                
                self.data_ready.emit(self.channel_idx, momentary, short_term, integrated)
                
        except Exception as e:
            print(f"Ошибка обработки SRT потока: {e}")
            import traceback
            traceback.print_exc()
        finally:
            if self.ffmpeg_process and self.ffmpeg_process.poll() is None:
                self.ffmpeg_process.terminate()
                self.ffmpeg_process.wait()
    
    def _process_audio_channels(self, audio_data, channel_mode, total_channels):
        if channel_mode == '1+2':
            return self._process_stereo(audio_data, total_channels)
        else:
            channel_num = int(channel_mode.split('+')[0]) - 1
            return self._process_mono(audio_data, channel_num, total_channels)
    
    def _process_stereo(self, audio_data, total_channels):
        if len(audio_data) >= total_channels * 2:
            left_channel = audio_data[0::total_channels]
            right_channel = audio_data[1::total_channels]
            return (left_channel.astype(np.float32) + right_channel.astype(np.float32)) / 2
        return audio_data.astype(np.float32)
    
    def _process_mono(self, audio_data, channel_num, total_channels):
        if len(audio_data) >= total_channels and channel_num < total_channels:
            return audio_data[channel_num::total_channels].astype(np.float32)
        elif len(audio_data) > 0:
            return audio_data[0::total_channels].astype(np.float32)
        return audio_data.astype(np.float32)
    
    def stop(self):
        self.running = False
        if self.ffmpeg_process and self.ffmpeg_process.poll() is None:
            self.ffmpeg_process.terminate()
        self.wait()


class AudioStreamThread(QThread):
    """Поток для захвата аудио с устройства"""
    data_ready = pyqtSignal(int, float, float, float)
    
    def __init__(self, device_index, channel_idx, channel_mode, device_type, calibration_offset=0.0, parent=None):
        super().__init__(parent)
        self.device_index = device_index
        self.channel_idx = channel_idx
        self.channel_mode = channel_mode
        self.device_type = device_type
        self.calibration_offset = calibration_offset
        self.running = False
        self.audio = pyaudio.PyAudio()
        self.processor = R128EBUProcessor(calibration_offset=calibration_offset)
        
    def run(self):
        self.running = True
        stream = None
        
        try:
            channels = 2
            
            if self.device_type == 'Output':
                try:
                    kwargs = {
                        'format': FORMAT,
                        'channels': channels,
                        'rate': RATE,
                        'input': True,
                        'input_device_index': self.device_index,
                        'frames_per_buffer': CHUNK,
                    }
                    if IS_WINDOWS:
                        kwargs['as_loopback'] = True
                    stream = self.audio.open(**kwargs)
                except Exception:
                    stream = self.audio.open(
                        format=FORMAT,
                        channels=channels,
                        rate=RATE,
                        input=True,
                        input_device_index=self.device_index,
                        frames_per_buffer=CHUNK
                    )
            else:
                stream = self.audio.open(
                    format=FORMAT,
                    channels=channels,
                    rate=RATE,
                    input=True,
                    input_device_index=self.device_index,
                    frames_per_buffer=CHUNK
                )
            
            while self.running:
                try:
                    data = stream.read(CHUNK, exception_on_overflow=False)
                    audio_data = np.frombuffer(data, dtype=np.int16)
                    
                    if self.channel_mode == '1+2':
                        processed_data = self._process_stereo(audio_data)
                    elif self.channel_mode in ['1+1', '2+2']:
                        channel_num = int(self.channel_mode.split('+')[0]) - 1
                        processed_data = self._process_mono(audio_data, channel_num)
                    else:
                        processed_data = self._process_mono(audio_data, 0)
                    
                    momentary, short_term, integrated = self.processor.process_audio(processed_data)
                    
                    self.data_ready.emit(self.channel_idx, momentary, short_term, integrated)
                    
                except Exception as e:
                    print(f"Ошибка чтения аудио: {e}")
                    break
                    
        except Exception as e:
            print(f"Ошибка открытия аудиоустройства {self.device_type}: {e}")
        finally:
            if stream:
                stream.stop_stream()
                stream.close()
    
    def _process_stereo(self, audio_data):
        if len(audio_data) >= 2:
            left_channel = audio_data[::2]
            right_channel = audio_data[1::2]
            return (left_channel.astype(np.float32) + right_channel.astype(np.float32)) / 2
        return audio_data.astype(np.float32)
    
    def _process_mono(self, audio_data, channel=0):
        if len(audio_data) >= 2:
            if channel == 0:
                return audio_data[::2].astype(np.float32)
            else:
                return audio_data[1::2].astype(np.float32)
        return audio_data.astype(np.float32)
    
    def stop(self):
        self.running = False
        self.wait()


class VirtualOutputDeviceThread(QThread):
    """Виртуальный поток для эмуляции выходных устройств"""
    data_ready = pyqtSignal(int, float, float, float)
    
    def __init__(self, channel_idx, channel_mode, calibration_offset=0.0, parent=None):
        super().__init__(parent)
        self.channel_idx = channel_idx
        self.channel_mode = channel_mode
        self.calibration_offset = calibration_offset
        self.running = False
        self.processor = R128EBUProcessor(calibration_offset=calibration_offset)
        
    def run(self):
        self.running = True
        
        import math
        sample_count = 0
        
        while self.running:
            try:
                frequency = 440
                amplitude = 0.5
                
                samples = np.zeros(CHUNK, dtype=np.float32)
                for i in range(CHUNK):
                    sample = amplitude * math.sin(2 * math.pi * frequency * (sample_count + i) / RATE)
                    samples[i] = sample
                
                sample_count += CHUNK
                
                momentary, short_term, integrated = self.processor.process_audio(samples)
                
                self.data_ready.emit(self.channel_idx, momentary, short_term, integrated)
                
                time.sleep(CHUNK / RATE)
                
            except Exception as e:
                print(f"Ошибка виртуального устройства: {e}")
                break
    
    def stop(self):
        self.running = False
        self.wait()


class VolumeMeterWidget(QWidget):
    """Виджет для отображения измерителя громкости"""
    def __init__(self, target_lufs=-10.0, display_time=10, parent=None):
        super().__init__(parent)
        self.target_lufs = target_lufs
        self.display_time = display_time
        self.values = []
        self.history = []
        self.colors = []
        self.labels = []
        self.max_history = int(display_time * 10)
        self.fill_enabled = False
        
        self.setMinimumSize(300, 200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        self.current_momentary = -70.0
        self.current_short_term = -70.0
        self.current_integrated = -70.0
        
    def set_target(self, target_lufs):
        self.target_lufs = target_lufs
        self.update()
        
    def set_display_time(self, display_time):
        self.display_time = display_time
        self.max_history = int(display_time * 10)
        
        for i in range(len(self.history)):
            if len(self.history[i]) > self.max_history:
                self.history[i] = self.history[i][-self.max_history:]
            else:
                self.history[i] = [-70.0] * (self.max_history - len(self.history[i])) + self.history[i]
        
        self.update()
        
    def set_fill_enabled(self, enabled):
        self.fill_enabled = enabled
        self.update()
        
    def add_channel(self, color, label):
        self.colors.append(QColor(color))
        self.labels.append(label)
        self.values.append((-70.0, -70.0, -70.0))
        self.history.append([-70.0] * self.max_history)
        
    def update_value(self, channel_idx, momentary, short_term, integrated):
        if 0 <= channel_idx < len(self.values):
            self.values[channel_idx] = (momentary, short_term, integrated)
            self.current_momentary = momentary
            self.current_short_term = short_term
            self.current_integrated = integrated
            
            self.history[channel_idx].pop(0)
            self.history[channel_idx].append(momentary)
            
            self.update()
            
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        width = self.width()
        height = self.height()
        
        if hasattr(self.window(), 'is_dark_mode') and self.window().is_dark_mode:
            bg_color = QColor(30, 30, 30)
            grid_color = QColor(80, 80, 80)
            text_color = QColor(220, 220, 220)
            fill_color = QColor(60, 60, 60, 100)
        else:
            bg_color = QColor(240, 240, 240)
            grid_color = QColor(180, 180, 180)
            text_color = QColor(40, 40, 40)
            fill_color = QColor(200, 200, 200, 100)
        
        painter.fillRect(0, 0, width, height, bg_color)
        
        self._draw_grid(painter, width, height, grid_color, text_color)
        
        if self.fill_enabled:
            self._draw_fill(painter, width, height, fill_color)
        
        self._draw_target_level(painter, width, height)
        
        self._draw_graphs(painter, width, height)
        
        self._draw_current_values(painter, width, height, text_color)
        
    def _draw_grid(self, painter, width, height, grid_color, text_color):
        painter.setPen(QPen(grid_color, 1))
        
        for db in range(-60, 1, 10):
            y = height - 20 - int((db + 70) * (height - 40) / 70)
            painter.drawLine(50, y, width - 10, y)
            painter.setPen(text_color)
            painter.drawText(10, y + 5, f"{db}")
            painter.setPen(QPen(grid_color, 1))
            
        time_interval = max(1, self.max_history // 5)
        for i in range(0, self.max_history + 1, time_interval):
            x = 50 + int(i * (width - 60) / max(1, self.max_history))
            painter.drawLine(x, 20, x, height - 20)
            time_sec = i / 10
            painter.setPen(text_color)
            painter.drawText(x - 15, height - 5, f"{time_sec:.1f}")
            painter.setPen(QPen(grid_color, 1))
            
        painter.setPen(text_color)
        painter.drawText(width // 2 - 20, height - 5, "Время (с)")
        painter.drawText(5, height // 2, "LUFS")
        
    def _draw_fill(self, painter, width, height, fill_color):
        if not self.history:
            return
            
        graph_width = width - 60
        graph_height = height - 40
        
        for i, history in enumerate(self.history):
            if i >= len(self.colors):
                continue
                
            polygon = QPolygonF()
            
            polygon.append(QPointF(50, height - 20))
            
            for j, value in enumerate(history):
                x = 50 + int(j * graph_width / max(1, self.max_history))
                y = height - 20 - int((value + 70) * graph_height / 70)
                polygon.append(QPointF(x, y))
            
            polygon.append(QPointF(width - 10, height - 20))
            
            painter.setBrush(fill_color)
            painter.setPen(Qt.NoPen)
            painter.drawPolygon(polygon)
        
    def _draw_target_level(self, painter, width, height):
        target_y = height - 20 - int((self.target_lufs + 70) * (height - 40) / 70)
        painter.setPen(QPen(QColor(255, 0, 0), 2, Qt.DashLine))
        painter.drawLine(50, target_y, width - 10, target_y)
        
        if hasattr(self.window(), 'is_dark_mode') and self.window().is_dark_mode:
            text_color = QColor(255, 150, 150)
        else:
            text_color = QColor(200, 0, 0)
            
        painter.setPen(text_color)
        painter.drawText(width - 40, target_y - 5, f"{self.target_lufs:.1f}")
        
    def _draw_graphs(self, painter, width, height):
        if not self.history:
            return
            
        graph_width = width - 60
        graph_height = height - 40
        
        for i, history in enumerate(self.history):
            if i >= len(self.colors):
                continue
                
            painter.setPen(QPen(self.colors[i], 2))
            
            path = []
            for j, value in enumerate(history):
                x = 50 + int(j * graph_width / max(1, self.max_history))
                y = height - 20 - int((value + 70) * graph_height / 70)
                path.append((x, y))
                
            for j in range(1, len(path)):
                painter.drawLine(path[j-1][0], path[j-1][1], path[j][0], path[j][1])
                
            legend_x = 60 + i * 100
            legend_y = 15
            if legend_x < width - 50:
                painter.drawLine(legend_x, legend_y, legend_x + 30, legend_y)
                
                if hasattr(self.window(), 'is_dark_mode') and self.window().is_dark_mode:
                    painter.setPen(QColor(220, 220, 220))
                else:
                    painter.setPen(QColor(40, 40, 40))
                    
                painter.drawText(legend_x + 35, legend_y + 5, self.labels[i])
            
    def _draw_current_values(self, painter, width, height, text_color):
        painter.setPen(text_color)
        font = QFont("Arial", 8)
        painter.setFont(font)
        
        text = f"M:{self.current_momentary:.1f} S:{self.current_short_term:.1f} I:{self.current_integrated:.1f} T:{self.target_lufs:.1f}"
        metrics = QFontMetrics(font)
        text_width = metrics.horizontalAdvance(text) if hasattr(metrics, 'horizontalAdvance') else metrics.width(text)
        
        if text_width < width - 20:
            painter.drawText(10, 15, text)
        else:
            short_text = f"M:{self.current_momentary:.1f} T:{self.target_lufs:.1f}"
            painter.drawText(10, 15, short_text)


class AudioDeviceManager:
    """Менеджер аудиоустройств и SRT потоков"""
    def __init__(self):
        self.audio = pyaudio.PyAudio()
        self.devices = self.get_all_audio_devices()
        self.srt_streams = []
        
    def get_all_audio_devices(self):
        devices = []
        
        for i in range(self.audio.get_device_count()):
            device_info = self.audio.get_device_info_by_index(i)
            if device_info['maxInputChannels'] > 0:
                devices.append((
                    i, 
                    f"[Input] {device_info['name']}", 
                    device_info['maxInputChannels'],
                    'Input'
                ))
        
        for i in range(self.audio.get_device_count()):
            device_info = self.audio.get_device_info_by_index(i)
            if (device_info['maxOutputChannels'] > 0 and 
                device_info['maxInputChannels'] > 0 and
                'output' in device_info['name'].lower()):
                devices.append((
                    i, 
                    f"[Output] {device_info['name']}", 
                    device_info['maxOutputChannels'],
                    'Output'
                ))
        
        devices.append((-1, "[Virtual] System Output", 2, 'Output'))
        
        return devices
    
    def add_srt_stream(self, url, name):
        self.srt_streams.append((url, name, 'SRT Stream'))
        print(f"Добавлен SRT поток: {name} -> {url}")
        
    def get_all_devices(self):
        all_devices = self.devices.copy()
        
        for url, name, device_type in self.srt_streams:
            all_devices.append((-2, f"[SRT] {name}", 2, device_type))
            
        return all_devices
    
    def get_device_index_by_name(self, name):
        for idx, device_name, _, device_type in self.get_all_devices():
            if device_name == name:
                return idx
        return None
    
    def get_device_type(self, name):
        for idx, device_name, _, device_type in self.get_all_devices():
            if device_name == name:
                return device_type
        return 'Input'


class ChannelConfigWidget(QWidget):
    """Виджет для настройки канала"""
    def __init__(self, channel_idx, audio_manager, parent=None):
        super().__init__(parent)
        self.channel_idx = channel_idx
        self.audio_manager = audio_manager
        self.setup_ui()
        
    def setup_ui(self):
        layout = QHBoxLayout(self)
        
        self.enabled_checkbox = QCheckBox(f"Канал {self.channel_idx + 1}")
        self.enabled_checkbox.setChecked(True)
        
        self.device_combo = QComboBox()
        self.refresh_devices()
        
        self.channel_mode_combo = QComboBox()
        self.channel_mode_combo.addItems(["1+2 (Стерео)", "1+1 (Моно L)", "2+2 (Моно R)"])
        self.channel_mode_combo.setCurrentIndex(0)
        
        self.color_combo = QComboBox()
        self.color_combo.addItems(["Серый", "Зеленый", "Красный", "Синий", "Желтый", "Пурпурный", "Голубой"])
        self.color_combo.setCurrentIndex(self.channel_idx % 7)
        
        layout.addWidget(self.enabled_checkbox)
        layout.addWidget(QLabel("Устройство:"))
        layout.addWidget(self.device_combo)
        layout.addWidget(QLabel("Режим:"))
        layout.addWidget(self.channel_mode_combo)
        layout.addWidget(QLabel("Цвет:"))
        layout.addWidget(self.color_combo)
        
        self.apply_theme()
        
    def refresh_devices(self):
        self.device_combo.clear()
        for _, name, _, _ in self.audio_manager.get_all_devices():
            self.device_combo.addItem(name)
        
    def apply_theme(self):
        if hasattr(self.window(), 'is_dark_mode') and self.window().is_dark_mode:
            self.setStyleSheet("""
                QCheckBox, QLabel { color: white; }
                QComboBox { 
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
            "Пурпурный": "orange",
            "Голубой": "cyan"
        }
        return color_map[self.color_combo.currentText()]
    
    def is_enabled(self):
        return self.enabled_checkbox.isChecked()
    
    def get_device_name(self):
        return self.device_combo.currentText()
    
    def get_channel_mode(self):
        mode_text = self.channel_mode_combo.currentText()
        if "Стерео" in mode_text:
            return "1+2"
        elif "Моно L" in mode_text:
            return "1+1"
        else:
            return "2+2"


class MeterWindow(QWidget):
    """Окно с измерителем громкости"""
    def __init__(self, window_idx, audio_manager, calibration_offset=0.0, parent=None):
        super().__init__(parent)
        self.window_idx = window_idx
        self.audio_manager = audio_manager
        self.calibration_offset = calibration_offset
        self.channels = []
        self.audio_threads = []
        self.custom_title = f"Окно {window_idx + 1}"
        
        self.setup_ui()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        
        self.title_edit = QLineEdit(self.custom_title)
        self.title_edit.setStyleSheet("font-weight: bold; font-size: 14px; border: 1px solid #ccc; padding: 2px;")
        self.title_edit.textChanged.connect(self.update_title)
        
        self.toggle_button = QPushButton("▲")
        self.toggle_button.setFixedSize(20, 20)
        self.toggle_button.clicked.connect(self.toggle_config)
        
        header_layout.addWidget(self.title_edit)
        header_layout.addWidget(self.toggle_button)
        header_layout.addStretch()
        
        layout.addWidget(header_widget)
        
        self.config_widget = QWidget()
        self.config_layout = QVBoxLayout(self.config_widget)
        
        self.channel_layout = QVBoxLayout()
        for i in range(2):
            channel_config = ChannelConfigWidget(i, self.audio_manager)
            self.channels.append(channel_config)
            self.channel_layout.addWidget(channel_config)
        
        self.config_layout.addLayout(self.channel_layout)
        
        self.add_channel_btn = QPushButton("+ Добавить канал")
        self.add_channel_btn.clicked.connect(self.add_channel)
        self.config_layout.addWidget(self.add_channel_btn)
        
        layout.addWidget(self.config_widget)
        
        self.volume_meter = VolumeMeterWidget()
        layout.addWidget(self.volume_meter)
        
        self.config_visible = True
        
    def update_title(self, text):
        self.custom_title = text
        self.update()
        
    def toggle_config(self):
        self.config_visible = not self.config_visible
        self.config_widget.setVisible(self.config_visible)
        self.toggle_button.setText("▼" if self.config_visible else "▲")
        
    def add_channel(self):
        new_idx = len(self.channels)
        channel_config = ChannelConfigWidget(new_idx, self.audio_manager)
        self.channels.append(channel_config)
        self.channel_layout.addWidget(channel_config)
        
    def set_calibration_offset(self, offset):
        self.calibration_offset = offset
        
    def start_measurement(self):
        self.stop_measurement()
        
        self.volume_meter.values = []
        self.volume_meter.history = []
        self.volume_meter.colors = []
        self.volume_meter.labels = []
        
        print(f"Запуск измерения для окна {self.custom_title} (калибровка: {self.calibration_offset} dB)")
        
        for i, channel in enumerate(self.channels):
            if channel.is_enabled():
                device_name = channel.get_device_name()
                device_index = self.audio_manager.get_device_index_by_name(device_name)
                device_type = self.audio_manager.get_device_type(device_name)
                channel_mode = channel.get_channel_mode()
                
                print(f"  Канал {i+1}: {device_name} (режим: {channel_mode})")
                
                self.volume_meter.add_channel(channel.get_color(), f"Канал {i + 1}")
                
                if device_type == 'SRT Stream':
                    url = None
                    for srt_url, srt_name, _ in self.audio_manager.srt_streams:
                        if f"[SRT] {srt_name}" == device_name:
                            url = srt_url
                            break
                    
                    if url:
                        print(f"    Запуск SRT процессора: {url}")
                        thread = SRTStreamProcessor(url, i, channel_mode, self.calibration_offset)
                        thread.data_ready.connect(self.volume_meter.update_value)
                        thread.start()
                        self.audio_threads.append(thread)
                    else:
                        print(f"    Не найден URL для SRT потока: {device_name}")
                        
                elif device_index == -1:
                    print(f"    Запуск виртуального устройства")
                    thread = VirtualOutputDeviceThread(i, channel_mode, self.calibration_offset)
                    thread.data_ready.connect(self.volume_meter.update_value)
                    thread.start()
                    self.audio_threads.append(thread)
                    
                else:
                    print(f"    Запуск аудиоустройства: {device_name}")
                    thread = AudioStreamThread(device_index, i, channel_mode, device_type, self.calibration_offset)
                    thread.data_ready.connect(self.volume_meter.update_value)
                    thread.start()
                    self.audio_threads.append(thread)
        
        print(f"Измерение запущено для {len(self.audio_threads)} каналов")
    
    def stop_measurement(self):
        for thread in self.audio_threads:
            thread.stop()
        self.audio_threads.clear()
    
    def refresh_devices(self):
        for channel in self.channels:
            channel.refresh_devices()
    
    def apply_theme(self):
        for channel in self.channels:
            channel.apply_theme()
    
    def set_target(self, target_lufs):
        self.volume_meter.set_target(target_lufs)
    
    def set_display_time(self, display_time):
        self.volume_meter.set_display_time(display_time)
        
    def set_fill_enabled(self, enabled):
        self.volume_meter.set_fill_enabled(enabled)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.audio_manager = AudioDeviceManager()
        self.meter_windows = []
        self.is_dark_mode = False
        self.measuring = False
        self.fill_enabled = False
        self.calibration_offset = 0.0
        
        self.setup_ui()
        
    def setup_ui(self):
        self.setWindowTitle("Анализатор громкости R128 EBU - SRT & Audio")
        self.setGeometry(100, 100, 1200, 800)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        self.create_menu()
        
        self.control_panel = QGroupBox("Настройки")
        self.control_panel.setCheckable(True)
        self.control_panel.setChecked(True)
        self.control_panel.toggled.connect(self.toggle_control_panel)
        
        control_layout = QGridLayout(self.control_panel)
        
        control_layout.addWidget(QLabel("Целевой уровень LUFS:"), 0, 0)
        self.target_spin = QDoubleSpinBox()
        self.target_spin.setRange(-50, 0)
        self.target_spin.setValue(-10.0)
        self.target_spin.setSingleStep(0.5)
        self.target_spin.valueChanged.connect(self.update_all_targets)
        control_layout.addWidget(self.target_spin, 0, 1)
        
        control_layout.addWidget(QLabel("Время отображения (сек):"), 0, 2)
        self.display_time_spin = QSpinBox()
        self.display_time_spin.setRange(1, 60)
        self.display_time_spin.setValue(10)
        self.display_time_spin.valueChanged.connect(self.update_display_time)
        control_layout.addWidget(self.display_time_spin, 0, 3)
        
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
        
        self.fill_checkbox = QCheckBox("Заливка под графиками")
        self.fill_checkbox.setChecked(self.fill_enabled)
        self.fill_checkbox.stateChanged.connect(self.toggle_fill)
        control_layout.addWidget(self.fill_checkbox, 2, 0)
        
        self.start_btn = QPushButton("Старт")
        self.start_btn.clicked.connect(self.toggle_measurement)
        control_layout.addWidget(self.start_btn, 2, 1)
        
        info_text = f"Доступно устройств: {len(self.audio_manager.get_all_devices())} (Input/Output/SRT/Virtual)"
        info_label = QLabel(info_text)
        info_label.setStyleSheet("color: #888; font-size: 10px;")
        control_layout.addWidget(info_label, 3, 0, 1, 4)
        
        main_layout.addWidget(self.control_panel)
        
        self.graphs_container = QWidget()
        self.graphs_layout = QGridLayout(self.graphs_container)
        self.graphs_layout.setSpacing(5)
        
        self.meter_windows = []
        
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.graphs_container)
        
        main_layout.addWidget(self.scroll_area)
        
        self.add_meter_window()
        
        self.apply_theme()
        
    def create_menu(self):
        menubar = self.menuBar()
        
        file_menu = menubar.addMenu('Файл')
        
        add_srt_action = QAction('Добавить SRT поток...', self)
        add_srt_action.triggered.connect(self.add_srt_stream)
        file_menu.addAction(add_srt_action)
        
        refresh_action = QAction('Обновить устройства', self)
        refresh_action.triggered.connect(self.refresh_all_devices)
        file_menu.addAction(refresh_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction('Выход', self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        view_menu = menubar.addMenu('Вид')
        
        self.toggle_theme_action = QAction('Тёмный режим', self)
        self.toggle_theme_action.setCheckable(True)
        self.toggle_theme_action.setChecked(False)
        self.toggle_theme_action.triggered.connect(self.toggle_theme)
        view_menu.addAction(self.toggle_theme_action)
        
    def toggle_theme(self):
        self.is_dark_mode = not self.is_dark_mode
        self.toggle_theme_action.setChecked(self.is_dark_mode)
        self.apply_theme()
        
    def toggle_fill(self, state):
        self.fill_enabled = state == Qt.Checked
        for window in self.meter_windows:
            window.set_fill_enabled(self.fill_enabled)
            
    def update_calibration_offset(self):
        self.calibration_offset = self.calibration_spin.value()
        for window in self.meter_windows:
            window.set_calibration_offset(self.calibration_offset)
        
        if self.measuring:
            self.stop_all_measurements()
            self.start_all_measurements()
        
    def apply_theme(self):
        if self.is_dark_mode:
            self.setStyleSheet("""
                QMainWindow {
                    background-color: #2b2b2b;
                    color: white;
                }
                QWidget {
                    background-color: #2b2b2b;
                    color: white;
                }
                QGroupBox {
                    background-color: #404040;
                    color: white;
                    border: 1px solid #555;
                    border-radius: 5px;
                    margin-top: 1ex;
                    padding-top: 10px;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 5px 0 5px;
                }
                QPushButton {
                    background-color: #404040;
                    color: white;
                    border: 1px solid #555;
                    padding: 5px;
                    border-radius: 3px;
                }
                QPushButton:hover {
                    background-color: #505050;
                }
                QPushButton:pressed {
                    background-color: #606060;
                }
                QLabel {
                    color: white;
                }
                QDoubleSpinBox, QSpinBox {
                    background-color: #333;
                    color: white;
                    border: 1px solid #555;
                    padding: 2px;
                }
                QScrollArea {
                    background-color: #2b2b2b;
                    border: none;
                }
                QCheckBox {
                    color: white;
                }
                QCheckBox::indicator {
                    width: 13px;
                    height: 13px;
                }
                QCheckBox::indicator:unchecked {
                    border: 1px solid #555;
                    background-color: #333;
                }
                QCheckBox::indicator:checked {
                    border: 1px solid #555;
                    background-color: #0078d7;
                }
                QComboBox {
                    background-color: #333;
                    color: white;
                    border: 1px solid #555;
                    padding: 2px;
                }
                QComboBox::drop-down {
                    border: 0px;
                }
                QComboBox::down-arrow {
                    image: none;
                    border: 0px;
                }
                QMenuBar {
                    background-color: #404040;
                    color: white;
                }
                QMenuBar::item {
                    background-color: transparent;
                    padding: 4px 10px;
                }
                QMenuBar::item:selected {
                    background-color: #505050;
                }
                QMenu {
                    background-color: #404040;
                    color: white;
                    border: 1px solid #555;
                }
                QMenu::item {
                    padding: 5px 20px;
                }
                QMenu::item:selected {
                    background-color: #505050;
                }
            """)
        else:
            self.setStyleSheet("")
            
        for window in self.meter_windows:
            window.apply_theme()
            for channel in window.channels:
                channel.apply_theme()
                
        self.update()
        
    def toggle_control_panel(self, visible):
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
        for i in reversed(range(self.graphs_layout.count())): 
            self.graphs_layout.itemAt(i).widget().setParent(None)
        
        num_windows = len(self.meter_windows)
        if num_windows == 0:
            return
            
        cols = min(6, int(np.ceil(np.sqrt(num_windows))))
        rows = int(np.ceil(num_windows / cols))
        
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
            
    def update_all_targets(self):
        target = self.target_spin.value()
        for window in self.meter_windows:
            window.set_target(target)
            
    def update_display_time(self):
        display_time = self.display_time_spin.value()
        for window in self.meter_windows:
            window.set_display_time(display_time)
            
    def toggle_measurement(self):
        if self.measuring:
            self.stop_all_measurements()
            self.start_btn.setText("Старт")
        else:
            self.start_all_measurements()
            self.start_btn.setText("Стоп")
            
        self.measuring = not self.measuring
        
    def start_all_measurements(self):
        for window in self.meter_windows:
            window.start_measurement()
            
    def stop_all_measurements(self):
        for window in self.meter_windows:
            window.stop_measurement()
            
    def add_srt_stream(self):
        dialog = SRTStreamDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            url, name = dialog.get_srt_data()
            if url:
                self.audio_manager.add_srt_stream(url, name)
                self.refresh_all_devices()
                QMessageBox.information(self, "Успех", f"SRT поток '{name}' добавлен!")
    
    def refresh_all_devices(self):
        for window in self.meter_windows:
            window.refresh_devices()
            
    def closeEvent(self, event):
        self.stop_all_measurements()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    try:
        startupinfo = create_process_no_window()
        kwargs = {'capture_output': True, 'text': True}
        if IS_WINDOWS:
            kwargs['startupinfo'] = startupinfo
        result = subprocess.run(['ffmpeg', '-version'], **kwargs)
        if result.returncode == 0:
            print("FFmpeg найден")
        else:
            print("FFmpeg не найден. Убедитесь, что ffmpeg установлен и добавлен в PATH")
    except Exception:
        print("FFmpeg не найден. Убедитесь, что ffmpeg установлен и добавлен в PATH")
        print("Установка на macOS: brew install ffmpeg")
    
    if IS_MACOS:
        print("Запуск на macOS. Для захвата системного аудио установите BlackHole:")
        print("  brew install blackhole-2ch")
        print("  Затем выберите BlackHole как устройство ввода в настройках Audio MIDI Setup")
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec_())
