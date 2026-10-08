import { useEffect, useState } from 'react'
import { Headset, Plus, RotateCcw, Save, Send, Trash2 } from 'lucide-react'
import { api, post, useResource, type Device } from './api'
import { Button, Card, CardTitle, CopyButton, ErrorBox, Field, Heading, Loading, ResponseBox, useToast } from './components'
import './customer-service.css'

type Option = { id: string; label: string; target: string }
type Node = { id: string; title: string; text: string; handoff: boolean; options: Option[] }
type Config = {
  enabled: boolean; business_name: string; admin_phone: string; devices: string[]
  reply_mode: 'buttons' | 'list' | 'legacy' | 'text'; start_on_first_message: boolean
  keywords: string[]; cooldown_seconds: number; session_ttl_minutes: number; handoff_minutes: number
  root_node: string; nodes: Node[]
}
type Reply = { title: string; body: string; footer: string; node: string; handoff: boolean; options: Option[]; mode: string }
type Preview = { reply: Reply; message: unknown; sent: false }
type Conversation = { phone: string; chat: string; node: string; paused: boolean; pause_remaining: number }

export function CustomerServicePage() {
  const [draft, setDraft] = useState<Config | null>(null)
  const [selected, setSelected] = useState('menu')
  const [keywords, setKeywords] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [preview, setPreview] = useState<Preview | null>(null)
  const [testInput, setTestInput] = useState('')
  const [testing, setTesting] = useState(false)
  const [testError, setTestError] = useState('')
  const devices = useResource<{ devices: Device[] }>('/api/web/devices')
  const sessions = useResource<{ conversations: Conversation[] }>('/api/web/customer-service/conversations', 10000)
  const notify = useToast()

  useEffect(() => {
    let active = true
    api<{ config: Config }>('/api/web/customer-service').then(({ config }) => {
      if (active) { setDraft(config); setSelected(config.root_node); setKeywords(config.keywords.join(', ')) }
    }).catch(e => { if (active) setError(e.message) })
    return () => { active = false }
  }, [])

  useEffect(() => {
    if (!draft) return
    const controller = new AbortController()
    const timer = setTimeout(() => {
      const config = { ...draft, keywords: keywords.split(',').map(x => x.trim()).filter(Boolean) }
      void api<Preview>('/api/web/customer-service/preview', {
        method: 'POST', body: JSON.stringify({ config, text: '', current_node: selected }), signal: controller.signal,
      }).then(result => { setPreview(result); setTestError('') }).catch(e => {
        if (!controller.signal.aborted) { setPreview(null); setTestError(e.message) }
      })
    }, 450)
    return () => { clearTimeout(timer); controller.abort() }
  }, [draft, keywords, selected])

  if (!draft) return error ? <ErrorBox error={error} /> : <Loading />
  const node = draft.nodes.find(n => n.id === selected) || draft.nodes[0]
  const config: Config = { ...draft, keywords: keywords.split(',').map(x => x.trim()).filter(Boolean) }
  const set = (changes: Partial<Config>) => { setDraft({ ...draft, ...changes }); setDirty(true) }
  const editNode = (changes: Partial<Node>) => set({ nodes: draft.nodes.map(n => n.id === node.id ? { ...n, ...changes } : n) })
  const addNode = () => {
    const id = `page-${Date.now().toString(36)}`
    set({ nodes: [...draft.nodes, { id, title: 'Layanan baru', text: 'Tulis jawaban layanan Anda di sini.', handoff: false, options: [{ id: 'menu', label: 'Menu utama', target: draft.root_node }] }] })
    setSelected(id)
  }
  const removeNode = () => {
    set({ nodes: draft.nodes.filter(n => n.id !== node.id).map(n => ({ ...n, options: n.options.filter(o => o.target !== node.id) })) })
    setSelected(draft.root_node)
    notify('Halaman dan tombol menuju halaman tersebut dihapus dari draft.')
  }
  async function save() {
    setBusy(true); setError('')
    try {
      const result = await api<{ config: Config }>('/api/web/customer-service', { method: 'PUT', body: JSON.stringify(config) })
      setDraft(result.config); setKeywords(result.config.keywords.join(', ')); setDirty(false)
      await sessions.refresh(); notify('Pengaturan Bot CS disimpan. Percakapan baru memakai alur ini.')
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  async function simulate(value: string) {
    setTesting(true); setTestError('')
    try {
      setPreview(await post<Preview>('/api/web/customer-service/preview', { config, text: value, current_node: preview?.reply.node || selected }))
      setTestInput('')
    } catch (e) { setTestError((e as Error).message) } finally { setTesting(false) }
  }
  async function resetChat(conversation: Conversation) {
    try { await post('/api/web/customer-service/reset', { phone: conversation.phone, chat: conversation.chat }); await sessions.refresh(); notify('Percakapan direset. Bot dapat merespons pesan berikutnya.') }
    catch (e) { notify((e as Error).message, 'error') }
  }
  const payload = JSON.stringify(config, null, 2)
  const curl = `curl --request PUT '${window.location.origin}/api/web/customer-service' \\\n  --header 'Content-Type: application/json' \\\n  --header 'Cookie: session=COOKIE_SESSION' \\\n  --data-raw '${payload.replaceAll("'", "'\\''")}'`

  return <>
    <Heading eyebrow="CUSTOMER SERVICE" title="Bot CS" description="Menu layanan, FAQ, dan bantuan admin dalam percakapan WhatsApp otomatis.">
      <Button onClick={() => void save()} disabled={busy}>{busy ? 'Menyimpan…' : <><Save size={16} />Simpan pengaturan</>}</Button>
    </Heading>
    <ErrorBox error={error} />
    <div className="info-strip"><Headset size={22} /><div><strong>{dirty ? 'Ada perubahan yang belum disimpan' : draft.enabled ? 'Bot aktif sesuai pengaturan tersimpan' : 'Bot belum aktif'}</strong><span>Simulator tidak mengirim WhatsApp. Setelah disimpan, Bot CS menangani chat pribadi sebelum aturan Auto Reply.</span></div></div>
    <div className="cs-layout">
      <div className="cs-editor">
        <Card>
          <CardTitle title="Pengaturan layanan" subtitle="Atur identitas, perangkat, dan kapan bot menjawab." />
          <label className="check-label"><input type="checkbox" checked={draft.enabled} onChange={e => set({ enabled: e.target.checked })} />Aktifkan Bot CS</label>
          <div className="cs-fields">
            <Field label="Nama bisnis / layanan"><input value={draft.business_name} maxLength={80} onChange={e => set({ business_name: e.target.value })} /></Field>
            <Field label="Nomor admin"><input value={draft.admin_phone} inputMode="tel" placeholder="62812xxxxxxxx" onChange={e => set({ admin_phone: e.target.value })} /><small>Diperlukan untuk alur Hubungi Admin. Gunakan kode negara.</small></Field>
            <Field label="Jenis balasan"><select value={draft.reply_mode} onChange={e => set({ reply_mode: e.target.value as Config['reply_mode'] })}><option value="buttons">Tombol balasan cepat</option><option value="list">List / pilihan layanan</option><option value="legacy">Tombol legacy (maks. 3)</option><option value="text">Teks bernomor</option></select></Field>
            <Field label="Kata pemicu"><input value={keywords} onChange={e => { setKeywords(e.target.value); setDirty(true) }} placeholder="menu, halo, mulai" /><small>Pisahkan dengan koma. “menu”, “0”, dan “kembali” selalu membuka menu awal.</small></Field>
            <Field label="Menu awal"><select value={draft.root_node} onChange={e => set({ root_node: e.target.value })}>{draft.nodes.map(n => <option key={n.id} value={n.id}>{n.title}</option>)}</select></Field>
            <Field label="Jeda antarbalasan (detik)"><input type="number" min={0} max={60} value={draft.cooldown_seconds} onChange={e => set({ cooldown_seconds: Number(e.target.value) })} /></Field>
            <Field label="Percakapan kedaluwarsa (menit)"><input type="number" min={1} max={1440} value={draft.session_ttl_minutes} onChange={e => set({ session_ttl_minutes: Number(e.target.value) })} /></Field>
            <Field label="Jeda saat ke admin (menit)"><input type="number" min={1} max={1440} value={draft.handoff_minutes} onChange={e => set({ handoff_minutes: Number(e.target.value) })} /></Field>
          </div>
          <label className="check-label"><input type="checkbox" checked={draft.start_on_first_message} onChange={e => set({ start_on_first_message: e.target.checked })} />Buka menu pada pesan pertama, tanpa harus mengetik kata pemicu</label>
          <div className="field"><span>Perangkat yang menjalankan bot</span><small>Kosongkan pilihan untuk semua perangkat akun. Tidak merespons grup, channel, atau status.</small><ErrorBox error={devices.error} /><div className="cs-device-list">{devices.data?.devices.length ? devices.data.devices.map(d => <label className="check-label" key={d.phone}><input type="checkbox" checked={draft.devices.includes(d.phone)} onChange={e => set({ devices: e.target.checked ? [...draft.devices, d.phone] : draft.devices.filter(p => p !== d.phone) })} />+{d.phone} · {d.online ? 'Online' : 'Offline'}</label>) : <small>Hubungkan perangkat di halaman Perangkat untuk mulai menerima pesan.</small>}</div></div>
        </Card>
        <Card>
          <CardTitle title="Editor alur layanan" subtitle="Setiap tombol mengarahkan pelanggan ke halaman jawaban."><Button variant="secondary" onClick={addNode} disabled={draft.nodes.length >= 30}><Plus size={15} />Tambah halaman</Button></CardTitle>
          <div className="cs-node-tabs" aria-label="Halaman alur">{draft.nodes.map(n => <button type="button" key={n.id} className={node.id === n.id ? 'active' : ''} onClick={() => setSelected(n.id)}>{n.title || n.id}{n.handoff ? ' · Admin' : ''}</button>)}</div>
          <div className="cs-node-heading"><span className="tag">{node.id === draft.root_node ? 'Menu awal' : 'Halaman'} · {node.id}</span><Button variant="ghost" disabled={node.id === draft.root_node} onClick={removeNode}><Trash2 size={15} />Hapus</Button></div>
          <Field label="Judul halaman"><input value={node.title} maxLength={60} onChange={e => editNode({ title: e.target.value })} /></Field>
          <Field label="Pesan balasan"><textarea rows={6} value={node.text} maxLength={4000} onChange={e => editNode({ text: e.target.value })} /><small>Gunakan {'{name}'} untuk nama pelanggan dan {'{business}'} untuk nama layanan.</small></Field>
          <label className="check-label"><input type="checkbox" checked={node.handoff} onChange={e => editNode({ handoff: e.target.checked })} />Halaman ini mengarahkan ke admin dan menjeda bot</label>
          <div className="cs-option-heading"><strong>Tombol / pilihan layanan</strong><Button variant="secondary" disabled={node.options.length >= (draft.reply_mode === 'legacy' ? 3 : 10)} onClick={() => editNode({ options: [...node.options, { id: `opt-${Date.now().toString(36)}`, label: 'Pilihan baru', target: draft.root_node }] })}><Plus size={15} />Tambah pilihan</Button></div>
          {node.options.map((option, index) => <div className="cs-option" key={option.id}><span>{index + 1}</span><Field label="Label"><input value={option.label} maxLength={25} onChange={e => editNode({ options: node.options.map(o => o.id === option.id ? { ...o, label: e.target.value } : o) })} /></Field><Field label="Tujuan"><select value={option.target} onChange={e => editNode({ options: node.options.map(o => o.id === option.id ? { ...o, target: e.target.value } : o) })}>{draft.nodes.map(n => <option key={n.id} value={n.id}>{n.title}</option>)}</select></Field><Button variant="ghost" aria-label={`Hapus pilihan ${option.label}`} onClick={() => editNode({ options: node.options.filter(o => o.id !== option.id) })}><Trash2 size={15} /></Button></div>)}
          <p className="cs-help">Tombol cepat dengan lebih dari 3 pilihan otomatis memakai list. Pelanggan juga dapat membalas nomor atau label pilihan. Dukungan tampilan tombol mengikuti versi WhatsApp penerima.</p>
        </Card>
      </div>
      <div className="cs-side">
        <Card>
          <CardTitle title="Simulator percakapan" subtitle="Klik tombol atau ketik balasan untuk menelusuri alur."><Button variant="ghost" disabled={testing} onClick={() => void simulate('menu')} aria-label="Kembali ke menu utama"><RotateCcw size={17} /></Button></CardTitle>
          <ErrorBox error={testError} />
          {preview && <div className="cs-chat"><div className="cs-chat-header"><Headset size={18} /><span>{draft.business_name}</span><span className="tag">Preview</span></div><div className="cs-chat-bubble"><strong>{preview.reply.title}</strong><p>{preview.reply.body}</p><small>{preview.reply.footer}</small></div>{preview.reply.options.length > 0 && <div className="cs-reply-options">{preview.reply.options.map(o => <button key={o.id} disabled={testing} type="button" onClick={() => void simulate(o.id)}>{o.label}</button>)}</div>}{preview.reply.handoff && <div className="cs-help">Pada percakapan nyata, balasan otomatis dijeda. Ketik menu untuk melanjutkan.</div>}</div>}
          <form className="cs-test-input" onSubmit={e => { e.preventDefault(); if (testInput.trim()) void simulate(testInput) }}><input aria-label="Balasan uji pelanggan" value={testInput} onChange={e => setTestInput(e.target.value)} placeholder="Ketik menu, 1, atau nama pilihan…" /><Button type="submit" disabled={testing || !testInput.trim()} aria-label="Uji balasan"><Send size={16} /></Button></form>
          <details className="cs-code"><summary>Protobuf hasil preview</summary><ResponseBox result={preview?.message} /></details>
        </Card>
        <Card>
          <CardTitle title="Percakapan aktif" subtitle="Status alur tersimpan di memori, terpisah per perangkat." />
          <ErrorBox error={sessions.error} />
          {sessions.data?.conversations.length ? sessions.data.conversations.map(c => <div className="cs-conversation" key={`${c.phone}:${c.chat}`}><strong>{c.chat}</strong><small>Perangkat +{c.phone} · {c.node}</small><span className="tag">{c.paused ? `Dijeda ${Math.ceil(c.pause_remaining / 60)} menit` : 'Bot aktif'}</span><Button variant="secondary" onClick={() => void resetChat(c)}><RotateCcw size={14} />Reset chat</Button></div>) : <p className="cs-help">Belum ada percakapan aktif. Aktifkan bot, simpan, lalu kirim pesan ke perangkat yang terhubung.</p>}
        </Card>
        <Card><CardTitle title="Request pengaturan" subtitle="Payload mengikuti draft editor. Endpoint memakai cookie login." /><details className="cs-code"><summary>cURL lengkap dan payload</summary><CopyButton value={curl} label="Salin cURL" /><pre>{curl}</pre><CopyButton value={payload} label="Salin JSON" /></details></Card>
      </div>
    </div>
  </>
}
