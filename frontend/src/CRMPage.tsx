import { useEffect, useState } from 'react'
import { Code2, Plus, Play, Save, Trash2 } from 'lucide-react'
import { api, post, useResource, type Device } from './api'
import { Button, Card, CardTitle, CopyButton, DeviceSelect, Empty, ErrorBox, Field, Heading, Modal, ResponseBox, useToast } from './components'
import './crm.css'

type RawItem = {id:string;name:string;kind:'saved'|'action';payload:Record<string,unknown>;source_chat:string;created_at:string}
type Items = {items:RawItem[];total:number;page_size:number}
const example = JSON.stringify({conversation:'Halo dari Utusan!'},null,2)

export function CRMPage() {
  const [kind,setKind]=useState(''); const [page,setPage]=useState(1)
  const list=useResource<Items>(`/api/web/crm/items?page=${page}${kind?`&kind=${kind}`:''}`,10000)
  const devices=useResource<{devices:Device[]}>('/api/web/devices',5000)
  const [selected,setSelected]=useState<RawItem|null>(null);const [name,setName]=useState('Pesan baru');const [raw,setRaw]=useState(example)
  const [phone,setPhone]=useState('');const [to,setTo]=useState('');const [busy,setBusy]=useState(false)
  const [error,setError]=useState('');const [result,setResult]=useState<unknown>(null);const [remove,setRemove]=useState<RawItem|null>(null)
  const notify=useToast()
  const access=useResource<{owners:string[];linked_devices:string[]}>('/api/web/crm/config')
  const [owners,setOwners]=useState('');const [jid,setJid]=useState('');const [conversion,setConversion]=useState<{result:string;direction:string}|null>(null)
  useEffect(()=>{if(access.data)setOwners(access.data.owners.join('\n'))},[access.data])
  useEffect(()=>{if(!phone){const online=devices.data?.devices.find(d=>d.online);if(online)setPhone(online.phone)}},[devices.data,phone])
  const dirty=!!selected && (raw!==JSON.stringify(selected.payload,null,2)||name!==selected.name)
  function open(item:RawItem|null){setSelected(item);setName(item?.name||'Pesan baru');setRaw(item?JSON.stringify(item.payload,null,2):example);setTo(item?.source_chat||'');setError('');setResult(null)}
  async function perform(task:()=>Promise<void>){setError('');setBusy(true);try{await task()}catch(e){const message=(e as Error).message;setError(message);notify(message,'error')}finally{setBusy(false)}}
  function payload(){const parsed=JSON.parse(raw);if(!parsed||Array.isArray(parsed)||typeof parsed!=='object')throw new Error('Raw message harus berupa objek JSON.');return parsed}
  async function save(as:'saved'|'action') {await perform(async()=>{const item=await post<RawItem>('/api/web/crm/items',{name,kind:as,payload:payload()});open(item);await list.refresh();notify(as==='saved'?'Raw message tersimpan ke DB.':'Raw message ditambahkan ke Aksi.')})}
  async function addAction(){if(!selected)return;await perform(async()=>{const item=await post<RawItem>(`/api/web/crm/items/${selected.id}/action`,{});open(item);await list.refresh();notify('Raw message ditambahkan ke Aksi.')})}
  async function run(){if(!selected)return;await perform(async()=>{setResult(null);const response=await post(`/api/web/crm/items/${selected.id}/run`,{phone,to,request_id:crypto.randomUUID()});setResult(response);notify('Raw message terkirim.')})}
  async function deleteItem(){if(!remove)return;await perform(async()=>{await api(`/api/web/crm/items/${remove.id}`,{method:'DELETE'});if(selected?.id===remove.id)open(null);setRemove(null);await list.refresh();notify('Raw message dihapus.')})}
  async function saveOwners(){await perform(async()=>{await post('/api/web/crm/config',{owners:owners.split(/[\n,]/).map(v=>v.trim()).filter(Boolean)});await access.refresh();notify('Akses owner CRM disimpan.')})}
  async function convert(){await perform(async()=>{setConversion(null);setConversion(await post('/api/web/convert-jid',{phone,jid}))})}
  return <>
    <Heading eyebrow="OWNER TOOLS" title="CRM • Raw Message" description="Ambil, simpan, dan kirim ulang pesan WhatsApp dalam bentuk JSON."/>
    <Card className="crm-guide"><Code2 size={24}/><div><h2>Reply pesan → ketik <code>crm</code></h2><p>Gunakan nomor WhatsApp terhubung atau owner tambahan, di grup atau chat pribadi. Hasil JSON dan tombol dikirim ke chat pribadi owner yang meminta.</p><div className="crm-guide-actions"><span><strong>Jalankan</strong> · kirim ulang ke chat asal</span><span><strong>Simpan ke DB</strong> · arsip pesan</span><span><strong>Tambah ke Aksi</strong> · pesan siap dijalankan</span></div><small>Tombol WhatsApp berlaku 15 menit. Pesan yang sudah disimpan tetap tersedia di akun Anda.</small></div></Card>
    <ErrorBox error={list.error||devices.error||access.error}/>
    <div className="crm-settings"><Card><CardTitle title="Owner CRM" subtitle="Nomor tambahan ini dapat memakai CRM pada semua perangkat akun Anda."/><p className="crm-note">Nomor terhubung selalu memiliki akses: {access.data?.linked_devices.map(p=>'+'+p).join(', ')||'Belum ada perangkat'}.</p><Field label="Owner tambahan" hint="Satu nomor berkode negara per baris. Kosongkan untuk mencabut seluruh owner tambahan."><textarea disabled={busy} value={owners} onChange={e=>setOwners(e.target.value)} placeholder="62812xxxxxxxx" rows={3}/></Field><Button disabled={busy||!access.data} onClick={saveOwners}>Simpan akses owner</Button></Card>
    <Card><CardTitle title="Konversi JID ↔ LID" subtitle="Gunakan mapping identitas pada perangkat WhatsApp yang online."/><DeviceSelect devices={devices.data?.devices||[]} value={phone} onChange={setPhone}/><Field label="JID / nomor untuk konversi"><input disabled={busy} value={jid} onChange={e=>setJid(e.target.value)} placeholder="62812xxxxxxxx@s.whatsapp.net atau 123456789@lid"/></Field><Button disabled={busy||!phone||!jid.trim()} onClick={convert}>Konversi</Button>{conversion&&<div className="crm-conversion"><span>{conversion.direction}</span><strong>{conversion.result}</strong><CopyButton value={conversion.result} label="Salin hasil"/></div>}</Card></div>
    <div className="crm-grid"><Card className="crm-library">
      <CardTitle title="Koleksi Anda" subtitle={`${list.data?.total||0} pesan tersimpan`}><Button variant="secondary" disabled={busy} onClick={()=>open(null)}><Plus size={15}/>Baru</Button></CardTitle>
      <Field label="Tampilkan"><select value={kind} onChange={e=>{setKind(e.target.value);setPage(1)}}><option value="">Semua pesan</option><option value="saved">Tersimpan</option><option value="action">Aksi</option></select></Field>
      {!list.data?.items.length?<Empty title={list.loading?'Memuat koleksi…':'Belum ada raw message'} description="Reply pesan dengan crm lalu simpan, atau masukkan JSON di editor."/>:<div className="crm-items">{list.data.items.map(item=><button disabled={busy} key={item.id} className={`crm-item ${selected?.id===item.id?'active':''}`} onClick={()=>open(item)}><span className="tag">{item.kind==='action'?'Aksi':'Tersimpan'}</span><strong>{item.name}</strong><small>{Object.keys(item.payload).join(', ')}</small><small>{new Date(item.created_at).toLocaleString('id-ID')}</small></button>)}</div>}
      {!!list.data?.total&&<div className="crm-pagination"><Button variant="ghost" disabled={page===1||busy} onClick={()=>setPage(p=>p-1)}>Sebelumnya</Button><span>{page}</span><Button variant="ghost" disabled={page*list.data.page_size>=list.data.total||busy} onClick={()=>setPage(p=>p+1)}>Berikutnya</Button></div>}
    </Card><Card className="crm-editor">
      <CardTitle title={selected?'Detail raw message':'Raw message baru'} subtitle="JSON protobuf WhatsApp. Hanya akun Anda yang dapat membuka koleksi ini."><CopyButton value={raw} label="Salin JSON"/></CardTitle>
      <Field label="Nama pesan"><input disabled={busy} value={name} maxLength={100} onChange={e=>setName(e.target.value)}/></Field>
      <Field label="Raw message JSON" hint="Gunakan nama field protobuf yang tepat, misalnya buttonParamsJSON."><textarea className="crm-json" disabled={busy} value={raw} onChange={e=>{setRaw(e.target.value);setResult(null)}} spellCheck={false}/></Field>
      <ErrorBox error={error}/>
      <div className="crm-actions"><Button busy={busy} onClick={()=>save('saved')}><Save size={16}/>{selected?'Simpan salinan ke DB':'Simpan ke DB'}</Button>{selected?.kind!=='action'&&<Button variant="secondary" disabled={busy} onClick={()=>selected&&!dirty?addAction():save('action')}><Plus size={16}/>Tambah ke Aksi</Button>}{selected&&<Button variant="danger" disabled={busy} onClick={()=>setRemove(selected)}><Trash2 size={16}/>Hapus</Button>}</div>
      <div className="crm-send"><h3>Jalankan pesan</h3><p>Kirim JSON tersimpan melalui perangkat yang dipilih ke nomor atau JID tujuan.</p>
        <DeviceSelect devices={devices.data?.devices||[]} value={phone} onChange={setPhone}/>
        <Field label="Tujuan" hint="Contoh: 62812xxxxxxxx atau 120363xxxxxxxx@g.us"><input disabled={busy} value={to} onChange={e=>setTo(e.target.value)} placeholder="Nomor dengan kode negara / JID grup"/></Field>
        <p className="crm-target">Tujuan pengiriman: <strong>{to||'Belum dipilih'}</strong></p>
        {dirty&&<p className="crm-note">JSON atau nama berubah. Simpan salinan dahulu agar pesan yang dijalankan sesuai editor.</p>}
        {!selected&&<p className="crm-note">Simpan JSON dahulu untuk menjalankannya.</p>}
        <Button disabled={busy||!selected||dirty||!phone||!to.trim()||!devices.data?.devices.some(d=>d.phone===phone&&d.online)} busy={busy} onClick={run}><Play size={16}/>Jalankan</Button>
        <ResponseBox result={result}/>
      </div>
    </Card></div>
    {remove&&<Modal title="Hapus raw message?" onClose={()=>!busy&&setRemove(null)}><p>Hapus “{remove.name}” dari koleksi akun Anda?</p><div className="crm-actions"><Button variant="secondary" disabled={busy} onClick={()=>setRemove(null)}>Batal</Button><Button variant="danger" busy={busy} onClick={deleteItem}>Hapus dari DB</Button></div></Modal>}
  </>
}
