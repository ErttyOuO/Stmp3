import OpenAI from 'openai';
import { getKey } from './keys.js';
import { spawn } from 'node:child_process';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { writeFile, readFile, unlink } from 'node:fs/promises';

export async function createWhisperTranscription(fileBuffer, filename) {
  const mode = (process.env.WHISPER_MODE || 'api').toLowerCase();
  if (mode === 'local') {
    return transcribeLocal(fileBuffer, filename);
  }
  return transcribeWithOpenAI(fileBuffer, filename);
}

async function transcribeWithOpenAI(fileBuffer, filename) {
  const key = (await getKey('openai')) || process.env.OPENAI_API_KEY;
  if (!key) throw new Error('缺少 OpenAI API Key');
  const client = new OpenAI({ apiKey: key });

  const file = await OpenAI.toFile(fileBuffer, filename);
  const resp = await client.audio.transcriptions.create({
    file,
    model: process.env.WHISPER_MODEL || 'whisper-1',
    language: 'zh',
    response_format: 'text'
  });

  if (typeof resp === 'string') return resp.trim();
  if (resp?.text) return resp.text.trim();
  return String(resp || '').trim();
}

async function transcribeLocal(fileBuffer, filename) {
  const tmpAudio = join(tmpdir(), `audio-${Date.now()}-${filename}`);
  const tmpOut = join(tmpdir(), `trans-${Date.now()}.txt`);
  await writeFile(tmpAudio, fileBuffer);

  const py = process.env.PYTHON_EXEC || 'python';
  const model = process.env.LOCAL_WHISPER_MODEL || 'large-v3-turbo';
  const device = process.env.LOCAL_DEVICE || 'cpu';
  const compute = process.env.LOCAL_COMPUTE || 'int8';

  const args = ['-u', join(process.cwd(), 'src', 'services', 'whisper_local.py'), tmpAudio, tmpOut, model, device, compute];

  const code = await new Promise((resolve, reject) => {
    const ps = spawn(py, args, { stdio: ['ignore', 'pipe', 'pipe'] });
    let stderr = '';
    ps.stderr.on('data', d => { stderr += d.toString(); });
    ps.on('close', c => {
      if (c === 0) resolve(c); else reject(new Error(stderr || `python exited ${c}`));
    });
  });

  const text = await readFile(tmpOut, 'utf8').catch(() => '');
  await Promise.allSettled([unlink(tmpAudio), unlink(tmpOut)]);
  return text.trim();
}
