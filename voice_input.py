"""本地离线语音输入:按住热键说话,松开后把识别结果粘贴到光标处。

模型: Qwen3-ASR-1.7B (MLX,在 Apple 芯片 GPU 上运行),完全离线。
用法: 双击 start.command,或 .venv/bin/python voice_input.py
测试: .venv/bin/python voice_input.py --file some.wav
"""
import os
import queue
import signal
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path

import numpy as np

# ---------------- 配置 ----------------
HOTKEY = "alt_r"          # 按住说话的键,pynput 的 Key 名: alt_r=右Option, cmd_r=右Command, f13 ...
MIN_SECONDS = 0.3         # 短于此时长视为误触
RESTORE_CLIPBOARD = True  # 粘贴后恢复原剪贴板(仅文本)
STOP_TIMEOUT = 3          # 关闭麦克风超过这么多秒视为卡死,自动重启
# --------------------------------------

BASE = Path(__file__).resolve().parent
MODEL_DIR = BASE / "models" / "Qwen3-ASR-1.7B-8bit"
REPLACE_FILE = BASE / "replace.txt"
SAMPLE_RATE = 16000


def load_recognizer():
    from mlx_audio.stt import load

    return load(str(MODEL_DIR))


def load_vocab():
    """读 replace.txt,返回 (热词列表, 替换对列表)。

    单独一行的词是热词;"错误写法 => 正确写法" 是替换,右边的正确写法也自动算热词。
    """
    hotwords, pairs = [], []
    if REPLACE_FILE.exists():
        for line in REPLACE_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=>" in line:
                src, dst = (s.strip() for s in line.split("=>", 1))
                if src:
                    pairs.append((src, dst))
                word = dst
            else:
                word = line
            if word and word not in hotwords:
                hotwords.append(word)
    return hotwords, pairs


def transcribe(recognizer, samples):
    hotwords, replacements = load_vocab()
    text = recognizer.generate(samples, hotwords=hotwords or None).text.strip()
    for src, dst in replacements:
        text = text.replace(src, dst)
    return text


def read_wav(path):
    with wave.open(str(path)) as f:
        assert f.getsampwidth() == 2, "只支持 16-bit wav"
        data = np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16)
        data = data.reshape(-1, f.getnchannels()).mean(axis=1) / 32768.0
        rate = f.getframerate()
    if rate != SAMPLE_RATE:
        idx = np.arange(0, len(data), rate / SAMPLE_RATE)
        data = np.interp(idx, np.arange(len(data)), data)
    return data.astype(np.float32)


UTF8_ENV = {**os.environ, "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8"}


def paste_text(text, keyboard_ctl, Key):
    old = None
    if RESTORE_CLIPBOARD:
        old = subprocess.run(["pbpaste"], capture_output=True, env=UTF8_ENV).stdout
    subprocess.run(["pbcopy"], input=text.encode("utf-8"), env=UTF8_ENV)
    time.sleep(0.05)
    with keyboard_ctl.pressed(Key.cmd):
        keyboard_ctl.press("v")
        keyboard_ctl.release("v")
    if old:
        time.sleep(0.4)
        subprocess.run(["pbcopy"], input=old, env=UTF8_ENV)


def missing_permissions(prompt=False):
    """返回缺少的权限名列表;prompt=True 时顺便弹出系统授权框。"""
    import Quartz
    from ApplicationServices import AXIsProcessTrustedWithOptions

    missing = []
    # 输入监控: 直接试着建一个只读事件监听,建不出来就是没权限(授权后无需重启即可探测到)
    tap = Quartz.CGEventTapCreate(
        Quartz.kCGSessionEventTap,
        Quartz.kCGHeadInsertEventTap,
        Quartz.kCGEventTapOptionListenOnly,
        Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown),
        lambda proxy, type_, event, refcon: event,
        None,
    )
    if tap is None:
        missing.append("输入监控")
        if prompt:
            Quartz.CGRequestListenEventAccess()
    else:
        Quartz.CFMachPortInvalidate(tap)
    if not AXIsProcessTrustedWithOptions({"AXTrustedCheckOptionPrompt": prompt}):
        missing.append("辅助功能")
    return missing


def restart():
    """原地重启本进程(仍挂在 App 外壳下,权限不变)。"""
    os.execv(sys.executable, [sys.executable, "-u", str(BASE / "voice_input.py")])


