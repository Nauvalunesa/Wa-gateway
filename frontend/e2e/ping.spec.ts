import { test, expect } from '@playwright/test'

test('dashboard ping switch persists, failed saves keep state, and mobile layout fits', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', e => errors.push(e.message))
  await page.goto('/register')
  await page.getByLabel('Username', { exact: false }).fill(`pingui${Date.now()}`)
  await page.getByLabel('Password', { exact: true }).fill('Testing-password-2026')
  await page.getByLabel('Konfirmasi password', { exact: true }).fill('Testing-password-2026')
  await page.getByRole('button', { name: 'Buat akun Utusan' }).click()
  const toggle = page.getByRole('switch', { name: 'Aktifkan balasan Ping' })
  await expect(toggle).toBeChecked()
  await toggle.click()
  await expect(toggle).not.toBeChecked()
  await page.reload()
  await expect(toggle).not.toBeChecked()
  await page.route('**/api/web/ping-settings', async route => {
    if (route.request().method() === 'PUT') return route.fulfill({ status: 500, json: { detail: 'Simpan gagal' } })
    return route.continue()
  })
  await toggle.click()
  await expect(page.locator('.ping-control')).toContainText('Simpan gagal')
  await expect(toggle).not.toBeChecked()
  await page.unroute('**/api/web/ping-settings')
  await toggle.click()
  await expect(toggle).toBeChecked()
  await page.reload()
  await expect(toggle).toBeChecked()
  for (const width of [375, 390, 768, 1440]) {
    await page.setViewportSize({ width, height: 844 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  }
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.locator('.sidebar')).toHaveCSS('transform', 'matrix(1, 0, 0, 1, -270, 0)')
  await page.screenshot({ path: 'test-results/ping-mobile.png', fullPage: true })
  await page.getByRole('button', { name: 'Aktifkan dark mode' }).click()
  await page.screenshot({ path: 'test-results/ping-dark-mobile.png', fullPage: true })
  expect(errors).toEqual([])
})
