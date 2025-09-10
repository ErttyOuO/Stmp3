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

duration = getattr(info, 'duration', None) or 0.0
last_progress = -1

with open(out_txt, 'w', encoding='utf-8') as f:
    for segment in segments:
        text = (segment.text or '').strip()
        if text:
            f.write(text + "\n")
        # 計算進度：使用片段結束時間 / 總長度
        if duration and getattr(segment, 'end', None) is not None:
            pct = int(min(100, max(0, (segment.end / duration) * 100)))
            # 僅在整數進度前進時輸出，減少雜訊
            if pct != last_progress:
                print(f"PROGRESS {pct}", flush=True)
                last_progress = pct

# 確保最終輸出 100
if last_progress < 100:
    print("PROGRESS 100", flush=True)
