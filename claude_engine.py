"""用 Claude Code 自带的语音听写做识别。

做法参考 viachm/claude-whisper 和 maximcdq/claude-dictate-mac:
在一个看不见的伪终端里常驻一个 claude 会话并打开语音听写(只对这个会话生效),
按住热键时每 50ms 往终端里写一个空格,模拟"按住空格";Claude Code 把语音转成文字放进输入框。
松开后按 Ctrl+G,Claude Code 会把输入框内容交给 $EDITOR,这里的 EDITOR 是一个小脚本,
它把文字写进 outbox 文件并清空输入框,于是拿到文字,而且什么都不会发给 Claude 模型。

用的是本机正版 claude 命令和你自己的 claude.ai 登录,不碰登录凭据。
听写不消耗 Claude 的消息和 token。只支持英文等 20 种语言,不支持中文。
"""
import fcntl
import json
import os
import pty
import re
import select
import shutil
import signal
import struct
import subprocess
import termios
import threading
import time
from pathlib import Path

SUPPORT = Path.home() / "Library" / "Application Support" / "LocalVoiceInput"
WORKSPACE = SUPPORT / "claude-workspace"
OUTBOX = SUPPORT / "claude-outbox.txt"
CAPTURE_SCRIPT = Path.home() / "Library" / "Caches" / "LocalVoiceInput" / "claude-capture.sh"  # Claude Code 按空格切分 $EDITOR,路径里不能有空格
PID_FILE = SUPPORT / "claude.pid"

# 只对这个隐藏会话生效的设置:开听写、按住模式、不自动发送;
# 再加一个 UserPromptSubmit 钩子拦下任何提交,双保险确保不会有内容发给模型
SESSION_SETTINGS = {
    "voice": {"enabled": True, "mode": "hold", "autoSubmit": False},
    "language": "english",
    "hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": "exit 2"}]}]},
}

# Claude Code 报错时屏幕上会出现的文字(见官方文档 voice-dictation 的 Troubleshooting)
ERROR_PATTERNS = [
    "Voice mode requires",
    "Voice mode is disabled",
    "Voice connection failed",
    "Voice stream error",
    "Voice input is failing",
    "Dictation error",
    "Microphone access is denied",
    "No audio detected",
    "Unknown command: /voice",
    "Please run /login",
    "Not logged in",
]
READY_MARKS = ["hold space to speak", "? for shortcuts", "shift+tab to cycle", 'Try "']
ESCAPES = re.compile(r"\x1b\[[0-9;?<>=]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b.")


class ClaudeError(Exception):
    pass


