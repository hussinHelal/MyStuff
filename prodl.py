import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
import yt_dlp
import threading
import os
import json
from datetime import datetime
import sys

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

class ProDLApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("ProDL - Professional Video Downloader")
        self.geometry("1000x720")
        self.minsize(900, 680)

        self.downloading = False
        self.current_process = None
        self.output_folder = os.path.expanduser("~/Downloads/ProDL")
        os.makedirs(self.output_folder, exist_ok=True)

        self.history = []
        self.load_history()

        self.create_widgets()

    def create_widgets(self):
        # Header
        header = ctk.CTkFrame(self, height=80, fg_color="#1f1f1f")
        header.pack(fill="x", padx=20, pady=(20,10))
        header.pack_propagate(False)

        ctk.CTkLabel(header, text="ProDL", font=ctk.CTkFont(size=32, weight="bold")).pack(side="left", padx=20)
        ctk.CTkLabel(header, text="Universal Downloader", font=ctk.CTkFont(size=14), text_color="gray").pack(side="left", pady=8)

        # URL Section
        url_frame = ctk.CTkFrame(self)
        url_frame.pack(fill="x", padx=20, pady=10)

        ctk.CTkLabel(url_frame, text="Video / Playlist URL", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=20, pady=(15,5))

        self.url_entry = ctk.CTkEntry(url_frame, height=50, placeholder_text="Paste YouTube, TikTok, Instagram, Twitter, or any supported link...")
        self.url_entry.pack(fill="x", padx=20, pady=(0,15))

        analyze_btn = ctk.CTkButton(url_frame, text="Analyze Link", height=45, font=ctk.CTkFont(size=15, weight="bold"),
                                   command=self.analyze_url)
        analyze_btn.pack(pady=10, padx=20, fill="x")

        # Main Content Frame
        self.main_frame = ctk.CTkScrollableFrame(self)
        self.main_frame.pack(fill="both", expand=True, padx=20, pady=10)

        # Formats Frame (will be populated dynamically)
        self.formats_frame = ctk.CTkFrame(self.main_frame)
        self.formats_frame.pack(fill="x", padx=10, pady=10)

        # Download Controls
        self.control_frame = ctk.CTkFrame(self, height=220)
        self.control_frame.pack(fill="x", padx=20, pady=10)
        self.control_frame.pack_propagate(False)

        self.create_control_widgets()

    def create_control_widgets(self):
        # Type Selection
        type_frame = ctk.CTkFrame(self.control_frame)
        type_frame.pack(fill="x", padx=20, pady=15)

        ctk.CTkLabel(type_frame, text="Download Type:", font=ctk.CTkFont(size=14)).pack(anchor="w")

        self.type_var = ctk.StringVar(value="video_audio")
        ctk.CTkRadioButton(type_frame, text="🎥 Video + Audio (Best)", variable=self.type_var, value="video_audio").pack(anchor="w", padx=20)
        ctk.CTkRadioButton(type_frame, text="🎞️ Video Only", variable=self.type_var, value="video").pack(anchor="w", padx=20)
        ctk.CTkRadioButton(type_frame, text="🎵 Audio Only (MP3)", variable=self.type_var, value="audio").pack(anchor="w", padx=20)

        # Folder
        folder_frame = ctk.CTkFrame(self.control_frame)
        folder_frame.pack(fill="x", padx=20, pady=10)

        ctk.CTkLabel(folder_frame, text="Save To:").pack(anchor="w")
        self.folder_label = ctk.CTkLabel(folder_frame, text=self.output_folder, text_color="lightblue")
        self.folder_label.pack(anchor="w", padx=10)

        ctk.CTkButton(folder_frame, text="Change Folder", width=150, command=self.change_folder).pack(anchor="w", padx=10, pady=5)

    def change_folder(self):
        folder = filedialog.askdirectory(initialdir=self.output_folder)
        if folder:
            self.output_folder = folder
            self.folder_label.configure(text=folder)

    def analyze_url(self):
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showerror("Error", "Please enter a URL")
            return

        for widget in self.formats_frame.winfo_children():
            widget.destroy()

        ctk.CTkLabel(self.formats_frame, text="Analyzing...", font=ctk.CTkFont(size=16)).pack(pady=30)

        threading.Thread(target=self.fetch_formats_thread, args=(url,), daemon=True).start()

    def fetch_formats_thread(self, url):
        try:
            with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl:
                info = ydl.extract_info(url, download=False)

            self.after(0, lambda: self.show_formats(info, url))
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Error", f"Failed to analyze link:\n{str(e)}"))

    def show_formats(self, info, url):
        for widget in self.formats_frame.winfo_children():
            widget.destroy()

        title = info.get('title', 'Unknown Title')
        ctk.CTkLabel(self.formats_frame, text=f"Title: {title}", font=ctk.CTkFont(size=16, weight="bold"), wraplength=900).pack(anchor="w", padx=20, pady=10)

        # Best options
        best_frame = ctk.CTkFrame(self.formats_frame)
        best_frame.pack(fill="x", padx=20, pady=10)

        ctk.CTkButton(best_frame, text="⬇️ Best Video + Audio", fg_color="green", hover_color="darkgreen",
                     command=lambda: self.start_download(url, "best")).pack(side="left", padx=10, pady=10, expand=True, fill="x")

        ctk.CTkButton(best_frame, text="🎵 Best Audio (MP3)", fg_color="purple", hover_color="#6b21a8",
                     command=lambda: self.start_download(url, "bestaudio")).pack(side="left", padx=10, pady=10, expand=True, fill="x")

    def start_download(self, url, format_type="best"):
        if self.downloading:
            messagebox.showwarning("Busy", "Already downloading...")
            return

        self.downloading = True
        threading.Thread(target=self.download_thread, args=(url, format_type), daemon=True).start()

    def download_thread(self, url, format_type):
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            ydl_opts = {
                'outtmpl': os.path.join(self.output_folder, '%(title)s_%(id)s.%(ext)s'),
                'progress_hooks': [self.progress_hook],
                'quiet': False,
                'no_warnings': False,
            }

            if format_type == "bestaudio":
                ydl_opts['format'] = 'bestaudio/best'
                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }]
            elif format_type == "best":
                ydl_opts['format'] = 'bestvideo+bestaudio/best'

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                self.current_process = ydl
                info = ydl.extract_info(url, download=True)

            self.after(0, lambda: self.download_complete(info))

        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Download Failed", str(e)))
        finally:
            self.downloading = False
            self.current_process = None

    def progress_hook(self, d):
        if d['status'] == 'downloading':
            try:
                percent = d.get('_percent_str', '0%').strip()
                speed = d.get('_speed_str', 'N/A')
                eta = d.get('_eta_str', 'N/A')
                self.after(0, lambda: self.update_progress(percent, speed, eta))
            except:
                pass

    def update_progress(self, percent, speed, eta):
        # You can add a progress bar in control_frame if you want more advanced UI
        print(f"Progress: {percent} | Speed: {speed} | ETA: {eta}")

    def download_complete(self, info):
        title = info.get('title', 'Download')
        messagebox.showinfo("Success", f"✅ Download completed!\n\n{title}")
        self.add_to_history(title, self.url_entry.get())

    def add_to_history(self, title, url):
        self.history.append({
            "title": title,
            "url": url,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M")
        })
        self.save_history()

    def load_history(self):
        try:
            if os.path.exists("history.json"):
                with open("history.json", "r") as f:
                    self.history = json.load(f)
        except:
            self.history = []

    def save_history(self):
        try:
            with open("history.json", "w") as f:
                json.dump(self.history[-50:], f)  # Keep last 50
        except:
            pass


if __name__ == "__main__":
    app = ProDLApp()
    app.mainloop()
