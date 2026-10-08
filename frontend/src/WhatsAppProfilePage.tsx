import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Camera, RefreshCw, Save, UserRound } from 'lucide-react'
import { api, query, useResource, type Device } from './api'
import { Button, Card, CardTitle, CopyButton, Empty, ErrorBox, Field, Heading, Loading, useToast } from './components'
import './whatsapp-profile.css'
import { WhatsAppPrivacyPanel } from './WhatsAppPrivacyPanel'

type Profile = { phone: string; jid: string; name: string; about: string | null; photo_url: string | null; warnings: string[] }
type PhotoPreview = { preview: string; sha256: string; width: number; height: number; source_size: number[]; size_bytes: number; experimental: boolean }
type PhotoMode = 'contain' | 'cover' | 'original'
const quote = (value: string) => `'${value.replaceAll("'", "'\\''")}'`

export function WhatsAppProfilePage() {
  const [params, setParams] = useSearchParams()
  const phone = params.get('phone') || ''
  const devices = useResource<{ devices: Device[] }>('/api/web/devices', 5000)
  const [profile, setProfile] = useState<Profile | null>(null)
  const [name, setName] = useState('')
  const [about, setAbout] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [reload, setReload] = useState(0)
  const [busy, setBusy] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [mode, setMode] = useState<PhotoMode>('contain')
  const [background, setBackground] = useState('#ffffff')
  const [preview, setPreview] = useState<PhotoPreview | null>(null)
  const [previewing, setPreviewing] = useState(false)
  const [photoError, setPhotoError] = useState('')
  const notify = useToast()
  const online = devices.data?.devices.some(d => d.phone === phone && d.online) || false

  useEffect(() => {
    const controller = new AbortController()
    setProfile(null); setError(''); setName(''); setAbout('')
    if (!phone) { setLoading(false); return }
    setLoading(true)
    void api<Profile>(query('/api/web/wa-profile', { phone }), { signal: controller.signal }).then(result => {
      setProfile(result); setName(result.name); setAbout(result.about || '')
    }).catch(e => { if (!controller.signal.aborted) setError(e.message) }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [phone, reload])

  useEffect(() => { setFile(null); setPreview(null); setPhotoError('') }, [phone])
  useEffect(() => {
    setPreview(null); setPhotoError('')
    if (!file) { setPreviewing(false); return }
    const controller = new AbortController()
    setPreviewing(true)
    const timer = setTimeout(() => {
      const body = new FormData(); body.set('file', file); body.set('mode', mode); body.set('background', background)
      void api<PhotoPreview>('/api/web/wa-profile/photo/preview', { method: 'POST', body, signal: controller.signal })
        .then(setPreview).catch(e => { if (!controller.signal.aborted) setPhotoError(e.message) })
        .finally(() => { if (!controller.signal.aborted) setPreviewing(false) })
    }, 250)
    return () => { clearTimeout(timer); controller.abort() }
  }, [file, mode, background])

  async function saveField(field: 'name' | 'about') {
    if (!phone || !online || busy) return
    setBusy(field); setError('')
    try {
      const data = await api<Record<string, string>>(`/api/web/wa-profile/${field}`, {
        method: 'PUT', body: JSON.stringify({ phone, [field]: field === 'name' ? name : about }),
      })
      if (field === 'name') setName(data.name)
      if (field === 'about') setAbout(data.about)
      notify(`${field === 'name' ? 'Nama' : 'Info/about'} dikirim ke WhatsApp. Tampilan perangkat bisa menunggu sinkronisasi.`)
    } catch (e) { setError((e as Error).message) } finally { setBusy('') }
  }
  async function savePhoto() {
    if (!file || !preview || !phone || !online || busy) return
    setBusy('photo'); setPhotoError('')
    try {
      const body = new FormData()
      body.set('phone', phone); body.set('file', file); body.set('mode', mode); body.set('background', background); body.set('sha256', preview.sha256)
      await api('/api/web/wa-profile/photo', { method: 'POST', body })
      notify('Foto profil diterapkan melalui WhatsApp. Muat ulang untuk memeriksa profil tersinkron.')
    } catch (e) { setPhotoError((e as Error).message) } finally { setBusy('') }
  }
  const request = (field: 'name' | 'about') => `curl --request PUT ${quote(`${window.location.origin}/api/web/wa-profile/${field}`)} \\\n  --header 'Content-Type: application/json' \\\n  --header 'Cookie: session=COOKIE_SESSION' \\\n  --data-raw ${quote(JSON.stringify({ phone, [field]: field === 'name' ? name : about }, null, 2))}`
  const photoCurl = `curl --request POST ${quote(`${window.location.origin}/api/web/wa-profile/photo`)} \\\n  --header 'Cookie: session=COOKIE_SESSION' \\\n  --form ${quote(`phone=${phone}`)} \\\n  --form ${quote(`file=@/PATH/${file?.name || 'foto.jpg'}`)} \\\n  --form ${quote(`mode=${mode}`)} \\\n  --form ${quote(`background=${background}`)} \\\n  --form ${quote(`sha256=${preview?.sha256 || 'HASH_DARI_ENDPOINT_PREVIEW'}`)}`

  return <>
    <Heading eyebrow="WHATSAPP IDENTITY" title="Profil WhatsApp" description="Ubah nama, info/about, dan foto pada perangkat WhatsApp milik akun Anda.">
      <Button variant="secondary" disabled={!phone || loading || !!busy} onClick={() => setReload(v => v + 1)}><RefreshCw size={16} />Muat ulang profil</Button>
    </Heading>
    <Card><Field label="Perangkat untuk pengaturan profil"><select value={phone} disabled={!!busy} onChange={e => setParams(e.target.value ? { phone: e.target.value } : {})}><option value="">Pilih perangkat WhatsApp</option>{devices.data?.devices.map(d => <option key={d.phone} value={d.phone}>+{d.phone} · {d.online ? 'Online' : 'Offline'}</option>)}</select><small>Pilih nomor yang ingin diubah. Perangkat harus online untuk membaca dan menyimpan profil.</small></Field><ErrorBox error={devices.error} /></Card>
    <ErrorBox error={error} />
    {!phone ? <Card className="mt-card"><Empty icon={UserRound} title="Pilih perangkat WhatsApp" description="Pengaturan profil diterapkan hanya pada nomor yang Anda pilih."><Link className="btn btn-secondary" to="/devices">Kelola perangkat</Link></Empty></Card> : loading ? <Loading /> : <div className="wa-profile-layout">
      <div className="wa-profile-details">
        <Card>
          <CardTitle title="Profil saat ini" subtitle={profile?.jid || `Perangkat +${phone}`} />
          <div className="wa-profile-identity"><div className="wa-profile-avatar">{profile?.photo_url ? <img src={profile.photo_url} alt="Foto profil WhatsApp saat ini" onError={e => { e.currentTarget.style.display = 'none' }} /> : <UserRound size={30} />}</div><div><strong>{profile?.name || `+${phone}`}</strong><p>{profile?.about ?? 'Info/about belum dimuat'}</p><span className="tag">{online ? 'Online' : 'Offline'}</span></div></div>
          {profile?.warnings.map(warning => <p className="wa-profile-note" key={warning}>{warning}</p>)}
        </Card>
        <Card><CardTitle title="Nama profil" subtitle="Nama WhatsApp yang dibagikan kepada kontak." /><Field label="Nama profil WhatsApp"><input value={name} maxLength={25} disabled={!!busy} onChange={e => setName(e.target.value)} /><small>{Array.from(name).length}/25 karakter</small></Field><Button busy={busy === 'name'} disabled={!online || !name.trim() || !!busy} onClick={() => void saveField('name')}><Save size={16} />Simpan nama</Button><details className="wa-profile-code"><summary>Request nama profil</summary><CopyButton value={request('name')} label="Salin cURL" /><pre>{request('name')}</pre></details></Card>
        <Card><CardTitle title="Info / About" subtitle="Teks singkat pada profil, terpisah dari status/story." /><Field label="Info / About WhatsApp"><textarea rows={3} maxLength={139} value={about} disabled={!!busy} onChange={e => setAbout(e.target.value)} /><small>Batas editor: {Array.from(about).length}/139 karakter. WhatsApp dapat menerapkan batas berbeda pada akun Anda.</small></Field><Button busy={busy === 'about'} disabled={!online || !!busy} onClick={() => void saveField('about')}><Save size={16} />Simpan info</Button><details className="wa-profile-code"><summary>Request info/about</summary><CopyButton value={request('about')} label="Salin cURL" /><pre>{request('about')}</pre></details></Card>
      </div>
      <Card>
        <CardTitle title="Foto profil" subtitle="Preview dibuat dari JPEG yang sama dengan file yang akan dikirim." />
        <Field label="Unggah foto profil"><input type="file" accept="image/jpeg,image/png,image/webp" disabled={!!busy} onChange={e => {
          const chosen = e.target.files?.[0] || null
          if (chosen && chosen.size > 10 * 1024 * 1024) { setPhotoError('Ukuran foto maksimal 10 MB'); setFile(null); e.target.value = ''; return }
          setFile(chosen)
        }} /><small>JPEG, PNG, WebP; maksimal 10 MB dan 20 megapiksel.</small></Field>
        <Field label="Mode foto profil"><select value={mode} disabled={!!busy} onChange={e => setMode(e.target.value as PhotoMode)}><option value="contain">Foto utuh dalam kotak</option><option value="cover">Crop kotak di tengah</option><option value="original">Rasio asli / PP panjang (eksperimental)</option></select></Field>
        <Field label="Warna latar foto"><input type="color" value={background} disabled={!!busy} onChange={e => setBackground(e.target.value)} /></Field>
        {mode === 'original' && <p className="wa-profile-note">Rasio asli mempertahankan bentuk foto panjang tanpa crop kotak. WhatsApp dapat menolak, memotong, atau mengubah tampilannya; hasil panjang belum dijamin.</p>}
        <ErrorBox error={photoError} />
        {previewing ? <Loading /> : preview ? <div className="wa-profile-photo-preview"><div><span>JPEG yang akan dikirim</span><img src={preview.preview} alt="Preview foto profil yang akan dikirim" /></div><div><span>Ilustrasi thumbnail bulat</span><img className="wa-profile-circle" src={preview.preview} alt="Ilustrasi foto profil dalam thumbnail bulat" /></div><small>Sumber {preview.source_size.join(' × ')} → {preview.width} × {preview.height} px · {Math.ceil(preview.size_bytes / 1024)} KB</small></div> : <div className="wa-profile-photo-empty"><Camera size={28} /><p>Pilih foto untuk melihat hasil pengolahan.</p></div>}
        <Button className="w-full" busy={busy === 'photo'} disabled={!online || !preview || previewing || !!busy} onClick={() => void savePhoto()}><Camera size={17} />Terapkan foto profil</Button>
        <p className="wa-profile-note">Foto utuh menambahkan latar agar bagian gambar tetap masuk dalam kotak. Crop kotak memotong sisi berlebih. Preview bukan jaminan tampilan akhir pada WhatsApp penerima.</p>
        <details className="wa-profile-code"><summary>Request foto profil</summary><CopyButton value={photoCurl} label="Salin cURL" /><pre>{photoCurl}</pre></details>
      </Card>
      <WhatsAppPrivacyPanel phone={phone} online={online} busy={busy} setBusy={setBusy} reload={reload} />
    </div>}
  </>
}
