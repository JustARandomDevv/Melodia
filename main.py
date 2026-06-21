import os
import random
from types import ModuleType
import threading
import urllib.request
from io import BytesIO
import time
from tkinter import messagebox
import asyncio
import json

import customtkinter as ctk
from PIL import Image, ImageTk, ImageDraw
from ytmusicapi import YTMusic
import pygame
import yt_dlp
from mutagen.mp3 import MP3

try:
    import keyboard
    HAS_KEYBOARD = True
except ImportError:
    HAS_KEYBOARD = False

try:
    import pystray
    from pystray import MenuItem as item
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False

try:
    from pypresence import Presence
    HAS_DISCORD = True
    print("Discord Rich Presence features enabled.")
except ImportError:
    HAS_DISCORD = False

DISCORD_APP_CLIENT_ID = "1508167962547458268"

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("green") 

class MelodiaApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Melodia")
        self.geometry("1100x750")
        self.minsize(950, 650)
        
        # Core State Tracking System
        self.yt_api = YTMusic()
        pygame.mixer.init()
        
        # State Management Anchors
        self.current_position = 0.0     
        self.last_update_time = time.time()
        self.track_duration = 0  
        self.is_playing = False
        self.is_paused = False
        self.is_scrubbing = False    
        self.is_switching_track = False  
        
        self.download_dir = os.path.join(os.path.expanduser("~"), "Music", "MelodiaDownloads")
        os.makedirs(self.download_dir, exist_ok=True)
        
        # User Data Storage
        self.settings_file = os.path.join(self.download_dir, "settings.json")
        self.playlists_file = os.path.join(self.download_dir, "playlists.json")
        self.favorites_file = os.path.join(self.download_dir, "favorites.json")
        
        self.settings = {"run_in_background": True, "auto_play": True}
        self.playlists = {}
        self.favorites = []
        self._load_user_data()
        
        self.queue = []
        self.current_queue_idx = -1
        self.current_frame_name = "home"
        
        # Infinite Scroll State
        self.rec_is_loading = False
        self.discover_cards_count = 0
        
        # Background Discord Integration Initialization
        self.rpc = None
        self.discord_connected = False
        if HAS_DISCORD:
            threading.Thread(target=self._init_discord_rpc, daemon=True).start()
        
        self._build_ui()
        self._init_system_tray()
        self._init_media_keys()
        
        self.refresh_local_library()
        self._load_recommendations()
        
        # Start the master monitor loops
        self._playback_monitor_loop()
        self._poll_infinite_scroll()

    def _load_user_data(self):
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, "r") as f: self.settings.update(json.load(f))
            if os.path.exists(self.playlists_file):
                with open(self.playlists_file, "r") as f: self.playlists = json.load(f)
            if os.path.exists(self.favorites_file):
                with open(self.favorites_file, "r") as f: self.favorites = json.load(f)
        except Exception as e:
            print("Error loading data:", e)

    def _save_user_data(self, *args):
        try:
            if hasattr(self, 'bg_var'):
                self.settings["run_in_background"] = self.bg_var.get()
                self.settings["auto_play"] = self.ap_var.get()
            with open(self.settings_file, "w") as f: json.dump(self.settings, f)
            with open(self.playlists_file, "w") as f: json.dump(self.playlists, f)
            with open(self.favorites_file, "w") as f: json.dump(self.favorites, f)
        except Exception as e:
            print("Error saving data:", e)

    def _load_image_to_label(self, source, label_widget, size=(120, 120)):
        """Downloads/Loads image asynchronously and binds it to prevent Tkinter garbage collection."""
        try:
            if source.startswith("http"):
                req = urllib.request.Request(source, headers={'User-Agent': 'Mozilla/5.0'})
                raw_data = urllib.request.urlopen(req, timeout=5).read()
                img = Image.open(BytesIO(raw_data)).convert("RGB")
            else:
                img = Image.open(source).convert("RGB")
                
            img = img.resize(size, Image.Resampling.LANCZOS)
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=size)
            
            def apply_img():
                try:
                    label_widget.configure(image=ctk_img, text="")
                    label_widget.image = ctk_img  
                except: pass
                
            self.after(0, apply_img)
        except Exception as e: 
            print(f"Failed to load image: {e}")

    def _add_hover_effect(self, widget, normal_color, hover_color):
        widget.configure(fg_color=normal_color)
        def on_enter(e): widget.configure(fg_color=hover_color)
        def on_leave(e): widget.configure(fg_color=normal_color)
        widget.bind("<Enter>", on_enter)
        widget.bind("<Leave>", on_leave)
        for child in widget.winfo_children():
            try:
                child.bind("<Enter>", on_enter)
                child.bind("<Leave>", on_leave)
            except: pass

    def _build_ui(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        
        # SIDEBAR PANEL
        self.sidebar = ctk.CTkFrame(self, width=220, corner_radius=0, fg_color="#121212")
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        ctk.CTkLabel(self.sidebar, text="🎵 Melodia", font=("Arial", 24, "bold"), text_color="#1DB954").pack(pady=(30, 20), padx=20, anchor="w")
        
        self._sidebar_btn("🏠 Discover", lambda: self._show_frame("home"))
        self._sidebar_btn("🔍 Search Cloud", lambda: self._show_frame("search"))
        self._sidebar_btn("📚 Local Library", lambda: self._show_frame("library"))
        self._sidebar_btn("🗂️ Playlists", lambda: self._show_frame("playlists"))
        self._sidebar_btn("📋 Playlist Queue", lambda: self._show_frame("playlist"))
        self._sidebar_btn("🎤 Lyrics", lambda: self._show_frame("lyrics"))
        self._sidebar_btn("⚙ Settings", lambda: self._show_frame("settings"))

        # APPLICATION CENTRAL CONTAINER
        self.main_container = ctk.CTkFrame(self, corner_radius=0, fg_color="#181818")
        self.main_container.grid(row=0, column=1, sticky="nsew")
        self.main_container.grid_rowconfigure(0, weight=1)
        self.main_container.grid_columnconfigure(0, weight=1)
        
        self.frames = {}
        self._build_home_frame()
        self._build_search_frame()
        self._build_library_frame()
        self._build_playlists_tab()
        self._build_playlist_frame() 
        self._build_lyrics_frame()
        self._build_settings_frame()
        self._show_frame("home")

        # MEDIA CONTROLLER FOOTER
        self.player_bar = ctk.CTkFrame(self, height=110, corner_radius=0, fg_color="#000000")
        self.player_bar.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.player_bar.grid_columnconfigure(1, weight=1)
        self.player_bar.grid_propagate(False)
        
        self.player_art_lbl = ctk.CTkLabel(self.player_bar, text="", width=60, height=60, fg_color="#282828")
        self.player_art_lbl.grid(row=0, column=0, rowspan=2, padx=15, pady=15)
        
        info_frame = ctk.CTkFrame(self.player_bar, fg_color="transparent")
        info_frame.grid(row=0, column=1, rowspan=2, sticky="w")
        self.player_title = ctk.CTkLabel(info_frame, text="No track playing", font=("Arial", 14, "bold"), text_color="white")
        self.player_title.pack(anchor="w")
        self.player_artist = ctk.CTkLabel(info_frame, text="-", font=("Arial", 11), text_color="#B3B3B3")
        self.player_artist.pack(anchor="w")
        
        center_controls = ctk.CTkFrame(self.player_bar, fg_color="transparent")
        center_controls.grid(row=0, column=2, padx=20, pady=(10, 0), sticky="n")
        
        ctk.CTkButton(center_controls, text="⏮", width=40, height=35, fg_color="transparent", hover_color="#333", font=("Arial", 18), command=self.play_prev).pack(side="left", padx=5)
        self.btn_play_pause = ctk.CTkButton(center_controls, text="▶", width=44, height=44, corner_radius=22, fg_color="white", text_color="black", hover_color="#ccc", font=("Arial", 18), command=self.toggle_pause)
        self.btn_play_pause.pack(side="left", padx=10)
        ctk.CTkButton(center_controls, text="⏭", width=40, height=35, fg_color="transparent", hover_color="#333", font=("Arial", 18), command=self.play_next).pack(side="left", padx=5)
        
        timeline_frame = ctk.CTkFrame(self.player_bar, fg_color="transparent")
        timeline_frame.grid(row=1, column=2, padx=20, pady=(0, 10), sticky="ew")
        
        self.lbl_time_current = ctk.CTkLabel(timeline_frame, text="0:00", font=("Arial", 11), text_color="#B3B3B3", width=35)
        self.lbl_time_current.pack(side="left")
        
        self.slider_progress = ctk.CTkSlider(timeline_frame, from_=0, to=100, width=450, button_color="white", button_hover_color="#1ED760", progress_color="#1DB954", fg_color="#3E3E3E")
        self.slider_progress.set(0)
        self.slider_progress.pack(side="left", padx=8)
        
        self.slider_progress.bind("<ButtonPress-1>", self._on_slider_press)
        self.slider_progress.bind("<ButtonRelease-1>", self._on_slider_release)
        
        self.lbl_time_total = ctk.CTkLabel(timeline_frame, text="0:00", font=("Arial", 11), text_color="#B3B3B3", width=35)
        self.lbl_time_total.pack(side="left")
        
        vol_frame = ctk.CTkFrame(self.player_bar, fg_color="transparent")
        vol_frame.grid(row=0, column=3, rowspan=2, padx=20, sticky="e")
        ctk.CTkLabel(vol_frame, text="🔈", font=("Arial", 14)).pack(side="left")
        self.vol_slider = ctk.CTkSlider(vol_frame, from_=0.0, to=1.0, width=90, button_color="white", progress_color="#1DB954", command=lambda v: pygame.mixer.music.set_volume(float(v)))
        self.vol_slider.set(1.0)
        self.vol_slider.pack(side="left", padx=8)

    def _sidebar_btn(self, text, command):
        btn = ctk.CTkButton(self.sidebar, text=text, fg_color="transparent", hover_color="#282828", text_color="#B3B3B3", font=("Arial", 14, "bold"), anchor="w", command=command)
        btn.pack(fill="x", padx=10, pady=5)

    def _show_frame(self, name):
        self.current_frame_name = name
        for f in self.frames.values(): f.grid_remove()
        self.frames[name].grid(row=0, column=0, sticky="nsew")
        if name == "playlist":
            self._refresh_playlist_ui()
        elif name == "playlists":
            self._refresh_playlists_ui()
        elif name == "library":
            self.refresh_local_library()

    def _format_time(self, seconds):
        if seconds is None or seconds < 0: seconds = 0
        mins = int(seconds) // 60
        secs = int(seconds) % 60
        return f"{mins}:{secs:02d}"

    def _on_slider_press(self, event):
        self.is_scrubbing = True

    def _on_slider_release(self, event):
        if self.is_playing:
            target_seconds = self.slider_progress.get()
            if target_seconds >= self.track_duration:
                self.is_scrubbing = False
                self._trigger_track_advance()
                return

            current_track = self.queue[self.current_queue_idx]
            pygame.mixer.music.stop()
            pygame.mixer.music.load(current_track['path'])
            pygame.mixer.music.play(start=float(target_seconds))
            
            if self.is_paused:
                pygame.mixer.music.pause()
                
            self.current_position = target_seconds
            self.last_update_time = time.time()
            self.lbl_time_current.configure(text=self._format_time(self.current_position))
        self.is_scrubbing = False

    def _playback_monitor_loop(self):
        if self.is_playing and not self.is_paused and not self.is_scrubbing and not self.is_switching_track:
            if pygame.mixer.music.get_busy():
                now = time.time()
                delta = now - self.last_update_time
                self.last_update_time = now
                self.current_position += delta
                
                if self.current_position >= self.track_duration and self.track_duration > 0:
                    self._trigger_track_advance()
                else:
                    self.slider_progress.set(self.current_position)
                    self.lbl_time_current.configure(text=self._format_time(self.current_position))
            else:
                if self.current_position > 1.0:
                    self._trigger_track_advance()
        else:
            self.last_update_time = time.time() 

        self.after(200, self._playback_monitor_loop)

    def _trigger_track_advance(self):
        self.is_switching_track = True
        pygame.mixer.music.stop()
        pygame.mixer.music.unload()
        
        self.current_position = 0.0
        self.slider_progress.set(0.0)
        self.lbl_time_current.configure(text="0:00")
        
        if not self.queue or self.current_queue_idx >= len(self.queue) - 1:
            if self.settings.get("auto_play", True):
                files = [f for f in os.listdir(self.download_dir) if f.endswith(".mp3")]
                if files:
                    random_file = random.choice(files)
                    full_path = os.path.join(self.download_dir, random_file)
                    parts = random_file.replace(".mp3", "").split("-")
                    artist = parts[1].strip() if len(parts) > 1 else "Unknown"
                    title = parts[0].strip()
                    track_data = {'title': title, 'artist': artist, 'path': full_path, 'img_url': None, 'video_id': None}
                    self.queue_and_play(track_data)
                    return
            
            self.stop_music()
            self.is_switching_track = False
            return
            
        self.play_next()

    def play_track(self, track_data):
        self.is_switching_track = True
        try:
            pygame.mixer.music.unload()
            try:
                audio = MP3(track_data['path'])
                self.track_duration = audio.info.length
            except Exception:
                self.track_duration = 180  
                
            self.current_position = 0.0
            self.last_update_time = time.time()
            
            self.slider_progress.configure(to=max(self.track_duration, 1.0))
            self.slider_progress.set(0.0)
            self.lbl_time_total.configure(text=self._format_time(self.track_duration))
            self.lbl_time_current.configure(text="0:00")
            
            pygame.mixer.music.load(track_data['path'])
            pygame.mixer.music.play()

            self.is_playing = True
            self.is_paused = False
            self.btn_play_pause.configure(text="⏸")
            
            self.player_title.configure(text=track_data['title'])
            self.player_artist.configure(text=track_data['artist'])
            
            self._load_album_art(track_data)
            self._fetch_lyrics(track_data)
            self._update_discord_status()
            self._refresh_playlist_ui()
        except Exception as e:
            print(f"Playback initiation issue: {e}")
        finally:
            self.is_switching_track = False

    def queue_and_play(self, track_data):
        self.queue = [track_data]
        self.current_queue_idx = 0
        self.play_track(track_data)

    def add_to_queue(self, track_data):
        self.queue.append(track_data)
        self._refresh_playlist_ui()
        
    def play_next(self):
        if not self.queue or self.current_queue_idx >= len(self.queue) - 1:
            self.stop_music()
            return
        self.current_queue_idx += 1
        self.play_track(self.queue[self.current_queue_idx])

    def play_prev(self):
        if not self.queue or self.current_queue_idx <= 0:
            if self.queue: self.play_track(self.queue[self.current_queue_idx])
            return
        self.current_queue_idx -= 1
        self.play_track(self.queue[self.current_queue_idx])

    def toggle_pause(self):
        if not self.is_playing: return
        if self.is_paused:
            pygame.mixer.music.unpause()
            self.last_update_time = time.time() 
            self.btn_play_pause.configure(text="⏸")
        else:
            pygame.mixer.music.pause()
            self.btn_play_pause.configure(text="▶")
        self.is_paused = not self.is_paused
        self._update_discord_status()

    def stop_music(self):
        pygame.mixer.music.stop()
        self.is_playing = False
        self.is_paused = False
        self.btn_play_pause.configure(text="▶")
        self.player_title.configure(text="No track playing")
        self.player_artist.configure(text="-")
        self.player_art_lbl.configure(image=None)
        self.slider_progress.set(0)
        self.current_position = 0.0
        self.lbl_time_current.configure(text="0:00")
        self.lbl_time_total.configure(text="0:00")
        self._update_discord_status()
        self._refresh_playlist_ui()

    def delete_local_track(self, mp3_path):
        track_name = os.path.basename(mp3_path).replace(".mp3", "")
        confirm = messagebox.askyesno(title="Confirm Storage Deletion", message=f"Are you sure you want to permanently delete:\n'{track_name}'?", parent=self)
        if not confirm: return
        try:
            if self.is_playing and self.current_queue_idx != -1:
                active_track = self.queue[self.current_queue_idx]
                if os.path.normpath(active_track['path']) == os.path.normpath(mp3_path):
                    self.stop_music()
            pygame.mixer.music.unload()
            if os.path.exists(mp3_path): os.remove(mp3_path)
            jpg_path = os.path.splitext(mp3_path)[0] + ".jpg"
            if os.path.exists(jpg_path): os.remove(jpg_path)
            
            filename = os.path.basename(mp3_path)
            if filename in self.favorites:
                self.favorites.remove(filename)
                self._save_user_data()
        except Exception as e: print(f"Storage clearance issue: {e}")
        self.refresh_local_library()

    def _init_discord_rpc(self):
        if not HAS_DISCORD: return
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self.rpc = Presence(DISCORD_APP_CLIENT_ID)
            self.rpc.connect()
            self.discord_connected = True
        except Exception as e:
            print(f"Discord RPC Error: {e}")
            self.discord_connected = False

    def _update_discord_status(self):
        if not getattr(self, 'discord_connected', False) or not self.rpc: return
        try:
            if not self.queue or self.current_queue_idx < 0:
                self.rpc.clear()
                return
            track = self.queue[self.current_queue_idx]
            details_str = track['title'][:127]
            state_str = f"by {track['artist']}"[:127]
            if self.is_playing and not self.is_paused:
                self.rpc.update(details=details_str, state=state_str, start=int(time.time() - self.current_position), large_image="logo", large_text="Melodia Streaming")
            elif self.is_paused:
                self.rpc.update(details=f"Paused: {details_str}"[:127], state=state_str, large_image="logo")
            else:
                self.rpc.clear()
        except Exception as e: print(f"Discord update fail: {e}")

    # --- UI CONTAINER DESIGN BLOCKS ---
    def _build_home_frame(self):
        frame = ctk.CTkScrollableFrame(self.main_container, fg_color="transparent")
        self.frames["home"] = frame
        ctk.CTkLabel(frame, text="Discover", font=("Arial", 28, "bold")).pack(anchor="w", padx=20, pady=20)
        self.rec_container = ctk.CTkFrame(frame, fg_color="transparent")
        self.rec_container.pack(fill="both", expand=True, padx=20)
        self.rec_loading = ctk.CTkProgressBar(frame, mode="indeterminate", width=200, progress_color="#1DB954")
        
        self.rec_grid = ctk.CTkFrame(self.rec_container, fg_color="transparent")
        self.rec_grid.pack(fill="x")
        for i in range(3): self.rec_grid.grid_columnconfigure(i, weight=1)

    def _poll_infinite_scroll(self):
        if getattr(self, "current_frame_name", "") == "home":
            try:
                yview = self.frames["home"]._parent_canvas.yview()
                if yview and yview[1] >= 0.98:
                    if not self.rec_is_loading:
                        self._load_more_recommendations()
            except: pass
        self.after(500, self._poll_infinite_scroll)

    def _build_search_frame(self):
        frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.frames["search"] = frame
        frame.grid_rowconfigure(1, weight=1)
        frame.grid_columnconfigure(0, weight=1)
        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=20, pady=20)
        self.search_entry = ctk.CTkEntry(top, placeholder_text="What do you want to listen to?", height=45, corner_radius=25, border_width=0, fg_color="#242424", font=("Arial", 14))
        self.search_entry.pack(fill="x", expand=True)
        self.search_entry.bind("<Return>", self.on_search)
        self.search_loading = ctk.CTkProgressBar(frame, mode="indeterminate", height=3, progress_color="#1DB954")
        self.search_scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        self.search_scroll.grid(row=1, column=0, sticky="nsew", padx=10)

    def _build_library_frame(self):
        frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.frames["library"] = frame
        frame.grid_rowconfigure(1, weight=1)
        frame.grid_columnconfigure(0, weight=1)
        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=20, pady=20)
        ctk.CTkLabel(top, text="Your Library", font=("Arial", 28, "bold")).pack(side="left")
        self.lib_search = ctk.CTkEntry(top, placeholder_text="Filter...", height=35, corner_radius=15, border_width=0, fg_color="#242424")
        self.lib_search.pack(side="right")
        self.lib_search.bind("<KeyRelease>", lambda e: self.refresh_local_library(self.lib_search.get()))
        self.lib_scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        self.lib_scroll.grid(row=1, column=0, sticky="nsew", padx=10)
        for i in range(4): self.lib_scroll.grid_columnconfigure(i, weight=1, uniform="lib_col")

    def _build_playlists_tab(self):
        frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.frames["playlists"] = frame
        frame.grid_rowconfigure(1, weight=1)
        frame.grid_columnconfigure(0, weight=1)
        
        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=20, pady=20)
        ctk.CTkLabel(top, text="Playlists", font=("Arial", 28, "bold")).pack(side="left")
        
        ctk.CTkButton(top, text="+ Create Playlist", width=140, height=35, fg_color="#1DB954", hover_color="#1ED760", text_color="black", command=self._open_create_playlist_dialog).pack(side="right")
        
        self.playlists_scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        self.playlists_scroll.grid(row=1, column=0, sticky="nsew", padx=10)

    def _open_create_playlist_dialog(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Create Playlist")
        dialog.geometry("450x550")
        dialog.transient(self)
        dialog.grab_set()
        
        ctk.CTkLabel(dialog, text="Playlist Name:", font=("Arial", 16, "bold")).pack(pady=(20, 5), padx=20, anchor="w")
        name_entry = ctk.CTkEntry(dialog, placeholder_text="Enter name...", height=40)
        name_entry.pack(pady=5, padx=20, fill="x")
        
        ctk.CTkLabel(dialog, text="Select Songs:", font=("Arial", 16, "bold")).pack(pady=(15, 5), padx=20, anchor="w")
        scroll = ctk.CTkScrollableFrame(dialog)
        scroll.pack(fill="both", expand=True, padx=20, pady=5)
        
        checkboxes = {}
        files = [f for f in os.listdir(self.download_dir) if f.endswith(".mp3")]
        for f in files:
            var = ctk.BooleanVar()
            display_name = f.replace(".mp3", "")
            cb = ctk.CTkCheckBox(scroll, text=display_name, variable=var)
            cb.pack(anchor="w", pady=5, padx=5)
            checkboxes[f] = var
            
        def save_playlist():
            p_name = name_entry.get().strip()
            if not p_name: return
            selected = [f for f, var in checkboxes.items() if var.get()]
            self.playlists[p_name] = selected
            self._save_user_data()
            self._refresh_playlists_ui()
            dialog.destroy()
            
        ctk.CTkButton(dialog, text="Save Playlist", fg_color="#1DB954", hover_color="#1ED760", text_color="black", height=40, command=save_playlist).pack(pady=20, padx=20, fill="x")

    def _refresh_playlists_ui(self):
        for w in self.playlists_scroll.winfo_children(): w.destroy()
        
        if not self.playlists:
            ctk.CTkLabel(self.playlists_scroll, text="No playlists created yet.", font=("Arial", 16), text_color="gray").pack(pady=40)
            return
            
        for p_name, files in self.playlists.items():
            row = ctk.CTkFrame(self.playlists_scroll, height=80, fg_color="transparent")
            row.pack(fill="x", pady=10, padx=10)
            row.pack_propagate(False)
            self._add_hover_effect(row, "transparent", "#2A2A2A")
            
            art_lbl = ctk.CTkLabel(row, text="🗂️", width=60, height=60, fg_color="#242424", font=("Arial", 24))
            art_lbl.pack(side="left", padx=10, pady=10)
            
            if files:
                random_file = random.choice(files)
                base_name = os.path.splitext(random_file)[0]
                jpg_path = os.path.join(self.download_dir, f"{base_name}.jpg")
                if os.path.exists(jpg_path):
                    threading.Thread(target=self._load_image_to_label, args=(jpg_path, art_lbl, (60, 60)), daemon=True).start()
            
            info_frame = ctk.CTkFrame(row, fg_color="transparent")
            info_frame.pack(side="left", padx=15, fill="both", expand=True)
            
            title_lbl = ctk.CTkLabel(info_frame, text=p_name, font=("Arial", 18, "bold"), text_color="white", anchor="w")
            title_lbl.pack(fill="x", pady=(10, 0))
            
            # Compute total duration in thread
            dur_lbl = ctk.CTkLabel(info_frame, text=f"{len(files)} tracks  •  Calculating duration...", font=("Arial", 12), text_color="#B3B3B3", anchor="w")
            dur_lbl.pack(fill="x")
            
            def calc_dur(lbl, file_list):
                total = 0
                for f in file_list:
                    p = os.path.join(self.download_dir, f)
                    if os.path.exists(p):
                        try: total += MP3(p).info.length
                        except: pass
                self.after(0, lambda: lbl.configure(text=f"{len(file_list)} tracks  •  {self._format_time(total)}"))
            threading.Thread(target=calc_dur, args=(dur_lbl, files), daemon=True).start()
            
            btn_frame = ctk.CTkFrame(row, fg_color="transparent")
            btn_frame.pack(side="right", padx=10)
            
            ctk.CTkButton(btn_frame, text="▶ Play All", width=100, height=35, fg_color="#1DB954", hover_color="#1ED760", text_color="black", command=lambda n=p_name: self._play_playlist(n)).pack(side="left", padx=5)
            ctk.CTkButton(btn_frame, text="🗑 Delete", width=80, height=35, fg_color="#441a1a", hover_color="#732626", text_color="#ffb3b3", command=lambda n=p_name: self._delete_playlist(n)).pack(side="left", padx=5)

    def _play_playlist(self, p_name):
        files = self.playlists.get(p_name, [])
        if not files: return
        self.stop_music()
        self.queue = []
        for f in files:
            full_path = os.path.join(self.download_dir, f)
            if os.path.exists(full_path):
                parts = f.replace(".mp3", "").split("-")
                artist = parts[1].strip() if len(parts) > 1 else "Unknown"
                title = parts[0].strip()
                self.queue.append({'title': title, 'artist': artist, 'path': full_path, 'img_url': None, 'video_id': None})
        if self.queue:
            self.current_queue_idx = 0
            self._refresh_playlist_ui()
            self.play_track(self.queue[0])

    def _delete_playlist(self, p_name):
        if p_name in self.playlists:
            del self.playlists[p_name]
            self._save_user_data()
            self._refresh_playlists_ui()

    def _build_playlist_frame(self):
        frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.frames["playlist"] = frame
        frame.grid_rowconfigure(1, weight=1)
        frame.grid_columnconfigure(0, weight=1)
        
        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=20, pady=20)
        ctk.CTkLabel(top, text="Current Playlist Queue", font=("Arial", 28, "bold")).pack(side="left")
        
        ctk.CTkButton(top, text="Clear Entire Queue", width=120, height=32, fg_color="#441a1a", hover_color="#732626", text_color="#ffb3b3",
                      command=self._clear_queue_action).pack(side="right")
        
        self.playlist_scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        self.playlist_scroll.grid(row=1, column=0, sticky="nsew", padx=10)

    def _build_settings_frame(self):
        frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.frames["settings"] = frame
        ctk.CTkLabel(frame, text="Settings", font=("Arial", 28, "bold")).pack(anchor="w", padx=20, pady=20)
        
        self.bg_var = ctk.BooleanVar(value=self.settings.get("run_in_background", True))
        bg_switch = ctk.CTkSwitch(frame, text="Run in background when closed", variable=self.bg_var, command=self._save_user_data)
        bg_switch.pack(anchor="w", padx=20, pady=10)
        
        self.ap_var = ctk.BooleanVar(value=self.settings.get("auto_play", True))
        ap_switch = ctk.CTkSwitch(frame, text="Auto-play random library song when queue ends", variable=self.ap_var, command=self._save_user_data)
        ap_switch.pack(anchor="w", padx=20, pady=10)

    def _clear_queue_action(self):
        self.stop_music()
        self.queue = []
        self.current_queue_idx = -1
        self._refresh_playlist_ui()

    def _refresh_playlist_ui(self):
        if not hasattr(self, 'playlist_scroll'): return
        for w in self.playlist_scroll.winfo_children(): w.destroy()
        
        if not self.queue:
            ctk.CTkLabel(self.playlist_scroll, text="No songs currently in your playlist queue.", font=("Arial", 16), text_color="gray").pack(pady=40)
            return
            
        for idx, track in enumerate(self.queue):
            is_current = (idx == self.current_queue_idx)
            
            row = ctk.CTkFrame(self.playlist_scroll, height=55, fg_color="#1f2d22" if is_current else "transparent")
            row.pack(fill="x", pady=4, padx=10)
            row.pack_propagate(False)
            
            if not is_current:
                self._add_hover_effect(row, "transparent", "#2A2A2A")
            
            status_text = "▶ Now" if is_current else f"{idx + 1}"
            status_lbl = ctk.CTkLabel(row, text=status_text, font=("Arial", 12, "bold" if is_current else "normal"), 
                                      text_color="#1DB954" if is_current else "gray", width=60)
            status_lbl.pack(side="left", padx=10)
            
            art_lbl = ctk.CTkLabel(row, text="🎵", width=40, height=40, fg_color="#181818")
            art_lbl.pack(side="left", padx=5, pady=7)
            
            base_name = os.path.splitext(os.path.basename(track['path']))[0]
            local_img = os.path.join(self.download_dir, f"{base_name}.jpg")
            img_src = local_img if os.path.exists(local_img) else track.get('img_url')
            if img_src:
                threading.Thread(target=self._load_image_to_label, args=(img_src, art_lbl, (40, 40)), daemon=True).start()
                
            text_color = "white" if is_current else "#EBEBEB"
            title_lbl = ctk.CTkLabel(row, text=f"{track['title']}  •  {track['artist']}", font=("Arial", 13, "bold" if is_current else "normal"), 
                                     text_color=text_color, anchor="w")
            title_lbl.pack(side="left", padx=15, fill="both", expand=True)
            
            def make_jump_callback(target_idx=idx):
                return lambda e: self._jump_to_queue_index(target_idx)
                
            if not is_current:
                row.bind("<Button-1>", make_jump_callback())
                title_lbl.bind("<Button-1>", make_jump_callback())
                art_lbl.bind("<Button-1>", make_jump_callback())
                
                remove_btn = ctk.CTkButton(row, text="✕", width=30, height=28, fg_color="transparent", hover_color="#333", text_color="gray",
                                           command=lambda target_idx=idx: self._remove_from_queue(target_idx))
                remove_btn.pack(side="right", padx=10, pady=13)

    def _jump_to_queue_index(self, index):
        if 0 <= index < len(self.queue):
            self.current_queue_idx = index
            self.play_track(self.queue[index])

    def _remove_from_queue(self, index):
        if 0 <= index < len(self.queue):
            del self.queue[index]
            if index < self.current_queue_idx:
                self.current_queue_idx -= 1
            self._refresh_playlist_ui()

    def _build_lyrics_frame(self):
        frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.frames["lyrics"] = frame
        frame.grid_rowconfigure(1, weight=1)
        frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(frame, text="Lyrics", font=("Arial", 28, "bold")).grid(row=0, column=0, sticky="w", padx=20, pady=20)
        self.lyric_text = ctk.CTkTextbox(frame, fg_color="transparent", font=("Arial", 16), text_color="#EBEBEB", wrap="word", state="disabled")
        self.lyric_text.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 20))

    def _get_safe_thumb(self, track):
        thumbs = track.get("thumbnails", [])
        if thumbs and isinstance(thumbs, list): return thumbs[-1].get("url")
        if thumbs and isinstance(thumbs, dict): return thumbs.get("url")
        return None

    def _load_recommendations(self):
        self.rec_loading.pack(pady=10)
        self.rec_loading.start()
        self.rec_is_loading = True
        
        def worker():
            try:
                files = [f for f in os.listdir(self.download_dir) if f.endswith(".mp3")]
                track_queries = []
                for f in files:
                    parts = f.replace(".mp3", "").split("-")
                    track_queries.append(" ".join([p.strip() for p in parts]))
                    
                if not track_queries:
                    results = self.yt_api.search("Top Hits Trending", filter="songs", limit=12)
                    self.after(0, lambda: self._render_recommendations(results))
                    return
                    
                seed_query = random.choice(track_queries)
                search_res = self.yt_api.search(seed_query, filter="songs", limit=1)
                if search_res and 'videoId' in search_res[0]:
                    seed_vid = search_res[0]['videoId']
                    watch = self.yt_api.get_watch_playlist(videoId=seed_vid, limit=15)
                    results = watch.get("tracks", [])[1:13]
                    self.after(0, lambda: self._render_recommendations(results))
                else: 
                    self.after(0, self._hide_rec_loading)
            except Exception: self.after(0, self._hide_rec_loading)
        threading.Thread(target=worker, daemon=True).start()

    def _hide_rec_loading(self):
        self.rec_loading.stop()
        self.rec_loading.pack_forget()
        self.rec_is_loading = False

    def _load_more_recommendations(self):
        self.rec_is_loading = True
        def worker():
            try:
                files = [f for f in os.listdir(self.download_dir) if f.endswith(".mp3")]
                if files:
                    seed_query = random.choice(files).replace(".mp3", "").replace("-", " ")
                    search_res = self.yt_api.search(seed_query, filter="songs", limit=1)
                    if search_res and 'videoId' in search_res[0]:
                        seed_vid = search_res[0]['videoId']
                        watch = self.yt_api.get_watch_playlist(videoId=seed_vid, limit=10)
                        results = watch.get("tracks", [])[1:7]
                        self.after(0, lambda: self._append_recommendations(results))
                        return
                results = self.yt_api.search("Trending Music", filter="songs", limit=6)
                self.after(0, lambda: self._append_recommendations(results))
            except Exception:
                self.after(0, lambda: setattr(self, 'rec_is_loading', False))
        threading.Thread(target=worker, daemon=True).start()

    def _render_recommendations(self, results):
        self._hide_rec_loading()
        for w in self.rec_grid.winfo_children(): w.destroy()
        self.discover_cards_count = 0
        self._append_recommendations(results)

    def _append_recommendations(self, results):
        self.rec_is_loading = False
        for track in results:
            self._create_card(self.rec_grid, track, self.discover_cards_count // 3, self.discover_cards_count % 3)
            self.discover_cards_count += 1

    def _create_card(self, parent, track, row, col):
        card = ctk.CTkFrame(parent, width=150, height=200, corner_radius=8)
        card.grid(row=row, column=col, padx=10, pady=10, sticky="new")
        card.grid_propagate(False)
        self._add_hover_effect(card, "#181818", "#282828")
        title = track.get("title", "Unknown")[:30]
        artist = track.get("artists", [{}])[0].get("name", "Unknown")
        vid = track.get("videoId")
        
        # --- UPDATE THIS SECTION TO SUPPORT BOTH PLURAL AND SINGULAR KEYS ---
        thumb_list = track.get("thumbnails") or track.get("thumbnail")
        thumb = thumb_list[-1].get("url") if (isinstance(thumb_list, list) and thumb_list) else None
        # --------------------------------------------------------------------

        img_lbl = ctk.CTkLabel(card, text="🎵", width=120, height=120, fg_color="#282828")
        img_lbl.pack(pady=10)
        
        if thumb: 
            threading.Thread(target=self._load_image_to_label, args=(thumb, img_lbl, (120, 120)), daemon=True).start()
            
        t_lbl = ctk.CTkLabel(card, text=title, font=("Arial", 12, "bold"), text_color="white", anchor="w")
        t_lbl.pack(padx=10, fill="x")
        
        a_lbl = ctk.CTkLabel(card, text=artist, font=("Arial", 11), text_color="#B3B3B3", anchor="w")
        a_lbl.pack(padx=10, fill="x")
        
        play_cmd = lambda e, v=vid, t=title, a=artist, im=thumb: self.handle_cloud_play(v, t, a, im)
        card.bind("<Button-1>", play_cmd)
        img_lbl.bind("<Button-1>", play_cmd)
        t_lbl.bind("<Button-1>", play_cmd)
        a_lbl.bind("<Button-1>", play_cmd)

    def on_search(self, event=None):
        query = self.search_entry.get().strip()
        if not query: return
        for w in self.search_scroll.winfo_children(): w.destroy()
        self.search_loading.grid(row=1, column=0, sticky="ew")
        self.search_loading.start()
        threading.Thread(target=self._search_worker, args=(query,), daemon=True).start()

    def _search_worker(self, query):
        try:
            results = self.yt_api.search(query, filter="songs")[:15]
            self.after(0, self._render_search_results, results)
        except Exception: self.after(0, self.search_loading.grid_remove)

    def _render_search_results(self, results):
        self.search_loading.stop()
        self.search_loading.grid_remove()
        for track in results:
            title = track.get("title", "Unknown")
            artist = track.get("artists", [{}])[0].get("name", "Unknown") if track.get("artists") else "Unknown"
            duration = track.get("duration", "0:00")
            v_id = track.get("videoId", "")
            thumb = self._get_safe_thumb(track)
            
            row = ctk.CTkFrame(self.search_scroll, height=55, fg_color="transparent")
            row.pack(fill="x", pady=4, padx=10)
            row.pack_propagate(False)
            self._add_hover_effect(row, "transparent", "#2A2A2A")
            
            search_art = ctk.CTkLabel(row, text="🎵", width=40, height=40, fg_color="#242424")
            search_art.pack(side="left", padx=10, pady=7)
            
            if thumb: 
                threading.Thread(target=self._load_image_to_label, args=(thumb, search_art, (40, 40)), daemon=True).start()
                
            lbl = ctk.CTkLabel(row, text=f"{title}  •  {artist} ({duration})", font=("Arial", 13), anchor="w")
            lbl.pack(side="left", padx=10, fill="both", expand=True)
            
            btn = ctk.CTkButton(row, text="▶ Play", width=80, height=28, fg_color="#1DB954", hover_color="#1ED760", text_color="black", command=lambda v=v_id, t=title, a=artist, im=thumb: self.handle_cloud_play(v, t, a, im))
            btn.pack(side="right", padx=10, pady=13)

    def toggle_favorite(self, filename):
        if filename in self.favorites:
            self.favorites.remove(filename)
        else:
            self.favorites.append(filename)
        self._save_user_data()
        self.refresh_local_library(self.lib_search.get())

    def refresh_local_library(self, filter_text=""):
        for w in self.lib_scroll.winfo_children(): w.destroy()
        if not os.path.exists(self.download_dir): return
        
        files = [f for f in os.listdir(self.download_dir) if f.endswith(".mp3")]
        files.sort(key=lambda x: (not (x in self.favorites), x.lower()))
        
        columns = 4 
        col_idx = 0
        row_idx = 0
        for f in files:
            title_str = f.replace(".mp3", "")
            if filter_text.lower() not in title_str.lower(): continue
            parts = title_str.split("-")
            artist = parts[1].strip() if len(parts) > 1 else "Unknown"
            title = parts[0].strip()
            full_mp3_path = os.path.join(self.download_dir, f)
            t_data = {'title': title, 'artist': artist, 'path': full_mp3_path, 'img_url': None, 'video_id': None}
            
            card = ctk.CTkFrame(self.lib_scroll, width=175, height=240, corner_radius=10, fg_color="#181818")
            card.grid(row=row_idx, column=col_idx, padx=10, pady=12, sticky="nsew")
            card.grid_propagate(False)
            self._add_hover_effect(card, "#181818", "#2A2A2A")
            
            art_lbl = ctk.CTkLabel(card, text="🎵", width=130, height=130, fg_color="#242424", corner_radius=8)
            art_lbl.pack(pady=(15, 10))
            
            base_name = os.path.splitext(f)[0]
            jpg_path = os.path.join(self.download_dir, f"{base_name}.jpg")
            if os.path.exists(jpg_path): 
                threading.Thread(target=self._load_image_to_label, args=(jpg_path, art_lbl, (130, 130)), daemon=True).start()
                
            display_title = title if len(title) <= 22 else title[:19] + "..."
            display_artist = artist if len(artist) <= 25 else artist[:22] + "..."
            
            ctk.CTkLabel(card, text=display_title, font=("Arial", 14, "bold"), text_color="white", anchor="w").pack(fill="x", padx=12)
            ctk.CTkLabel(card, text=display_artist, font=("Arial", 11), text_color="#B3B3B3", anchor="w").pack(fill="x", padx=12)
            
            btn_frame = ctk.CTkFrame(card, fg_color="transparent")
            btn_frame.pack(fill="x", padx=10, pady=(5,0))
            
            is_fav = f in self.favorites
            fav_color = "#e74c3c" if is_fav else "#B3B3B3"
            
            ctk.CTkButton(btn_frame, text="❤", width=30, height=28, fg_color="#242424", hover_color="#333", text_color=fav_color, command=lambda fn=f: self.toggle_favorite(fn)).pack(side="left", padx=2)
            ctk.CTkButton(btn_frame, text="▶", width=30, height=28, fg_color="#1DB954", hover_color="#1ED760", text_color="black", command=lambda td=t_data: self.queue_and_play(td)).pack(side="left", padx=2)
            ctk.CTkButton(btn_frame, text="⏏", width=30, height=28, fg_color="#242424", hover_color="#333", command=lambda td=t_data: self.add_to_queue(td)).pack(side="left", padx=2)
            ctk.CTkButton(btn_frame, text="🗑", width=30, height=28, fg_color="#441a1a", hover_color="#732626", text_color="#ffb3b3", command=lambda p=full_mp3_path: self.delete_local_track(p)).pack(side="right", padx=2)
            
            col_idx += 1
            if col_idx >= columns:
                col_idx = 0
                row_idx += 1

    def handle_cloud_play(self, video_id, title, artist, image_url):
        safe_name = "".join(c for c in f"{title} - {artist}" if c.isalnum() or c in (" ", "-", "_")).strip()
        mp3_path = os.path.join(self.download_dir, f"{safe_name}.mp3")
        jpg_path = os.path.join(self.download_dir, f"{safe_name}.jpg")
        track_data = {'title': title, 'artist': artist, 'path': mp3_path, 'img_url': image_url, 'video_id': video_id}
        if os.path.exists(mp3_path): self.queue_and_play(track_data)
        else:
            self.player_title.configure(text="Downloading...")
            threading.Thread(target=self._download_worker, args=(video_id, safe_name, mp3_path, jpg_path, track_data), daemon=True).start()

    def _download_worker(self, video_id, safe_name, mp3_path, jpg_path, track_data):
        try:
            if track_data['img_url']:
                req = urllib.request.Request(track_data['img_url'], headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=5) as res, open(jpg_path, 'wb') as f: f.write(res.read())
            ydl_opts = {
                'format': 'bestaudio/best', 'outtmpl': os.path.join(self.download_dir, safe_name + '.%(ext)s'),
                'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
                'quiet': True, 'no_warnings': True
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl: ydl.download([f"https://music.youtube.com/watch?v={video_id}"])
            self.after(0, lambda: self.queue_and_play(track_data))
            self.after(0, self.refresh_local_library)
        except Exception: self.after(0, lambda: self.player_title.configure(text="Download failed"))

    def _load_album_art(self, track_data):
        base_name = os.path.splitext(os.path.basename(track_data['path']))[0]
        local_img = os.path.join(self.download_dir, f"{base_name}.jpg")
        img_src = local_img if os.path.exists(local_img) else track_data['img_url']
        if not img_src: return
        threading.Thread(target=self._load_image_to_label, args=(img_src, self.player_art_lbl, (60, 60)), daemon=True).start()

    def _fetch_lyrics(self, track_data):
        self.lyric_text.configure(state="normal")
        self.lyric_text.delete("1.0", "end")
        self.lyric_text.insert("end", "Loading lyrics...\n")
        self.lyric_text.configure(state="disabled")
        def worker():
            try:
                vid = track_data.get('video_id')
                if not vid:
                    res = self.yt_api.search(f"{track_data['title']} {track_data['artist']}", filter="songs", limit=1)
                    if res: vid = res[0].get('videoId')
                if vid:
                    watch = self.yt_api.get_watch_playlist(videoId=vid)
                    lyrics_id = watch.get("lyrics")
                    if lyrics_id: text = self.yt_api.get_lyrics(lyrics_id).get("lyrics", "No lyrics available.")
                    else: text = "Instrumental or No Lyrics Found."
                else: text = "Could not identify track for lyrics."
            except Exception: text = "Failed to load lyrics."
            self.after(0, lambda: self._update_lyric_ui(text))
        threading.Thread(target=worker, daemon=True).start()

    def _update_lyric_ui(self, text):
        self.lyric_text.configure(state="normal")
        self.lyric_text.delete("1.0", "end")
        self.lyric_text.insert("end", text)
        self.lyric_text.configure(state="disabled")

    def _init_system_tray(self):
        if not HAS_TRAY: return
        try:
            image = Image.new('RGB', (64, 64), color=(29, 185, 84))
            draw = ImageDraw.Draw(image)
            draw.ellipse((16, 16, 48, 48), fill=(255, 255, 255))
            menu = (item('Play/Pause', lambda: self.after(0, self.toggle_pause)), item('Next', lambda: self.after(0, self.play_next)), item('Show Window', lambda: self.after(0, self.deiconify)), item('Exit', lambda: self.after(0, self.destroy)))
            self.tray_icon = pystray.Icon("Melodia", image, "Melodia Streaming", menu)
            threading.Thread(target=self.tray_icon.run, daemon=True).start()
            self.protocol("WM_DELETE_WINDOW", self._hide_window)
        except Exception: pass

    def _hide_window(self):
        if self.settings.get("run_in_background", True) and HAS_TRAY:
            self.withdraw()
        else:
            self.destroy()

    def _init_media_keys(self):
        if not HAS_KEYBOARD: return
        try:
            keyboard.add_hotkey('play/pause media', lambda: self.after(0, self.toggle_pause))
            keyboard.add_hotkey('next track', lambda: self.after(0, self.play_next))
            keyboard.add_hotkey('previous track', lambda: self.after(0, self.play_prev))
        except Exception: pass

if __name__ == "__main__":
    app = MelodiaApp()
    app.mainloop()