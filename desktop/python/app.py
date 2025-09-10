"""學習工具（桌面版）穩定精簡版
功能:
 1. 本機 faster-whisper (large-v3-turbo) 語音轉文字，顯示進度
 2. GPU→CPU 安全 fallback (缺 cuDNN / CUDA 不崩潰，自動改 CPU)
 3. OpenAI Whisper API 備用
 4. 分析：OpenAI / Google / 匯出+複製指令
 5. 金鑰加密儲存 (Fernet) 於 data/config.json

環境變數:
  STUDY_TOOL_FORCE_CPU=1          強制只用 CPU
  STUDY_TOOL_CUDNN_DIR=dir1;dir2  追加搜尋 cuDNN / CUDA DLL 目錄 (Windows)
"""

from __future__ import annotations
import os, json, threading, tkinter as tk, requests, mimetypes
from tkinter import ttk, filedialog, messagebox, scrolledtext
from pathlib import Path
from base64 import urlsafe_b64encode
from cryptography.fernet import Fernet

APP_DIR = Path(__file__).parent
DATA_DIR = APP_DIR / 'data'
DATA_DIR.mkdir(exist_ok=True)
CONF_FILE = DATA_DIR / 'config.json'

DEFAULT_PROMPT = (
    "假設您是一位專業講師，請依據以下文字內容，幫我撰寫一份適合放入 Notion 教學模板的教學講義。內容主題來自 [txt字幕輸出後] 的內容，請依格式完成：\n\n"
    "1. 開場導語\n   - 用簡單易懂的語言說明主題的重要性與學習價值。\n\n"
    "2. 教學重點\n   - 條列您在內容中看見的所有核心知識點，並為每個知識點撰寫 2-3 句的簡短說明，與白話解釋，並且提供一個舉例與回答。\n\n"
    "3. 一個實作任務\n   - 提供逐步指引，讓學員能夠親自應用所學。\n   - 描述兩個真實應用情境，幫助學員理解學以致用。\n\n"
    "4. 結語與思考題\n   - 撰寫簡短的收尾語，鼓勵學員持續學習。\n   - 提供 1-2 個思考題，讓學員反思並能與日常生活/工作連結。\n\n"
)

SECRET = urlsafe_b64encode(os.environ.get('STUDY_TOOL_SECRET','local-dev-secret').encode().ljust(32,b'0'))
fer = Fernet(SECRET)
def _enc(s:str)->str: return fer.encrypt(s.encode()).decode()
def _dec(s:str)->str: return fer.decrypt(s.encode()).decode()

def load_config():
    if not CONF_FILE.exists(): return {}
    try:
        raw=json.loads(CONF_FILE.read_text('utf-8'))
        for k in ('openai','google'):
            if raw.get(k): raw[k]=_dec(raw[k])
        return raw
    except Exception:
        return {}

def save_config(cfg:dict):
    out=cfg.copy()
    for k in ('openai','google'):
        if out.get(k): out[k]=_enc(out[k])
    CONF_FILE.write_text(json.dumps(out),encoding='utf-8')

WhisperModel=None
LOCAL_ENABLED=True
_LOCAL_MODEL=None
_LOCAL_MODEL_LABEL=''
_MODEL_LOCK=threading.Lock()
FORCE_CPU = os.environ.get('STUDY_TOOL_FORCE_CPU')=='1'

def _add_cudnn_paths():
    if os.name!='nt': return
    extra=os.environ.get('STUDY_TOOL_CUDNN_DIR')
    if not extra: return
    for p in extra.split(';'):
        p=p.strip()
        if p and Path(p).is_dir():
            try: os.add_dll_directory(p)
            except Exception: pass
            if p not in os.environ.get('PATH',''):
                os.environ['PATH']=p+os.pathsep+os.environ.get('PATH','')

def _maybe_import_model():
    global WhisperModel, LOCAL_ENABLED
    if WhisperModel is not None: return
    _add_cudnn_paths()
    if FORCE_CPU:
        os.environ.setdefault('CUDA_VISIBLE_DEVICES','-1')
    try:
        from faster_whisper import WhisperModel as WM  # type: ignore
        WhisperModel = WM
    except Exception:
        LOCAL_ENABLED=False
        WhisperModel=None

