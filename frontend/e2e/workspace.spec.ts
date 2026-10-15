import {test,expect,type Page} from '@playwright/test'
async function register(page:Page){const username='uitest'+Date.now()+Math.floor(Math.random()*100);await page.goto('/register');await page.getByLabel('Username',{exact:false}).fill(username);await page.getByLabel('Password',{exact:true}).fill('Testing-password-2026');await page.getByLabel('Konfirmasi password',{exact:true}).fill('Testing-password-2026');await page.getByRole('button',{name:'Buat akun Utusan'}).click();await expect(page.getByRole('heading',{name:`Halo, ${username}.`})).toBeVisible();return username}

test('login, registration, password confirmation, persistent auth and logout',async({page})=>{const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));await page.goto('/login');await expect(page.getByRole('heading',{name:'Senang melihat Anda lagi.'})).toBeVisible();await page.screenshot({path:'test-results/login-desktop.png',fullPage:true});const username=await register(page);await page.reload();await expect(page.getByRole('heading',{name:`Halo, ${username}.`})).toBeVisible();await page.screenshot({path:'test-results/dashboard-desktop.png',fullPage:true});await page.getByRole('button',{name:'Keluar dari workspace'}).click();await expect(page).toHaveURL(/\/login$/);await page.getByLabel('Username').fill(username);await page.getByLabel('Password',{exact:true}).fill('Testing-password-2026');await page.getByRole('button',{name:'Masuk ke workspace'}).click();await expect(page.getByRole('heading',{name:`Halo, ${username}.`})).toBeVisible();expect(errors).toEqual([])})

test('AI Rich validates actual payload, code blocks, editing and malformed JSON',async({page})=>{await register(page);await page.getByRole('link',{name:'AI Rich Studio NEW'}).click();await expect(page.getByRole('heading',{name:'AI Rich Studio',exact:true})).toBeVisible();await page.getByLabel('Jenis blok baru').selectOption('code');await page.getByRole('button',{name:'Tambah',exact:true}).click();await expect(page.getByLabel('Bahasa')).toHaveValue('html');await page.getByRole('button',{name:'Validasi & pratinjau JSON'}).click();await expect(page.locator('.response')).toContainText('"sent": false');await expect(page.locator('.response')).toContainText('codeLanguage');await page.getByLabel('Jenis blok baru').selectOption('table');await page.getByRole('button',{name:'Tambah',exact:true}).click();await page.getByLabel('Isi blok (JSON)').fill('invalid');await page.getByRole('button',{name:'Validasi & pratinjau JSON'}).click();await expect(page.getByRole('alert').last()).toContainText('Perbaiki JSON');await page.screenshot({path:'test-results/airich-desktop.png',fullPage:true})})

test('device pairing flow renders returned code and detects connection',async({page})=>{await register(page);let online=false;await page.route('**/api/web/devices',route=>route.fulfill({json:{devices:online?[{phone:'628123456789',number:'628123456789',online:true,pairing:false}]:[]}}));await page.route('**/api/pair',route=>route.fulfill({json:{success:true,code:'TEST-CODE'}}));await page.goto('/devices');await page.getByRole('button',{name:'Hubungkan perangkat',exact:true}).first().click();await page.getByLabel('Nomor WhatsApp').fill('628123456789');await page.getByRole('button',{name:'Dapatkan kode pairing'}).click();await expect(page.getByText('TEST-CODE',{exact:true})).toBeVisible();online=true;await expect(page.getByRole('heading',{name:'Perangkat terhubung!'})).toBeVisible({timeout:10000})})

test('CSV parsing, device selection and broadcast request',async({page})=>{await register(page);await page.route('**/api/web/devices',route=>route.fulfill({json:{devices:[{phone:'628123456789',number:'628123456789',online:true,pairing:false}]}}));let request:Record<string,unknown>|undefined;await page.route('**/api/blast',route=>{request=route.request().postDataJSON();return route.fulfill({json:{success:true,message:'Queued'}})});await page.goto('/blast');await page.getByLabel('Unggah CSV penerima').setInputFiles({name:'recipients.csv',mimeType:'text/csv',buffer:Buffer.from('phone,name\n6281776348790,Contoh\n')});await expect(page.getByText('1 penerima berhasil dimuat')).toBeVisible();await page.getByRole('checkbox').check();await page.getByRole('button',{name:'Mulai broadcast'}).click();await expect(page.locator('.response')).toContainText('Queued');expect(request?.phone_data).toEqual([{phone:'6281776348790',name:'Contoh'}]);expect(request?.devices).toEqual(['628123456789'])})

