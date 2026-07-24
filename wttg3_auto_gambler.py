from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from pathlib import Path
from statistics import median
from tkinter import messagebox, simpledialog, ttk

from PIL import Image, ImageChops, ImageGrab, ImageOps, ImageStat


ROOT = Path(__file__).parent
WORKFLOW_PATH = ROOT / "wttg3_workflow.json"
VK_F8, VK_F9 = 0x77, 0x78
KEYEVENTF_KEYUP = 0x0002
MOUSEEVENTF_MOVE = 0x0001
WM_INPUT, RID_INPUT, RIDEV_REMOVE, RIDEV_INPUTSINK, PM_REMOVE = 0x00FF, 0x10000003, 0x0001, 0x0100, 0x0001
MOUSE = {
    1: ("left", 0x0002, 0x0004),
    2: ("right", 0x0008, 0x0010),
}
user32 = ctypes.windll.user32


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [("usUsagePage", wintypes.USHORT), ("usUsage", wintypes.USHORT),
                ("dwFlags", wintypes.DWORD), ("hwndTarget", wintypes.HWND)]


class RAWMOUSEBUTTONS(ctypes.Structure):
    _fields_ = [("usButtonFlags", wintypes.USHORT), ("usButtonData", wintypes.USHORT)]


class RAWMOUSEBUTTONUNION(ctypes.Union):
    _fields_ = [("ulButtons", wintypes.ULONG), ("buttons", RAWMOUSEBUTTONS)]


class RAWMOUSE(ctypes.Structure):
    _anonymous_ = ("button_union",)
    _fields_ = [("usFlags", wintypes.USHORT), ("button_union", RAWMOUSEBUTTONUNION),
                ("ulRawButtons", wintypes.ULONG), ("lLastX", wintypes.LONG),
                ("lLastY", wintypes.LONG), ("ulExtraInformation", wintypes.ULONG)]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [("dwType", wintypes.DWORD), ("dwSize", wintypes.DWORD),
                ("hDevice", wintypes.HANDLE), ("wParam", wintypes.WPARAM)]


class RAWINPUTDATA(ctypes.Union):
    _fields_ = [("mouse", RAWMOUSE)]


class RAWINPUT(ctypes.Structure):
    _fields_ = [("header", RAWINPUTHEADER), ("data", RAWINPUTDATA)]


user32.CreateWindowExW.restype = wintypes.HWND


def find_tesseract() -> str:
    candidates = (
        os.environ.get("TESSERACT_CMD"),
        shutil.which("tesseract"),
        Path(os.environ.get("ProgramFiles", "")) / "Tesseract-OCR" / "tesseract.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Tesseract-OCR" / "tesseract.exe",
    )
    return next((str(path) for path in candidates if path and Path(path).is_file()), "")


def open_raw_mouse() -> int:
    hwnd = user32.CreateWindowExW(0, "STATIC", "", 0, 0, 0, 0, 0,
                                  wintypes.HWND(-3), None, None, None)
    device = RAWINPUTDEVICE(1, 2, RIDEV_INPUTSINK, hwnd)
    if not hwnd or not user32.RegisterRawInputDevices(ctypes.byref(device), 1, ctypes.sizeof(device)):
        raise ctypes.WinError()
    return hwnd


def read_raw_mouse(hwnd: int) -> list[tuple[int, int]]:
    moves: list[tuple[int, int]] = []
    message = wintypes.MSG()
    while user32.PeekMessageW(ctypes.byref(message), hwnd, WM_INPUT, WM_INPUT, PM_REMOVE):
        size = wintypes.UINT()
        user32.GetRawInputData(message.lParam, RID_INPUT, None, ctypes.byref(size), ctypes.sizeof(RAWINPUTHEADER))
        buffer = ctypes.create_string_buffer(size.value)
        if user32.GetRawInputData(message.lParam, RID_INPUT, buffer, ctypes.byref(size), ctypes.sizeof(RAWINPUTHEADER)) == size.value:
            raw = ctypes.cast(buffer, ctypes.POINTER(RAWINPUT)).contents
            if raw.header.dwType == 0 and (raw.data.mouse.lLastX or raw.data.mouse.lLastY):
                moves.append((raw.data.mouse.lLastX, raw.data.mouse.lLastY))
    return moves