def _load_local_model():
    global _LOCAL_MODEL,_LOCAL_MODEL_LABEL
    if not LOCAL_ENABLED:
        raise RuntimeError('本機模型不可用，請改用 OpenAI Whisper')
    if _LOCAL_MODEL is not None: return _LOCAL_MODEL,_LOCAL_MODEL_LABEL
    _maybe_import_model()
    if WhisperModel is None:
        raise RuntimeError('faster-whisper 未安裝或初始化失敗')
    attempts = [] if FORCE_CPU else [('cuda','float16'),('cuda','int8_float16'),('cuda','int8')]
    attempts += [('cpu','int8'),('cpu','int8_float16'),('cpu','float32')]
    errs=[]
    with _MODEL_LOCK:
        if _LOCAL_MODEL is not None: return _LOCAL_MODEL,_LOCAL_MODEL_LABEL
        for dev,ctype in attempts:
            try:
                m=WhisperModel('large-v3-turbo', device=dev, compute_type=ctype)
                _LOCAL_MODEL=m; _LOCAL_MODEL_LABEL=f'{dev}/{ctype}'
                break
            except Exception as e:
                msg=str(e); errs.append(f'{dev}/{ctype}: {msg}')
                if ('cudnn' in msg.lower() or 'cublas' in msg.lower()) and dev=='cuda':
                    # 停止後續 CUDA 嘗試
                    attempts=[t for t in attempts if t[0]!='cuda']
        if _LOCAL_MODEL is None:
            raise RuntimeError('模型載入失敗 (已改 CPU):\n'+'\n'.join(errs))
    return _LOCAL_MODEL,_LOCAL_MODEL_LABEL

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('學習工具（桌面版）')
        self.geometry('1150x860')
        self.cfg=load_config()
        self.audio_path=tk.StringVar()
        self.mode=tk.StringVar(value='local' if LOCAL_ENABLED else 'openai')
        self.openai_key=tk.StringVar(value=self.cfg.get('openai',''))
        self.google_key=tk.StringVar(value=self.cfg.get('google',''))
        self.prompt=tk.StringVar(value=DEFAULT_PROMPT)
        self.provider=tk.StringVar(value='openai')
        self.is_busy=False
        self._model_loaded=False
        self._model_label=''
        self._build_ui()

    # UI
    def _build_ui(self):
        style=ttk.Style()
        try: style.theme_use('vista')
        except Exception: style.theme_use('clam')
        style.configure('Header.TLabel', font=('Segoe UI',13,'bold'))
        root=ttk.Frame(self); root.pack(fill='both',expand=True,padx=14,pady=14)
        ttk.Label(root,text='學習工具：語音轉文字＋講義生成',style='Header.TLabel').pack(anchor='w',pady=(0,8))

        f1=ttk.Labelframe(root,text='1) 音檔',padding=8); f1.pack(fill='x',pady=5)
        ttk.Entry(f1,textvariable=self.audio_path,width=78).pack(side='left',padx=4)
        ttk.Button(f1,text='選擇檔案',command=self.choose_file).pack(side='left',padx=4)

        f2=ttk.Labelframe(root,text='2) 模式 / 金鑰',padding=8); f2.pack(fill='x',pady=5)
        self.rb_local=ttk.Radiobutton(f2,text='本機 large-v3-turbo',variable=self.mode,value='local'); self.rb_local.pack(side='left',padx=6)
        if not LOCAL_ENABLED: self.rb_local.state(['disabled'])
        self.rb_openai=ttk.Radiobutton(f2,text='OpenAI Whisper API',variable=self.mode,value='openai'); self.rb_openai.pack(side='left',padx=6)
        ttk.Label(f2,text='OpenAI:').pack(side='left',padx=(12,3))
        self.ent_openai=ttk.Entry(f2,textvariable=self.openai_key,width=24,show='*'); self.ent_openai.pack(side='left')
        ttk.Label(f2,text='Google:').pack(side='left',padx=(12,3))
        self.ent_google=ttk.Entry(f2,textvariable=self.google_key,width=24,show='*'); self.ent_google.pack(side='left')
        ttk.Button(f2,text='儲存金鑰',command=self.save_keys).pack(side='left',padx=8)
        self.lbl_device=ttk.Label(f2,text='(device: 未載入'+(' /CPU' if FORCE_CPU else '')+')'); self.lbl_device.pack(side='left',padx=6)

        f3=ttk.Labelframe(root,text='3) 轉錄',padding=8); f3.pack(fill='x',pady=5)
        self.btn_transcribe=ttk.Button(f3,text='開始轉文字',command=self.run_transcribe); self.btn_transcribe.pack(side='left',padx=6)
        self.status=ttk.Label(f3,text='就緒'); self.status.pack(side='left',padx=10)
        self.progress=ttk.Progressbar(f3,mode='indeterminate',length=210); self.progress.pack(side='left',padx=10)

        f4=ttk.Labelframe(root,text='4) 轉換文字 (txt)',padding=8); f4.pack(fill='both',expand=True,pady=5)
        self.txt_input=scrolledtext.ScrolledText(f4,height=10); self.txt_input.pack(fill='both',expand=True)

        f5=ttk.Labelframe(root,text='5) 分析方式',padding=8); f5.pack(fill='x',pady=5)
        ttk.Radiobutton(f5,text='OpenAI',variable=self.provider,value='openai').pack(side='left',padx=6)
        ttk.Radiobutton(f5,text='Google',variable=self.provider,value='google').pack(side='left',padx=6)
        ttk.Radiobutton(f5,text='匯出+複製指令',variable=self.provider,value='export').pack(side='left',padx=6)
        self.btn_analyze=ttk.Button(f5,text='開始分析 / 匯出',command=self.run_analyze); self.btn_analyze.pack(side='left',padx=12)

        f6=ttk.Labelframe(root,text='6) 結果輸出',padding=8); f6.pack(fill='both',expand=True,pady=5)
        self.txt_out=scrolledtext.ScrolledText(f6,height=16); self.txt_out.pack(fill='both',expand=True)

        self.statusbar=ttk.Label(self,text='Ready',anchor='w'); self.statusbar.pack(fill='x',side='bottom')

    # Events / actions
    def choose_file(self):
        p=filedialog.askopenfilename(filetypes=[('Audio','*.mp3 *.wav')])
        if p: self.audio_path.set(p)

    def save_keys(self):
        cfg=load_config(); cfg['openai']=self.openai_key.get().strip(); cfg['google']=self.google_key.get().strip(); save_config(cfg)
        messagebox.showinfo('訊息','金鑰已儲存')

    # Transcribe
    def run_transcribe(self):
        if not self.audio_path.get():
            messagebox.showwarning('提醒','請先選擇音檔'); return
        self._set_busy(True,'正在初始化模型…' if (self.mode.get()=='local' and not self._model_loaded) else '正在生成字幕中…')
        threading.Thread(target=self._do_transcribe,daemon=True).start()

    def _do_transcribe(self):
        try:
            if self.mode.get()=='local' and LOCAL_ENABLED:
                txt=self._local_transcribe(self.audio_path.get())
            else:
                txt=self._openai_transcribe(self.audio_path.get())
            self.txt_input.delete('1.0','end'); self.txt_input.insert('end',txt)
            suffix=f' (本機 {self._model_label})' if (self.mode.get()=='local' and self._model_loaded) else ''
            self._set_busy(False,'字幕生成完成'+suffix)
        except Exception as e:
            self._set_busy(False,'字幕生成失敗'); messagebox.showerror('錯誤',str(e))

    def _local_transcribe(self,path:str):
        if not self._model_loaded:
            self._update_status('正在載入本機模型 (GPU→CPU fallback)…')
            model,label=_load_local_model(); self._model_loaded=True; self._model_label=label; self._update_device(label)
            self._update_status(f'模型已載入：{label}，開始轉錄…')
        else:
            model,label=_LOCAL_MODEL,self._model_label
            self._update_status(f'使用已載入模型：{label}，開始轉錄…'); self._update_device(label)
        self._progress_to_determinate()
        segments,info=model.transcribe(path,language='zh',task='transcribe')  # type: ignore
        duration=getattr(info,'duration',0) or 0
        lines=[]; last=-1
        for seg in segments:
            t=(seg.text or '').strip()
            if t: lines.append(t)
            if duration and getattr(seg,'end',None) is not None:
                pct=int(min(100,max(0,seg.end/duration*100)))
                if pct!=last: last=pct; self._update_progress(pct)
        if last<100: self._update_progress(100)
        return '\n'.join(lines)

    def _openai_transcribe(self,path:str):
        key=self.openai_key.get().strip()
        if not key: raise RuntimeError('缺少 OpenAI API Key')
        mt=mimetypes.guess_type(path)[0] or 'audio/mpeg'
        url='https://api.openai.com/v1/audio/transcriptions'
        with open(path,'rb') as f:
            files={'file':(os.path.basename(path),f,mt),'model':(None,'whisper-1'),'language':(None,'zh'),'response_format':(None,'text')}
            r=requests.post(url,files=files,headers={'Authorization':f'Bearer {key}'},timeout=180)
            if r.status_code>=300: raise RuntimeError(f'OpenAI 轉錄失敗: {r.status_code} {r.text}')
            return r.text.strip()

    # Analyze / Export
    def run_analyze(self):
        txt=self.txt_input.get('1.0','end').strip()
        if not txt: messagebox.showwarning('提醒','請先完成轉文字'); return
        if self.provider.get()=='export':
            self.clipboard_clear(); self.clipboard_append(self.prompt.get())
            p=filedialog.asksaveasfilename(defaultextension='.txt',initialfile='transcript.txt')
            if p: Path(p).write_text(txt,encoding='utf-8')
            self.txt_out.delete('1.0','end'); self.txt_out.insert('end','已複製「製作筆記」指令並匯出 transcript.txt'); return
        self._set_busy(True,'正在製作筆記…')
        threading.Thread(target=self._do_analyze,daemon=True).start()

    def _do_analyze(self):
        try:
            txt=self.txt_input.get('1.0','end').strip()
            prompt_full=f"{self.prompt.get()}\n\n{txt}"
            if self.provider.get()=='openai': out=self._openai_analyze(prompt_full)
            else: out=self._google_analyze(prompt_full)
            self.txt_out.delete('1.0','end'); self.txt_out.insert('end',out)
            self._set_busy(False,'筆記完成')
        except Exception as e:
            self._set_busy(False,'筆記失敗'); messagebox.showerror('錯誤',str(e))

    # Busy / progress helpers
    def _progress_to_determinate(self):
        try:
            if str(self.progress.cget('mode'))!='determinate':
                self.progress.config(mode='determinate',maximum=100,value=0)
            else: self.progress.config(value=0)
        except Exception: pass

    def _set_busy(self,busy:bool,msg:str=''):
        self.is_busy=busy
        try:
            if busy:
                if self.mode.get()=='local' and LOCAL_ENABLED: self._progress_to_determinate()
                else:
                    if str(self.progress.cget('mode'))!='indeterminate': self.progress.config(mode='indeterminate')
                    self.progress.start(12)
            else:
                if str(self.progress.cget('mode'))=='indeterminate': self.progress.stop()
        except Exception: pass
        self.status.config(text=msg or ('處理中…' if busy else '就緒'))
        self.statusbar.config(text=msg or ('處理中…' if busy else 'Ready'))
        for w in [self.btn_transcribe,self.btn_analyze,self.rb_local,self.rb_openai,self.ent_openai,self.ent_google]:
            try: w.state(['disabled']) if busy else w.state(['!disabled'])
            except Exception: pass

    def _update_status(self,msg:str):
        try: self.after(0,lambda:(self.status.config(text=msg),self.statusbar.config(text=msg)))
        except Exception: pass

    def _update_progress(self,pct:int):
        def _do():
            if str(self.progress.cget('mode'))=='determinate':
                try: self.progress.config(value=pct)
                except Exception: pass
            if self.is_busy:
                base='正在生成字幕中…'; self.status.config(text=f'{base} {pct}%'); self.statusbar.config(text=f'{base} {pct}%')
        try: self.after(0,_do)
        except Exception: pass

    def _update_device(self,label:str):
        try: self.lbl_device.config(text=f'(device: {label})')
        except Exception: pass

    # Providers
    def _openai_analyze(self,prompt:str):
        key=self.openai_key.get().strip()
        if not key: raise RuntimeError('缺少 OpenAI API Key')
        body={'model':'gpt-4o-mini','messages':[{'role':'system','content':'你是專業講師與教學設計助理，請生成結構化、清晰、可教學的內容。'},{'role':'user','content':prompt}], 'temperature':0.7}
        r=requests.post('https://api.openai.com/v1/chat/completions',json=body,headers={'Authorization':f'Bearer {key}'},timeout=120)
        if r.status_code>=300: raise RuntimeError(f'OpenAI 分析失敗: {r.status_code} {r.text}')
        return r.json()['choices'][0]['message']['content'].strip()

    def _google_analyze(self,prompt:str):
        key=self.google_key.get().strip()
        if not key: raise RuntimeError('缺少 Google API Key')
        url=f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={key}'
        body={'contents':[{'role':'user','parts':[{'text':prompt}]}]}
        r=requests.post(url,json=body,timeout=120)
        if r.status_code>=300: raise RuntimeError(f'Google 分析失敗: {r.status_code} {r.text}')
        j=r.json(); return (j.get('candidates',[{}])[0].get('content',{}).get('parts',[{}])[0].get('text','')).strip()

def _enable_windows_dpi_awareness():
    if os.name!='nt': return
    try:
        import ctypes
        try: ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception: ctypes.windll.user32.SetProcessDPIAware()
    except Exception: pass

if __name__=='__main__':
    _enable_windows_dpi_awareness()
    App().mainloop()