test('mobile auth, drawer navigation, responsive pages and API key',async({page})=>{await page.setViewportSize({width:390,height:844});await page.goto('/login');await page.screenshot({path:'test-results/login-mobile.png',fullPage:true});await register(page);await page.getByRole('button',{name:'Buka navigasi'}).click();await page.getByRole('link',{name:'Pengaturan',exact:true}).click();await expect(page.getByRole('heading',{name:'Pengaturan & API'})).toBeVisible();await page.screenshot({path:'test-results/settings-mobile.png',fullPage:true});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();await page.goto('/airich');await expect(page.getByRole('heading',{name:'AI Rich Studio',exact:true})).toBeVisible();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy()})

const mockDevices=[{phone:'628123456789',number:'628123456789',online:true,pairing:false},{phone:'628987654321',number:'628987654321',online:true,pairing:false}]

test('message requests use cookies, prevent duplicate sends, and show API failures',async({page})=>{
  await register(page)
  await page.route('**/api/web/devices',route=>route.fulfill({json:{devices:mockDevices}}))
  let calls=0
  let release:()=>void=()=>{}
  await page.route('**/api/send-message?**',async route=>{
    calls++
    expect(route.request().headers()['x-api-key']).toBeUndefined()
    await new Promise<void>(resolve=>{release=resolve})
    await route.fulfill({json:{success:true,message:'Mock delivery'}})
  })
  await page.goto('/tools')
  await page.getByLabel('Perangkat pengirim').selectOption(mockDevices[0].phone)
  await page.getByLabel('Nomor WhatsApp penerima').fill('6281776348790')
  await page.getByLabel('Isi pesan',{exact:false}).fill('Hello')
  const send=page.getByRole('button',{name:'Kirim pesan',exact:true})
  await send.click()
  await expect(send).toBeDisabled()
  await send.evaluate(el=>(el as HTMLButtonElement).click())
  expect(calls).toBe(1)
  release()
  await expect(send).toBeEnabled()
  await page.unroute('**/api/send-message?**')
  await page.route('**/api/send-message?**',route=>route.fulfill({status:503,json:{detail:'Perangkat sedang offline'}}))
  await send.click()
  await expect(page.getByRole('alert')).toContainText('Perangkat sedang offline')
  await expect(page).toHaveURL(/\/tools$/)
  await page.unroute('**/api/send-message?**')
  await page.route('**/api/send-message?**',route=>route.fulfill({json:{success:false,message:'Pengiriman tidak berhasil'}}))
  await send.click()
  await expect(page.getByRole('alert')).toContainText('Pengiriman tidak berhasil')
})

test('group selections reset on device changes and channel names use metadata',async({page})=>{
  await register(page)
  await page.route('**/api/web/devices',route=>route.fulfill({json:{devices:mockDevices}}))
  await page.route('**/api/web/groups?**',route=>{
    const first=new URL(route.request().url()).searchParams.get('phone')===mockDevices[0].phone
    return route.fulfill({json:{groups:[{jid:first?'111@g.us':'222@g.us',name:first?'Grup pertama':'Grup kedua'}]}})
  })
  await page.route('**/api/newsletter/list?**',route=>route.fulfill({json:{newsletters:[{ID:{User:'120363000000001',Server:'newsletter'},ThreadMeta:{Name:{Text:'Channel contoh'}}}]}}))
  await page.goto('/tools')
  await page.getByLabel('Perangkat pengirim').selectOption(mockDevices[0].phone)
  await page.getByLabel('Tujuan pesan').selectOption('group')
  const group=page.getByLabel('Pilih grup WhatsApp',{exact:false})
  await expect(group.locator('option')).toContainText(['Pilih grup','Grup pertama'])
  await group.selectOption('111@g.us')
  await page.getByLabel('Perangkat pengirim').selectOption(mockDevices[1].phone)
  await expect(group).toHaveValue('')
  await expect(group.locator('option')).toContainText(['Pilih grup','Grup kedua'])
  await expect(group.locator('option')).not.toContainText(['Grup pertama'])
  await page.getByLabel('Tujuan pesan').selectOption('channel')
  await expect(page.getByLabel('Pilih channel WhatsApp',{exact:false}).locator('option')).toContainText(['Pilih channel','Channel contoh'])
})

