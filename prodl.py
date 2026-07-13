import sys
import re
import os
from PySide6.QtCore import QThread, Signal, Slot
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QProgressBar, QLabel, 
                             QComboBox, QTextEdit, QLineEdit, QFileDialog, QCheckBox)
import yt_dlp

class InfoWorker(QThread):
    info_fetched = Signal(dict)
    error_signal = Signal(str)

    def __init__(self, url):
        super().__init__()
        self.url = url

    def run(self):
        try:
            ydl_opts = {
                'quiet': True,
                'extract_flat': 'in_playlist',
                'skip_download': True,
                'ignoreerrors': True
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(self.url, download=False)
                if not info:
                    self.error_signal.emit("Could not fetch information.")
                    return
                
                is_playlist = 'entries' in info and info['entries'] is not None
                if is_playlist:
                    entries = list(info['entries'])
                    display_title = f"[Playlist] {info.get('title', 'Unknown')} ({len(entries)} items)"
                    folder_name = info.get('title', 'Unknown Playlist').strip()
                    total_items = len(entries)
                else:
                    display_title = info.get('title', 'Unknown Title')
                    folder_name = display_title.strip()
                    total_items = 1
                
                # Sanitize folder name for filesystem safety
                folder_name = re.sub(r'[\\/*?:"<>|]', '_', folder_name)[:100]
                
                self.info_fetched.emit({
                    'title': display_title,
                    'folder_name': folder_name,
                    'is_playlist': is_playlist,
                    'total_items': total_items
                })
        except Exception as e:
            self.error_signal.emit(f"Failed to fetch info: {str(e)}")


class DownloadThread(QThread):
    progress_signal = Signal(dict)
    log_signal = Signal(str)
    finished_signal = Signal(bool, str)

    def __init__(self, url, download_type, resolution, output_path, folder_name="", download_subs=True, total_items=1):
        super().__init__()
        self.url = url
        self.download_type = download_type
        self.resolution = resolution
        self.output_path = output_path
        self.folder_name = folder_name or "Download"
        self.download_subs = download_subs
        self.total_items = total_items
        self.current_item = 0

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
                percentage = min(100, max(0, (downloaded_bytes / total_bytes) * 100))
            except (ZeroDivisionError, TypeError):
                percentage = 0.0

            filename = os.path.basename(d.get('filename', 'Video File'))
            
            # Playlist indexing
            index_info = ""
            if self.total_items > 1:
                # Try to extract current index from filename or info
                match = re.search(r'(\d+)', filename)
                if match:
                    try:
                        self.current_item = int(match.group(1))
                    except:
                        pass
                index_info = f"[{self.current_item}/{self.total_items}] "
            
            progress_data = {
                'percentage': percentage,
                'status_text': f"{index_info}Target: {filename[:35]}... | {downloaded} / {total} @ {speed} | ETA: {eta}"
            }
            self.progress_signal.emit(progress_data)
        elif d['status'] == 'finished':
            self.log_signal.emit(f"✅ Completed: {d.get('filename', 'file')}")

    def run(self):
        # Create dedicated subfolder for this download
        target_dir = os.path.join(self.output_path, self.folder_name)
        os.makedirs(target_dir, exist_ok=True)
        
        # Smart output template with playlist indexing
        outtmpl = os.path.join(target_dir, '%(playlist_index)s - %(title)s.%(ext)s')
        
        ydl_opts = {
            'outtmpl': outtmpl,
            'progress_hooks': [self.progress_hook],
            'logger': self,
            'ignoreerrors': True,
            'no_warnings': False,
            'extractor_retries': 3,
            'retries': 3,
            'concurrent_fragment_downloads': 4,
            'writethumbnail': True,
            'writeinfojson': True,
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

        # Subtitles
        ydl_opts['writesubtitles'] = self.download_subs
        ydl_opts['writeautomaticsub'] = self.download_subs

        try:
            self.log_signal.emit(f"Downloading to folder: {target_dir}")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([self.url])
            self.finished_signal.emit(True, f"Download completed! Files saved in: {self.folder_name}")
        except Exception as e:
            error_msg = f"Download failed: {str(e)}"
            self.log_signal.emit(error_msg)
            self.finished_signal.emit(False, error_msg)

    def debug(self, msg): self.log_signal.emit(self.clean_ansi_codes(msg))
    def info(self, msg): self.log_signal.emit(self.clean_ansi_codes(msg))
    def warning(self, msg): self.log_signal.emit(self.clean_ansi_codes(msg))
    def error(self, msg): self.log_signal.emit(self.clean_ansi_codes(msg))


class ProDLWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ProDL - Professional Video & Playlist Downloader")
        self.setMinimumSize(950, 620)
        self.current_folder_name = ""
        self.current_is_playlist = False
        self.current_total_items = 1
        self.init_ui()
        self.apply_dark_theme()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(12)

        # 1. URL Input
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

        # 2. Save Location
        save_layout = QHBoxLayout()
        save_label = QLabel("Save Location:     ")
        self.save_input = QLineEdit()
        default_path = os.path.normpath(os.path.expanduser("~/Downloads"))
        self.save_input.setText(default_path)
        
        self.browse_btn = QPushButton("📁 Browse...")
        self.browse_btn.clicked.connect(self.browse_folder)
        
        save_layout.addWidget(save_label)
        save_layout.addWidget(self.save_input)
        save_layout.addWidget(self.browse_btn)
        main_layout.addLayout(save_layout)

        # 3. Options
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
        self.res_combo.addItems(["Best Available", "4K (2160p)", "1080p", "720p", "480p", "360p"])
        
        self.subs_check = QCheckBox("Download Subtitles")
        self.subs_check.setChecked(True)
        
        options_layout.addWidget(type_label)
        options_layout.addWidget(self.type_combo)
        options_layout.addWidget(res_label)
        options_layout.addWidget(self.res_combo)
        options_layout.addWidget(self.subs_check)
        options_layout.addStretch()
        main_layout.addLayout(options_layout)

        # 4. Target Title
        title_layout = QHBoxLayout()
        title_lbl = QLabel("Target Name:")
        self.title_display = QLineEdit()
        self.title_display.setReadOnly(True)
        self.title_display.setPlaceholderText("Click 'Fetch Info' to resolve target details...")
        title_layout.addWidget(title_lbl)
        title_layout.addWidget(self.title_display)
        main_layout.addLayout(title_layout)

        # 5. Console Log
        self.console_log = QTextEdit()
        self.console_log.setReadOnly(True)
        main_layout.addWidget(self.console_log)

        # 6. Progress
        self.status_label = QLabel("Status: Idle")
        main_layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        main_layout.addWidget(self.progress_bar)

        # 7. Action Buttons
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
            QComboBox, QCheckBox { background-color: #1E1E1E; color: white; border: 1px solid #333; padding: 6px; border-radius: 4px; }
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
        selected_dir = QFileDialog.getExistingDirectory(self, "Select Save Directory", self.save_input.text())
        if selected_dir:
            self.save_input.setText(os.path.normpath(selected_dir))

    def fetch_link_details(self):
        url = self.url_input.text().strip()
        if not url: 
            return

        self.title_display.setText("Resolving link properties... please wait...")
        self.fetch_btn.setEnabled(False)

        self.info_thread = InfoWorker(url)
        self.info_thread.info_fetched.connect(self.on_info_success)
        self.info_thread.error_signal.connect(self.on_info_failure)
        self.info_thread.start()

    @Slot(dict)
    def on_info_success(self, data):
        self.title_display.setText(data['title'])
        self.current_folder_name = data.get('folder_name', 'Unknown')
        self.current_is_playlist = data.get('is_playlist', False)
        self.current_total_items = data.get('total_items', 1)
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
        
        if not target_url or not output_dir: 
            self.console_log.append("Error: URL or save location is missing.")
            return

        modes = ["both", "video_only", "audio_only"]
        selected_mode = modes[self.type_combo.currentIndex()]

        resolutions = ["best", "2160", "1080", "720", "480", "360"]
        selected_res = resolutions[self.res_combo.currentIndex()]

        folder_name = getattr(self, 'current_folder_name', 'Unknown_Download')
        download_subs = self.subs_check.isChecked()

        self.console_log.clear()
        self.console_log.append(f"Starting execution [Mode: {selected_mode.upper()} | Res Limit: {selected_res}]...")
        if self.current_total_items > 1:
            self.console_log.append(f"Playlist mode: {self.current_total_items} items")
        self.console_log.append(f"Target folder: {folder_name}")
        self.console_log.append(f"Saving files to: {output_dir}\n")

        self.thread = DownloadThread(
            target_url, selected_mode, selected_res, 
            output_dir, folder_name, download_subs, 
            self.current_total_items
        )
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
            self.thread.wait(5000)
            self.download_finished(False, "Execution halted by user.")
            self.console_log.append("Download stopped by user.")

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
        if success:
            self.console_log.append("✅ All downloads completed!")
        else:
            self.console_log.append("❌ Download process ended with issues.")


if __name__ == "__main__":
    try:
        app = QApplication(sys.argv)
        window = ProDLWindow()
        window.show()
        sys.exit(app.exec())
    except Exception as e:
        print(f"Application startup error: {e}")
        import traceback
        traceback.print_exc()
