import tkinter as tk
from tkinter import ttk, messagebox
import yt_dlp
import os
import threading

class YouTubeDownloader:
    def __init__(self, root):
        self.root = root
        self.root.title("YouTube Downloader")
        self.root.geometry("600x400")

        # URL Label and Entry
        self.url_label = ttk.Label(root, text="YouTube URL (Video or Playlist):")
        self.url_label.pack(pady=10)

        self.url_entry = ttk.Entry(root, width=60)
        self.url_entry.pack(pady=5)

        # Download Type Selection
        self.type_label = ttk.Label(root, text="Download Type:")
        self.type_label.pack(pady=10)

        self.type_var = tk.StringVar(value="both")
        self.type_frame = ttk.Frame(root)
        self.type_frame.pack(pady=5)

        ttk.Radiobutton(self.type_frame, text="Audio Only", variable=self.type_var, value="audio").pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(self.type_frame, text="Video Only", variable=self.type_var, value="video").pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(self.type_frame, text="Both", variable=self.type_var, value="both").pack(side=tk.LEFT, padx=5)

        # Quality Selection
        self.quality_label = ttk.Label(root, text="Select Quality:")
        self.quality_label.pack(pady=10)

        self.quality_var = tk.StringVar()
        self.quality_combo = ttk.Combobox(root, textvariable=self.quality_var, state="readonly", width=40)
        self.quality_combo.pack(pady=5)

        # Progress Bar
        self.progress = ttk.Progressbar(root, length=400, mode='determinate')
        self.progress.pack(pady=10)

        # Buttons
        self.button_frame = ttk.Frame(root)
        self.button_frame.pack(pady=10)

        self.load_button = ttk.Button(self.button_frame, text="Load Info", command=self.load_video)
        self.load_button.pack(side=tk.LEFT, padx=5)

        self.download_button = ttk.Button(self.button_frame, text="Download", command=self.start_download)
        self.download_button.pack(side=tk.LEFT, padx=5)

        # Status Label
        self.status_label = ttk.Label(root, text="")
        self.status_label.pack(pady=10)

        self.video_info = None
        self.downloading = False
        self.is_playlist = False
        self.total_videos = 0
        self.current_video = 0

    def progress_hook(self, d):
        if d['status'] == 'downloading':
            if 'total_bytes' in d and d['total_bytes']:
                percent = (d['downloaded_bytes'] / d['total_bytes']) * 100
                if self.is_playlist:
                    overall_progress = ((self.current_video - 1) / self.total_videos + percent / (100 * self.total_videos)) * 100
                    self.progress['value'] = overall_progress
                    self.status_label.config(text=f"Downloading video {self.current_video}/{self.total_videos}: {percent:.1f}%")
                else:
                    self.progress['value'] = percent
                    self.status_label.config(text=f"Downloading: {percent:.1f}%")
                self.root.update()
        elif d['status'] == 'finished':
            if not self.is_playlist:
                self.progress['value'] = 100
                self.status_label.config(text="Download completed!")
                self.downloading = False
                messagebox.showinfo("Success", "Download finished successfully!")

    def load_video(self):
        try:
            url = self.url_entry.get().strip()
            if not url:
                messagebox.showerror("Error", "Please enter a YouTube URL")
                return

            self.status_label.config(text="Loading information...")
            self.root.update()

            ydl_opts = {
                'quiet': True,
                'extract_flat': True,  # For faster playlist processing
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                self.video_info = info

                # Check if it's a playlist
                self.is_playlist = 'entries' in info
                if self.is_playlist:
                    self.total_videos = len(info['entries'])
                    self.status_label.config(text=f"Loaded playlist: {info['title']} ({self.total_videos} videos)")
                else:
                    self.total_videos = 1
                    self.status_label.config(text=f"Loaded video: {info['title']}")

                # Filter formats based on download type
                download_type = self.type_var.get()
                if not self.is_playlist:  # For single video, get detailed format info
                    ydl_opts.pop('extract_flat')
                    self.video_info = ydl.extract_info(url, download=False)
                    if download_type == "audio":
                        formats = [f"{f['format_id']} - {f.get('abr', 'unknown')}kbps (audio)"
                                for f in self.video_info['formats'] if f.get('acodec') != 'none' and f.get('vcodec') == 'none']
                    elif download_type == "video":
                        formats = [f"{f['format_id']} - {f.get('resolution', 'unknown')} ({f.get('fps', 'unknown')}fps)"
                                for f in self.video_info['formats'] if f.get('vcodec') != 'none' and f.get('acodec') == 'none']
                    else:  # both
                        video_heights = set()
                        for f in self.video_info['formats']:
                            if f.get('vcodec') != 'none' and f.get('height'):
                                video_heights.add(f['height'])
                        formats = [f"res:{height}p" for height in sorted(video_heights, reverse=True)] or ["best"]
                else:  # For playlists, use simplified quality options
                    if download_type == "audio":
                        formats = ["best audio"]
                    elif download_type == "video":
                        formats = ["best video"]
                    else:
                        formats = ["360p", "480p", "720p", "1080p", "best"]

                if not formats:
                    messagebox.showerror("Error", "No suitable formats found for selected type")
                    return

                self.quality_combo['values'] = formats
                self.quality_combo.set(formats[0])

        except Exception as e:
            messagebox.showerror("Error", f"Failed to load: {str(e)}")
            self.status_label.config(text="")

    def start_download(self):
        if not self.video_info:
            messagebox.showerror("Error", "Please load a video/playlist first")
            return

        if self.downloading:
            messagebox.showwarning("Warning", "Download already in progress")
            return

        quality = self.quality_var.get()
        if not quality:
            messagebox.showerror("Error", "Please select a quality")
            return

        self.downloading = True
        self.progress['value'] = 0
        self.current_video = 0
        threading.Thread(target=self.download_content, args=(quality,), daemon=True).start()

    def download_content(self, quality):
        try:
            download_type = self.type_var.get()
            url = self.url_entry.get()

            ydl_opts = {
                'outtmpl': '%(playlist_title)s/%(title)s.%(ext)s' if self.is_playlist else '%(title)s.%(ext)s',
                'progress_hooks': [self.progress_hook],
            }

            if download_type == "audio":
                if not self.is_playlist:
                    format_id = quality.split(" - ")[0]
                    ydl_opts['format'] = f"{format_id}/bestaudio"
                else:
                    ydl_opts['format'] = "bestaudio"
                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }]
            elif download_type == "video":
                if not self.is_playlist:
                    format_id = quality.split(" - ")[0]
                    ydl_opts['format'] = f"{format_id}/bestvideo"
                else:
                    ydl_opts['format'] = "bestvideo"
            else:  # both
                if self.is_playlist and quality != "best":
                    height = quality.replace("p", "")
                    ydl_opts['format'] = f"bestvideo[height<={height}]+bestaudio/best"
                elif not self.is_playlist and quality != "best":
                    height = quality.split(":")[1].replace("p", "")
                    ydl_opts['format'] = f"bestvideo[height={height}]+bestaudio/best"
                else:
                    ydl_opts['format'] = "bestvideo+bestaudio/best"
                ydl_opts['merge_output_format'] = 'mp4'

            # Create playlist directory if needed
            if self.is_playlist:
                os.makedirs(self.video_info['title'], exist_ok=True)

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                if self.is_playlist:
                    for i, entry in enumerate(self.video_info['entries'], 1):
                        self.current_video = i
                        ydl.download([entry['url']])
                    self.downloading = False
                    self.progress['value'] = 100
                    self.status_label.config(text="Playlist download completed!")
                    messagebox.showinfo("Success", "Playlist download finished successfully!")
                else:
                    ydl.download([url])

        except Exception as e:
            self.downloading = False
            messagebox.showerror("Error", f"Download failed: {str(e)}")
            self.status_label.config(text="Download failed")
            self.progress['value'] = 0

def main():
    root = tk.Tk()
    app = YouTubeDownloader(root)
    root.mainloop()

if __name__ == "__main__":
    main()
