import { Low } from 'lowdb';
import { JSONFile } from 'lowdb/node';
import crypto from 'crypto';
import { join } from 'node:path';
import { existsSync, mkdirSync } from 'node:fs';

const dataDir = join(process.cwd(), 'data');
const dbFile = join(dataDir, 'db.json');

const secret = process.env.SECRET_PASSPHRASE || 'dev-secret';

let db;

export function ensureDb() {
  if (!existsSync(dataDir)) mkdirSync(dataDir, { recursive: true });
  db = new Low(new JSONFile(dbFile), { keys: {} });
}

function encrypt(text) {
  const iv = crypto.randomBytes(16);
  const key = crypto.createHash('sha256').update(secret).digest();
  const cipher = crypto.createCipheriv('aes-256-cbc', key, iv);
  const enc = Buffer.concat([cipher.update(text, 'utf8'), cipher.final()]);
  return `${iv.toString('hex')}:${enc.toString('hex')}`;
}

function decrypt(payload) {
  const [ivHex, dataHex] = payload.split(':');
  const iv = Buffer.from(ivHex, 'hex');
  const data = Buffer.from(dataHex, 'hex');
  const key = crypto.createHash('sha256').update(secret).digest();
  const decipher = crypto.createDecipheriv('aes-256-cbc', key, iv);
  const dec = Buffer.concat([decipher.update(data), decipher.final()]);
  return dec.toString('utf8');
}

export async function setKey(provider, apiKey) {
  await db.read();
  db.data.keys[provider] = encrypt(apiKey);
  await db.write();
}

export async function getKey(provider, masked = false) {
  await db.read();
  const enc = db.data.keys[provider];
  if (!enc) return null;
  const key = decrypt(enc);
  if (masked) return key.replace(/.(?=.{4})/g, '*');
  return key;
}
