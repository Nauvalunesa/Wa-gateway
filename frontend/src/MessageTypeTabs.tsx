import { useEffect, useRef, useState } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'

export function MessageTypeTabs({ types, selected, onChange }: {
  types: string[][]
  selected: string
  onChange: (type: string) => void
}) {
  const track = useRef<HTMLDivElement>(null)
  const gesture = useRef({ pointerId: -1, startX: 0, startScroll: 0, dragged: false })
  const [limits, setLimits] = useState({ left: false, right: false })
  const [dragging, setDragging] = useState(false)

  function updateLimits() {
    const el = track.current
    if (el) setLimits({ left: el.scrollLeft > 1, right: el.scrollLeft + el.clientWidth < el.scrollWidth - 1 })
  }

  useEffect(() => {
    const el = track.current
    if (!el) return
    const observer = new ResizeObserver(updateLimits)
    observer.observe(el)
    Array.from(el.children).forEach(child => observer.observe(child))
    updateLimits()
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    const el = track.current
    const active = el?.querySelector<HTMLButtonElement>('button[aria-pressed="true"]')
    if (!el || !active) return
    const bounds = el.getBoundingClientRect()
    const item = active.getBoundingClientRect()
    if (item.left < bounds.left) el.scrollBy({ left: item.left - bounds.left - 6, behavior: 'smooth' })
    else if (item.right > bounds.right) el.scrollBy({ left: item.right - bounds.right + 6, behavior: 'smooth' })
  }, [selected])

  function scroll(direction: number) {
    track.current?.scrollBy({ left: direction * track.current.clientWidth * 0.75, behavior: 'smooth' })
  }

  return <nav className="message-types" aria-label="Jenis pesan">
    <button type="button" className="message-type-arrow" aria-label="Geser jenis pesan ke kiri" disabled={!limits.left} onClick={() => scroll(-1)}><ChevronLeft size={18}/></button>
    <div ref={track} className="type-tabs" data-dragging={dragging} onScroll={updateLimits}
      onPointerDown={e => {
        gesture.current.dragged = false
        if (e.pointerType !== 'mouse' || e.button !== 0) return
        gesture.current = { pointerId: e.pointerId, startX: e.clientX, startScroll: e.currentTarget.scrollLeft, dragged: false }
      }}
      onPointerMove={e => {
        const g = gesture.current
        if (g.pointerId !== e.pointerId) return
        const distance = e.clientX - g.startX
        if (!g.dragged && Math.abs(distance) < 6) return
        if (!g.dragged) {
          g.dragged = true
          setDragging(true)
          e.currentTarget.setPointerCapture(e.pointerId)
        }
        e.preventDefault()
        e.currentTarget.scrollLeft = g.startScroll - distance
      }}
      onPointerUp={e => {
        gesture.current.pointerId = -1
        setDragging(false)
        if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId)
      }}
      onPointerCancel={() => {
        gesture.current.pointerId = -1
        gesture.current.dragged = false
        setDragging(false)
      }}
      onClickCapture={e => {
        if (!gesture.current.dragged) return
        e.preventDefault()
        e.stopPropagation()
        gesture.current.dragged = false
      }}>
      {types.map(([value, label]) => <button type="button" key={value} className={selected === value ? 'active' : ''} aria-pressed={selected === value} onClick={() => onChange(value)}>{label}</button>)}
    </div>
    <button type="button" className="message-type-arrow" aria-label="Geser jenis pesan ke kanan" disabled={!limits.right} onClick={() => scroll(1)}><ChevronRight size={18}/></button>
  </nav>
}
