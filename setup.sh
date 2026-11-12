#!/bin/bash
# 在新 Mac 上首次运行: 建虚拟环境、装依赖、下载模型
set -e
cd "$(dirname "$0")"
MODEL=whisper-large-v3-turbo
PY=$(command -v python3.12 || command -v python3)
"$PY" -c 'import sys; assert sys.version_info >= (3, 10), "需要 Python 3.10 以上"'
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q "mlx-audio==0.6.1" sounddevice pynput numpy
if [ ! -f "models/$MODEL/weights.safetensors" ]; then
  .venv/bin/hf download "mlx-community/$MODEL" --local-dir "models/$MODEL"
fi
# MLX 版只有权重,分词器和预处理配置从 OpenAI 官方仓库补齐
if [ ! -f "models/$MODEL/tokenizer.json" ]; then
  .venv/bin/hf download "openai/$MODEL" preprocessor_config.json tokenizer.json tokenizer_config.json \
    vocab.json merges.txt normalizer.json added_tokens.json special_tokens_map.json generation_config.json \
    --local-dir "models/$MODEL"
fi
echo "安装完成,双击 start.command 启动"
