# 桌面版（Python / Tkinter）

免瀏覽器、雙擊可執行（或 `python app.py`）的簡易桌面 GUI：
- 上傳 mp3/wav
- 轉錄：本機 large-v3-turbo 或 OpenAI Whisper API
- 分析：OpenAI / Google / 直接匯出 txt（並複製模板指令）
- 金鑰本機儲存（加密）

## 安裝
1. 安裝 Python 3.9+
2. 安裝依賴
```powershell
cd "c:\Users\[使用者名稱]\Desktop\學習工具\desktop\python"
pip install -r requirements.txt
```

## 執行
```powershell
python app.py
```

首次開啟可在「設定」頁面輸入 API Key 與選擇轉錄模式。
