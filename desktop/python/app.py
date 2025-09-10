"""桌面版 學習工具：回滾至穩定 CPU + 進度版本，加入安全 GPU fallback。

功能：
1. 本機 faster-whisper 轉錄（large-v3-turbo），自動嘗試 GPU -> CPU。
2. 進度條：本機模式顯示百分比；雲端(openai)模式顯示旋轉不定進度。
3. OpenAI / Google 生成講義，或匯出 transcript + 複製提示詞。
4. API Key 本地加密儲存。
"""

import os
import json
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
from tkinter import ttk
from pathlib import Path
from base64 import urlsafe_b64encode
from cryptography.fernet import Fernet
import requests

# ---------------- Windows DPI -----------------
def _enable_windows_dpi_awareness():
    if os.name != 'nt':
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# ---------------- Local Whisper Availability -----------------
WhisperModel = None  # lazy import
LOCAL_ENABLED = True  # will flip to False if import fails

APP_DIR = Path(__file__).parent
DATA_DIR = APP_DIR / 'data'
DATA_DIR.mkdir(parents=True, exist_ok=True)
CONF_FILE = DATA_DIR / 'config.json'

DEFAULT_PROMPT = (
    "假設您是一位專業講師，請依據以下文字內容，幫我撰寫一份適合放入 Notion 教學模板的教學講義。內容主題來自 [txt字幕輸出後] 的內容，請依格式完成：\n\n"
    "1. 開場導語\n   - 用簡單易懂的語言說明主題的重要性與學習價值。\n\n"
    "2. 教學重點\n   - 條列您在內容中看見的所有核心知識點，並為每個知識點撰寫 2-3 句的簡短說明，與白話解釋，並且提供一個舉例與回答。\n\n"
    "3. 一個實作任務\n   - 提供逐步指引，讓學員能夠親自應用所學。\n   - 描述兩個真實應用情境，幫助學員理解學以致用。\n\n"
    "4. 結語與思考題\n   - 撰寫簡短的收尾語，鼓勵學員持續學習。\n   - 提供 1-2 個思考題，讓學員反思並能與日常生活/工作連結。\n\n"
)

SECRET = urlsafe_b64encode(os.environ.get('STUDY_TOOL_SECRET', 'local-dev-secret').encode().ljust(32, b'0'))
fer = Fernet(SECRET)

def enc(s: str) -> str:
    return fer.encrypt(s.encode()).decode()

def dec(s: str) -> str:
    return fer.decrypt(s.encode()).decode()

def load_config():
    if CONF_FILE.exists():
        try:
            raw = json.loads(CONF_FILE.read_text('utf-8'))
            for k in ('openai','google'):
                if raw.get(k):
                    raw[k] = dec(raw[k])
            return raw
        except Exception:
            return {}
    return {}

def save_config(cfg: dict):
    out = cfg.copy()
    for k in ('openai','google'):
        if out.get(k):
            out[k] = enc(out[k])
    CONF_FILE.write_text(json.dumps(out), encoding='utf-8')

# ------------- Lazy Model (GPU -> CPU fallback) -------------
_LOCAL_MODEL = None
_LOCAL_MODEL_LABEL = ''  # e.g. 'cuda/float16' or 'cpu/int8'
_MODEL_LOCK = threading.Lock()
FORCE_CPU = os.environ.get('STUDY_TOOL_FORCE_CPU') == '1'

def _cuda_runtime_available():
    """粗略檢查是否存在可用 CUDA runtime 與 cuDNN DLL。
    只做快速檢測，避免在無效環境硬嘗試多次造成閃退。
    """
    if FORCE_CPU:
        return False
    if os.name != 'nt':
        # 非 Windows 視為有機會（交給後續 try/except 真正判斷）
        return True
    path_entries = os.environ.get('PATH', '').split(os.pathsep)
    keywords = ['cudnn', 'cublas', 'cudart']
    found_any = False
    for entry in path_entries:
        try:
            if not entry or not os.path.isdir(entry):
                continue
            files = [f.lower() for f in os.listdir(entry)]
            if any(any(k in f for k in keywords) for f in files):
                found_any = True
                break
        except Exception:
            pass
    return found_any