def acquire_single_instance_lock():
    import fcntl

    lock_file = open(Path.home() / "Library" / "Caches" / "LocalVoiceInput.lock", "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("已有一个语音输入在运行,本次启动退出")
        sys.exit(0)
    return lock_file


def main():
    print("加载模型中…")
    recognizer = load_recognizer()

    if len(sys.argv) == 3 and sys.argv[1] == "--file":
        samples = read_wav(sys.argv[2])
        t0 = time.time()
        text = transcribe(recognizer, samples)
        print(f"[{len(samples) / SAMPLE_RATE:.1f}s 音频, 用时 {time.time() - t0:.2f}s] {text}")
        return

    instance_lock = acquire_single_instance_lock()  # noqa: F841 进程存活期间一直持有

    import sounddevice as sd
    from AppKit import NSApplication, NSApplicationActivationPolicyAccessory, NSTimer
    from pynput import keyboard
    from pynput.keyboard import Key
    from PyObjCTools import AppHelper

    from overlay import Overlay, StatusMenu

    hotkey = getattr(Key, HOTKEY)
    keyboard_ctl = keyboard.Controller()
    jobs = queue.Queue()
    frames = []
    state = {"stream": None, "recording": False, "level": 0.0}
    lock = threading.Lock()

    # 浮窗必须在主线程创建和更新,其他线程通过 AppHelper.callAfter 调用
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    overlay = Overlay(lambda: state["level"])
    menu = StatusMenu(BASE)

    # 缺权限时弹系统授权框,并每 2 秒探测一次,授权后自动重启生效
    missing = missing_permissions(prompt=True)
    if missing:
        print("缺少权限:", "、".join(missing))
        menu.set_status("⚠️ 请在系统设置里授权: " + "、".join(missing))

        def recheck(_t):
            if not missing_permissions():
                print("权限已就绪,重启")
                restart()

        NSTimer.scheduledTimerWithTimeInterval_repeats_block_(2.0, True, recheck)
    else:
        menu.set_status("按住右 Option 说话")
        # 开一下麦克风,让首次运行时的麦克风授权框现在就弹出来
        threading.Thread(
            target=lambda: sd.rec(1600, samplerate=SAMPLE_RATE, channels=1, dtype="float32", blocking=True),
            daemon=True,
        ).start()

    def on_audio(indata, n, t, status):
        x = indata[:, 0]
        frames.append(x.copy())
        db = 20 * np.log10(float(np.sqrt((x * x).mean())) + 1e-7)
        state["level"] = min(max((db + 55) / 40, 0.0), 1.0)

    def pick_input_device():
        """优先内置麦克风,避开 Zoom 虚拟声卡/聚合设备;找不到则用系统默认。"""
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0 and "MacBook" in d["name"]:
                return i
        return None

    def open_stream():
        # 设备插拔/切换后 PortAudio 的设备列表会过期,每次开流前刷新(此时没有打开的流)
        sd._terminate()
        sd._initialize()
        stream = sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="float32",
            device=pick_input_device(), callback=on_audio,
        )
        stream.start()
        return stream

    def on_press(key):
        if key != hotkey:
            return
        with lock:
            if state["stream"] is not None:   # 正在录音,或上一次的流还没关完
                return
            frames.clear()
            try:
                state["stream"] = open_stream()
            except Exception as e:
                state["stream"] = None
                print(f"打开麦克风失败: {e}")
                return
            state["recording"] = True
        AppHelper.callAfter(overlay.show_recording)

    def close_stream(stream):
        # PortAudio 在 macOS 上关流偶尔会和 CoreAudio 的 IO 线程互相死锁,
        # 所以放到单独线程里关并限时;真卡死了就等手头的识别做完后重启进程自愈
        def close():
            stream.stop()
            stream.close()

        t = threading.Thread(target=close, daemon=True)
        t.start()
        t.join(STOP_TIMEOUT)
        if t.is_alive():
            print("关闭麦克风卡死,识别完成后自动重启")
            jobs.join()
            time.sleep(0.6)   # 等粘贴和剪贴板恢复落地
            restart()
        with lock:
            state["stream"] = None

    def on_release(key):
        if key != hotkey:
            return
        with lock:
            if not state["recording"]:
                return
            state["recording"] = False
            stream = state["stream"]
            samples = np.concatenate(frames) if frames else np.zeros(0, dtype=np.float32)
        AppHelper.callAfter(overlay.show_transcribing)
        jobs.put(samples)
        threading.Thread(target=close_stream, args=(stream,), daemon=True).start()

    def worker():
        while True:
            samples = jobs.get()
            seconds = len(samples) / SAMPLE_RATE
            t0 = time.time()
            try:
                if seconds < MIN_SECONDS:
                    AppHelper.callAfter(overlay.hide)
                    continue
                text = transcribe(recognizer, samples)
                AppHelper.callAfter(overlay.hide)
                if text:
                    paste_text(text, keyboard_ctl, Key)
                print(f"[{seconds:.1f}s → {time.time() - t0:.2f}s] {text}")
            except Exception as e:
                AppHelper.callAfter(overlay.hide)
                print(f"识别出错: {e}")
            finally:
                jobs.task_done()

    threading.Thread(target=worker, daemon=True).start()
    print(f"就绪。按住 {HOTKEY}(右 Option)说话,松开后自动输入。从菜单栏麦克风图标或 Ctrl+C 退出。")
    keyboard.Listener(on_press=on_press, on_release=on_release, daemon=True).start()

    # Ctrl+C: 事件循环在原生代码里跑,靠一个空定时器让 Python 有机会处理信号
    def quit_now(*_):
        print("\n已退出")
        os._exit(0)

    signal.signal(signal.SIGINT, quit_now)
    NSTimer.scheduledTimerWithTimeInterval_repeats_block_(0.25, True, lambda _t: None)
    AppHelper.runEventLoop(installInterrupt=False)


if __name__ == "__main__":
    main()