def close_raw_mouse(hwnd: int) -> None:
    device = RAWINPUTDEVICE(1, 2, RIDEV_REMOVE, None)
    user32.RegisterRawInputDevices(ctypes.byref(device), 1, ctypes.sizeof(device))
    user32.DestroyWindow(hwnd)


def default_workflow() -> dict:
    return {
        "setup": [],
        "restart": None,
        "spin": None,
        "regions": {
            "yolo": [0.7734375, 0.9756944444, 0.80859375, 0.9965277778],
            "dos": [0.8203125, 0.9756944444, 0.8515625, 0.9965277778],
        },
        "tesseract": find_tesseract(),
    }


def load_workflow() -> dict:
    if not WORKFLOW_PATH.exists():
        return default_workflow()
    saved = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
    base = default_workflow()
    base.update(saved)
    base["regions"].update(saved.get("regions", {}))
    if not Path(base["tesseract"]).is_file():
        base["tesseract"] = find_tesseract()
    return base


def save_workflow(workflow: dict) -> None:
    WORKFLOW_PATH.write_text(json.dumps(workflow, indent=2), encoding="utf-8")


def screen_size() -> tuple[int, int]:
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def key_down(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def set_key(vk: int, down: bool) -> None:
    user32.keybd_event(vk, 0, 0 if down else KEYEVENTF_KEYUP, 0)


def tap_key(vk: int) -> None:
    set_key(vk, True)
    time.sleep(0.06)
    set_key(vk, False)


def click(x: int, y: int, button: str = "left") -> None:
    user32.SetCursorPos(x, y)
    set_mouse_button(button, True)
    set_mouse_button(button, False)


def set_mouse_button(button: str, down: bool) -> None:
    flags = next(value[1:] for value in MOUSE.values() if value[0] == button)
    user32.mouse_event(flags[0 if down else 1], 0, 0, 0, 0)


def cursor() -> tuple[int, int]:
    point = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


def find_game_window() -> int:
    found: list[int] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd: int, _lparam: int) -> bool:
        title = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, title, 256)
        if "Welcome to the Game III" in title.value:
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(each, 0)
    if not found:
        raise RuntimeError("WTTG3 window not found")
    return found[0]


def activate_game() -> None:
    hwnd = find_game_window()
    user32.ShowWindow(hwnd, 5)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.3)


def wait_for_release(vk: int, stop: threading.Event) -> None:
    while key_down(vk):
        if stop.is_set():
            raise InterruptedError
        time.sleep(0.02)


def wait_for_press(vk: int, stop: threading.Event) -> None:
    wait_for_release(vk, stop)
    while not key_down(vk):
        if stop.is_set():
            raise InterruptedError
        time.sleep(0.02)


