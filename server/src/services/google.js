import axios from 'axios';
import { getKey } from './keys.js';

export async function analyzeWithGoogle(prompt) {
  const key = (await getKey('google')) || process.env.GOOGLE_API_KEY;
  if (!key) throw new Error('缺少 Google API Key');
  const model = process.env.GOOGLE_MODEL || 'gemini-2.5-flash';

  const url = `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${key}`;
  const body = {
    contents: [
      {
        role: 'user',
        parts: [{ text: prompt }]
      }
    ]
  };
  const resp = await axios.post(url, body, {
    headers: { 'Content-Type': 'application/json' }
  });
  const text = resp.data?.candidates?.[0]?.content?.parts?.[0]?.text || '';
  return text.trim();
}
