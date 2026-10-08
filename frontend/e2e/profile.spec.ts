import { test, expect } from '@playwright/test'
import { fileURLToPath } from 'node:url'

test('profile photo preview, per-device privacy and mobile layout', async ({ page }) => {
  const errors: string[] = []
  const mutations: { url: string; body: any }[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/register')
  await page.getByLabel('Username', { exact: false }).fill(`profile${Date.now()}`)
  await page.getByLabel('Password', { exact: true }).fill('Testing-password-2026')
  await page.getByLabel('Konfirmasi password', { exact: true }).fill('Testing-password-2026')
  await page.getByRole('button', { name: 'Buat akun Utusan' }).click()
  await expect(page.getByRole('heading', { name: /Halo,/ })).toBeVisible()
  await page.route('**/api/web/devices', route => route.fulfill({ json: { devices: [{ phone: '628123456789', online: true }, { phone: '628111111111', online: false }] } }))
  await page.route('**/api/web/wa-profile**', async route => {
    const request = route.request(), url = new URL(request.url())
    if (url.pathname.endsWith('/photo/preview')) return route.continue()
    if (request.method() !== 'GET') {
      const body = request.postDataJSON()
      mutations.push({ url: url.pathname, body })
      return route.fulfill({ json: { success: true, ...body } })
    }
    if (url.searchParams.get('phone') === '628111111111') return route.fulfill({ status: 503, json: { detail: 'Perangkat offline' } })
    if (url.pathname.endsWith('/privacy')) return route.fulfill({ json: { preferences: { auto_read: false, auto_read_scope: 'private' }, privacy: { read_receipts: 'all', last_seen: 'contacts', online: 'match_last_seen', profile_photo: 'contacts', group_add: 'contacts', calls: 'known' }, warnings: [] } })
    return route.fulfill({ json: { phone: '628123456789', jid: '628123456789@s.whatsapp.net', name: 'CS Toko', about: 'Siap membantu', photo_url: null, warnings: [] } })
  })
  await page.goto('/wa-profile?phone=628123456789')
  await expect(page.getByLabel('Nama profil WhatsApp')).toHaveValue('CS Toko')
  await page.getByLabel('Nama profil WhatsApp').fill('CS Baru')
  await page.getByRole('button', { name: 'Simpan nama', exact: true }).click()
  await expect.poll(() => mutations.some(m => m.body.name === 'CS Baru' && m.body.phone === '628123456789')).toBeTruthy()
  await page.getByLabel('Unggah foto profil').setInputFiles(fileURLToPath(new URL('./fixtures/profile-long.png', import.meta.url)))
  await page.getByLabel('Mode foto profil').selectOption('original')
  await expect(page.locator('.wa-profile-photo-preview')).toContainText('120 × 360 px')
  const img = page.getByAltText('Preview foto profil yang akan dikirim')
  await expect.poll(() => img.evaluate((el: HTMLImageElement) => el.naturalHeight)).toBe(360)
  await page.getByLabel('Tandai pesan masuk sebagai dibaca secara otomatis').check()
  await page.getByLabel('Cakupan auto-read').selectOption('all')
  await page.getByRole('button', { name: 'Simpan auto-read', exact: true }).click()
  await expect.poll(() => mutations.some(m => m.body.auto_read && m.body.auto_read_scope === 'all')).toBeTruthy()
  await page.getByLabel('Laporan dibaca / centang biru').selectOption('none')
  await page.locator('.wa-privacy-setting').filter({ hasText: 'Laporan dibaca' }).getByRole('button', { name: 'Terapkan', exact: true }).click()
  await expect.poll(() => mutations.some(m => m.body.setting === 'read_receipts' && m.body.value === 'none')).toBeTruthy()
  for (const width of [375, 390, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  }
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.locator('.sidebar')).toHaveCSS('transform', 'matrix(1, 0, 0, 1, -270, 0)')
  await page.screenshot({ path: 'test-results/profile-mobile.png', fullPage: true })
  await page.evaluate(() => { document.documentElement.dataset.theme = 'dark' })
  await page.screenshot({ path: 'test-results/profile-dark-mobile.png', fullPage: true })
  await page.getByLabel('Perangkat untuk pengaturan profil').selectOption('628111111111')
  await expect(page.getByRole('button', { name: 'Simpan nama', exact: true })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Terapkan foto profil', exact: true })).toBeDisabled()
  expect(errors).toEqual([])
})
