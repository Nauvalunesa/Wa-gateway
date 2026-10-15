import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { ExternalLink, Eye, Megaphone, MessageCircle, Send, Shield, Timer, Users, Zap } from 'lucide-react'
import { api, post, query, useResource, type Device } from './api'
import { Button, Card, CardTitle, DeviceSelect, ErrorBox, Field, Heading, ResponseBox, useToast } from './components'
import { MessageTypeTabs } from './MessageTypeTabs'

type Tool = 'ad' | 'after-read' | 'private-reply' | 'spr'
type ToolSettings = { ephemeral_default_seconds: number }
type Result = Record<string, unknown>
type Group = { jid: string; name: string }
type GroupParticipant = { jid: string; spr_jid: string; phone: string; lid: string; is_admin: boolean; is_super_admin: boolean; is_self: boolean }
type SPRCapability = { supported: boolean; connected: boolean; method: string; reason: string }

const tabs = [['ad', 'Iklan interaktif'], ['after-read', 'Pesan setelah dibaca'], ['spr', 'SPR grup A/B'], ['private-reply', 'DM anggota grup']]
const safeImageUrl = (value: string) => {
  try { const url = new URL(value); return url.protocol === 'https:' ? url.href : '' } catch { return '' }
}
const sprEndpointError = (cause: unknown, feature: string) => {
  const message = cause instanceof Error ? cause.message : String(cause || '')
  if (/\bnot found\b/i.test(message)) {
    return `Backend aktif belum memiliki endpoint ${feature}. Perbarui dan restart backend agar fitur SPR dapat dimuat.`
  }
  return message || `Gagal memuat ${feature}.`
}

