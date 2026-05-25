import sys
import re
import os
from PySide6.QtCore import QThread, Signal, Slot
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QProgressBar, QLabel, 
                             QComboBox, QTextEdit, QLineEdit, QFileDialog)
import yt_dlp

class InfoWorker(QThread):
    info_fetched = Signal(dict)
    error_signal = Signal(str)

    def __init__(self, url):
        super().__init__()
        self.url = url

    def run(self):
        try:
            ydl_opts = {'quiet': True, 'extract_flat': 'in_playlist', 'skip_download': True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(self.url, download=False)
                if not info:
                    self.error_signal.emit("Could not fetch information.")
                    return
                if 'entries' in info:
                    entries = list(info['entries'])
                    title = f"[Playlist] {info.get('title', 'Unknown')} ({len(entries)} items)"
                else:
                    title = info.get('title', 'Unknown Title')
                self.info_fetched.emit({'title': title})
        except Exception as e:
            self.error_signal.emit(str(e))


class DownloadThread(QThread):
    progress_signal = Signal(dict)
    log_signal = Signal(str)
    finished_signal = Signal(bool, str)

    def __init__(self, url, download_type, resolution, output_path):
        super().__init__()
        self.url = url
        self.download_type = download_type
        self.resolution = resolution
        self.output_path = output_path

    def clean_ansi_codes(self, text):
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        return ansi_escape.sub('', text)

    def progress_hook(self, d):
        if d['status'] == 'downloading':
            downloaded = self.clean_ansi_codes(str(d.get('_downloaded_bytes_str', '0B')))
            total = self.clean_ansi_codes(str(d.get('_total_bytes_str', d.get('_total_bytes_estimate_str', 'N/A'))))
            speed = self.clean_ansi_codes(str(d.get('_speed_str', 'N/A')))
            eta = self.clean_ansi_codes(str(d.get('_eta_str', 'N/A')))
            
            try:
                total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate') or 1
                downloaded_bytes = d.get('downloaded_bytes', 0)
                percentage = (downloaded_bytes / total_bytes) * 100
            except ZeroDivisionError:
                percentage = 0.0

            filename = os.path.basename(d.get('filename', 'Video File'))
            progress_data = {
                'percentage': percentage,
                'status_text': f"Target: {filename[:30]}... | {downloaded} / {total} @ {speed} | ETA: {eta}"
            }
            self.progress_signal.emit(progress_data)

    def run(self):
        ydl_opts = {
            'outtmpl': os.path.join(self.output_path, '%(title)s.%(ext)s'),
            'progress_hooks': [self.progress_hook],
            'logger': self,
            'ignoreerrors': True,
        }

        res_filter = f"[height<={self.resolution}]" if self.resolution != "best" else ""

        if self.download_type == "both":
            ydl_opts['format'] = f'bv*{res_filter}+ba/b{res_filter}'
            ydl_opts['merge_output_format'] = 'mp4'
        elif self.download_type == "video_only":
            ydl_opts['format'] = f'bv*{res_filter}'
        elif self.download_type == "audio_only":
            ydl_opts['format'] = 'ba/b'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([self.url])
            self.finished_signal.emit(True, "Process completed successfully!")
        except Exception as e:
            self.finished_signal.emit(False, str(e))

    def debug(self, msg): self.log_signal.emit(self.clean_ansi_codes(msg))
    def info(self, msg): self.log_signal.emit(self.clean_ansi_codes(msg))
    def warning(self, msg): self.log_signal.emit(self.clean_ansi_codes(msg))
    def error(self, msg): self.log_signal.emit(self.clean_ansi_codes(msg))


class ProDLWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ProDL - Professional Video & Playlist Downloader")
        self.setMinimumSize(900, 560)
        self.init_ui()
        self.apply_dark_theme()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(12)

        # 1. URL Input & Fetch Action Row
        url_layout = QHBoxLayout()
        url_label = QLabel("Video/Playlist URL:")
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Paste video link or full playlist URL...")
        
        self.fetch_btn = QPushButton("🔍 Fetch Info")
        self.fetch_btn.clicked.connect(self.fetch_link_details)
        self.fetch_btn.setEnabled(False)
        
        url_layout.addWidget(url_label)
        url_layout.addWidget(self.url_input)
        url_layout.addWidget(self.fetch_btn)
        main_layout.addLayout(url_layout)

        # 2. Save Location Row (NEW FEATURE)
        save_layout = QHBoxLayout()
        save_label = QLabel("Save Location:     ")
        self.save_input = QLineEdit()
        # Default to user's standard Downloads directory
        default_path = os.path.normpath(os.path.expanduser("~/Downloads"))
        self.save_input.setText(default_path)
        
        self.browse_btn = QPushButton("📁 Browse...")
        self.browse_btn.clicked.connect(self.browse_folder)
        
        save_layout.addWidget(save_label)
        save_layout.addWidget(self.save_input)
        save_layout.addWidget(self.browse_btn)
        main_layout.addLayout(save_layout)

        # 3. Options Grid Configuration
        options_layout = QHBoxLayout()
        
        type_label = QLabel("Mode:")
        self.type_combo = QComboBox()
        self.type_combo.addItems([
            "🎬 Video + Audio (Combined)", 
            "🎞️ Video Only (No Audio)", 
            "🎵 Audio Only (MP3)"
        ])
        
        res_label = QLabel("Max Quality:")
        self.res_combo = QComboBox()
        self.res_combo.addItems(["Best Available", "4K (2160p)", "1080p", "720p", "480p"])
        
        options_layout.addWidget(type_label)
        options_layout.addWidget(self.type_combo)
        options_layout.addWidget(res_label)
        options_layout.addWidget(self.res_combo)
        options_layout.addStretch()
        main_layout.addLayout(options_layout)

        # 4. Dedicated Target Title Box
        title_layout = QHBoxLayout()
        title_lbl = QLabel("Target Name:")
        self.title_display = QLineEdit()
        self.title_display.setReadOnly(True)
        self.title_display.setPlaceholderText("Click 'Fetch Info' to resolve target details...")
        title_layout.addWidget(title_lbl)
        title_layout.addWidget(self.title_display)
        main_layout.addLayout(title_layout)

        # 5. Terminal Log Frame
        self.console_log = QTextEdit()
        self.console_log.setReadOnly(True)
        main_layout.addWidget(self.console_log)

        # 6. Output Progress Indicators
        self.status_label = QLabel("Status: Idle")
        main_layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        main_layout.addWidget(self.progress_bar)

        # 7. Primary Action Bars
        button_layout = QHBoxLayout()
        self.start_btn = QPushButton("▶ Start Download")
        self.stop_btn = QPushButton("⏹ Stop")
        
        self.start_btn.clicked.connect(self.start_download)
        self.stop_btn.clicked.connect(self.stop_download)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)

        self.url_input.textChanged.connect(lambda text: self.fetch_btn.setEnabled(len(text.strip()) > 0))

        button_layout.addWidget(self.start_btn)
        button_layout.addWidget(self.stop_btn)
        main_layout.addLayout(button_layout)

    def apply_dark_theme(self):
        self.setStyleSheet("""
            QMainWindow { background-color: #121212; color: #E0E0E0; }
            QLabel { color: #E0E0E0; font-size: 13px; font-weight: bold; }
            QLineEdit { background-color: #1E1E1E; color: white; border: 1px solid #333; padding: 8px; border-radius: 4px; }
            QComboBox { background-color: #1E1E1E; color: white; border: 1px solid #333; padding: 6px; border-radius: 4px; min-width: 160px; }
            QTextEdit { background-color: #1A1A1A; color: #A0A0A0; border: 1px solid #2D2D2D; border-radius: 6px; font-family: 'Consolas', monospace; }
            QProgressBar { background-color: #1E1E1E; border: 1px solid #333; border-radius: 5px; text-align: center; color: white; font-weight: bold; height: 25px; }
            QProgressBar::chunk { background-color: #007ACC; border-radius: 4px; }
            QPushButton { font-weight: bold; font-size: 13px; padding: 10px 16px; border-radius: 4px; background-color: #2D2D2D; color: white; border: 1px solid #444; }
            QPushButton:hover { background-color: #3D3D3D; }
            QPushButton#start_btn { background-color: #2EA44F; color: white; font-size: 14px; padding: 12px; }
            QPushButton#start_btn:hover { background-color: #34c25e; }
            QPushButton#stop_btn { background-color: #FA4549; color: white; font-size: 14px; padding: 12px; }
            QPushButton#stop_btn:hover { background-color: #ff5c60; }
            QPushButton:disabled { background-color: #202020; color: #606060; border: 1px solid #2A2A2A; }
        """)
        self.start_btn.setObjectName("start_btn")
        self.stop_btn.setObjectName("stop_btn")
        self.title_display.setStyleSheet("background-color: #181818; color: #00FF66; font-weight: bold; border: 1px solid #2A2A2A;")

    def browse_folder(self):
        """Opens a folder selection dialog box"""
        selected_dir = QFileDialog.getExistingDirectory(self, "Select Save Directory", self.save_input.text())
        if selected_dir:
            self.save_input.setText(os.path.normpath(selected_dir))

    def fetch_link_details(self):
        url = self.url_input.text().strip()
        if not url: return

        self.title_display.setText("Resolving link properties... please wait...")
        self.fetch_btn.setEnabled(False)

        self.info_thread = InfoWorker(url)
        self.info_thread.info_fetched.connect(self.on_info_success)
        self.info_thread.error_signal.connect(self.on_info_failure)
        self.info_thread.start()

    @Slot(dict)
    def on_info_success(self, data):
        self.title_display.setText(data['title'])
        self.fetch_btn.setEnabled(True)
        self.start_btn.setEnabled(True)

    @Slot(str)
    def on_info_failure(self, err_msg):
        self.title_display.setText("Failed to read URL.")
        self.console_log.append(f"Error resolving link: {err_msg}")
        self.fetch_btn.setEnabled(True)
        self.start_btn.setEnabled(False)

    def start_download(self):
        target_url = self.url_input.text().strip()
        output_dir = self.save_input.text().strip()
        
        if not target_url or not output_dir: return

        modes = ["both", "video_only", "audio_only"]
        selected_mode = modes[self.type_combo.currentIndex()]

        resolutions = ["best", "2160", "1080", "720", "480"]
        selected_res = resolutions[self.res_combo.currentIndex()]

        self.console_log.clear()
        self.console_log.append(f"Starting execution [Mode: {selected_mode.upper()} | Res Limit: {selected_res}]...")
        self.console_log.append(f"Saving files to: {output_dir}\n")

        self.thread = DownloadThread(target_url, selected_mode, selected_res, output_dir)
        self.thread.progress_signal.connect(self.update_progress)
        self.thread.log_signal.connect(self.update_log)
        self.thread.finished_signal.connect(self.download_finished)
        self.thread.start()

        self.start_btn.setEnabled(False)
        self.fetch_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

    def stop_download(self):
        if hasattr(self, 'thread') and self.thread.isRunning():
            self.thread.terminate()
            self.thread.wait()
            self.download_finished(False, "Execution halted by user.")

    @Slot(dict)
    def update_progress(self, data):
        self.progress_bar.setValue(int(data['percentage']))
        self.status_label.setText(data['status_text'])

    @Slot(str)
    def update_log(self, text):
        self.console_log.append(text)

    @Slot(bool, str)
    def download_finished(self, success, message):
        self.start_btn.setEnabled(True)
        self.fetch_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress_bar.setValue(100 if success else 0)
        self.status_label.setText(f"Status: {message}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ProDLWindow()
    window.show()
    sys.exit(app.exec())