class ClaudeDictation:
    def __init__(self, log=print):
        self.log = log
        self.state = "stopped"        # stopped / starting / settling / ready
        self.fd = -1
        self.proc = None
        self.screen = ""
        self.last_output = 0.0
        self.last_chunk = ""
        self.holding = threading.Event()
        self.busy = threading.Lock()  # 一次只做一段听写
        self.mark = 0
        self.lock = threading.Lock()
        self.fail_count = 0

    # ---------- 会话生命周期 ----------

    def start(self):
        """在后台线程里启动会话,退出后自动重启。"""
        threading.Thread(target=self._supervise, daemon=True).start()

    def _supervise(self):
        while True:
            started = time.time()
            try:
                self._spawn()
                self._read_loop()   # 会话退出时返回
            except Exception as e:
                self.log(f"Claude 会话出错: {e}")
            self.state = "stopped"
            self.fail_count = self.fail_count + 1 if time.time() - started < 60 else 1
            wait = min(5 * 2 ** (self.fail_count - 1), 300)
            self.log(f"Claude 会话已退出,{wait}s 后重启。最后屏幕: {self.tail(300)}")
            time.sleep(wait)

    def _spawn(self):
        claude = shutil.which("claude") or str(Path.home() / ".local" / "bin" / "claude")
        if not os.path.exists(claude):
            raise ClaudeError("找不到 claude 命令")
        SUPPORT.mkdir(parents=True, exist_ok=True)
        WORKSPACE.mkdir(parents=True, exist_ok=True)
        CAPTURE_SCRIPT.parent.mkdir(parents=True, exist_ok=True)
        CAPTURE_SCRIPT.write_text(
            '#!/bin/sh\n'
            '# Claude Code 在 Ctrl+G 时把输入框内容交给这个"编辑器": 存到 outbox,再清空输入框\n'
            'cat "$1" > "$LVI_OUTBOX.tmp" && mv "$LVI_OUTBOX.tmp" "$LVI_OUTBOX"\n'
            ': > "$1"\n'
        )
        CAPTURE_SCRIPT.chmod(0o755)
        self._kill_stale()

        env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
        env.update(
            TERM="xterm-256color",
            EDITOR=str(CAPTURE_SCRIPT),
            VISUAL=str(CAPTURE_SCRIPT),
            LVI_OUTBOX=str(OUTBOX),
            DISABLE_AUTOUPDATER="1",   # 隐藏会话里弹更新提示会卡住听写
            LANG=env.get("LANG") or "en_US.UTF-8",
        )
        env.pop("ANTHROPIC_API_KEY", None)        # 有 API key 时语音听写不可用
        env.pop("ANTHROPIC_AUTH_TOKEN", None)
        env["PATH"] = env.get("PATH", "/usr/bin:/bin") + f":{Path.home()}/.local/bin:/opt/homebrew/bin"

        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 120, 0, 0))
        # --restricted: 不读你自己的 settings(钩子、插件、全屏界面等),只用上面这份设置;登录照常
        args = [claude, "--restricted", "--strict-mcp-config", "--settings", json.dumps(SESSION_SETTINGS)]
        self.proc = subprocess.Popen(
            args, stdin=slave, stdout=slave, stderr=slave,
            cwd=WORKSPACE, env=env, start_new_session=True,
        )
        os.close(slave)
        PID_FILE.write_text(str(self.proc.pid))
        self.fd = master
        self.screen = ""
        self.state = "starting"
        self.log(f"已启动隐藏的 Claude Code 会话 (pid {self.proc.pid})")

    def _kill_stale(self):
        """上次没退干净的隐藏会话。"""
        try:
            pid = int(PID_FILE.read_text())
            cmd = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True).stdout
            if "claude" in cmd and "--restricted" in cmd:
                os.killpg(pid, signal.SIGKILL)
        except Exception:
            pass

    def stop(self):
        p = self.proc
        if p and p.poll() is None:
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except Exception:
                pass

    def _read_loop(self):
        fd = self.fd
        try:
            while True:
                r, _, _ = select.select([fd], [], [], 0.2)
                if not r:
                    if self.proc.poll() is not None:
                        return
                    # 界面出现后再安静 1 秒才算就绪,免得语音模块还没加载好
                    if self.state == "settling" and time.time() - self.last_output > 1.0:
                        self.state = "ready"
                        self.fail_count = 0
                        self.log("Claude Code 听写已就绪")
                    continue
                try:
                    data = os.read(fd, 65536)
                except OSError:
                    return
                if not data:
                    return
                # Claude 会问终端光标位置和终端类型,照普通终端回答
                if b"\x1b[6n" in data:
                    self._write("\x1b[1;1R")
                if b"\x1b[c" in data or b"\x1b[0c" in data:
                    self._write("\x1b[?62;22c")
                text = ESCAPES.sub(" ", data.decode("utf-8", "replace"))
                with self.lock:
                    self.screen += text
                    if len(self.screen) > 40000:
                        cut = len(self.screen) - 20000
                        self.screen = self.screen[cut:]
                        self.mark = max(0, self.mark - cut)
                    self.last_output = time.time()
                    self.last_chunk = text
                if self.state == "starting":
                    if "trust this folder" in self.screen:
                        # 首次在工作目录启动: 选 "Yes, I trust this folder"
                        with self.lock:
                            self.screen = ""
                        self._write("\x1b[B")
                        time.sleep(0.4)
                        self._write("\r")
                    elif any(m in self.screen for m in READY_MARKS):
                        self.state = "settling"
        finally:
            self.holding.clear()
            try:
                os.close(fd)
            except OSError:
                pass
            self.fd = -1
            if self.proc.poll() is None:
                self.stop()
            self.proc.wait()

    def _write(self, s):
        if self.fd >= 0:
            try:
                os.write(self.fd, s.encode())
            except OSError:
                pass

    def tail(self, n):
        return re.sub(r"\s+", " ", self.screen[-n:]).strip()

    def _since_mark(self):
        with self.lock:
            return self.screen[self.mark:]

    # ---------- 听写 ----------

    def begin(self):
        """按下热键时调用。会话没就绪或正忙时抛 ClaudeError,由调用方改用备用模型。"""
        if self.state != "ready":
            raise ClaudeError("Claude Code 会话没在运行" if self.state == "stopped" else "Claude Code 会话还没就绪")
        if not self.busy.acquire(blocking=False):
            raise ClaudeError("上一段 Claude 听写还没处理完")
        with self.lock:
            self.mark = len(self.screen)
        self.holding.set()
        threading.Thread(target=self._hold, daemon=True).start()

    def _hold(self):
        # 像真按住空格一样,每 50ms 发一次按键重复
        while self.holding.is_set():
            self._write(" ")
            time.sleep(0.05)

    def end(self):
        """松开热键时立刻调用,停止"按住"。"""
        self.holding.clear()

    def collect(self):
        """等 Claude 转写完,取出文字。返回文字(没听到话时为 ""),出错抛 ClaudeError。"""
        try:
            return self._collect()
        finally:
            self.busy.release()

    def _collect(self):
        started = time.time()
        saw_processing = False
        saw_listening = False
        time.sleep(0.1)
        while True:
            since = self._since_mark()
            for pat in ERROR_PATTERNS:
                i = since.find(pat)
                if i >= 0:
                    msg = re.sub(r"\s+", " ", since[i:i + 160]).strip()
                    self._clear_prompt()
                    raise ClaudeError(msg)
            if "No speech detected" in since:
                self._clear_prompt()
                return ""
            if "listening" in since or "processing" in since:
                saw_listening = True
            if "processing" in since:
                saw_processing = True
            quiet = time.time() - self.last_output
            elapsed = time.time() - started
            if self.state != "ready":
                raise ClaudeError("Claude Code 会话中途退出了")
            if saw_processing and "processing" not in self.last_chunk and quiet > 0.15:
                break
            if not saw_processing and elapsed > 2.5 and quiet > 0.6:
                if not saw_listening:
                    self._clear_prompt()
                    raise ClaudeError("Claude Code 没有开始录音: " + self.tail(160))
                break
            if elapsed > 20:
                self._clear_prompt()
                raise ClaudeError("等 Claude Code 转写超时")
            time.sleep(0.05)
        text = self._capture()
        if not text and saw_processing:
            time.sleep(0.4)   # 极少数情况下文字还没落进输入框,再取一次
            text = self._capture()
        return text

    def _capture(self):
        """Ctrl+G: 让 Claude Code 把输入框交给 EDITOR 脚本,脚本写出 outbox 并清空输入框。"""
        try:
            OUTBOX.unlink()
        except FileNotFoundError:
            pass
        self._write("\x07")
        deadline = time.time() + 4
        while time.time() < deadline:
            if OUTBOX.exists():
                text = OUTBOX.read_text(encoding="utf-8").strip()
                OUTBOX.unlink(missing_ok=True)
                return text
            time.sleep(0.05)
        raise ClaudeError("从 Claude Code 取文字超时")

    def _clear_prompt(self):
        try:
            self._capture()
        except ClaudeError:
            pass
