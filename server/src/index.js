import 'dotenv/config';
import express from 'express';
import cors from 'cors';
import multer from 'multer';
import { createWhisperTranscription } from './services/whisper.js';
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
app.post('/api/transcribe', upload.single('audio'), async (req, res) => {
  try {
    if (!req.file) return res.status(400).json({ error: '缺少 audio 檔案' });
  const mime = req.file.mimetype;
  const okMimes = new Set(['audio/mpeg','audio/mp3','audio/wav','audio/x-wav','audio/wave','audio/x-pn-wav']);
  if (!okMimes.has(mime)) {
      return res.status(400).json({ error: '僅支援 mp3 或 wav' });
    }
    const buf = req.file.buffer;
    const txt = await createWhisperTranscription(buf, req.file.originalname);
    res.json({ text: txt });
  } catch (e) {
    console.error('Transcribe error:', e);
    res.status(500).json({ error: e?.response?.data || e?.message || 'Unknown error' });
  }
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
