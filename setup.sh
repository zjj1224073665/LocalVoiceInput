#!/bin/bash
# 在新 Mac 上首次运行: 建虚拟环境、装依赖、下载模型
set -e
cd "$(dirname "$0")"
MODEL=sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q sherpa-onnx sounddevice pynput numpy
if [ ! -f "models/$MODEL/model.int8.onnx" ]; then
  mkdir -p models
  curl -L -o models/sv.tar.bz2 "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/$MODEL.tar.bz2"
  tar xjf models/sv.tar.bz2 -C models && rm models/sv.tar.bz2
fi
echo "安装完成,双击 start.command 启动"
