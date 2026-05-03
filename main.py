#!/usr/bin/python3

import tkinter as tk
from tkinter import filedialog, simpledialog, messagebox
import os
import time
import random
import subprocess
import webbrowser

import requests
from io import BytesIO
from PIL import Image, ImageTk, ImageEnhance

class DrawingSession(tk.Toplevel):
    """A window that displays both the image and the timer."""
    def __init__(self, image_data, seconds, is_path=True, source=None, source_type=None):
        super().__init__()
        self.title("Drawing Session")
        # Open window almost full screen
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        width = int(sw * 0.8)
        height = int(sh * 0.8)
        x = (sw // 2) - (width // 2)
        y = (sh // 2) - (height // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.initial_seconds = seconds
        self.seconds_left = seconds
        self.source = source
        self.source_type = source_type
        self.original_bg = self.cget("bg")

        self.blink_on = False
        self.scale = 1.0
        self.img_container = None
        self.img_x = 0
        self.img_y = 0
        self.pan_last_x = 0
        self.pan_last_y = 0
        self.paused = False
        self.flipped = False
        self.is_bw = False
        self.show_grid = False
        self.grid_divisions = 3
        self.grid_offset_x = 0.0
        self.grid_offset_y = 0.0
        self.grid_pan_last_x = 0
        self.grid_pan_last_y = 0
        self.grid_lines = []
        self.brightness_val = tk.DoubleVar(value=1.0)
        self.contrast_val = tk.DoubleVar(value=1.0)
        self.ui_visible = True
        self.last_win_size = (width, height)
        self.ms_to_next_tick = 1000
        self.last_tick_start = time.time()
        self._timer_after_id = None
        self.original_pil = None

        # Image area (Canvas for zoom and pan)
        self.canvas = tk.Canvas(self, bg="#2e2e2e", highlightthickness=0)
        self.canvas.pack(expand=True, fill="both")
        self.canvas.bind("<Configure>", self.on_resize)

        # Bindings for zoom and pan
        self.canvas.bind("<ButtonPress-1>", self.start_pan)
        self.canvas.bind("<B1-Motion>", self.pan)
        self.canvas.bind("<ButtonPress-3>", self.start_grid_pan)
        self.canvas.bind("<B3-Motion>", self.grid_pan)
        self.canvas.bind("<MouseWheel>", self.zoom)      # Windows/macOS
        self.canvas.bind("<Button-4>", self.zoom)        # Linux Scroll Up
        self.canvas.bind("<Button-5>", self.zoom)        # Linux Scroll Down

        # Keyboard Shortcuts
        self.bind("<space>", lambda e: self.toggle_pause())
        self.bind("r", lambda e: self.reset_view())
        self.bind("f", lambda e: self.toggle_flip())
        self.bind("g", lambda e: self.toggle_grid())
        self.bind("+", lambda e: self.change_grid_divisions(1))
        self.bind("-", lambda e: self.change_grid_divisions(-1))
        self.bind("b", lambda e: self.toggle_bw())
        self.bind("n", lambda e: self.next_image())
        self.bind("t", lambda e: self.restart_timer())
        self.bind("h", lambda e: self.toggle_ui())
        self.bind("?", lambda e: self.show_help())
        self.bind("<Control-g>", lambda e: self.toggle_grid())
        self.bind("<F1>", lambda e: self.show_help())
        self.bind("<F11>", lambda e: self.toggle_fullscreen())
        self.bind("<Escape>", lambda e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # Modern timer container (Floating Pill Design)
        self.timer_frame = tk.Frame(self, bg="#1a1a1a", padx=15, pady=10)
        self.timer_label = tk.Label(self.timer_frame, text=self.format_time(), 
                                    font=("Helvetica", 42, "bold"), 
                                    bg="#1a1a1a", fg="#ffffff",
                                    pady=5)
        self.timer_label.pack(side="left", padx=(0, 15), pady=(5, 0))

        # Button styling constants
        btn_style = {
            "bg": "#1a1a1a",
            "fg": "#cccccc",
            "activebackground": "#333333",
            "activeforeground": "#ffffff",
            "bd": 0,
            "highlightthickness": 0,
            "font": ("Helvetica", 24),
            "width": 2,
            "cursor": "hand2"
        }

        self.pause_button = tk.Button(self.timer_frame, text="⏸", 
                                      command=self.toggle_pause,
                                      **btn_style)
        self.pause_button.pack(side="left", padx=(0, 10))

        self.restart_timer_button = tk.Button(self.timer_frame, text="⏱", 
                                              command=self.restart_timer,
                                              **btn_style)
        self.restart_timer_button.pack(side="left", padx=(0, 10))

        self.next_button = tk.Button(self.timer_frame, text="⏭", 
                                     command=self.next_image,
                                     **btn_style)
        self.next_button.pack(side="left", padx=(0, 10))

        self.reset_button = tk.Button(self.timer_frame, text="🔄", 
                                      command=self.reset_view,
                                      **btn_style)
        self.reset_button.pack(side="left", padx=(0, 10))

        self.flip_button = tk.Button(self.timer_frame, text="↔", 
                                     command=self.toggle_flip,
                                     **btn_style)
        self.flip_button.pack(side="left")

        self.grid_button = tk.Button(self.timer_frame, text="▦", 
                                     command=self.toggle_grid,
                                     **btn_style)
        self.grid_button.pack(side="left", padx=(10, 0))

        self.bw_button = tk.Button(self.timer_frame, text="🌓", 
                                   command=self.toggle_bw,
                                   **btn_style)
        self.bw_button.pack(side="left", padx=(10, 0))

        # Brightness & Contrast Sliders
        tk.Label(self.timer_frame, text="B", bg="#1a1a1a", fg="#cccccc", font=("Helvetica", 12, "bold")).pack(side="left", padx=(10, 0))
        self.bright_scale = tk.Scale(self.timer_frame, variable=self.brightness_val, from_=0.0, to=3.0, 
                                     resolution=0.1, orient="horizontal", showvalue=True,
                                     bg="#1a1a1a", fg="#ffffff", troughcolor="#333333",
                                     activebackground="#444444", highlightthickness=0, bd=0, 
                                     sliderrelief="flat", width=15, length=100, 
                                     font=("Helvetica", 9), command=self.on_adj_change)
        self.bright_scale.pack(side="left", padx=5)
        self.bright_scale.bind("<Double-1>", lambda e: (self.brightness_val.set(1.0), self.on_adj_change(None)))

        tk.Label(self.timer_frame, text="C", bg="#1a1a1a", fg="#cccccc", font=("Helvetica", 12, "bold")).pack(side="left", padx=(10, 0))
        self.contrast_scale = tk.Scale(self.timer_frame, variable=self.contrast_val, from_=0.0, to=3.0, 
                                       resolution=0.1, orient="horizontal", showvalue=True,
                                       bg="#1a1a1a", fg="#ffffff", troughcolor="#333333",
                                       activebackground="#444444", highlightthickness=0, bd=0, 
                                       sliderrelief="flat", width=15, length=100, 
                                       font=("Helvetica", 9), command=self.on_adj_change)
        self.contrast_scale.pack(side="left", padx=5)
        self.contrast_scale.bind("<Double-1>", lambda e: (self.contrast_val.set(1.0), self.on_adj_change(None)))

        self.help_button = tk.Button(self.timer_frame, text="?", 
                                     command=self.show_help,
                                     **btn_style)
        self.help_button.pack(side="left", padx=(15, 0))

        # Load and display image
        self.display_image(image_data, is_path)
        
        # Always show the UI pill
        self.timer_frame.place(x=25, y=25, anchor="nw")
        self.timer_frame.lift()

        if self.seconds_left > 0:
            self.update_timer()
        else:
            # Hide timer-specific elements if timer is off
            self.timer_label.pack_forget()
            self.pause_button.pack_forget()
            self.restart_timer_button.pack_forget()

    def display_image(self, data, is_path):
        try:
            if is_path:
                self.original_pil = Image.open(data)
            else:
                self.original_pil = Image.open(BytesIO(data))

            # Reset view properties for the new image
            if self.img_container is not None:
                self.img_x = self.winfo_width() // 2
                self.img_y = self.winfo_height() // 2

            self.calculate_fit()
            self.render_image()
        except Exception as e:
            print(f"Fehler beim Laden des Bildes: {e}")

    def calculate_fit(self):
        """Calculates the fit_scale based on current canvas dimensions."""
        if self.original_pil:
            self.update_idletasks()
            cw = self.canvas.winfo_width()
            ch = self.canvas.winfo_height()
            if cw < 10 or ch < 10: return # Avoid division by zero
            iw, ih = self.original_pil.size
            self.fit_scale = min(cw/iw, ch/ih)

    def on_resize(self, event):
        """Handles window resize events to keep the image fitting correctly."""
        if self.original_pil and (event.width, event.height) != self.last_win_size:
            self.last_win_size = (event.width, event.height)
            # Re-calculate fit without resetting zoom scale
            old_fit = self.fit_scale
            self.calculate_fit()
            # Adjust internal coordinates to keep image relatively in the same place
            ratio = self.fit_scale / old_fit if old_fit > 0 else 1
            self.img_x *= ratio
            self.img_y *= ratio
            self.render_image(resample=Image.Resampling.BILINEAR)

    def render_image(self, resample=Image.Resampling.LANCZOS):
        """Recalculates the image based on the zoom level."""
        if not self.winfo_exists() or self.original_pil is None:
            return
        
        w, h = self.original_pil.size
        new_size = (int(w * self.fit_scale * self.scale), int(h * self.fit_scale * self.scale))
        
        # Protection against invalid sizes
        if new_size[0] < 10 or new_size[1] < 10: return
        if new_size[0] > 10000 or new_size[1] > 10000: return

        resized_img = self.original_pil.resize(new_size, resample)
        
        # Apply horizontal flipping
        if self.flipped:
            resized_img = resized_img.transpose(Image.FLIP_LEFT_RIGHT)
            
        if self.is_bw:
            resized_img = resized_img.convert("L")
            
        # Apply brightness and contrast enhancements
        resized_img = ImageEnhance.Brightness(resized_img).enhance(self.brightness_val.get())
        resized_img = ImageEnhance.Contrast(resized_img).enhance(self.contrast_val.get())
            
        self.photo = ImageTk.PhotoImage(resized_img)
        
        if self.img_container is None:
            # Center on the first call
            self.img_x, self.img_y = self.winfo_width() // 2, self.winfo_height() // 2
            self.img_container = self.canvas.create_image(self.img_x, self.img_y, image=self.photo, anchor="center")
        else:
            # Only update the image object, maintain position
            self.canvas.itemconfig(self.img_container, image=self.photo)
            self.canvas.coords(self.img_container, self.img_x, self.img_y)

        self.draw_grid()

    def draw_grid(self):
        """Draws a grid over the image if enabled."""
        for line in self.grid_lines:
            self.canvas.delete(line)
        self.grid_lines = []

        if self.show_grid and self.photo:
            iw, ih = self.photo.width(), self.photo.height()
            # Image bounds
            x_min, y_min = self.img_x - iw//2, self.img_y - ih//2
            x_max, y_max = x_min + iw, y_min + ih
            
            # Draw vertical lines
            step_x = iw / self.grid_divisions
            curr_x = (self.grid_offset_x * iw) % step_x
            while curr_x < iw:
                if 1 < curr_x < iw - 1:
                    lx = x_min + curr_x
                    line = self.canvas.create_line(lx, y_min, lx, y_max, fill="#ffffff", dash=(4, 4), stipple="gray50")
                    self.grid_lines.append(line)
                curr_x += step_x
            
            # Draw horizontal lines
            step_y = ih / self.grid_divisions
            curr_y = (self.grid_offset_y * ih) % step_y
            while curr_y < ih:
                if 1 < curr_y < ih - 1:
                    ly = y_min + curr_y
                    line = self.canvas.create_line(x_min, ly, x_max, ly, fill="#ffffff", dash=(4, 4), stipple="gray50")
                    self.grid_lines.append(line)
                curr_y += step_y

    def zoom(self, event):
        # Determine zoom factor and direction
        ratio = 1.1 if (event.num == 4 or event.delta > 0) else 0.909090909

        # Simple zoom: change scale, position (img_x, img_y) remains the same
        self.scale *= ratio

        # Update position in canvas immediately for fluid feedback
        if self.img_container:
            self.canvas.coords(self.img_container, self.img_x, self.img_y)

        # Bundle render jobs
        if hasattr(self, "_zoom_job_fast"): self.after_cancel(self._zoom_job_fast)
        if hasattr(self, "_zoom_job_slow"): self.after_cancel(self._zoom_job_slow)

        self._zoom_job_fast = self.after(20, lambda: self.render_image(resample=Image.Resampling.BILINEAR))
        self._zoom_job_slow = self.after(400, self.render_image)

    def on_adj_change(self, _):
        """Handles slider changes with debounced rendering."""
        if hasattr(self, "_adj_job_fast"): self.after_cancel(self._adj_job_fast)
        if hasattr(self, "_adj_job_slow"): self.after_cancel(self._adj_job_slow)
        
        self._adj_job_fast = self.after(20, lambda: self.render_image(resample=Image.Resampling.BILINEAR))
        self._adj_job_slow = self.after(400, self.render_image)

    def toggle_ui(self):
        """Toggles the visibility of the timer and buttons."""
        if self.ui_visible:
            self.timer_frame.place_forget()
        else:
            self.timer_frame.place(x=25, y=25, anchor="nw")
            self.timer_frame.lift()
        self.ui_visible = not self.ui_visible

    def toggle_fullscreen(self):
        """Toggles fullscreen mode."""
        is_full = self.attributes("-fullscreen")
        self.attributes("-fullscreen", not is_full)

    def toggle_flip(self):
        """Flips the image horizontally."""
        self.flipped = not self.flipped
        self.render_image()

    def toggle_grid(self):
        """Toggles the grid overlay."""
        self.show_grid = not self.show_grid
        self.render_image()

    def change_grid_divisions(self, delta):
        """Increases or decreases the number of grid divisions."""
        self.grid_divisions = max(2, self.grid_divisions + delta)
        if self.show_grid:
            self.draw_grid()

    def toggle_bw(self):
        """Toggles black and white mode."""
        self.is_bw = not self.is_bw
        self.render_image()

    def reset_view(self):
        """Resets zoom, position, and all image adjustments."""
        self.scale = 1.0
        self.flipped = False
        self.is_bw = False
        self.brightness_val.set(1.0)
        self.contrast_val.set(1.0)
        self.grid_offset_x = 0.0
        self.grid_offset_y = 0.0
        self.img_x = self.winfo_width() // 2
        self.img_y = self.winfo_height() // 2
        self.render_image(resample=Image.Resampling.LANCZOS)

    def show_help(self):
        """Displays a message box with keyboard shortcuts."""
        help_text = (
            "Keyboard Shortcuts:\n\n"
            "Space\t: Pause / Resume Timer\n"
            "T\t: Restart Timer\n"
            "N\t: Next Image\n"
            "R\t: Reset Zoom & Pan\n"
            "G\t: Toggle Grid\n"
            "+ / -\t: Adjust Grid Density\n"
            "F\t: Flip Image Horizontally\n"
            "B\t: Toggle Black & White\n"
            "H\t: Toggle UI Visibility\n"
            "F11\t: Toggle Fullscreen\n"
            "Esc\t: Exit Session\n"
            "F1 / ?\t: Show this Help"
        )
        messagebox.showinfo("VanGogh - Shortcuts", help_text, parent=self)

    def restart_timer(self):
        """Restarts the countdown timer to its initial value."""
        if self.initial_seconds <= 0: return  # Nothing to restart if timer is off
        self.seconds_left = self.initial_seconds
        self.ms_to_next_tick = 1000
        self.last_tick_start = time.time()
        self.blink_on = False
        self.timer_label.config(text=self.format_time(), bg="#1a1a1a", fg="#ffffff")
        self.update_timer()

    def next_image(self):
        """Loads the next image based on the session source."""
        if self.source_type == "local" and self.source:
            new_path = random.choice(self.source)
            self.display_image(new_path, is_path=True)
            self.restart_timer()
        elif self.source_type == "web" and self.source:
            image_url = f"https://loremflickr.com/1920/1080/{self.source}"
            try:
                response = requests.get(image_url)
                response.raise_for_status()
                self.display_image(response.content, is_path=False)
                self.restart_timer()
            except Exception as e:
                print(f"Error fetching next web image: {e}")

    def start_pan(self, event):
        self.pan_last_x, self.pan_last_y = event.x, event.y

    def pan(self, event):
        dx, dy = event.x - self.pan_last_x, event.y - self.pan_last_y
        self.img_x += dx
        self.img_y += dy
        if self.img_container:
            self.canvas.move(self.img_container, dx, dy)
        # Move grid lines to follow the image
        for line in self.grid_lines:
            self.canvas.move(line, dx, dy)
        self.pan_last_x, self.pan_last_y = event.x, event.y

    def start_grid_pan(self, event):
        self.grid_pan_last_x, self.grid_pan_last_y = event.x, event.y

    def grid_pan(self, event):
        if not self.show_grid or not self.photo: return
        iw, ih = self.photo.width(), self.photo.height()
        dx, dy = event.x - self.grid_pan_last_x, event.y - self.grid_pan_last_y
        
        self.grid_offset_x = (self.grid_offset_x + dx / iw) % 1.0
        self.grid_offset_y = (self.grid_offset_y + dy / ih) % 1.0
        
        self.grid_pan_last_x, self.grid_pan_last_y = event.x, event.y
        self.draw_grid()

    def format_time(self):
        mins, secs = divmod(self.seconds_left, 60)
        return f"{mins:02d}:{secs:02d}"

    def toggle_pause(self):
        """Toggles the pause status."""
        if self.initial_seconds <= 0: return  # Pausing has no effect if timer is off
        self.paused = not self.paused
        self.pause_button.config(text="▶" if self.paused else "⏸")
        if not self.paused:
            # Resume: restart timing and wait only for the remaining time
            self.last_tick_start = time.time()
            self._timer_after_id = self.after(int(max(0, self.ms_to_next_tick)), self.update_timer)
        else:
            # Pause: calculate how many milliseconds have passed from the current interval
            if self._timer_after_id:
                elapsed_ms = (time.time() - self.last_tick_start) * 1000
                self.ms_to_next_tick -= elapsed_ms
                self.after_cancel(self._timer_after_id)
                self._timer_after_id = None

    def on_close(self):
        """Ensures clean termination when closing the window."""
        if self._timer_after_id:
            self.after_cancel(self._timer_after_id)
        self.destroy()

    def update_timer(self):
        # Cancel existing job, if any, to avoid duplicates
        if self._timer_after_id:
            self.after_cancel(self._timer_after_id)
            self._timer_after_id = None

        if not self.winfo_exists() or self.paused: return
        if self.seconds_left > 0:
            self.seconds_left -= 1
            self.timer_label.config(text=self.format_time())
            
            # Initialize new 1-second interval
            self.ms_to_next_tick = 1000
            self.last_tick_start = time.time()
            self._timer_after_id = self.after(1000, self.update_timer)
        else:
            self.start_blinking()

    def start_blinking(self):
        if not self.winfo_exists(): return
        self.blink_on = not self.blink_on
        color = "#ffffff" if self.blink_on else "#ff4444"
        self.timer_label.config(bg=color, fg="#000000" if self.blink_on else "#ffffff")
        self._timer_after_id = self.after(500, self.start_blinking)

def get_timer_seconds():
    """Returns the seconds based on the selection."""
    mode = time_var.get()
    if mode == "Off": return 0

    if mode == "Custom":
        mins = simpledialog.askinteger("Custom Timer", "Enter minutes:", parent=root, minvalue=1)
        return mins * 60 if mins else 0
    return int(mode.replace("min", "")) * 60

def open_local_images():
    """Selects a folder, searches for images and starts a session."""
    # 1. Define default directory
    default_dir = os.path.expanduser('~/Pictures')
    
    # 2. Open folder dialog
    folder_path = filedialog.askdirectory(
        title="Select Folder with Images", 
        initialdir=default_dir
    )
    
    if not folder_path:
        return # The user clicked 'Cancel'

    # 2. Search images recursively in all subfolders
    valid_extensions = ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp')
    image_paths = [] # Store full absolute paths

    for root_dir, sub_dirs, files in os.walk(folder_path):
        for file in files:
            if file.lower().endswith(valid_extensions):
                full_path = os.path.join(root_dir, file)
                image_paths.append(full_path)

    if not image_paths:
        info_label.config(text="No images found in folder or subfolders!", fg="red")
        return
    
    # 4. Select random image
    selected_image_path = random.choice(image_paths)
    
    filename_only = os.path.basename(selected_image_path)
    info_label.config(text=f"Opened: {filename_only}", fg="green")

    # 5. Start Drawing Session
    seconds = get_timer_seconds()
    DrawingSession(selected_image_path, seconds, is_path=True, source=image_paths, source_type="local")
        
def open_random_web_image():
    """Downloads a web image and displays it internally."""
    # Read text and remove spaces at edges
    keyword = search_entry.get().strip()
    
    if not keyword:
         info_label.config(text="Please enter a search term!", fg="red")
         return
    
    image_url = f"https://loremflickr.com/1920/1080/{keyword}"
    info_label.config(text="Loading image from the web...", fg="yellow")
    root.update()

    try:
        response = requests.get(image_url)
        response.raise_for_status()
        seconds = get_timer_seconds()
        DrawingSession(response.content, seconds, is_path=False, source=keyword, source_type="web")
        info_label.config(text=f"Web image for '{keyword}' loaded", fg="green")
    except Exception as e:
        info_label.config(text="Download error!", fg="red")

# 1. Create the main application window
root = tk.Tk()
root.title("VanGogh")

# Define the window dimensions
window_width = 320
window_height = 250

# Get the user's screen width and height
screen_width = root.winfo_screenwidth()
screen_height = root.winfo_screenheight()

# Calculate the x and y coordinates to center the window
center_x = int((screen_width / 2) - (window_width / 2))
center_y = int((screen_height / 2) - (window_height / 2))

# Apply the dimensions and placement coordinates
# The format is 'WidthxHeight+X+Y'
root.geometry(f"{window_width}x{window_height}+{center_x}+{center_y}")



###### UI Elements

# --- Area 0: Time mode ---
time_options = ["Off", "1min", "2min", "3min", "5min", "10min", "15min", "30min", "Custom"]
time_var = tk.StringVar(root)
time_var.set(time_options[0])

timer_frame = tk.Frame(root)
timer_frame.pack(pady=(15, 0))
tk.Label(timer_frame, text="Time Mode:").pack(side="left", padx=5)
tk.OptionMenu(timer_frame, time_var, *time_options).pack(side="left")

# --- Area 1: Local images ---
local_images_button = tk.Button(root, text="Select Images from Folder", command=open_local_images)
local_images_button.pack(pady=(20, 10))

separator = tk.Frame(root, height=2, bd=1, relief="sunken")
separator.pack(fill="x", padx=20, pady=10)


# --- Area 2: Web image search ---
search_frame = tk.Frame(root)
search_frame.pack(pady=5)

search_entry = tk.Entry(search_frame, width=15)
search_entry.pack(side="left", padx=5)

# The button now calls our new function
search_button = tk.Button(search_frame, text="Random Web Image", command=open_random_web_image)
search_button.pack(side="left")

# --- Area 3: Info Label ---
info_label = tk.Label(root, text="Waiting for input...")
info_label.pack(pady=10)

root.mainloop()