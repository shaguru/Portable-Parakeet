"""Local push-to-talk dictation using a Parakeet runtime beside this app.

Hold Win+Alt to record; release either key to transcribe and paste at the caret.
Run with: python parakeet_dictation.py
"""
from __future__ import annotations
import ctypes, ctypes.wintypes as wt, json, os, queue, re, subprocess, sys, tempfile, threading, wave
from pathlib import Path
import tkinter as tk
from tkinter import ttk
import numpy as np
import sounddevice as sd
import pyperclip

ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
MODEL_DIR = ROOT / "models"
PREFS = ROOT / "preferences.json"
MODEL = MODEL_DIR / "ggml-parakeet-tdt-0.6b-v2-q5_0.bin"
CLI = MODEL_DIR / "parakeet-cli.exe"
SAMPLE_RATE = 16000

_FINITE_VERBS = (
    r"(?:think|know|want|need|believe|feel|guess|remember|mean)s?"
    r"|thought|knew|wanted|needed|felt|am|is|are|was|were|have|has|had"
    r"|(?:don|doesn|didn|can|couldn|won|wouldn|shouldn)['’]t"
)

def clean_filler_like(value: str) -> str:
    """Remove clear discourse markers, retaining uncertain semantic uses."""
    def remove_aside(match):
        before = re.findall(r"[\w’']+", value[:match.start()].lower())
        following = re.match(r"[\w’']+", value[match.end():].lower())
        previous = before[-1] if before else ""
        next_word = following.group() if following else ""
        # Pauses do not make comparisons, examples or preferences into fillers.
        if previous in {
            "look", "looks", "looked", "sound", "sounds", "sounded",
            "feel", "feels", "felt", "seem", "seems", "seemed",
            "taste", "tastes", "smell", "smells", "act", "acts",
            "something", "anything", "nothing", "someone", "things", "stuff",
            "just", "exactly", "much", "more", "less", "would",
            "could", "might", "may", "really", "also", "still", "not",
        }:
            return match.group()
        if previous in {"don't", "doesn't", "didn't", "don’t", "doesn’t", "didn’t"}:
            return match.group()
        if previous in {"am", "is", "are", "was", "were", "be", "been"} or previous.endswith(
            ("'s", "’s", "'re", "’re", "'m", "’m")
        ):
            if not next_word.endswith("ing"):
                return match.group()
        if previous in {"i", "you", "we", "they", "he", "she"}:
            if not re.fullmatch(_FINITE_VERBS, next_word):
                return match.group()
        return " "

    # Run asides first, so their two commas are removed together.
    value = re.sub(r"(?i),\s*like\s*[,;:]\s*", remove_aside, value)
    # A start-of-sentence discourse marker is signalled by a pause.
    value = re.sub(r"(?i)(^|[.!?]\s+)like\s*[,;:]\s*", r"\1", value)
    value = re.sub(
        r"(?i)\b(and|but|so)\s+like\s*[,;:]\s*", r"\1 ", value
    )
    # Some transcriptions omit pauses: "I like don't know" has a finite verb
    # after "like", whereas "I like swimming" is a preference and stays.
    value = re.sub(
        rf"(?i)\b(i|you|we|they|he|she)\s+like\s+(?=(?:{_FINITE_VERBS})\b)",
        r"\1 ", value,
    )
    value = re.sub(
        r"(?i)\b(i|you|we|they|he|she)\s+(was|were|am|are)\s+like\s+(?=\w+ing\b)",
        r"\1 \2 ", value,
    )
    value = re.sub(
        rf"(?i)\b(i|you|we|they|he|she)\s+like\s*[,;:]\s*(?=(?:{_FINITE_VERBS})\b)",
        r"\1 ", value,
    )
    return value

def clean_transcript(value: str) -> str:
    """Apply small, conservative cleanup after speech recognition.

    Only standalone hesitation sounds and clearly marked discourse ``like``
    are removed; words such as ``umbrella`` remain unchanged. The semantic
    uses in ``I like this`` and ``That thing is like this`` are preserved.
    """
    value = re.sub(r"\s+", " ", value).strip()
    value = re.sub(
        r"(?i)[,;:]\s*(?:um+|uhm+|uh+|erm+|er+|hmm+)(?!\w)[,.;:!?]*\s*",
        " ",
        value,
    )
    value = re.sub(
        r"(?i)(^|[.!?]\s+|\s)[,;:]?\s*(?:um+|uhm+|uh+|erm+|er+|hmm+)(?!\w)[,.;:!?]*\s*",
        r"\1",
        value,
    )
    value = clean_filler_like(value)
    value = re.sub(r"\s+([,.;:!?])", r"\1", value)
    return re.sub(r"\s+", " ", value).strip()

