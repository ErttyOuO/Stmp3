import 'dotenv/config';
import express from 'express';
import cors from 'cors';
import multer from 'multer';
import { createWhisperTranscription } from './services/whisper.js';
import { spawn } from 'node:child_process';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { writeFile, readFile } from 'node:fs/promises';
import { analyzeWithOpenAI } from './services/openai.js';
import { analyzeWithGoogle } from './services/google.js';
import { ensureDb, getKey, setKey } from './services/keys.js';
import { addNotePrefix } from './services/prompt.js';

const app = express();
app.use(cors());
app.use(express.json({ limit: '25mb' }));
app.use(express.urlencoded({ extended: true }));

ensureDb();

const upload = multer({ storage: multer.memoryStorage(), limits: { fileSize: 100 * 1024 * 1024 } });

// 簡易記憶體 job 儲存（若需長期可改 DB / Redis）
const jobs = new Map(); // id -> { status, progress, result, error }
import { randomUUID } from 'node:crypto';

app.get('/health', (_req, res) => {
  res.json({ ok: true, ts: Date.now() });
});

// 造訪根路由時的簡單說明，避免看到 "Cannot GET /"
app.get('/', (_req, res) => {
  res.type('text').send('API server is running. Use /api endpoints.');
});

// 儲存或取得 API Key
app.post('/api/keys', async (req, res) => {
  const { provider, apiKey } = req.body || {};
  if (!provider || !apiKey) return res.status(400).json({ error: 'provider 與 apiKey 必填' });
  try {
    await setKey(provider, apiKey);
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.get('/api/keys/:provider', async (req, res) => {
  const provider = req.params.provider;
  try {
    const masked = await getKey(provider, true);
    res.json({ provider, key: masked });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// 上傳音檔並轉文字
// 新：非同步轉錄（回傳 jobId，前端輪詢進度）
app.post('/api/transcribe', upload.single('audio'), async (req, res) => {
  try {
    if (!req.file) return res.status(400).json({ error: '缺少 audio 檔案' });
    const mime = req.file.mimetype;
    const okMimes = new Set(['audio/mpeg','audio/mp3','audio/wav','audio/x-wav','audio/wave','audio/x-pn-wav']);
    if (!okMimes.has(mime)) {
      return res.status(400).json({ error: '僅支援 mp3 或 wav' });
    }

    const mode = (process.env.WHISPER_MODE || 'api').toLowerCase();
    // API 模式先維持同步（速度較快）
    if (mode !== 'local') {
      const buf = req.file.buffer;
      const txt = await createWhisperTranscription(buf, req.file.originalname);
      return res.json({ text: txt, mode: 'api', done: true });
    }

    const jobId = randomUUID();
    jobs.set(jobId, { status: 'processing', progress: 0, result: null, error: null });
    res.json({ jobId, mode: 'local', done: false });

    // 背景執行本地 whisper（含進度）
    const wavPath = join(tmpdir(), `in-${jobId}-${req.file.originalname}`);
    const outPath = join(tmpdir(), `out-${jobId}.txt`);
    await writeFile(wavPath, req.file.buffer);

    const py = process.env.PYTHON_EXEC || 'python';
    const model = process.env.LOCAL_WHISPER_MODEL || 'large-v3-turbo';
    const device = process.env.LOCAL_DEVICE || 'cpu';
    const compute = process.env.LOCAL_COMPUTE || 'int8';
    const script = join(process.cwd(), 'src', 'services', 'whisper_local.py');
    const args = [script, wavPath, outPath, model, device, compute];
    const ps = spawn(py, args, { stdio: ['ignore', 'pipe', 'pipe'] });
    ps.stdout.on('data', d => {
      const lines = d.toString().split(/\n+/).filter(Boolean);
      for (const line of lines) {
        const m = line.match(/PROGRESS (\d{1,3})/);
        if (m) {
          const pct = Math.min(100, parseInt(m[1], 10));
          const job = jobs.get(jobId);
          if (job && job.status === 'processing') {
            job.progress = pct;
          }
        }
      }
    });
    let stderr = '';
    ps.stderr.on('data', d => { stderr += d.toString(); });
    ps.on('close', async code => {
      const job = jobs.get(jobId);
      if (!job) return;
      if (code === 0) {
        try {
          const text = await readFile(outPath, 'utf8');
          job.status = 'done';
          job.progress = 100;
          job.result = text.trim();
        } catch (err) {
          job.status = 'error';
          job.error = err.message;
        }
      } else {
        job.status = 'error';
        job.error = stderr || `exit code ${code}`;
      }
    });
  } catch (e) {
    console.error('Transcribe error:', e);
    res.status(500).json({ error: e?.response?.data || e?.message || 'Unknown error' });
  }
});

// 查詢轉錄進度
app.get('/api/transcribe/:jobId', (req, res) => {
  const job = jobs.get(req.params.jobId);
  if (!job) return res.status(404).json({ error: 'job 不存在' });
  res.json(job);
});

// 分析文字（OpenAI / Google）
app.post('/api/analyze', async (req, res) => {
  try {
    const { provider, text } = req.body || {};
    if (!provider || !text) return res.status(400).json({ error: 'provider 與 text 必填' });
    const prompt = addNotePrefix(text);

    if (provider === 'openai') {
      const out = await analyzeWithOpenAI(prompt);
      return res.json({ result: out });
    }
    if (provider === 'google') {
      const out = await analyzeWithGoogle(prompt);
      return res.json({ result: out });
    }
    return res.status(400).json({ error: '未知 provider' });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// 匯出 txt 並複製「製作筆記」指令
app.post('/api/export', async (req, res) => {
  try {
    const { text } = req.body || {};
    if (!text) return res.status(400).json({ error: 'text 必填' });
    const prompt = addNotePrefix('');
    res.json({ prompt, text });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

const PORT = process.env.PORT || 3001;
app.listen(PORT, () => console.log(`server listening on port ${PORT}`));
