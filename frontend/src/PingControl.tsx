import { useEffect, useState } from 'react'
import { Gauge } from 'lucide-react'
import { api } from './api'
import { Card, ErrorBox, useToast } from './components'
import './ping-control.css'

export function PingControl() {
  const [enabled, setEnabled] = useState<boolean | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const notify = useToast()
  useEffect(() => {
    const controller = new AbortController()
    void api<{ enabled: boolean }>('/api/web/ping-settings', { signal: controller.signal })
      .then(data => setEnabled(data.enabled))
      .catch(e => { if (!controller.signal.aborted) setError(e.message) })
    return () => controller.abort()
  }, [])
  async function toggle(value: boolean) {
    setBusy(true); setError('')
    try {
      const result = await api<{ enabled: boolean }>('/api/web/ping-settings', { method: 'PUT', body: JSON.stringify({ enabled: value }) })
      setEnabled(result.enabled)
      notify(`Balasan Ping ${result.enabled ? 'diaktifkan' : 'dinonaktifkan'} untuk semua nomor akun.`)
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  return <Card className="ping-control"><div className="ping-control-row"><span className="ping-control-icon"><Gauge size={23} /></span><div className="ping-control-description"><h3>Balasan Ping</h3><p>Ketik ping untuk mendapat pong!, waktu respons dalam ms, dan ringkasan spesifikasi server.</p></div><label className="ping-control-switch"><input type="checkbox" role="switch" aria-label="Aktifkan balasan Ping" checked={enabled === true} disabled={enabled === null || busy} onChange={e => void toggle(e.target.checked)} /><span className="ping-switch-track" aria-hidden="true" /><strong>{busy ? 'Menyimpan…' : enabled === null ? 'Memuat…' : enabled ? 'Aktif' : 'Nonaktif'}</strong></label></div><p className="ping-control-help">Berlaku untuk balasan pong! bawaan pada semua nomor akun ini dan tersimpan setelah restart. Bot CS dan aturan Auto Reply tetap mengikuti pengaturannya.</p><ErrorBox error={error} />{error && enabled === null && <button className="btn btn-secondary" onClick={() => window.location.reload()}>Muat ulang</button>}</Card>
}