def preferred_device():
    try:
        prefs = json.loads(PREFS.read_text(encoding="utf-8"))
        wanted = prefs.get("microphoneId", "").lower()
        for i, d in enumerate(sd.query_devices()):
            if wanted and wanted in str(d.get("name", "")).lower():
                return i
    except Exception:
        pass
    # Prefer a USB microphone when one is present; otherwise use the default.
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] and "usb pnp" in d["name"].lower():
            return i
    return None

class Dictation:
    def __init__(self, status):
        self.status = status
        self.lock = threading.Lock()
        self.frames = []
        self.stream = None
        self.recording = False
        self.worker = None
        self.device = preferred_device()

    def start(self):
        with self.lock:
            if self.recording: return
            self.frames = []
            try:
                self.stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                    device=self.device, callback=lambda data, n, t, s: self.frames.append(data.copy()))
                self.stream.start(); self.recording = True
                self.status("Recording… release Win or Alt to transcribe")
            except Exception as e:
                self.status(f"Microphone error: {e}")

    def stop(self):
        with self.lock:
            if not self.recording: return
            self.recording = False
            try: self.stream.stop(); self.stream.close()
            except Exception: pass
            frames = self.frames[:]
        if frames: self.worker = threading.Thread(target=self.transcribe, args=(frames,), daemon=True); self.worker.start()

    def transcribe(self, frames):
        self.status("Transcribing locally…")
        try:
            audio = np.concatenate(frames).reshape(-1)
            pcm = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
            with tempfile.TemporaryDirectory(prefix="parakeet-") as td:
                wav = Path(td) / "dictation.wav"
                with wave.open(str(wav), "wb") as f:
                    f.setnchannels(1); f.setsampwidth(2); f.setframerate(SAMPLE_RATE); f.writeframes(pcm.tobytes())
                cmd = [str(CLI), "-m", str(MODEL), "-np", "-f", str(wav)]
                # parakeet-cli is a console executable. Hide its console window
                # while keeping stdout/stderr available for diagnostics.
                startupinfo = None
                creationflags = 0
                if os.name == "nt":
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    startupinfo.wShowWindow = subprocess.SW_HIDE
                    creationflags = subprocess.CREATE_NO_WINDOW
                r = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=180,
                    cwd=str(MODEL_DIR),
                    startupinfo=startupinfo,
                    creationflags=creationflags,
                )
                text = clean_transcript(r.stdout)
                if r.returncode or not text: raise RuntimeError(r.stderr.strip() or "No speech detected")
                pyperclip.copy(text + " ")
                paste = lambda: (ctypes.windll.user32.keybd_event(0x11,0,0,0), ctypes.windll.user32.keybd_event(0x56,0,0,0), ctypes.windll.user32.keybd_event(0x56,0,2,0), ctypes.windll.user32.keybd_event(0x11,0,2,0))
                paste()
                self.status(f"Inserted: {text[:90]}")
        except Exception as e:
            self.status(f"Transcription error: {e}")

# Win+Alt is polled with GetAsyncKeyState, avoiding a global callback thread.
user32 = ctypes.windll.user32
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
VK_LWIN, VK_RWIN, VK_LALT, VK_RALT = 0x5B, 0x5C, 0xA4, 0xA5

def run():
    root = tk.Tk(); root.title("Parakeet Dictation"); root.geometry("430x170"); root.resizable(False, False)
    status = tk.StringVar(value="Ready — hold Win+Alt to dictate")
    ttk.Label(root, text="Parakeet Dictation", font=("Segoe UI", 16, "bold")).pack(pady=(18, 4))
    ttk.Label(root, textvariable=status, wraplength=400).pack(pady=4)
    ttk.Label(root, text="Hold Win + Alt, speak, then release either key. Text is pasted at the caret.", foreground="#555").pack(pady=8)
    d = Dictation(lambda s: root.after(0, status.set, s))
    active = False
    def poll_keys():
        nonlocal active
        held = any(user32.GetAsyncKeyState(v) & 0x8000 for v in (VK_LWIN, VK_RWIN)) and any(user32.GetAsyncKeyState(v) & 0x8000 for v in (VK_LALT, VK_RALT))
        if held and not active: d.start(); active = True
        elif not held and active: d.stop(); active = False
        root.after(20, poll_keys)
    poll_keys()
    root.protocol("WM_DELETE_WINDOW", lambda: (d.stop(), root.destroy()))
    root.mainloop()

if __name__ == "__main__": run()
