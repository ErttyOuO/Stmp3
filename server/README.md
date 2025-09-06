# 後端（server）

## 啟動

1. 複製 `.env.example` 為 `.env` 並填入必要金鑰。
2. 啟動伺服器：`npm run dev`（或 `npm start`）。

預設 http://localhost:3001

## Whisper 模式
- 預設使用 OpenAI Whisper API（`WHISPER_MODE=api`）
- 若要使用本機 large-v3-turbo：
	- 安裝 Python 3.9+ 與套件：`pip install -r requirements.txt`
	- `.env` 設定：
		- `WHISPER_MODE=local`
		- `LOCAL_WHISPER_MODEL=large-v3-turbo`
		- `LOCAL_DEVICE=cpu`（或 `cuda`）
		- `LOCAL_COMPUTE=int8`（或 `float16`）
	- 可設定 `PYTHON_EXEC=python`（或 `python3`）

## API
 - POST /api/analyze { provider: 'openai' | 'google', text } (default/example: gemini-2.5-flash)
