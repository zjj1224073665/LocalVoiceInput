#!/bin/bash
# 在新 Mac 上首次运行: 建虚拟环境、装依赖、下载模型
set -e
cd "$(dirname "$0")"
MODEL=Qwen3-ASR-1.7B-8bit
PY=$(command -v python3.12 || command -v python3)
"$PY" -c 'import sys; assert sys.version_info >= (3, 10), "需要 Python 3.10 以上"'
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q "mlx-audio==0.6.1" sounddevice pynput numpy
if [ ! -f "models/$MODEL/model.safetensors" ]; then
  .venv/bin/hf download "mlx-community/$MODEL" --local-dir "models/$MODEL"
fi
echo "安装完成,双击 start.command 启动"
