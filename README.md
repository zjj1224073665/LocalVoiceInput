# LocalVoiceInput

macOS 上的本地离线语音输入:按住右 Option 说话,松开后文字自动粘贴到光标处。不联网、不用登录。

- 识别模型:[Qwen3-ASR-1.7B](https://github.com/QwenLM/Qwen3-ASR)(8bit),通过 [mlx-audio](https://github.com/Blaizzy/mlx-audio) 在 Apple 芯片 GPU 上运行,中文、英文、中英混说都比较准,支持热词
- 录音时屏幕底部显示一个玻璃胶囊浮窗(macOS 26 用 Liquid Glass,旧系统回退到毛玻璃)
- 可开机自启动,后台运行,菜单栏有麦克风图标

## 安装

需要 Apple 芯片的 Mac、Python 3.10 以上和 Xcode 命令行工具(`xcode-select --install`)。

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
| 让专有名词认得更准 | 在 `replace.txt` 里加一行这个词(热词),或 `错误写法 => 正确写法`(强制替换),保存后下次说话生效 |
| 调浮窗位置和大小 | 改 `overlay.py` 顶部的常量 |
| 退出 | 菜单栏麦克风图标 → 退出语音输入 |
| 取消自启动 | `./autostart.sh uninstall` |
| 看日志 | `~/Library/Logs/LocalVoiceInput.log` |

## 文件

- `voice_input.py`:主程序(热键、录音、识别、粘贴)
- `overlay.py`:浮窗和菜单栏图标
- `app/launcher.c`:后台 App 的启动器,让系统权限记在 LocalVoiceInput 名下
- `setup.sh` / `autostart.sh` / `start.command`:安装、自启动、手动启动