def record_clip(stop: threading.Event) -> list[dict]:
    activate_game()
    wait_for_release(VK_F8, stop)
    tracked = [vk for vk in range(8, 256) if vk not in (VK_F8, VK_F9)]
    previous_keys = {vk: key_down(vk) for vk in tracked}
    previous_mouse = {vk: key_down(vk) for vk in MOUSE}
    width, height = screen_size()
    start_x, start_y = cursor()
    previous_position = (start_x, start_y)
    screen_center = (width // 2, height // 2)
    events: list[dict] = [{"dt": 0, "type": "mouse_anchor",
                           "x": start_x / width, "y": start_y / height}]
    last = time.monotonic()
    raw_mouse = open_raw_mouse()
    try:
        while not stop.is_set() and not key_down(VK_F8):
            now = time.monotonic()
            raw_moves = read_raw_mouse(raw_mouse)
            position = cursor()
            moved = abs(position[0] - previous_position[0]) >= 2 or abs(position[1] - previous_position[1]) >= 2
            locked_at_center = (abs(position[0] - screen_center[0]) <= 3 and
                                abs(position[1] - screen_center[1]) <= 3 and
                                abs(previous_position[0] - screen_center[0]) <= 3 and
                                abs(previous_position[1] - screen_center[1]) <= 3)
            if moved:
                events.append({"dt": now - last, "type": "move",
                               "x": position[0] / width, "y": position[1] / height})
                last = now
                previous_position = position
            elif locked_at_center:
                for dx, dy in raw_moves:
                    events.append({"dt": now - last, "type": "mouse_move", "dx": dx, "dy": dy})
                    last = now
            for vk, (name, _down, _up) in MOUSE.items():
                state = key_down(vk)
                if state != previous_mouse[vk]:
                    events.append({"dt": now - last, "type": "mouse_button",
                                   "button": name, "down": state})
                    last = now
                previous_mouse[vk] = state
            for vk in tracked:
                state = key_down(vk)
                if state != previous_keys[vk]:
                    events.append({"dt": now - last, "type": "key", "vk": vk, "down": state})
                    last = now
                previous_keys[vk] = state
            time.sleep(0.01)
        for vk, state in previous_keys.items():
            if state:
                events.append({"dt": 0, "type": "key", "vk": vk, "down": False})
        for vk, state in previous_mouse.items():
            if state:
                events.append({"dt": 0, "type": "mouse_button", "button": MOUSE[vk][0], "down": False})
    finally:
        close_raw_mouse(raw_mouse)
    wait_for_release(VK_F8, threading.Event())
    if stop.is_set():
        raise InterruptedError
    # Menus use absolute cursor positions; a centered FPS mouse uses raw relative deltas.
    return events


def interruptible_wait(seconds: float, stop: threading.Event) -> None:
    if stop.wait(max(0, seconds)):
        raise InterruptedError


def replay_clip(events: list[dict], stop: threading.Event, skip_initial_delay: bool = False) -> None:
    activate_game()
    width, height = screen_size()
    held: set[int] = set()
    held_mouse: set[str] = set()
    deadline = time.monotonic()
    try:
        for index, event in enumerate(events):
            deadline += 0 if skip_initial_delay and index == 0 else float(event.get("dt", 0))
            interruptible_wait(deadline - time.monotonic(), stop)
            kind = event["type"]
            if kind == "click":
                click(round(event["x"] * width), round(event["y"] * height), event["button"])
            elif kind == "mouse_anchor":
                user32.SetCursorPos(round(event["x"] * width), round(event["y"] * height))
            elif kind == "mouse_move":
                user32.mouse_event(MOUSEEVENTF_MOVE, int(event["dx"]), int(event["dy"]), 0, 0)
            elif kind == "move":
                user32.SetCursorPos(round(event["x"] * width), round(event["y"] * height))
            elif kind == "mouse_button":
                button, down = event["button"], bool(event["down"])
                set_mouse_button(button, down)
                held_mouse.add(button) if down else held_mouse.discard(button)
            elif "down" not in event:  # Old key recordings remain playable.
                tap_key(int(event["vk"]))
            else:
                vk, down = int(event["vk"]), bool(event["down"])
                set_key(vk, down)
                held.add(vk) if down else held.discard(vk)
    finally:
        for vk in held:
            set_key(vk, False)
        for button in held_mouse:
            set_mouse_button(button, False)


def parse_amount(text: str) -> float:
    text = text.strip().replace(" ", "")
    text = text.replace(",", "") if "," in text and "." in text else text.replace(",", ".")
    tokens = re.findall(r"\d+(?:\.\d+)?", text)
    if not tokens:
        raise ValueError(f"No amount in OCR output: {text!r}")
    values = [int(token) / 100 if "." not in token and len(token) >= 5 else float(token)
              for token in tokens]
    return max(values)


def read_amount(workflow: dict, currency: str, thorough: bool = False) -> float:
    screen = ImageGrab.grab()
    width, height = screen.size
    region = list(workflow["regions"][currency])
    box = tuple(round(value * (width if index % 2 == 0 else height))
                for index, value in enumerate(region))
    crop = screen.crop(box)
    crops = [crop]
    if thorough:
        crops.append(crop.crop((crop.width // 5, 0, crop.width, crop.height)))
    images = []
    for source in crops:
        gray = ImageOps.autocontrast(ImageOps.grayscale(source.resize((source.width * 5, source.height * 5))))
        images.extend((gray, gray.point(lambda pixel: 255 if pixel > 80 else 0),
                       gray.point(lambda pixel: 255 if pixel > 120 else 0),
                       gray.point(lambda pixel: 255 if pixel > 150 else 0)))
    values: list[float] = []
    last_error: Exception | None = None
    for image in images:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp:
            path = Path(temp.name)
        try:
            image.save(path)
            result = subprocess.run(
                [workflow["tesseract"], str(path), "stdout", "--psm", "7",
                 "-c", "tessedit_char_whitelist=0123456789."],
                capture_output=True, text=True, timeout=5, check=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            try:
                values.append(parse_amount(result.stdout))
                if not thorough:
                    return values[-1]
            except ValueError as error:
                last_error = error
        finally:
            path.unlink(missing_ok=True)
    if values:
        return max(values)
    raise last_error or ValueError("OCR failed")


def spin_button_brightness(workflow: dict) -> float:
    screen = ImageGrab.grab()
    width, height = screen.size
    x, y = workflow["spin"]
    radius = max(10, round(height * 0.013))
    center_x, center_y = round(x * width), round(y * height)
    crop = ImageOps.grayscale(screen.crop(
        (center_x - radius, center_y - radius, center_x + radius, center_y + radius)))
    return ImageStat.Stat(crop).mean[0]


def cannot_bet(brightness: float, balance: float, wager: float) -> bool:
    return brightness < 80 and balance < wager


def persistently_disabled(*brightness: float) -> bool:
    return len(brightness) >= 2 and all(value < 80 for value in brightness)


def target_confirmed(samples: list[float], target: float) -> bool:
    return len(samples) == 3 and all(value >= target for value in samples)


def should_restart(samples: list[float], wager: float, motion: float) -> bool:
    low = not samples or (len(samples) == 3 and all(value < wager for value in samples))
    return low and motion < 1.5


def reel_motion(workflow: dict, stop: threading.Event) -> float:
    width, height = screen_size()
    x, y = workflow["spin"]
    center_x, center_y = round(x * width), round(y * height)
    box = (round(center_x - width * 0.13), round(center_y - height * 0.34),
           round(center_x + width * 0.13), round(center_y - height * 0.08))
    first = ImageOps.grayscale(ImageGrab.grab(box).resize((96, 96)))
    motion = 0.0
    for _ in range(6):
        interruptible_wait(0.15, stop)
        current = ImageOps.grayscale(ImageGrab.grab(box).resize((96, 96)))
        motion = max(motion, ImageStat.Stat(ImageChops.difference(first, current)).mean[0])
    return motion


def ocr_consensus(samples: list[float]) -> float | None:
    return median(samples) if len(samples) >= 2 else None


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.workflow = load_workflow()
        self.stop = threading.Event()
        self.worker: threading.Thread | None = None
        root.title("WTTG3 Workflow Gambler")
        root.geometry("720x620")
        root.protocol("WM_DELETE_WINDOW", self.close)

        values = ttk.Frame(root, padding=10)
        values.pack(fill="x")
        self.target = self.field(values, "Target YoloYen", "30000", 0)
        self.deposit = self.field(values, "Deposit DOS", "100", 1)
        self.wager = self.field(values, "Wager", "100", 2)

        setup = ttk.LabelFrame(root, text="Complete automation flow", padding=10)
        setup.pack(fill="both", expand=True, padx=10, pady=5)
        self.steps = tk.Listbox(setup, height=9)
        self.steps.pack(fill="both", expand=True)
        row = ttk.Frame(setup)
        row.pack(fill="x", pady=(8, 0))
        ttk.Button(row, text="RECORD MAIN MENU → GAMBLING READY", command=self.record_full_setup).pack(side="left")
        ttk.Button(row, text="RECORD NEXT STEP", command=self.record_step).pack(side="left")
        ttk.Button(row, text="ADD DOS WAIT", command=self.add_wait).pack(side="left", padx=6)
        ttk.Button(row, text="REMOVE SELECTED", command=self.remove_step).pack(side="left")

        calibration = ttk.LabelFrame(root, text="Restart and gambling loop", padding=10)
        calibration.pack(fill="x", padx=10, pady=5)
        ttk.Button(calibration, text="RECORD RESTART → MAIN MENU", command=self.record_restart).grid(row=0, column=0, padx=3, pady=3)
        ttk.Button(calibration, text="SET SPIN POINT", command=lambda: self.capture_point("spin")).grid(row=0, column=1, padx=3, pady=3)
        ttk.Button(calibration, text="SET YOLO BOX", command=lambda: self.capture_box("yolo")).grid(row=1, column=0, padx=3, pady=3)
        ttk.Button(calibration, text="SET DOS BOX", command=lambda: self.capture_box("dos")).grid(row=1, column=1, padx=3, pady=3)

        controls = ttk.Frame(root, padding=10)
        controls.pack(fill="x")
        ttk.Button(controls, text="START FROM SELECTED STEP", command=self.start_bot).pack(side="left", expand=True, fill="x")
        ttk.Button(controls, text="STOP", command=self.stop_bot).pack(side="left", expand=True, fill="x", padx=(8, 0))
        self.status = tk.StringVar(value="Ready. Record setup steps in order.")
        ttk.Label(root, textvariable=self.status).pack(fill="x", padx=12)
        self.log_box = tk.Text(root, height=7, state="disabled")
        self.log_box.pack(fill="both", padx=10, pady=8)
        self.refresh_steps()

    @staticmethod
    def field(parent: ttk.Frame, label: str, value: str, column: int) -> ttk.Entry:
        frame = ttk.Frame(parent)
        frame.grid(row=0, column=column, padx=6, sticky="ew")
        ttk.Label(frame, text=label).pack(anchor="w")
        entry = ttk.Entry(frame, width=16)
        entry.insert(0, value)
        entry.pack(fill="x")
        parent.columnconfigure(column, weight=1)
        return entry

    def log(self, message: str) -> None:
        self.root.after(0, self._log, message)

    def _log(self, message: str) -> None:
        self.status.set(message)
        self.log_box.configure(state="normal")
        self.log_box.insert("end", message + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def task(self, function) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Busy", "Stop or finish the current action first.")
            return
        self.stop.clear()

        def run() -> None:
            try:
                function()
            except InterruptedError:
                self.log("Stopped.")
            except Exception as error:
                self.log(f"ERROR: {error}")

        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()

    def refresh_steps(self) -> None:
        self.steps.delete(0, "end")
        self.step_rows: list[tuple[str, int | None]] = []
        for index, step in enumerate(self.workflow["setup"], 1):
            label = f"recorded: {step['name']}" if step["type"] == "clip" else "WAIT until DOS deposit arrives"
            self.steps.insert("end", f"{index}. {label}")
            self.step_rows.append(("setup", index - 1))
        next_index = len(self.step_rows) + 1
        loop_ready = bool(self.workflow["spin"] and self.workflow["regions"].get("yolo"))
        self.steps.insert("end", f"{next_index}. GAMBLE LOOP until target or broke [{'READY' if loop_ready else 'SET SPIN/YOLO'}]")
        self.step_rows.append(("gamble", None))
        restart_ready = bool(self.workflow["restart"])
        self.steps.insert("end", f"{next_index + 1}. IF BROKE: restart → main menu [{'READY' if restart_ready else 'RECORD IT'}]")
        self.step_rows.append(("restart", None))
        self.steps.insert("end", f"{next_index + 2}. REPEAT from step 1")
        self.step_rows.append(("repeat", None))
        self.steps.selection_set(0)

    def show_step(self, kind: str, index: int | None = None) -> None:
        def select() -> None:
            row = self.step_rows.index((kind, index))
            self.steps.selection_clear(0, "end")
            self.steps.selection_set(row)
            self.steps.see(row)

        self.root.after(0, select)

    def record_step(self) -> None:
        name = simpledialog.askstring("Setup step", "Name this step:", parent=self.root)
        if not name:
            return

        def work() -> None:
            self.log(f"Recording {name!r}. Perform only this step, then press F8.")
            events = record_clip(self.stop)
            self.workflow["setup"].append({"type": "clip", "name": name, "events": events})
            save_workflow(self.workflow)
            self.root.after(0, self.refresh_steps)
            self.log(f"Saved {name!r}: {len(events)} actions.")

        self.task(work)

    def record_full_setup(self) -> None:
        def work() -> None:
            self.log("Recording main menu → gambling ready. Press F8 when the wager is set and SPIN is ready.")
            events = record_clip(self.stop)
            self.workflow["setup"] = [{"type": "clip", "name": "main menu → gambling ready", "events": events}]
            save_workflow(self.workflow)
            self.root.after(0, self.refresh_steps)
            self.log(f"Saved full setup: {len(events)} actions.")

        self.task(work)

    def add_wait(self) -> None:
        self.workflow["setup"].append({"type": "wait_dos"})
        save_workflow(self.workflow)
        self.refresh_steps()
        self.log("Added automatic DOS deposit wait.")

    def remove_step(self) -> None:
        selected = self.steps.curselection()
        if not selected:
            return
        kind, setup_index = self.step_rows[selected[0]]
        if kind != "setup":
            self.log("The gambling/restart loop is automatic; use its setup buttons below.")
            return
        assert setup_index is not None
        del self.workflow["setup"][setup_index]
        save_workflow(self.workflow)
        self.refresh_steps()

    def record_restart(self) -> None:
        def work() -> None:
            self.log("Record: broke Meramun → main menu only. Press F8 at the main menu.")
            self.workflow["restart"] = record_clip(self.stop)
            save_workflow(self.workflow)
            self.root.after(0, self.refresh_steps)
            self.log(f"Saved restart: {len(self.workflow['restart'])} actions.")

        self.task(work)

    def capture_point(self, name: str) -> None:
        def work() -> None:
            activate_game()
            self.log("Move over the SPIN button and press F9.")
            wait_for_press(VK_F9, self.stop)
            x, y = cursor()
            width, height = screen_size()
            self.workflow[name] = [x / width, y / height]
            save_workflow(self.workflow)
            self.root.after(0, self.refresh_steps)
            wait_for_release(VK_F9, self.stop)
            self.log("Spin point saved.")

        self.task(work)

    def capture_box(self, name: str) -> None:
        def work() -> None:
            activate_game()
            self.log(f"Move to the TOP-LEFT of the {name.upper()} amount and press F9.")
            wait_for_press(VK_F9, self.stop)
            first = cursor()
            wait_for_release(VK_F9, self.stop)
            self.log(f"Move to the BOTTOM-RIGHT of the {name.upper()} amount and press F9.")
            wait_for_press(VK_F9, self.stop)
            second = cursor()
            width, height = screen_size()
            left, right = sorted((first[0], second[0]))
            top, bottom = sorted((first[1], second[1]))
            self.workflow["regions"][name] = [left / width, top / height, right / width, bottom / height]
            save_workflow(self.workflow)
            self.root.after(0, self.refresh_steps)
            wait_for_release(VK_F9, self.stop)
            self.log(f"{name.upper()} OCR box saved.")

        self.task(work)

    def values(self) -> tuple[float, float, float]:
        values = float(self.target.get()), float(self.deposit.get()), float(self.wager.get())
        if min(values) <= 0:
            raise ValueError("Target, deposit, and wager must be positive")
        return values

    def read_retry(self, currency: str, thorough: bool = False) -> float:
        last_error: Exception | None = None
        for _ in range(10):
            if self.stop.is_set():
                raise InterruptedError
            try:
                return read_amount(self.workflow, currency, thorough)
            except Exception as error:
                last_error = error
                interruptible_wait(0.5, self.stop)
        raise RuntimeError(f"{currency.upper()} OCR failed: {last_error}")

    def read_yolo_consensus(self) -> float | None:
        samples: list[float] = []
        errors: list[str] = []
        for _ in range(5):
            if self.stop.is_set():
                raise InterruptedError
            try:
                samples.append(read_amount(self.workflow, "yolo", True))
            except Exception as error:
                errors.append(f"{type(error).__name__}: {error}")
            if len(samples) == 3:
                break
            interruptible_wait(0.25, self.stop)
        self.log("Yolo OCR samples: " + ", ".join(f"{value:.2f}" for value in samples))
        if not samples and errors:
            self.log("Yolo OCR error: " + errors[-1])
        return ocr_consensus(samples)

    def run_setup(self, deposit: float, start: int = 0) -> None:
        for index, step in enumerate(self.workflow["setup"][start:], start):
            self.show_step("setup", index)
            if step["type"] == "clip":
                self.log(f"Setup: {step['name']}")
                replay_clip(step["events"], self.stop)
            else:
                self.log(f"Waiting for {deposit:g} DOS...")
                deadline = time.monotonic() + 180
                while self.read_retry("dos") < deposit:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("DOS deposit did not arrive within 3 minutes")
                    interruptible_wait(1, self.stop)
        self.log("Waiting 16 seconds for the DOS exchange to finish.")
        interruptible_wait(16, self.stop)

    def restart_game(self, deposit: float) -> None:
        if not self.workflow["restart"]:
            raise RuntimeError("Record the restart step first")
        self.show_step("restart")
        self.log("Cannot bet; restarting the game.")
        replay_clip(self.workflow["restart"], self.stop, skip_initial_delay=True)
        self.log("Main menu selected; waiting 5 seconds.")
        interruptible_wait(5, self.stop)
        self.run_setup(deposit)

    def start_bot(self) -> None:
        selected = self.steps.curselection()
        start_kind, start_index = self.step_rows[selected[0] if selected else 0]

        def work() -> None:
            target, deposit, wager = self.values()
            self.run_bot(start_kind, start_index, target, deposit, wager)

        self.task(work)

    def run_bot(self, start_kind: str, start_index: int | None,
                target: float, deposit: float, wager: float) -> None:
        if start_kind != "gamble" and not self.workflow["setup"]:
            raise RuntimeError("Record setup steps first")
        if not self.workflow["spin"]:
            raise RuntimeError("Set the spin point first")
        if not Path(self.workflow["tesseract"]).is_file():
            raise RuntimeError("Tesseract OCR is missing; install it or set TESSERACT_CMD")
        activate_game()
        if start_kind == "setup":
            self.run_setup(deposit, start_index or 0)
        elif start_kind == "restart":
            self.restart_game(deposit)
        elif start_kind == "repeat":
            self.show_step("repeat")
            self.run_setup(deposit)
        width, height = screen_size()
        spin = self.workflow["spin"]
        spam_stop = threading.Event()

        def spam() -> None:
            while not self.stop.is_set() and not spam_stop.is_set():
                click(round(spin[0] * width), round(spin[1] * height))
                spam_stop.wait(0.02)

        def start_spam() -> threading.Thread:
            spam_stop.clear()
            worker = threading.Thread(target=spam, daemon=True)
            worker.start()
            return worker

        spam_worker = start_spam()
        try:
            while True:
                self.show_step("gamble")
                interruptible_wait(10, self.stop)

                balances: list[float] = []
                for _ in range(3):
                    try:
                        balances.append(read_amount(self.workflow, "yolo"))
                    except Exception:
                        pass
                    interruptible_wait(0.15, self.stop)
                self.log("Target check: " + (", ".join(f"{value:.2f}" for value in balances) or "OCR unavailable"))
                if target_confirmed(balances, target):
                    spam_stop.set()
                    spam_worker.join(1)
                    activate_game()
                    tap_key(27)
                    self.log("Target confirmed 3 times; game paused with Escape.")
                    return

                motion = reel_motion(self.workflow, self.stop)
                self.log(f"Reel motion: {motion:.1f}")
                if should_restart(balances, wager, motion):
                    spam_stop.set()
                    spam_worker.join(1)
                    self.log("Low balance and static reels; restarting.")
                    self.restart_game(deposit)
                    spam_worker = start_spam()
        finally:
            spam_stop.set()
            spam_worker.join(1)

    def stop_bot(self) -> None:
        self.stop.set()
        self.log("Stop requested.")

    def close(self) -> None:
        self.stop.set()
        self.root.destroy()


def demo() -> None:
    assert parse_amount(" 1,234.50 ") == 1234.5
    assert parse_amount("95.00") == 95.0
    assert parse_amount("261500") == 2615.0
    assert parse_amount("40000") == 400.0
    assert parse_amount("6000") == 6000.0
    assert parse_amount("icon54.30value6000.00") == 6000.0
    assert cannot_bet(70, 50, 100)
    assert not cannot_bet(90, 50, 100)
    assert not cannot_bet(70, 150, 100)
    assert persistently_disabled(70, 79)
    assert not persistently_disabled(70, 90)
    assert target_confirmed([30000, 30010, 40000], 30000)
    assert not target_confirmed([30000, 29999, 40000], 30000)
    assert not target_confirmed([30000, 30000], 30000)
    assert should_restart([5, 5, 5], 100, 0)
    assert not should_restart([5, 5, 5], 100, 10)
    assert not should_restart([375, 375, 375], 100, 0)
    assert median([10, 30000, 30000]) == 30000
    assert ocr_consensus([3010, 3010]) == 3010
    assert ocr_consensus([3010]) is None


class HeadlessApp(App):
    def __init__(self) -> None:
        self.workflow = load_workflow()
        self.stop = threading.Event()

    def log(self, message: str) -> None:
        print(message.encode(sys.stdout.encoding or "utf-8", "replace").decode(sys.stdout.encoding or "utf-8"), flush=True)

    def show_step(self, kind: str, index: int | None = None) -> None:
        pass


if __name__ == "__main__":
    demo()
    if len(sys.argv) >= 7 and sys.argv[1] == "--headless":
        kind = sys.argv[2]
        index = None if sys.argv[3] == "-" else int(sys.argv[3])
        HeadlessApp().run_bot(kind, index, float(sys.argv[4]), float(sys.argv[5]), float(sys.argv[6]))
    else:
        root = tk.Tk()
        App(root)
        root.mainloop()

