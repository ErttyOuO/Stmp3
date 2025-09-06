import OpenAI from 'openai';
import { getKey } from './keys.js';

export async function analyzeWithOpenAI(prompt) {
  const key = (await getKey('openai')) || process.env.OPENAI_API_KEY;
  if (!key) throw new Error('缺少 OpenAI API Key');
  const client = new OpenAI({ apiKey: key });
  const model = process.env.OPENAI_MODEL || 'gpt-4o-mini';

  const resp = await client.chat.completions.create({
    model,
    messages: [
      { role: 'system', content: '你是專業講師與教學設計助理，請生成結構化、清晰、可教學的內容。' },
      { role: 'user', content: prompt }
    ],
    temperature: 0.7
  });
  return resp.choices?.[0]?.message?.content?.trim() || '';
}