# 嘗試延遲匯入 faster_whisper：若缺少 CUDA DLL，自動隱藏 GPU 讓其走純 CPU。
def _ensure_import_faster_whisper():
    global WhisperModel, LOCAL_ENABLED
    if WhisperModel is not None:
        return
    # 若無 CUDA DLL，避免 GPU 掃描：隱藏 GPU
    if not _cuda_runtime_available():
        os.environ.setdefault('CUDA_VISIBLE_DEVICES', '-1')
    try:
        from faster_whisper import WhisperModel as _WM  # type: ignore
        WhisperModel = _WM
    except Exception:
        LOCAL_ENABLED = False
        WhisperModel = None

def _load_local_model():  # returns model, label
    global _LOCAL_MODEL, _LOCAL_MODEL_LABEL
    if not LOCAL_ENABLED:
        raise RuntimeError('本機模型不可用，請改用 OpenAI 模式')
    if _LOCAL_MODEL is not None:
        return _LOCAL_MODEL, _LOCAL_MODEL_LABEL
    _ensure_import_faster_whisper()
    if WhisperModel is None:
        raise RuntimeError('faster-whisper 未安裝，或初始化失敗')
    # 根據檢測結果決定嘗試列表
    if _cuda_runtime_available():
        attempts = [
            ('cuda', 'float16'),
            ('cuda', 'int8_float16'),
            ('cuda', 'int8'),
            ('cpu', 'int8'),
            ('cpu', 'int8_float16'),
            ('cpu', 'float32'),
        ]
    else:
        attempts = [
            ('cpu', 'int8'),
            ('cpu', 'int8_float16'),
            ('cpu', 'float32'),
        ]
    errors = []
    with _MODEL_LOCK:
        if _LOCAL_MODEL is not None:  # double-check after acquiring lock
            return _LOCAL_MODEL, _LOCAL_MODEL_LABEL
        disable_cuda = False
        for dev, ctype in attempts:
            if disable_cuda and dev == 'cuda':
                continue
            try:
                m = WhisperModel('large-v3-turbo', device=dev, compute_type=ctype)
                _LOCAL_MODEL = m
                _LOCAL_MODEL_LABEL = f'{dev}/{ctype}'
                break
            except Exception as e:
                msg = str(e)
                errors.append(f'{dev}/{ctype}: {msg}')
                lower = msg.lower()
                if 'cudnn' in lower or 'cublas' in lower or 'could not locate' in lower or 'cannot load symbol' in lower:
                    disable_cuda = True
                    os.environ['CUDA_VISIBLE_DEVICES'] = '-1'
        if _LOCAL_MODEL is None:
            hint = ''
            if not _cuda_runtime_available() or FORCE_CPU:
                hint = '\n提示：未偵測到完整 CUDA/cuDNN (或已強制 CPU)，如需 GPU 請安裝對應 CUDA Toolkit 與 cuDNN DLL，或設定 STMP3 環境。'
            raise RuntimeError('本機模型載入失敗:\n' + '\n'.join(errors) + hint)
    return _LOCAL_MODEL, _LOCAL_MODEL_LABEL


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('學習工具（桌面版）')
        self.geometry('1200x890')
        self.resizable(True, True)

        self.cfg = load_config()
        self.audio_path = tk.StringVar()
        self.mode = tk.StringVar(value='local' if LOCAL_ENABLED else 'openai')
        self.openai_key = tk.StringVar(value=self.cfg.get('openai',''))
        self.google_key = tk.StringVar(value=self.cfg.get('google',''))
        self.prompt = tk.StringVar(value=DEFAULT_PROMPT)
        self.is_busy = False
        self._model_loaded = False
        self._model_label = ''

        self._build_ui()
        if os.name == 'nt':
            try:
                dpi = self.winfo_fpixels('1i')
                self.tk.call('tk', 'scaling', dpi/72.0)
            except Exception:
                pass

    # ---------------- UI -----------------
    def _build_ui(self):
        style = ttk.Style()
        try:
            style.theme_use('vista')
        except Exception:
            style.theme_use('clam')
        style.configure('Header.TLabel', font=('Segoe UI', 13, 'bold'))
        style.configure('Card.TLabelframe', padding=10)
        style.configure('Card.TLabelframe.Label', font=('Segoe UI', 11, 'bold'))

        container = ttk.Frame(self)
        container.pack(fill='both', expand=True, padx=14, pady=14)
        ttk.Label(container, text='學習工具：語音轉文字＋講義生成（桌面版）', style='Header.TLabel').pack(anchor='w', pady=(0,8))

        f1 = ttk.Labelframe(container, text='1) 上傳音檔（mp3/wav）', style='Card.TLabelframe')
        f1.pack(fill='x', pady=5)
        self.ent_audio = ttk.Entry(f1, textvariable=self.audio_path, width=80)
        self.ent_audio.pack(side='left', padx=5, pady=5)
        self.btn_choose = ttk.Button(f1, text='選擇檔案', command=self.choose_file)
        self.btn_choose.pack(side='left', padx=5)

        f2 = ttk.Labelframe(container, text='2) 轉錄模式與金鑰', style='Card.TLabelframe')
        f2.pack(fill='x', pady=5)
        self.rb_local = ttk.Radiobutton(f2, text='本機 large-v3-turbo', variable=self.mode, value='local')
        if not LOCAL_ENABLED:
            self.rb_local.state(['disabled'])
        self.rb_local.pack(side='left', padx=8)
        self.rb_openai = ttk.Radiobutton(f2, text='OpenAI Whisper API', variable=self.mode, value='openai')
        self.rb_openai.pack(side='left', padx=8)
        ttk.Label(f2, text='OpenAI API Key:').pack(side='left', padx=5)
        self.ent_openai = ttk.Entry(f2, textvariable=self.openai_key, width=30, show='*')
        self.ent_openai.pack(side='left')
        ttk.Label(f2, text='Google API Key:').pack(side='left', padx=5)
        self.ent_google = ttk.Entry(f2, textvariable=self.google_key, width=30, show='*')
        self.ent_google.pack(side='left')
        self.btn_save_keys = ttk.Button(f2, text='儲存金鑰', command=self.save_keys)
        self.btn_save_keys.pack(side='left', padx=8)

        f3 = ttk.Labelframe(container, text='3) 轉錄與分析', style='Card.TLabelframe')
        f3.pack(fill='both', expand=False, pady=5)
        self.btn_transcribe = ttk.Button(f3, text='開始轉文字', command=self.run_transcribe)
        self.btn_transcribe.pack(side='left', padx=6, pady=6)
        self.status = ttk.Label(f3, text='就緒')
        self.status.pack(side='left', padx=10)
        self.progress = ttk.Progressbar(f3, mode='indeterminate', length=180)
        self.progress.pack(side='left', padx=10)

        f4 = ttk.Labelframe(container, text='4) 轉換文字（txt）', style='Card.TLabelframe')
        f4.pack(fill='both', expand=True, pady=5)
        self.txt_input = scrolledtext.ScrolledText(f4, height=10)
        self.txt_input.pack(fill='both', expand=True)

        f5 = ttk.Labelframe(container, text='5) 分析方式', style='Card.TLabelframe')
        f5.pack(fill='x', pady=5)
        self.provider = tk.StringVar(value='openai')
        self.rb_p_openai = ttk.Radiobutton(f5, text='OpenAI API', variable=self.provider, value='openai')
        self.rb_p_openai.pack(side='left', padx=8)
        self.rb_p_google = ttk.Radiobutton(f5, text='Google AI API', variable=self.provider, value='google')
        self.rb_p_google.pack(side='left', padx=8)
        self.rb_p_export = ttk.Radiobutton(f5, text='直接匯出 txt + 複製指令', variable=self.provider, value='export')
        self.rb_p_export.pack(side='left', padx=8)
        self.btn_analyze = ttk.Button(f5, text='開始分析 / 匯出', command=self.run_analyze)
        self.btn_analyze.pack(side='left', padx=6)

        f6 = ttk.Labelframe(container, text='6) 結果輸出', style='Card.TLabelframe')
        f6.pack(fill='both', expand=True, pady=5)
        self.txt_out = scrolledtext.ScrolledText(f6, height=14)
        self.txt_out.pack(fill='both', expand=True)

        self.statusbar = ttk.Label(self, text='Ready', anchor='w')
        self.statusbar.pack(fill='x', side='bottom')

    # ---------------- Events -----------------
    def choose_file(self):
        p = filedialog.askopenfilename(filetypes=[('Audio','*.mp3 *.wav')])
        if p:
            self.audio_path.set(p)

    def save_keys(self):
        self.cfg['openai'] = self.openai_key.get().strip()
        self.cfg['google'] = self.google_key.get().strip()
        save_config(self.cfg)
        messagebox.showinfo('訊息', '金鑰已儲存')

    def run_transcribe(self):
        path = self.audio_path.get()
        if not path:
            messagebox.showwarning('提醒','請先選擇音檔')
            return
        self._set_busy(True, '正在初始化模型…' if (self.mode.get()=='local' and not self._model_loaded) else '正在生成字幕中…')
        threading.Thread(target=self._do_transcribe, args=(path,), daemon=True).start()

    def _do_transcribe(self, path):
        try:
            if self.mode.get() == 'local' and LOCAL_ENABLED:
                text = self._local_transcribe(path)
            else:
                text = self._openai_transcribe(path)
            self.txt_input.delete('1.0', 'end')
            self.txt_input.insert('end', text)
            suffix = f' (本機 {self._model_label})' if (self.mode.get()=='local' and self._model_loaded) else ''
            self._set_busy(False, f'字幕生成完成{suffix}')
        except Exception as e:
            self._set_busy(False, '字幕生成失敗')
            messagebox.showerror('錯誤', str(e))

    # ---------------- Transcription -----------------
    def _local_transcribe(self, path):
        if not self._model_loaded:
            # 先顯示初始化狀態
            self._update_status_inline('正在載入本機模型 (GPU→CPU fallback)…')
            model, label = _load_local_model()
            self._model_loaded = True
            self._model_label = label
            self._update_status_inline(f'模型已載入：{label}，開始轉錄…')
        else:
            model, label = _LOCAL_MODEL, self._model_label
            self._update_status_inline(f'使用已載入模型：{label}，開始轉錄…')

        # 調整進度條為 determinate
        self._force_progress_mode_determinate()
        segments, info = model.transcribe(path, language='zh', task='transcribe')
        duration = getattr(info, 'duration', 0) or 0
        lines = []
        last_pct = -1
        for seg in segments:
            txt = (seg.text or '').strip()
            if txt:
                lines.append(txt)
            if duration and getattr(seg, 'end', None) is not None:
                pct = int(min(100, max(0, (seg.end / duration) * 100)))
                if pct != last_pct:
                    last_pct = pct
                    self._update_progress(pct)
        if last_pct < 100:
            self._update_progress(100)
        return '\n'.join(lines)

    def _openai_transcribe(self, path):
        key = self.openai_key.get().strip()
        if not key:
            raise RuntimeError('缺少 OpenAI API Key')
        url = 'https://api.openai.com/v1/audio/transcriptions'
        import mimetypes
        mt = mimetypes.guess_type(path)[0] or 'audio/mpeg'
        with open(path, 'rb') as f:
            files = {
                'file': (os.path.basename(path), f, mt),
                'model': (None, 'whisper-1'),
                'language': (None, 'zh'),
                'response_format': (None, 'text')
            }
            headers = { 'Authorization': f'Bearer {key}' }
            r = requests.post(url, files=files, headers=headers, timeout=120)
            if r.status_code >= 300:
                raise RuntimeError(f'OpenAI 轉錄失敗: {r.status_code} {r.text}')
            return r.text.strip()

    # ---------------- Analyze / Export -----------------
    def run_analyze(self):
        txt = self.txt_input.get('1.0', 'end').strip()
        if not txt:
            messagebox.showwarning('提醒','請先完成轉文字')
            return
        prov = self.provider.get()
        if prov == 'export':
            self.clipboard_clear()
            self.clipboard_append(self.prompt.get())
            p = filedialog.asksaveasfilename(defaultextension='.txt', initialfile='transcript.txt')
            if p:
                Path(p).write_text(txt, encoding='utf-8')
            self.txt_out.delete('1.0','end')
            self.txt_out.insert('end','已複製「製作筆記」指令到剪貼簿，並匯出 transcript.txt')
            return
        self._set_busy(True, '正在製作筆記…')
        threading.Thread(target=self._do_analyze, args=(prov, txt), daemon=True).start()

    def _do_analyze(self, prov, txt):
        try:
            prompt = f"{self.prompt.get()}\n\n{txt}"
            if prov == 'openai':
                out = self._openai_analyze(prompt)
            else:
                out = self._google_analyze(prompt)
            self.txt_out.delete('1.0','end')
            self.txt_out.insert('end', out)
            self._set_busy(False, '筆記完成')
        except Exception as e:
            self._set_busy(False, '筆記失敗')
            messagebox.showerror('錯誤', str(e))

    # ---------------- Busy / Progress -----------------
    def _force_progress_mode_determinate(self):
        try:
            if str(self.progress.cget('mode')) != 'determinate':
                self.progress.config(mode='determinate', maximum=100, value=0)
            else:
                self.progress.config(value=0)
        except Exception:
            pass

    def _set_busy(self, busy: bool, msg: str = ''):
        self.is_busy = busy
        try:
            if busy:
                if self.mode.get() == 'local' and LOCAL_ENABLED:
                    self._force_progress_mode_determinate()
                else:
                    if str(self.progress.cget('mode')) != 'indeterminate':
                        self.progress.config(mode='indeterminate')
                    self.progress.start(12)
            else:
                if str(self.progress.cget('mode')) == 'indeterminate':
                    self.progress.stop()
                # 保留最後進度顯示，不強制清零
        except Exception:
            pass
        self.status.config(text=msg or ('處理中…' if busy else '就緒'))
        self.statusbar.config(text=msg or ('處理中…' if busy else 'Ready'))
        widgets = [
            self.btn_choose, self.btn_save_keys, self.btn_transcribe, self.btn_analyze,
            self.rb_local, self.rb_openai, self.rb_p_openai, self.rb_p_google, self.rb_p_export,
            self.ent_audio, self.ent_openai, self.ent_google
        ]
        for w in widgets:
            try:
                if busy:
                    w.state(['disabled']) if isinstance(w, ttk.Widget) else w.config(state='disabled')
                else:
                    w.state(['!disabled']) if isinstance(w, ttk.Widget) else w.config(state='normal')
            except Exception:
                pass

    def _update_status_inline(self, msg: str):
        def _do():
            self.status.config(text=msg)
            self.statusbar.config(text=msg)
        try:
            self.after(0, _do)
        except Exception:
            pass

    def _update_progress(self, pct: int):
        def _do():
            if str(self.progress.cget('mode')) == 'determinate':
                try:
                    self.progress.config(value=pct)
                except Exception:
                    pass
            if self.is_busy:
                base = '正在生成字幕中…'
                self.status.config(text=f"{base} {pct}%")
                self.statusbar.config(text=f"{base} {pct}%")
        try:
            self.after(0, _do)
        except Exception:
            pass

    # ---------------- AI Providers -----------------
    def _openai_analyze(self, prompt):
        key = self.openai_key.get().strip()
        if not key:
            raise RuntimeError('缺少 OpenAI API Key')
        url = 'https://api.openai.com/v1/chat/completions'
        body = {
            'model': 'gpt-4o-mini',
            'messages': [
                { 'role': 'system', 'content': '你是專業講師與教學設計助理，請生成結構化、清晰、可教學的內容。'},
                { 'role': 'user', 'content': prompt }
            ],
            'temperature': 0.7
        }
        r = requests.post(url, json=body, headers={ 'Authorization': f'Bearer {key}' }, timeout=120)
        if r.status_code >= 300:
            raise RuntimeError(f'OpenAI 分析失敗: {r.status_code} {r.text}')
        j = r.json()
        return j['choices'][0]['message']['content'].strip()

    def _google_analyze(self, prompt):
        key = self.google_key.get().strip()
        if not key:
            raise RuntimeError('缺少 Google API Key')
        url = f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={key}'
        body = { 'contents': [{ 'role': 'user', 'parts': [{ 'text': prompt }] }] }
        r = requests.post(url, json=body, timeout=120)
        if r.status_code >= 300:
            raise RuntimeError(f'Google 分析失敗: {r.status_code} {r.text}')
        j = r.json()
        return (j.get('candidates',[{}])[0].get('content',{}).get('parts',[{}])[0].get('text','')).strip()


if __name__ == '__main__':
    _enable_windows_dpi_awareness()
    App().mainloop()
