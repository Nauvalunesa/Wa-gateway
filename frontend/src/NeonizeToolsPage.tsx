import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { ExternalLink, Eye, Megaphone, MessageCircle, Send, Timer, Zap } from 'lucide-react'
import { api, post, useResource, type Device } from './api'
import { Button, Card, CardTitle, DeviceSelect, ErrorBox, Field, Heading, ResponseBox, useToast } from './components'
import { MessageTypeTabs } from './MessageTypeTabs'

type Tool = 'ad' | 'after-read' | 'private-reply'
type ToolSettings = { ephemeral_default_seconds: number }
type Result = Record<string, unknown>

const tabs = [['ad', 'Iklan interaktif'], ['after-read', 'Pesan setelah dibaca'], ['private-reply', 'Balasan privat']]
const safeImageUrl = (value: string) => {
  try { const url = new URL(value); return url.protocol === 'https:' ? url.href : '' } catch { return '' }
}

export function NeonizeToolsPage() {
  const { data: deviceData } = useResource<{ devices: Device[] }>('/api/web/devices', 5000)
  const { data: settingsData, refresh: refreshSettings } = useResource<ToolSettings>('/api/web/neonize-tools/settings')
  const [tool, setTool] = useState<Tool>('ad')
  const [phone, setPhone] = useState('')
  const [to, setTo] = useState('')
  const [text, setText] = useState('')
  const [title, setTitle] = useState('Utusan')
  const [advertiser, setAdvertiser] = useState('Utusan.chat')
  const [sourceApp, setSourceApp] = useState('Utusan.chat')
  const [sourceUrl, setSourceUrl] = useState('https://utusan.chat')
  const [imageUrl, setImageUrl] = useState('')
  const [buttonLabel, setButtonLabel] = useState('Kunjungi website')
  const [duration, setDuration] = useState('60')
  const [recipients, setRecipients] = useState('')
  const [busy, setBusy] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<Result | null>(null)
  const notify = useToast()

  useEffect(() => {
    if (!phone && deviceData?.devices.length) {
      setPhone(deviceData.devices.find(device => device.online)?.phone || deviceData.devices[0].phone)
    }
  }, [deviceData, phone])

  useEffect(() => {
    if (settingsData) setDuration(String(settingsData.ephemeral_default_seconds || 60))
  }, [settingsData])

  const adPayload = useMemo(() => ({
    phone,
    to,
    text,
    title,
    advertiser,
    image_url: imageUrl,
    source_url: sourceUrl,
    source_app: sourceApp,
    button_label: buttonLabel,
  }), [phone, to, text, title, advertiser, imageUrl, sourceUrl, sourceApp, buttonLabel])

  async function sendAd(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(''); setResult(null)
    try { const response = await post<Result>('/api/web/neonize-tools/ad', adPayload); setResult(response); notify('Iklan interaktif dikirim.') }
    catch (cause) { setError((cause as Error).message) } finally { setBusy(false) }
  }

  async function saveDuration() {
    const value = Number(duration)
    if (!Number.isInteger(value) || value < 1 || value > 604800) { setError('Durasi harus 1–604800 detik.'); return }
    setSaving(true); setError('')
    try { await api('/api/web/neonize-tools/settings', { method: 'PUT', body: JSON.stringify({ ephemeral_default_seconds: value }) }); await refreshSettings(); notify('Durasi bawaan disimpan.') }
    catch (cause) { setError((cause as Error).message) } finally { setSaving(false) }
  }

  async function sendAfterRead(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(''); setResult(null)
    try {
      const response = await post<Result>('/api/web/neonize-tools/after-read', { phone, to, text, duration_seconds: Number(duration) })
      setResult(response); notify('Pesan dengan metadata setelah dibaca dikirim.')
    } catch (cause) { setError((cause as Error).message) } finally { setBusy(false) }
  }

  async function sendPrivate(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(''); setResult(null)
    try {
      const response = await post<Result>('/api/web/neonize-tools/private-reply', {
        phone,
        recipients: recipients.split(/[\n,]/).map(value => value.trim()).filter(Boolean),
        text,
      })
      setResult(response)
      notify(response.failed ? `Selesai: ${response.sent} terkirim, ${response.failed} gagal.` : `${response.sent} pesan privat terkirim.`)
    } catch (cause) { setError((cause as Error).message) } finally { setBusy(false) }
  }

  const request = tool === 'ad' ? { method: 'POST', url: '/api/web/neonize-tools/ad', body: adPayload }
    : tool === 'after-read' ? { method: 'POST', url: '/api/web/neonize-tools/after-read', body: { phone, to, text, duration_seconds: Number(duration) } }
      : { method: 'POST', url: '/api/web/neonize-tools/private-reply', body: { phone, recipients: recipients.split(/[\n,]/).map(value => value.trim()).filter(Boolean), text } }

  return <>
    <Heading eyebrow="NEONIZE TOOLS" title="Alat pesan tambahan" description="Susun kartu interaktif, atur pesan setelah dibaca, dan kirim balasan langsung dari perangkat Neonize." />
    <MessageTypeTabs types={tabs} selected={tool} onChange={value => { setTool(value as Tool); setError(''); setResult(null) }} />
    <div className="composer-grid neonize-tools-grid">
      <Card>
        <CardTitle title={tool === 'ad' ? 'Iklan interaktif' : tool === 'after-read' ? 'Pesan setelah dibaca' : 'Balasan privat'} subtitle="Pengiriman memakai sesi WhatsApp milik akun ini." />
        <form onSubmit={tool === 'ad' ? sendAd : tool === 'after-read' ? sendAfterRead : sendPrivate}>
          <DeviceSelect devices={deviceData?.devices || []} value={phone} onChange={setPhone} />
          {tool === 'private-reply' ? <Field label="Nomor atau JID penerima" hint="Pisahkan dengan koma atau baris baru. Maksimal 25 penerima; pesan dikirim sebagai chat pribadi biasa.">
            <textarea value={recipients} onChange={event => setRecipients(event.target.value)} rows={3} placeholder={'62812xxxxxxxx\n62813xxxxxxxx@s.whatsapp.net'} required />
          </Field> : <Field label={tool === 'ad' ? 'Nomor / JID chat atau grup' : 'Nomor / JID chat atau grup'} hint="Chat pribadi: nomor dengan kode negara. Grup: tempel JID yang berakhiran @g.us.">
            <input value={to} onChange={event => setTo(event.target.value)} placeholder="62812xxxxxxxx atau 12345@g.us" required />
          </Field>}

          {tool === 'ad' && <>
            <div className="form-grid neonize-tools-fields">
              <Field label="Judul kartu"><input value={title} onChange={event => setTitle(event.target.value)} maxLength={80} required /></Field>
              <Field label="Nama brand / pengiklan"><input value={advertiser} onChange={event => setAdvertiser(event.target.value)} maxLength={80} /></Field>
              <Field label="Nama aplikasi sumber"><input value={sourceApp} onChange={event => setSourceApp(event.target.value)} maxLength={80} /></Field>
              <Field label="Teks tombol"><input value={buttonLabel} onChange={event => setButtonLabel(event.target.value)} maxLength={25} required /></Field>
            </div>
            <Field label="Teks pesan"><textarea value={text} onChange={event => setText(event.target.value)} rows={4} maxLength={4000} placeholder="Tulis isi iklan atau pengumuman…" required /></Field>
            <Field label="URL tujuan tombol" hint="Harus URL HTTPS."><input type="url" value={sourceUrl} onChange={event => setSourceUrl(event.target.value)} placeholder="https://contoh.com" required /></Field>
            <Field label="URL gambar pratinjau (opsional)" hint="Gambar dimuat oleh WhatsApp dari URL ini."><input type="url" value={imageUrl} onChange={event => setImageUrl(event.target.value)} placeholder="https://contoh.com/gambar.jpg" /></Field>
          </>}

          {tool === 'after-read' && <>
            <Field label="Isi pesan"><textarea value={text} onChange={event => setText(event.target.value)} rows={4} maxLength={4000} placeholder="Tulis pesan…" required /></Field>
            <div className="neonize-duration-row">
              <Field label="Durasi setelah dibaca (detik)" hint="1–604800 detik. Pengaturan ini hanya berlaku untuk pesan pada halaman ini.">
                <input type="number" min={1} max={604800} step={1} value={duration} onChange={event => setDuration(event.target.value)} required />
              </Field>
              <Button type="button" variant="secondary" busy={saving} onClick={saveDuration}><Timer size={16} />Simpan durasi bawaan</Button>
            </div>
            <div className="small-tip"><Eye size={18} /><div><strong>Perilaku ditentukan WhatsApp.</strong><p>Gateway mengirim metadata after-read yang didukung protobuf Neonize. WhatsApp dapat mengabaikan atau mengubah perilaku ini pada perangkat penerima.</p></div></div>
          </>}

          {tool === 'private-reply' && <Field label="Isi balasan"><textarea value={text} onChange={event => setText(event.target.value)} rows={4} maxLength={4000} placeholder="Tulis pesan untuk dikirim melalui chat pribadi…" required /></Field>}

          {tool === 'private-reply' && <div className="small-tip"><MessageCircle size={18} /><div><strong>Pesan privat biasa.</strong><p>Setiap penerima mendapat chat langsung. Fitur ini tidak menyisipkan pesan tersembunyi ke dalam grup.</p></div></div>}
          <ErrorBox error={error} />
          <Button type="submit" busy={busy} disabled={!phone}><Send size={16} />{tool === 'ad' ? 'Kirim iklan interaktif' : tool === 'after-read' ? 'Kirim pesan sementara' : 'Kirim balasan privat'}</Button>
        </form>
        <ResponseBox result={result} />
        <details className="neonize-request">
          <summary>URL endpoint dan payload lengkap</summary>
          <div><code>{request.method} {window.location.origin}{request.url}</code><pre>{JSON.stringify(request.body, null, 2)}</pre><small>Otentikasi web memakai cookie sesi akun; tidak perlu API key.</small></div>
        </details>
      </Card>

      <aside className="composer-side neonize-tools-preview">
        {tool === 'ad' ? <Card className="neonize-ad-card">
          <CardTitle title="Pratinjau iklan" subtitle="Ilustrasi kartu; tampilan akhir mengikuti WhatsApp penerima." />
          <div className="neonize-ad-preview">
            <div className="neonize-ad-label"><Megaphone size={14} />{advertiser || 'Nama brand'}</div>
            {safeImageUrl(imageUrl) && <img src={safeImageUrl(imageUrl)} alt="Pratinjau iklan" />}
            <strong>{title || 'Judul kartu'}</strong>
            <p>{text || 'Isi pesan akan tampil di sini.'}</p>
            <small>{sourceApp || 'Aplikasi sumber'} · Pratinjau tautan</small>
            <span><ExternalLink size={15} />{buttonLabel || 'Kunjungi website'}</span>
            <code>{sourceUrl || 'https://contoh.com'}</code>
          </div>
        </Card> : <Card>
          <CardTitle title={tool === 'after-read' ? 'Pratinjau pesan' : 'Tujuan balasan'} subtitle={tool === 'after-read' ? 'Metadata akan dikirim bersama isi pesan.' : 'Pesan akan muncul sebagai chat pribadi di WhatsApp.'} />
          <div className="neonize-text-preview"><span>{tool === 'after-read' ? 'PESAN SETELAH DIBACA' : 'CHAT LANGSUNG'}</span><p>{text || (tool === 'after-read' ? 'Isi pesan tampil di sini.' : 'Isi balasan tampil di sini.')}</p>{tool === 'after-read' && <small><Timer size={13} /> Durasi: {duration || 0} detik</small>}{tool === 'private-reply' && <small><MessageCircle size={13} /> {recipients.split(/[\n,]/).filter(value => value.trim()).length} penerima</small>}</div>
        </Card>}
        <div className="small-tip"><Zap size={18} /><div><strong>Fitur memakai protobuf Neonize.</strong><p>Pesan interaktif memakai tombol CTA URL. Pengiriman biasa tetap tersedia di halaman Kirim pesan.</p></div></div>
      </aside>
    </div>
  </>
}
