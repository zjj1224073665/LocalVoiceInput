#!/bin/bash
# 开机自启动(无终端窗口):  ./autostart.sh install   |   ./autostart.sh uninstall
set -e
cd "$(dirname "$0")"
DIR="$(pwd)"
APP="$DIR/LocalVoiceInput.app"
LABEL=com.junjiezhao.localvoiceinput
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

build_app() {
  mkdir -p "$APP/Contents/MacOS"
  clang -O2 -arch arm64 -arch x86_64 -mmacosx-version-min=12.0 \
    -o "$APP/Contents/MacOS/LocalVoiceInput" app/launcher.c
  cat > "$APP/Contents/Info.plist" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>LocalVoiceInput</string>
  <key>CFBundleDisplayName</key><string>LocalVoiceInput</string>
  <key>CFBundleIdentifier</key><string>$LABEL</string>
  <key>CFBundleExecutable</key><string>LocalVoiceInput</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSUIElement</key><true/>
  <key>NSMicrophoneUsageDescription</key><string>按住热键说话时录音,并在本机离线转成文字。</string>
</dict></plist>
PL
  codesign --force --sign - "$APP"
}

case "$1" in
  install)
    # 已有 App 就不重编: 重编会改变签名,系统权限要重新授予
    [ -x "$APP/Contents/MacOS/LocalVoiceInput" ] || build_app
    mkdir -p "$HOME/Library/LaunchAgents"
    cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/open</string><string>-g</string><string>$APP</string>
  </array>
  <key>RunAtLoad</key><true/>
</dict></plist>
PL
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$PLIST"
    echo "已设为开机自启动,并已启动。菜单栏会出现麦克风图标。"
    ;;
  uninstall)
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    pkill -f "$DIR/LocalVoiceInput.app/Contents/MacOS/LocalVoiceInput" 2>/dev/null || true
    echo "已取消开机自启动并退出程序。"
    ;;
  *) echo "用法: $0 install | uninstall"; exit 1 ;;
esac
