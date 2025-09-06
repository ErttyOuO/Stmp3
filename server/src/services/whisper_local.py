import sys
import os
from pathlib import Path

# 依需求可改用 faster-whisper 或 openai-whisper
# 這裡示範 faster-whisper（速度快、可選 int8/cpu）

try:
    from faster_whisper import WhisperModel
except ImportError:
    print("Missing dependency: faster-whisper. Install with: pip install faster-whisper\n", file=sys.stderr)
    sys.exit(2)

if len(sys.argv) < 6:
    print("Usage: python whisper_local.py <in_audio> <out_txt> <model_name> <device> <compute>", file=sys.stderr)
    sys.exit(2)

in_audio = sys.argv[1]
out_txt = sys.argv[2]
model_name = sys.argv[3]
device = sys.argv[4]  # 'cpu' or 'cuda'
compute = sys.argv[5]  # 'int8' | 'float16' | 'auto'

# 建模參數
kwargs = {}
if device == 'cuda':
    kwargs["device"] = "cuda"
    if compute == 'float16' or compute == 'auto':
        kwargs["compute_type"] = "float16"
    elif compute == 'int8':
        kwargs["compute_type"] = "int8_float16"
else:
    kwargs["device"] = "cpu"
    if compute == 'int8' or compute == 'auto':
        kwargs["compute_type"] = "int8"
    else:
        kwargs["compute_type"] = "int8"  # 預設

model = WhisperModel(model_name, **kwargs)

segments, info = model.transcribe(in_audio, language="zh", task="transcribe")

with open(out_txt, 'w', encoding='utf-8') as f:
    for segment in segments:
        f.write(segment.text.strip() + "\n")