export function NeonizeToolsPage() {
  const { data: deviceData } = useResource<{ devices: Device[] }>('/api/web/devices', 5000)
  const { data: settingsData, refresh: refreshSettings } = useResource<ToolSettings>('/api/web/neonize-tools/settings')
  const [tool, setTool] = useState<Tool>('ad')
  const [destination, setDestination] = useState<'chat' | 'group'>('chat')
  const [phone, setPhone] = useState('')
  const [to, setTo] = useState('')
  const [text, setText] = useState('')
  const [adDraftText, setAdDraftText] = useState('')
  const [title, setTitle] = useState('Utusan')
  const [advertiser, setAdvertiser] = useState('Utusan.chat')
  const [sourceApp, setSourceApp] = useState('Utusan.chat')
  const [sourceUrl, setSourceUrl] = useState('https://utusan.chat')
  const [imageUrl, setImageUrl] = useState('')
  const [buttonLabel, setButtonLabel] = useState('Kunjungi website')
  const [duration, setDuration] = useState('60')
  const [recipients, setRecipients] = useState('')
  const [sprTargetMessage, setSprTargetMessage] = useState('')
  const [sprDecoyMessage, setSprDecoyMessage] = useState('')
  const [sprCapability, setSprCapability] = useState<SPRCapability | null>(null)
  const [groups, setGroups] = useState<Group[]>([])
  const [groupJid, setGroupJid] = useState('')
  const [groupsLoading, setGroupsLoading] = useState(false)
  const [groupsError, setGroupsError] = useState('')
  const [participants, setParticipants] = useState<GroupParticipant[]>([])
  const [participantsLoading, setParticipantsLoading] = useState(false)
  const [participantsError, setParticipantsError] = useState('')
  const [participantSearch, setParticipantSearch] = useState('')
  const [selectedRecipients, setSelectedRecipients] = useState<string[]>([])
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

  useEffect(() => {
    if (!phone || (!['private-reply', 'spr'].includes(tool) && destination !== 'group')) {
      setGroups([]); setGroupJid(''); setParticipants([]); setSelectedRecipients([])
      setGroupsError(''); setParticipantsError(''); setGroupsLoading(false)
      return
    }
    let active = true
    setGroupJid(''); setParticipants([]); setSelectedRecipients([]); setParticipantSearch('')
    setGroupsLoading(true); setGroupsError('')
    void api<{ groups?: Group[] }>(query('/api/web/groups', { phone }))
      .then(result => {
        if (!active) return
        const items = (result.groups || []).filter(group => group.jid && group.jid.endsWith('@g.us'))
        setGroups(items)
        setGroupJid(current => items.some(group => group.jid === current) ? current : '')
      })
      .catch(cause => { if (active) setGroupsError((cause as Error).message) })
      .finally(() => { if (active) setGroupsLoading(false) })
    return () => { active = false }
  }, [phone, tool, destination])

  useEffect(() => {
    if (!['private-reply', 'spr'].includes(tool) || !phone || !groupJid) {
      setParticipants([]); setSelectedRecipients([]); setParticipantsError(''); setParticipantsLoading(false)
      return
    }
    let active = true
    setParticipantsLoading(true); setParticipantsError(''); setSelectedRecipients([])
    void api<{ participants?: GroupParticipant[] }>(query('/api/web/neonize-tools/group-participants', { phone, group_jid: groupJid }))
      .then(result => { if (active) setParticipants((result.participants || []).filter(person => !person.is_self)) })
      .catch(cause => { if (active) setParticipantsError(sprEndpointError(cause, 'daftar anggota grup SPR')) })
      .finally(() => { if (active) setParticipantsLoading(false) })
    return () => { active = false }
  }, [phone, groupJid, tool])

  useEffect(() => {
    if (tool !== 'spr' || !phone) { setSprCapability(null); return }
    let active = true
    setSprCapability(null)
    void api<SPRCapability>(query('/api/web/neonize-tools/spr/capabilities', { phone }))
      .then(value => { if (active) setSprCapability(value) })
      .catch(cause => { if (active) setSprCapability({ supported: false, connected: false, method: 'send_spr_group', reason: sprEndpointError(cause, 'pemeriksaan kemampuan SPR') }) })
    return () => { active = false }
  }, [phone, tool])

  const target = destination === 'group' ? groupJid : to
  const adPayload = useMemo(() => ({
    phone,
    to: target,
    title,
    advertiser,
    image_url: imageUrl,
    source_url: sourceUrl,
    source_app: sourceApp,
    button_label: buttonLabel,
  }), [phone, target, title, advertiser, imageUrl, sourceUrl, sourceApp, buttonLabel])

  const recipientList = [...new Set([
    ...selectedRecipients,
    ...recipients.split(/[\n,]/).map(value => value.trim()).filter(Boolean),
  ])]
  const sprPayload = {
    phone,
    group_jid: groupJid,
    target_jids: selectedRecipients,
    target_message: sprTargetMessage,
    decoy_message: sprDecoyMessage,
  }
  const visibleParticipants = participants.filter(person => {
    const queryText = participantSearch.trim().toLowerCase()
    return !queryText || `${person.phone} ${person.jid} ${person.lid}`.toLowerCase().includes(queryText)
  })

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
      const response = await post<Result>('/api/web/neonize-tools/after-read', { phone, to: target, text, duration_seconds: Number(duration) })
      setResult(response); notify('Pesan dengan metadata setelah dibaca dikirim.')
    } catch (cause) { setError((cause as Error).message) } finally { setBusy(false) }
  }

  async function sendPrivate(event: FormEvent) {
    event.preventDefault(); setError(''); setResult(null)
    if (!recipientList.length) { setError('Pilih anggota grup atau masukkan nomor penerima.'); return }
    if (recipientList.length > 25) { setError('Maksimal 25 penerima per pengiriman.'); return }
    setBusy(true)
    try {
      const response = await post<Result>('/api/web/neonize-tools/private-reply', {
        phone,
        recipients: recipientList,
        text,
      })
      setResult(response)
      notify(response.failed ? `Selesai: ${response.sent} terkirim, ${response.failed} gagal.` : `${response.sent} pesan privat terkirim.`)
    } catch (cause) { setError((cause as Error).message) } finally { setBusy(false) }
  }

  async function sendSpr(event: FormEvent) {
    event.preventDefault(); setError(''); setResult(null)
    if (!groupJid) { setError('Pilih grup WhatsApp terlebih dahulu.'); return }
    if (!selectedRecipients.length) { setError('Pilih setidaknya satu target A dari daftar anggota grup.'); return }
    if (!sprTargetMessage.trim() || !sprDecoyMessage.trim()) { setError('Isi pesan A untuk target dan pesan B untuk anggota lain.'); return }
    if (!sprCapability?.supported) { setError(sprCapability?.reason || 'Transport SPR grup belum tersedia pada Neonize yang aktif.'); return }
    setBusy(true)
    try {
      const response = await post<Result>('/api/web/neonize-tools/spr', sprPayload)
      setResult(response)
      notify(`SPR grup dikirim untuk ${selectedRecipients.length} target.`)
    } catch (cause) { setError((cause as Error).message) } finally { setBusy(false) }
  }

  const request = tool === 'ad' ? { method: 'POST', url: '/api/web/neonize-tools/ad', body: adPayload }
    : tool === 'after-read' ? { method: 'POST', url: '/api/web/neonize-tools/after-read', body: { phone, to: target, text, duration_seconds: Number(duration) } }
      : tool === 'spr' ? { method: 'POST', url: '/api/web/neonize-tools/spr', body: sprPayload }
        : { method: 'POST', url: '/api/web/neonize-tools/private-reply', body: { phone, recipients: recipientList, text } }

  return <>
    <Heading eyebrow="NEONIZE TOOLS" title="Alat pesan tambahan" description="Susun kartu interaktif, pesan setelah dibaca, dan SPR grup. Pilih tujuan dari daftar." />
    <MessageTypeTabs types={tabs} selected={tool} onChange={value => { setTool(value as Tool); setError(''); setResult(null) }} />
    <div className="composer-grid neonize-tools-grid">
      <Card>
          <CardTitle title={tool === 'ad' ? 'Iklan interaktif' : tool === 'after-read' ? 'Pesan setelah dibaca' : tool === 'spr' ? 'SPR grup A/B' : 'DM anggota grup'} subtitle="Pengiriman memakai sesi WhatsApp milik akun ini." />
        <form onSubmit={tool === 'ad' ? sendAd : tool === 'after-read' ? sendAfterRead : tool === 'spr' ? sendSpr : sendPrivate}>
          <DeviceSelect devices={deviceData?.devices || []} value={phone} onChange={setPhone} />
          {tool === 'private-reply' || tool === 'spr' ? <>
            <Field label={tool === 'spr' ? 'Pilih grup tujuan SPR' : 'Pilih grup untuk mencari anggota (opsional)'} hint={tool === 'spr' ? 'Pesan A dan decoy B sama-sama dikirim dalam grup ini.' : 'Pilih grup, lalu centang anggota yang akan menerima DM pribadi.'}>
              <select value={groupJid} onChange={event => { setGroupJid(event.target.value); setParticipantSearch('') }} disabled={groupsLoading || !groups.length}>
                <option value="">{groupsLoading ? 'Memuat grup…' : groups.length ? 'Pilih grup WhatsApp' : 'Grup tidak tersedia'}</option>
                {groups.map(group => <option key={group.jid} value={group.jid}>{group.name}</option>)}
              </select>
              {groupsError && <small className="field-error">{groupsError}</small>}
              {!groupsLoading && !groupsError && !groups.length && <small className="field-hint">Pastikan perangkat online dan sudah bergabung ke grup.</small>}
            </Field>
            {groupJid && <div className="neonize-recipient-picker">
              <div className="neonize-recipient-tools">
                <Field label={tool === 'spr' ? 'Cari target A' : 'Cari anggota'}><input type="search" value={participantSearch} onChange={event => setParticipantSearch(event.target.value)} placeholder="Cari nama atau nomor" /></Field>
                <span>{selectedRecipients.length}/25 {tool === 'spr' ? 'target' : 'dipilih'}</span>
              </div>
              {participantsError && <small className="field-error">{participantsError}</small>}
              {participantsLoading ? <p className="neonize-recipient-empty">Memuat anggota grup…</p> : <div className="neonize-participant-list">
                {visibleParticipants.map(person => {
                  const selectedJid = tool === 'spr' ? person.spr_jid : person.jid
                  const checked = selectedRecipients.includes(selectedJid)
                  const label = person.phone ? `+${person.phone}` : 'Anggota WhatsApp'
                  return <label key={person.jid} className="neonize-participant">
                    <input type="checkbox" checked={checked} disabled={busy || (!checked && selectedRecipients.length >= 25)} onChange={event => setSelectedRecipients(current => event.target.checked ? [...current, selectedJid] : current.filter(jid => jid !== selectedJid))} />
                    <span><strong>{label}</strong><small>{person.phone ? 'Nomor WhatsApp' : 'Terdaftar dengan LID'}</small></span>
                    {(person.is_super_admin || person.is_admin) && <em>Admin</em>}
                  </label>
                })}
                {!visibleParticipants.length && !participantsError && <p className="neonize-recipient-empty">{participants.length ? 'Anggota tidak ditemukan.' : 'Belum ada anggota yang bisa ditampilkan.'}</p>}
              </div>}
              {!!selectedRecipients.length && <button type="button" className="text-link neonize-clear-recipients" onClick={() => setSelectedRecipients([])}>Hapus pilihan anggota</button>}
            </div>}
            {tool === 'private-reply' && <Field label="Tambah penerima manual (opsional)" hint="Nomor dengan kode negara atau JID pribadi. Pisahkan dengan koma/baris baru; maksimal 25 penerima total.">
              <textarea value={recipients} onChange={event => setRecipients(event.target.value)} rows={2} placeholder={'62812xxxxxxxx, 62813xxxxxxxx'} />
            </Field>}
          </> : <>
            <Field label="Tujuan pesan">
              <select value={destination} onChange={event => { setDestination(event.target.value as 'chat' | 'group'); setTo(''); setGroupJid('') }}>
                <option value="chat">Chat pribadi</option>
                <option value="group">Grup WhatsApp</option>
              </select>
            </Field>
            {destination === 'group' ? <Field label="Pilih grup WhatsApp" hint="Daftar grup berasal dari perangkat yang dipilih.">
              <select value={groupJid} onChange={event => setGroupJid(event.target.value)} disabled={groupsLoading || !groups.length} required>
                <option value="">{groupsLoading ? 'Memuat grup…' : groups.length ? 'Pilih grup' : 'Grup tidak tersedia'}</option>
                {groups.map(group => <option key={group.jid} value={group.jid}>{group.name}</option>)}
              </select>
              {groupsError && <small className="field-error">{groupsError}</small>}
              {!groupsLoading && !groupsError && !groups.length && <small className="field-hint">Pastikan perangkat online dan sudah bergabung ke grup.</small>}
            </Field> : <Field label="Nomor penerima" hint="Masukkan nomor dengan kode negara, misalnya 62812xxxxxxxx.">
              <input value={to} onChange={event => setTo(event.target.value)} placeholder="62812xxxxxxxx" required />
            </Field>}
          </>}

          {tool === 'ad' && <>
            <div className="form-grid neonize-tools-fields">
              <Field label="Judul kartu"><input value={title} onChange={event => setTitle(event.target.value)} maxLength={80} required /></Field>
              <Field label="Nama brand / pengiklan"><input value={advertiser} onChange={event => setAdvertiser(event.target.value)} maxLength={80} /></Field>
              <Field label="Nama aplikasi sumber"><input value={sourceApp} onChange={event => setSourceApp(event.target.value)} maxLength={80} /></Field>
              <Field label="Teks tombol"><input value={buttonLabel} onChange={event => setButtonLabel(event.target.value)} maxLength={25} required /></Field>
            </div>
            <Field label="URL tujuan tombol" hint="Harus URL HTTPS."><input type="url" value={sourceUrl} onChange={event => setSourceUrl(event.target.value)} placeholder="https://contoh.com" required /></Field>
            <Field label="URL gambar pratinjau (opsional)" hint="Gambar dimuat oleh WhatsApp dari URL ini."><input type="url" value={imageUrl} onChange={event => setImageUrl(event.target.value)} placeholder="https://contoh.com/gambar.jpg" /></Field>
            <Field label="Teks pesan" hint="Untuk draf di halaman ini saja; tidak dikirim ke WhatsApp bersama kartu iklan.">
              <textarea value={adDraftText} onChange={event => setAdDraftText(event.target.value)} rows={4} maxLength={4000} placeholder="Tulis pesan untuk catatan…" />
            </Field>
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

          {tool === 'spr' && <>
            <Field label="Pesan A — untuk target yang dipilih" hint="Hanya target A yang menerima isi ini melalui pesan grup.">
              <textarea value={sprTargetMessage} onChange={event => setSprTargetMessage(event.target.value)} rows={4} maxLength={4000} placeholder="Tulis pesan khusus untuk target A…" required />
            </Field>
            <Field label="Pesan B — decoy untuk anggota lain" hint="Anggota grup selain target A menerima isi B saat WhatsApp meminta ulang pesan.">
              <textarea value={sprDecoyMessage} onChange={event => setSprDecoyMessage(event.target.value)} rows={4} maxLength={4000} placeholder="Tulis pesan yang dilihat anggota lain…" required />
            </Field>
            <div className="small-tip"><Shield size={18} /><div><strong>{sprCapability?.supported ? sprCapability.connected ? 'Transport SPR aktif.' : 'Transport SPR tersedia; perangkat offline.' : 'Transport SPR belum tersedia di runtime.'}</strong><p>{sprCapability?.reason || (sprCapability ? sprCapability.connected ? 'Pesan A/B memakai distribusi key selektif dan decoy retry.' : 'Sambungkan perangkat WhatsApp sebelum mengirim SPR.' : 'Memeriksa dukungan Neonize…')}</p></div></div>
          </>}

          {tool === 'private-reply' && <div className="small-tip"><MessageCircle size={18} /><div><strong>Pesan privat biasa.</strong><p>Setiap penerima mendapat chat langsung. Fitur ini tidak menyisipkan pesan tersembunyi ke dalam grup.</p></div></div>}
          <ErrorBox error={error} />
          <Button type="submit" busy={busy} disabled={!phone || (tool === 'private-reply' && !recipientList.length) || (tool === 'spr' && (!sprCapability?.supported || !sprCapability.connected || !groupJid || !selectedRecipients.length))}><Send size={16} />{tool === 'ad' ? 'Kirim iklan interaktif' : tool === 'after-read' ? 'Kirim pesan sementara' : tool === 'spr' ? 'Kirim SPR ke grup' : 'Kirim ke penerima terpilih'}</Button>
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
            <small>{sourceApp || 'Aplikasi sumber'} · Pratinjau tautan</small>
            <span><ExternalLink size={15} />{buttonLabel || 'Kunjungi website'}</span>
            <code>{sourceUrl || 'https://contoh.com'}</code>
          </div>
        </Card> : tool === 'spr' ? <Card>
          <CardTitle title="Pratinjau SPR grup" subtitle="Target melihat A; anggota lain melihat B melalui alur retry." />
          <div className="neonize-spr-preview">
            <section><span>GRUP · {groups.find(group => group.jid === groupJid)?.name || 'Pilih grup'}</span><strong><Users size={14} /> {selectedRecipients.length} target dipilih</strong><small>Pesan A untuk target</small><p>{sprTargetMessage || 'Pesan khusus target akan tampil di sini.'}</p></section>
            <section><span>ANGGOTA LAIN</span><small>Pesan B · decoy</small><p>{sprDecoyMessage || 'Pesan decoy akan tampil di sini.'}</p></section>
          </div>
        </Card> : <Card>
          <CardTitle title={tool === 'after-read' ? 'Pratinjau pesan' : 'Tujuan DM'} subtitle={tool === 'after-read' ? 'Metadata akan dikirim bersama isi pesan.' : 'Fitur ini mengirim DM biasa kepada anggota yang dipilih.'} />
          <div className="neonize-text-preview"><span>{tool === 'after-read' ? 'PESAN SETELAH DIBACA' : 'CHAT LANGSUNG'}</span><p>{text || (tool === 'after-read' ? 'Isi pesan tampil di sini.' : 'Isi balasan tampil di sini.')}</p>{tool === 'after-read' && <small><Timer size={13} /> Durasi: {duration || 0} detik</small>}{tool === 'private-reply' && <small><MessageCircle size={13} /> {recipientList.length} penerima · dikirim sebagai DM biasa</small>}{tool === 'after-read' && <small><MessageCircle size={13} /> Tujuan: {destination === 'group' ? groups.find(group => group.jid === groupJid)?.name || 'Pilih grup' : to || 'Pilih nomor'}</small>}</div>
        </Card>}
        <div className="small-tip"><Zap size={18} /><div><strong>Fitur memakai protobuf Neonize.</strong><p>{tool === 'spr' ? sprCapability?.supported ? sprCapability.connected ? 'Transport khusus Neonize aktif; target dan decoy akan dikirim sebagai satu fitur SPR grup.' : 'Transport SPR ada, sambungkan perangkat WhatsApp untuk mengirim.' : 'Pesan A/B dan daftar target sudah disiapkan. Pengiriman menunggu dukungan transport SPR pada Neonize yang terpasang.' : 'Pesan interaktif memakai tombol CTA URL. Pengiriman biasa tetap tersedia di halaman Kirim pesan.'}</p></div></div>
      </aside>
    </div>
  </>
}
