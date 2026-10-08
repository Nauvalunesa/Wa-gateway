import { useEffect, useState } from 'react'
import { CheckCheck, Save, ShieldCheck } from 'lucide-react'
import { api, query } from './api'
import { Button, Card, CardTitle, CopyButton, ErrorBox, Field, Loading, useToast } from './components'

type Setting = 'read_receipts' | 'last_seen' | 'online' | 'profile_photo' | 'group_add' | 'calls'
type Preferences = { auto_read: boolean; auto_read_scope: 'private' | 'all' }
type Privacy = { preferences: Preferences; privacy: Partial<Record<Setting, string>>; warnings: string[] }
const settings: { key: Setting; label: string; options: [string, string][] }[] = [
  { key: 'read_receipts', label: 'Laporan dibaca / centang biru', options: [['all', 'Aktif'], ['none', 'Sembunyikan pada chat pribadi']] },
  { key: 'last_seen', label: 'Terakhir dilihat', options: [['all', 'Semua orang'], ['contacts', 'Kontak saya'], ['none', 'Tidak ada']] },
  { key: 'online', label: 'Siapa yang melihat online', options: [['all', 'Semua orang'], ['match_last_seen', 'Sama seperti terakhir dilihat']] },
  { key: 'profile_photo', label: 'Siapa yang melihat foto profil', options: [['all', 'Semua orang'], ['contacts', 'Kontak saya'], ['none', 'Tidak ada']] },
  { key: 'group_add', label: 'Siapa yang menambahkan ke grup', options: [['all', 'Semua orang'], ['contacts', 'Kontak saya'], ['none', 'Tidak ada']] },
  { key: 'calls', label: 'Panggilan dari nomor asing', options: [['all', 'Izinkan semua'], ['known', 'Batasi ke nomor yang dikenal']] },
]

export function WhatsAppPrivacyPanel({ phone, online, busy, setBusy, reload }: { phone: string; online: boolean; busy: string; setBusy: (value: string) => void; reload: number }) {
  const [values, setValues] = useState<Partial<Record<Setting, string>>>({})
  const [prefs, setPrefs] = useState<Preferences>({ auto_read: false, auto_read_scope: 'private' })
  const [error, setError] = useState('')
  const [warnings, setWarnings] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const notify = useToast()
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true); setValues({}); setError(''); setWarnings([]); setPrefs({ auto_read: false, auto_read_scope: 'private' })
    void api<Privacy>(query('/api/web/wa-profile/privacy', { phone }), { signal: controller.signal }).then(data => {
      setValues(data.privacy); setPrefs(data.preferences); setWarnings(data.warnings)
    }).catch(e => { if (!controller.signal.aborted) setError(e.message) }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [phone, reload])
  async function savePrefs() {
    setBusy('auto-read'); setError('')
    try {
      await api('/api/web/wa-profile/preferences', { method: 'PUT', body: JSON.stringify({ phone, ...prefs }) })
      notify('Pengaturan auto-read disimpan untuk perangkat ini.')
    } catch (e) { setError((e as Error).message) } finally { setBusy('') }
  }
  async function savePrivacy(setting: Setting) {
    setBusy(setting); setError('')
    try {
      await api('/api/web/wa-profile/privacy', { method: 'PUT', body: JSON.stringify({ phone, setting, value: values[setting] }) })
      notify('Pengaturan privasi dikirim ke WhatsApp.')
    } catch (e) { setError((e as Error).message) } finally { setBusy('') }
  }
  const payload = JSON.stringify({ phone, ...prefs }, null, 2)
  const curl = `curl --request PUT '${window.location.origin}/api/web/wa-profile/preferences' \\\n  --header 'Content-Type: application/json' \\\n  --header 'Cookie: session=COOKIE_SESSION' \\\n  --data-raw '${payload}'`
  return <Card className="wa-profile-privacy"><CardTitle title="Privasi & auto-read" subtitle="Pisahkan membaca pesan otomatis dari visibilitas centang biru."><ShieldCheck size={20} /></CardTitle><ErrorBox error={error} />{loading ? <Loading /> : <>
    {warnings.map(w => <p key={w} className="wa-profile-note">{w}</p>)}
    <div className="wa-auto-read"><div><CheckCheck size={21} /><strong>Auto-read pesan masuk</strong></div><label className="check-label"><input type="checkbox" checked={prefs.auto_read} disabled={!!busy} onChange={e => setPrefs({ ...prefs, auto_read: e.target.checked })} />Tandai pesan masuk sebagai dibaca secara otomatis</label><Field label="Cakupan auto-read"><select value={prefs.auto_read_scope} disabled={!!busy} onChange={e => setPrefs({ ...prefs, auto_read_scope: e.target.value as Preferences['auto_read_scope'] })}><option value="private">Chat pribadi saja</option><option value="all">Chat pribadi dan grup</option></select></Field><Button busy={busy === 'auto-read'} disabled={!online || !!busy} onClick={() => void savePrefs()}><Save size={15} />Simpan auto-read</Button><p className="wa-profile-note">Berlaku pada pesan masuk baru di perangkat ini dan tetap tersimpan setelah restart. Pengaturan privasi WhatsApp tetap menentukan receipt yang dikirim.</p></div>
    <div className="wa-privacy-grid">{settings.map(setting => <div className="wa-privacy-setting" key={setting.key}><Field label={setting.label}><select value={values[setting.key] || ''} disabled={!!busy} onChange={e => setValues({ ...values, [setting.key]: e.target.value })}>{!setting.options.some(([value]) => value === values[setting.key]) && <option value={values[setting.key] || ''} disabled>{values[setting.key] ? `Pengaturan WhatsApp: ${values[setting.key]}` : 'Pilih nilai privasi'}</option>}{setting.options.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field><Button variant="secondary" busy={busy === setting.key} disabled={!online || !!busy || !setting.options.some(([value]) => value === values[setting.key])} onClick={() => void savePrivacy(setting.key)}>Terapkan</Button></div>)}</div>
    <p className="wa-profile-note">Mematikan laporan dibaca menyembunyikan centang biru pada chat pribadi. WhatsApp mempunyai pengecualian untuk chat grup dan receipt pemutaran pesan suara. Pengaturan online yang mengikuti terakhir dilihat juga membutuhkan pengaturan terakhir dilihat yang sesuai.</p>
    <details className="wa-profile-code"><summary>Request auto-read</summary><CopyButton value={curl} label="Salin cURL" /><pre>{curl}</pre></details>
  </>}</Card>
}
