import React, { useState } from 'react'
import axios from 'axios'

const Section = ({ title, children }) => (
  <section style={{ margin: '16px 0', padding: 16, border: '1px solid #eee', borderRadius: 8 }}>
    <h2 style={{ margin: '0 0 8px', fontSize: 18 }}>{title}</h2>
    {children}
  </section>
)

export default function App() {
  const [audio, setAudio] = useState(null)
  const [transcribed, setTranscribed] = useState('')
  const [provider, setProvider] = useState('openai')
  const [openaiKey, setOpenaiKey] = useState('')
  const [googleKey, setGoogleKey] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState('')
  const [progress, setProgress] = useState(null) // null | number
  const [jobId, setJobId] = useState(null)

  const saveKey = async (provider, apiKey) => {
    if (!apiKey) return
    await axios.post('/api/keys', { provider, apiKey })
    alert(`${provider} 金鑰已保存`)
  }

  const pollJob = async (id) => {
    try {
      const { data } = await axios.get(`/api/transcribe/${id}`)
      if (typeof data.progress === 'number') setProgress(data.progress)
      if (data.status === 'done') {
        setTranscribed(data.result)
        setLoading(false)
        setJobId(null)
        return
      }
      if (data.status === 'error') {
        alert(data.error || '轉錄失敗')
        setLoading(false)
        setJobId(null)
        return
      }
      // 繼續輪詢
      setTimeout(() => pollJob(id), 1500)
    } catch (e) {
      console.error(e)
      setLoading(false)
      setJobId(null)
    }
  }

  const handleUpload = async () => {
    if (!audio) return alert('請先選擇 mp3 / wav 檔案')
    const form = new FormData()
    form.append('audio', audio)
    setLoading(true)
    setProgress(null)
    setJobId(null)
    try {
      const { data } = await axios.post('/api/transcribe', form)
      if (data.done) {
        setTranscribed(data.text)
        setLoading(false)
      } else if (data.jobId) {
        setJobId(data.jobId)
        setProgress(0)
        pollJob(data.jobId)
      }
    } catch (e) {
      alert(e?.response?.data?.error || e.message)
      setLoading(false)
    }
  }

  const handleAnalyze = async () => {
    if (!transcribed) return alert('請先完成轉文字')
    setLoading(true)
    try {
      if (provider === 'export') {
        const { data } = await axios.post('/api/export', { text: transcribed })
        // 將前置指令複製到剪貼簿，並提供下載 txt
        await navigator.clipboard.writeText(data.prompt)
        const blob = new Blob([transcribed], { type: 'text/plain;charset=utf-8' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = 'transcript.txt'
        a.click()
        URL.revokeObjectURL(url)
        setResult('已複製「製作筆記」指令到剪貼簿，並下載 transcript.txt')
        return
      }
      const { data } = await axios.post('/api/analyze', { provider, text: transcribed })
      setResult(data.result)
    } catch (e) {
      alert(e?.response?.data?.error || e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: 24, fontFamily: 'Inter, system-ui, -apple-system, Segoe UI, Roboto, Noto Sans, Arial' }}>
      <h1>學習工具：語音轉文字＋講義生成</h1>

      <Section title="1) 上傳音檔（mp3 / wav）">
        <input type="file" accept="audio/mpeg,audio/wav" onChange={e => setAudio(e.target.files?.[0] || null)} />
        <button onClick={handleUpload} disabled={loading} style={{ marginLeft: 8 }}>開始轉文字</button>
        {loading && progress === null && <span style={{ marginLeft: 8 }}>處理中…</span>}
        {loading && progress !== null && (
          <span style={{ marginLeft: 8 }}>
            轉錄進度：{progress}%
            <span style={{ display: 'inline-block', width: 120, height: 8, background: '#eee', marginLeft: 8, verticalAlign: 'middle' }}>
              <span style={{ display: 'block', width: `${progress}%`, height: '100%', background: '#4caf50', transition: 'width 0.5s' }} />
            </span>
          </span>
        )}
      </Section>

      <Section title="2) 金鑰管理">
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
          <div>
            <label>OpenAI API Key</label><br />
            <input value={openaiKey} onChange={e => setOpenaiKey(e.target.value)} placeholder="sk-..." style={{ width: 280 }} />
            <button onClick={() => saveKey('openai', openaiKey)} style={{ marginLeft: 8 }}>儲存</button>
          </div>
          <div>
            <label>Google API Key</label><br />
            <input value={googleKey} onChange={e => setGoogleKey(e.target.value)} placeholder="AIza..." style={{ width: 280 }} />
            <button onClick={() => saveKey('google', googleKey)} style={{ marginLeft: 8 }}>儲存</button>
          </div>
        </div>
      </Section>

      <Section title="3) 選擇分析方式">
        <label><input type="radio" name="provider" value="openai" checked={provider==='openai'} onChange={e => setProvider(e.target.value)} /> OpenAI API</label>
        <label style={{ marginLeft: 12 }}><input type="radio" name="provider" value="google" checked={provider==='google'} onChange={e => setProvider(e.target.value)} /> Google AI API</label>
        <label style={{ marginLeft: 12 }}><input type="radio" name="provider" value="export" checked={provider==='export'} onChange={e => setProvider(e.target.value)} /> 直接匯出 txt + 複製指令</label>
        <div style={{ marginTop: 12 }}>
          <button onClick={handleAnalyze} disabled={loading}>開始分析 / 匯出</button>
        </div>
      </Section>

      <Section title="4) 轉換文字（txt）">
        <textarea rows={10} style={{ width: '100%' }} value={transcribed} onChange={e => setTranscribed(e.target.value)} placeholder="這裡會顯示 Whisper 中文轉文字結果，可手動編修" />
      </Section>

      <Section title="5) 結果輸出">
        <textarea rows={16} style={{ width: '100%' }} value={result} readOnly placeholder="這裡會顯示教學講義格式的結果" />
      </Section>

      <footer style={{ textAlign: 'center', color: '#666', marginTop: 24 }}>
        <small>本工具僅供學習使用。請保護與妥善管理您的 API 金鑰。</small>
      </footer>
    </div>
  )
}