test('group utility needs no unrelated recipient and structured types have no duplicate caption',async({page})=>{
  await register(page)
  await page.route('**/api/web/devices',route=>route.fulfill({json:{devices:mockDevices}}))
  await page.route('**/api/groups?**',route=>route.fulfill({json:{success:true,groups:[],count:0}}))
  await page.goto('/tools')
  await page.getByLabel('Perangkat pengirim').selectOption(mockDevices[0].phone)
  await page.locator('.type-tabs').getByRole('button',{name:'Utilities',exact:true}).click()
  await page.getByLabel('Jenis pemeriksaan').selectOption('groups')
  await expect(page.getByLabel('Nomor / JID untuk diperiksa')).toHaveCount(0)
  await page.getByRole('button',{name:'Jalankan pemeriksaan'}).click()
  await expect(page.locator('.response')).toContainText('"count": 0')
  for(const name of ['Lokasi','Polling','Reaksi']){
    await page.locator('.type-tabs').getByRole('button',{name,exact:true}).click()
    await expect(page.getByLabel('Caption (opsional)')).toHaveCount(0)
  }
})

test('AI Rich preview 401 does not log out when cookie session is valid',async({page})=>{
  await register(page)
  await page.route('**/api/web/devices',route=>route.fulfill({json:{devices:[]}}))
  await page.route('**/api/airich/preview',route=>route.fulfill({status:401,json:{detail:'Preview authorization failed'}}))
  await page.goto('/airich')
  await page.getByRole('button',{name:'Validasi & pratinjau JSON'}).click()
  await expect(page.getByRole('alert').last()).toContainText('Preview authorization failed')
  await expect(page).toHaveURL(/\/airich$/)
  await expect(page.getByRole('heading',{name:'AI Rich Studio',exact:true})).toBeVisible()
})

test('AI Rich can target a selected WhatsApp group JID',async({page})=>{
  await register(page)
  await page.route('**/api/web/devices',route=>route.fulfill({json:{devices:mockDevices}}))
  await page.route('**/api/web/groups?**',route=>route.fulfill({json:{groups:[{jid:'120363000000001@g.us',name:'Grup uji'}]}}))
  let sent:Record<string,unknown>|undefined
  await page.route('**/api/send-airich',route=>{sent=route.request().postDataJSON();return route.fulfill({json:{success:true,message:'sent'}})})
  await page.goto('/airich')
  await page.getByLabel('Perangkat pengirim').selectOption(mockDevices[0].phone)
  await page.getByLabel('Tujuan AI Rich').selectOption('group')
  await page.getByLabel('Pilih grup WhatsApp').selectOption('120363000000001@g.us')
  await page.getByRole('button',{name:'Kirim AI Rich'}).click()
  await expect(page.getByRole('alert')).toContainText('Gateway menerima pesan AI Rich')
  expect(sent?.to).toBe('120363000000001@g.us')
})

test('AI Rich exposes complete cURL and saves autoresponder rules',async({page})=>{
  await register(page)
  await page.route('**/api/web/airich/auto-replies',route=>route.request().method()==='GET'?route.fulfill({json:{rules:[]}}):route.fulfill({json:{success:true,rules:route.request().postDataJSON().rules}}))
  await page.goto('/airich')
  const guide=page.locator('.request-guide')
  await guide.locator('summary').click()
  await expect(guide).toContainText("curl -X POST 'https://utusan.chat/api/send-airich'")
  await expect(guide.getByRole('button',{name:'Salin cURL'})).toBeVisible()
  await page.goto('/auto-reply')
  await page.getByLabel('Kata pemicu').fill('harga')
  await page.getByRole('button',{name:'Tambah aturan auto-reply'}).click()
  await expect(page.locator('.auto-reply-rule')).toContainText('harga')
})

