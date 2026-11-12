# LocalVoiceInput

macOS 上的语音输入:按住右 Option 说话,松开后文字自动粘贴到光标处。

- 默认识别引擎:Claude Code 自带的语音听写。程序在后台常驻一个看不见的 `claude` 会话,按住热键时替你"按住空格",松开后把输入框里的文字取出来粘贴。用的是本机的 `claude` 命令和你自己的 claude.ai 登录,听写不消耗 Claude 的消息和 token,也不会有任何内容发给模型。英文很准,但**不支持中文**
- 备用引擎:本地离线的 [Qwen3-ASR-1.7B](https://huggingface.co/mlx-community/Qwen3-ASR-1.7B-8bit),通过 [mlx-audio](https://github.com/Blaizzy/mlx-audio) 在 Apple 芯片 GPU 上运行,中英文都行,支持热词。Claude 出错(会话没起来、没登录、网络断了、录不到音等)时弹一条系统通知,并用 Qwen 识别同一段录音
- 录音时屏幕底部显示一个玻璃胶囊浮窗(macOS 26 用 Liquid Glass,旧系统回退到毛玻璃)
- 可开机自启动,后台运行,菜单栏有麦克风图标

隐藏会话的做法参考了 [viachm/claude-whisper](https://github.com/viachm/claude-whisper) 和 [maximcdq/claude-dictate-mac](https://github.com/maximcdq/claude-dictate-mac)。

## 安装

需要 Apple 芯片的 Mac、Python 3.10 以上和 Xcode 命令行工具(`xcode-select --install`)。要用 Claude 引擎,还需装好 [Claude Code](https://code.claude.com) 并用 claude.ai 账号登录(`claude` 里 `/login`);没装或没登录时每次都会弹通知并改用 Qwen,这种情况可以把 `ENGINE` 改成 `"qwen"`。

```bash
git clone https://github.com/zjj1224073665/LocalVoiceInput.git
cd LocalVoiceInput
./setup.sh              # 建虚拟环境、装依赖、下载模型(约 2.3 GB)
./autostart.sh install  # 编译后台 App、设为开机自启动并立即启动
```

首次启动时按系统提示给 LocalVoiceInput 授权:麦克风、输入监控、辅助功能(放在"文稿"文件夹里时还有文件夹访问)。授权后程序会自动重启生效。

不想自启动的话,双击 `start.command` 在终端里运行即可(权限授给终端)。

## 使用

光标放在任意输入框,按住右 Option 说话,松开后等待片刻,文字会粘贴进去。

| 想做什么 | 怎么做 |
|---|---|
| 换热键 | 改 `voice_input.py` 顶部的 `HOTKEY` |
| 只用本地 Qwen(比如说中文时) | 把 `voice_input.py` 顶部的 `ENGINE` 改成 `"qwen"`,然后重启 |
| 让专有名词认得更准 | 在 `replace.txt` 里加一行这个词(热词,只对 Qwen 有效),或 `错误写法 => 正确写法`(强制替换,两个引擎都生效),保存后下次说话生效 |
| 调浮窗位置和大小 | 改 `overlay.py` 顶部的常量 |
| 退出 | 菜单栏麦克风图标 → 退出语音输入 |
| 取消自启动 | `./autostart.sh uninstall` |
| 看日志 | `~/Library/Logs/LocalVoiceInput.log` |

## 文件

- `voice_input.py`:主程序(热键、录音、识别、粘贴、Claude 失败时切换 Qwen)
- `claude_engine.py`:隐藏的 Claude Code 听写会话
- `overlay.py`:浮窗和菜单栏图标
- `app/launcher.c`:后台 App 的启动器,让系统权限记在 LocalVoiceInput 名下
- `setup.sh` / `autostart.sh` / `start.command`:安装、自启动、手动启动
