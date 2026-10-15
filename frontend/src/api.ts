import { useCallback, useEffect, useState } from 'react'
export type User = {username: string; api_key: string}
export type Device = {phone: string; number: string; online: boolean; pairing: boolean}
export type Log = {id: number; timestamp: string; sender: string; receiver: string; message: string; type: string}
export type Overview = {devices: Device[]; connected: number; messages: number; today: number; recent: Log[]; daily: {date: string; count: number}[]}
let sessionCheck: Promise<boolean> | undefined
async function sessionIsExpired() {
  if (!sessionCheck) {
    sessionCheck = fetch('/api/web/me', {credentials: 'same-origin'}).then(response => response.status === 401).catch(() => false).finally(() => { sessionCheck = undefined })
  }
  return sessionCheck
}
export async function api<T = Record<string, unknown>>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  const response = await fetch(path, {...options, headers, credentials: 'same-origin'})
  const raw = await response.text()
  let body: Record<string, any>
  try { body = raw ? JSON.parse(raw) : {} }
  catch { body = {detail: `Server mengirim respons non-JSON (HTTP ${response.status}).`} }
  if (!response.ok) {
    if (response.status === 401 && path !== '/api/web/me' && await sessionIsExpired()) window.dispatchEvent(new Event('session-expired'))
    if (response.status === 401 && path === '/api/web/me') window.dispatchEvent(new Event('session-expired'))
    const detail = Array.isArray(body.detail) ? body.detail.map((x: {msg: string}) => x.msg).join('; ') : body.detail
    throw new Error(detail || `Permintaan gagal (${response.status}).`)
  }
  if (body.success === false) throw new Error(body.message || body.detail || 'Permintaan tidak berhasil.')
  return body as T
}
export const post = <T = Record<string, unknown>>(path: string, data: unknown) => api<T>(path, {method: 'POST', body: JSON.stringify(data)})
export function query(path: string, values: Record<string, unknown>) {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(values)) if (value !== '' && value !== null && value !== undefined) params.set(key, String(value))
  return `${path}?${params}`
}
export function useResource<T>(path: string, interval = 0) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const refresh = useCallback(async () => {
    try { setData(await api<T>(path)); setError('') } catch (e) { setError((e as Error).message) } finally { setLoading(false) }
  }, [path])
  useEffect(() => { let active = true; const load = async () => { try {const result = await api<T>(path); if(active){setData(result); setError('')}} catch(e) {if(active)setError((e as Error).message)} finally {if(active)setLoading(false)} }; setLoading(true); void load(); const timer = interval ? window.setInterval(() => {if(!document.hidden)void load()}, interval) : undefined; return () => {active=false; if(timer)clearInterval(timer)} }, [path, interval])
  return {data, error, loading, refresh}
}
export function formatNumber(value: number) { return new Intl.NumberFormat('id-ID').format(value) }
export function formatTime(value: string) { return new Date(value.replace(' ', 'T')).toLocaleString('id-ID', {day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'}) }