test('AI Rich adds all message block types separately and keeps cURL synced',async({page})=>{
  await register(page)
  await page.goto('/airich')
  await expect(page.getByLabel('HTML, CSS & JavaScript')).toHaveCount(0)
  const guide=page.locator('.request-guide')
  await expect(guide.locator('summary')).toContainText('Panduan API lengkap')
  await expect(guide.locator('.request-guide-curl')).toContainText('"type": "text"')
  await page.getByRole('button',{name:'Tambahkan semua blok'}).click()
  await expect(page.locator('.rich-block')).toHaveCount(13)
  for(const label of ['HTML interaktif (eksperimental)','Teks & Markdown','Kode sumber','Tabel','Gambar','Video','Sumber','Produk','Reels','Post','Tips','Saran']){
    await expect(page.locator('.rich-block').filter({hasText:label}).first()).toBeVisible()
  }
  await expect(guide.locator('.request-guide-curl')).toContainText('"type": "suggest"')
  await expect(page.getByRole('heading',{name:'AI Rich Auto Reply'})).toHaveCount(0)
})

test('all workspace pages fit mobile and tablet viewports',async({page})=>{
  await register(page)
  await page.route('**/api/web/logs?**',route=>route.fulfill({json:{rows:[{id:17,timestamp:'2026-10-03 12:30:00',sender:'628123456789@s.whatsapp.net',receiver:'120363000000001@g.us',message:'Pesan contoh untuk detail riwayat.',type:'OUTGOING'}],total:1,page:1,limit:20}}))
  const routes=['/','/devices','/tools','/airich','/blast','/channels','/auto-reply','/logs','/settings']
  for(const width of [390,768]){
    await page.setViewportSize({width,height:900})
    for(const route of routes){
      await page.goto(route)
      await page.waitForTimeout(80)
      const overflow=await page.evaluate(()=>({scroll:document.documentElement.scrollWidth,inner:window.innerWidth,offenders:Array.from(document.querySelectorAll('.main-shell *')).filter(el=>{const s=getComputedStyle(el),r=el.getBoundingClientRect();return s.display!=='none'&&s.visibility!=='hidden'&&r.width>0&&r.right>innerWidth+2&&!el.closest('.type-tabs')}).slice(0,6).map(el=>({tag:el.tagName,cls:typeof el.className==='string'?el.className:'',right:Math.round(el.getBoundingClientRect().right),width:Math.round(el.getBoundingClientRect().width)}))}))
      await page.screenshot({path:`test-results/page-${width}-${route.slice(1)||'home'}.png`,fullPage:true})
      expect(overflow.offenders,`Elements past right edge at ${route} / ${width}px`).toEqual([])
      expect(overflow.scroll,`${route} scroll overflow at ${width}px: ${JSON.stringify(overflow.offenders)}`).toBeLessThanOrEqual(width)
      if(route==='/logs'){await page.locator('.log-detail-button:visible').first().click();const detail=page.getByRole('dialog',{name:'Detail pesan'});await expect(detail).toBeVisible();await expect(detail.getByText('628123456789@s.whatsapp.net')).toBeVisible();await page.getByRole('button',{name:'Tutup dialog'}).click()}
    }
  }
  await page.setViewportSize({width:390,height:560})
  await page.goto('/')
  await page.getByRole('button',{name:'Buka navigasi'}).click()
  const drawer=page.locator('.sidebar')
  await expect(drawer).toHaveClass(/is-open/)
  await expect.poll(()=>page.evaluate(()=>getComputedStyle(document.body).overflow)).toBe('hidden')
  const scrollState=await drawer.evaluate(el=>{el.scrollTop=120;return {top:el.scrollTop,scrollHeight:el.scrollHeight,clientHeight:el.clientHeight}})
  expect(scrollState.scrollHeight).toBeGreaterThan(scrollState.clientHeight)
  expect(scrollState.top).toBeGreaterThan(0)
  await page.getByRole('button',{name:'Tutup navigasi'}).first().click()
  await expect.poll(()=>page.evaluate(()=>getComputedStyle(document.body).overflow)).toBe('')
})
