export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString()
}

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return 'never'
  const secs = Math.round((Date.now() - new Date(iso).getTime()) / 1000)
  if (secs < 60) return 'just now'
  const mins = Math.round(secs / 60)
  if (mins < 60) return `${mins} min ago`
  const hrs = Math.round(mins / 60)
  if (hrs < 48) return `${hrs} h ago`
  return `${Math.round(hrs / 24)} days ago`
}

export function sourceLabel(source: string): string {
  return source === 'agent' ? 'Agent' : source === 'upload_excel' ? 'Excel upload' : source
}

export function countLabel(n: number | null | undefined): string {
  return n === null || n === undefined ? '—' : String(n)
}
