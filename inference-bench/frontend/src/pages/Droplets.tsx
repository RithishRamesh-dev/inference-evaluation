import { useState, useEffect, useRef } from 'react'
import { api } from '../api'
import type { GpuDroplet, DropletProgress, DropletOptions, GpuSizeOption, DropletRegion, DropletImageOption } from '../types'

// ── Fallbacks (no-backend preview, or if the live DO fetch fails) ─────────────
// Specs are stable; pricing is null here — connect a token (DO_API_TOKEN) for live prices.
const FALLBACK_REGIONS: DropletRegion[] = [
  { slug: 'nyc2', name: 'New York 2', available: true },
  { slug: 'tor1', name: 'Toronto 1', available: true },
  { slug: 'atl1', name: 'Atlanta 1', available: true },
]

const FALLBACK_SIZES: GpuSizeOption[] = [
  { slug: 'gpu-h100x1-80gb', description: 'NVIDIA H100', gpu_platform: 'NVIDIA', gpu_model: 'H100', gpu_count: 1, gpu_vram_gb: 80, vcpus: 20, memory_gb: 240, disk_gb: 720, price_hourly: null, price_monthly: null, price_per_gpu_hourly: null, available: true, regions: ['nyc2', 'tor1', 'atl1'] },
  { slug: 'gpu-h100x8-640gb', description: 'NVIDIA H100 ×8', gpu_platform: 'NVIDIA', gpu_model: 'H100', gpu_count: 8, gpu_vram_gb: 640, vcpus: 160, memory_gb: 1920, disk_gb: 5760, price_hourly: null, price_monthly: null, price_per_gpu_hourly: null, available: true, regions: ['nyc2', 'tor1', 'atl1'] },
  { slug: 'gpu-mi300x1-192gb', description: 'AMD MI300X', gpu_platform: 'AMD', gpu_model: 'MI300X', gpu_count: 1, gpu_vram_gb: 192, vcpus: 20, memory_gb: 240, disk_gb: 720, price_hourly: null, price_monthly: null, price_per_gpu_hourly: null, available: true, regions: ['atl1'] },
  { slug: 'gpu-mi300x8-1536gb', description: 'AMD MI300X ×8', gpu_platform: 'AMD', gpu_model: 'MI300X', gpu_count: 8, gpu_vram_gb: 1536, vcpus: 160, memory_gb: 1920, disk_gb: 5760, price_hourly: null, price_monthly: null, price_per_gpu_hourly: null, available: true, regions: ['atl1'] },
]

// DO's GPU AI/ML base images (slugs confirmed from /v2/images, type=base).
const FALLBACK_IMAGES: DropletImageOption[] = [
  { value: 'gpu-amd-base', label: 'AMD AI/ML Ready Image', kind: 'ai-ml', recommended: true, vendor: 'AMD', nvlink: false, regions: [] },
  { value: 'gpu-h100x1-base', label: 'NVIDIA AI/ML Ready', kind: 'ai-ml', recommended: true, vendor: 'NVIDIA', nvlink: false, regions: [] },
  { value: 'gpu-h100x8-base', label: 'NVIDIA AI/ML Ready with NVLink', kind: 'ai-ml', recommended: true, vendor: 'NVIDIA', nvlink: true, regions: [] },
]

// Pick DO's AI/ML base image that matches the plan's vendor (and NVLink for
// multi-GPU NVIDIA) — mirrors what the DO GUI auto-selects.
function pickImage(images: DropletImageOption[], size: GpuSizeOption | undefined, fallback: string | null): string {
  if (!images.length) return fallback || ''
  if (size?.gpu_platform) {
    const multi = (size.gpu_count || 1) > 1
    const exact = images.find(i => i.recommended && i.vendor === size.gpu_platform && i.nvlink === multi)
    if (exact) return exact.value
    const byVendor = images.find(i => i.recommended && i.vendor === size.gpu_platform)
    if (byVendor) return byVendor.value
  }
  if (fallback && images.some(i => i.value === fallback)) return fallback
  return (images.find(i => i.recommended) || images[0]).value
}

// DO's only rule: name may contain letters, numbers, dashes, and periods.
const NAME_RE = /^[a-zA-Z0-9.-]{1,255}$/

const STATUS_COLOR: Record<string, string> = {
  provisioning: 'bg-yellow-500', active: 'bg-green-500', destroying: 'bg-yellow-500',
  destroyed: 'bg-gray-400', failed: 'bg-red-500',
}
const STATUS_TEXT: Record<string, string> = {
  provisioning: 'text-yellow-600', active: 'text-green-600', destroying: 'text-yellow-600',
  destroyed: 'text-gray-500', failed: 'text-red-600',
}

function fmtDuration(ms: number): string {
  if (ms < 0) ms = 0
  const s = Math.floor(ms / 1000)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  if (h > 0) return `${h}h ${m}m`
  return `${m}m ${s % 60}s`
}
function money(n: number | null | undefined): string {
  return n != null ? `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—'
}
function costToDate(d: GpuDroplet): { hours: number; cost: number } | null {
  if (!d.created_at || d.hourly_price_usd == null) return null
  const start = new Date(d.created_at).getTime()
  const end = d.destroyed_at ? new Date(d.destroyed_at).getTime() : Date.now()
  const hours = Math.max(0, (end - start) / 3_600_000)
  return { hours, cost: hours * d.hourly_price_usd }
}
function suggestName(size: GpuSizeOption | undefined, region: string): string {
  const model = (size?.gpu_model || 'gpu').toLowerCase().replace(/[^a-z0-9]+/g, '')
  const count = size?.gpu_count && size.gpu_count > 1 ? `x${size.gpu_count}` : ''
  return `bench-${model}${count}-${region}`.replace(/[^a-zA-Z0-9.-]+/g, '-').slice(0, 63)
}

export default function Droplets() {
  const [droplets, setDroplets] = useState<GpuDroplet[]>([])
  const [selected, setSelected] = useState<GpuDroplet | null>(null)
  const [progress, setProgress] = useState<DropletProgress | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [now, setNow] = useState(Date.now())
  const esRef = useRef<EventSource | null>(null)

  const load = () => api.droplets.list().then(setDroplets)

  useEffect(() => { load() }, [])
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])

  // stream provisioning/teardown progress for the selected droplet
  useEffect(() => {
    esRef.current?.close()
    setProgress(null)
    if (!selected) return
    if (selected.status !== 'provisioning' && selected.status !== 'destroying') return
    const es = new EventSource(api.droplets.streamUrl(selected.id))
    esRef.current = es
    es.onmessage = (e) => {
      try {
        const data: DropletProgress = JSON.parse(e.data)
        setProgress(data)
        if (['active', 'failed', 'destroyed'].includes(data.status)) {
          es.close()
          load()
          api.droplets.get(selected.id).then(setSelected).catch(() => {})
        }
      } catch { /* ignore */ }
    }
    es.onerror = () => { /* auto-reconnects */ }
    return () => { es.close() }
  }, [selected?.id, selected?.status])

  const onCreated = (d: GpuDroplet) => {
    setShowCreate(false)
    load()
    setSelected(d)
  }

  const destroyDroplet = async (d: GpuDroplet) => {
    if (!confirm(`Destroy droplet "${d.name}"? This deletes the DO droplet and its SSH key.`)) return
    const updated = await api.droplets.destroy(d.id)
    await load()
    if (selected?.id === d.id) setSelected(updated)
  }
  const deleteRecord = async (d: GpuDroplet) => {
    if (!confirm('Remove this droplet record from history?')) return
    await api.droplets.delete(d.id)
    if (selected?.id === d.id) setSelected(null)
    load()
  }

  const liveCount = droplets.filter(d => d.status === 'active' || d.status === 'provisioning').length

  return (
    <div className="flex h-full">
      {/* Left: droplet list */}
      <div className="w-72 border-r border-do-grey-200 flex flex-col shrink-0">
        <div className="p-4 border-b border-do-grey-200">
          <div className="flex items-center justify-between mb-0.5">
            <h1 className="text-sm font-bold text-gray-800">GPU Droplets</h1>
            <button onClick={() => { setShowCreate(true); setSelected(null) }} className="text-xs text-do-blue hover:underline">＋ Create</button>
          </div>
          <p className="text-xs text-gray-500">{liveCount} live · provisioned via DigitalOcean</p>
        </div>
        <div className="flex-1 overflow-y-auto">
          {droplets.length === 0 && <p className="text-xs text-gray-600 px-4 py-3">No droplets yet</p>}
          {droplets.map(d => {
            const c = costToDate(d)
            return (
              <button key={d.id} onClick={() => { setSelected(d); setShowCreate(false) }}
                className={`w-full text-left px-4 py-3 border-b border-do-grey-200 hover:bg-do-grey-100 ${selected?.id === d.id ? 'bg-do-grey-100' : ''}`}>
                <div className="flex items-center gap-2">
                  <span className={`w-2 h-2 rounded-full shrink-0 ${STATUS_COLOR[d.status] || 'bg-gray-400'} ${d.status === 'provisioning' || d.status === 'destroying' ? 'animate-pulse' : ''}`} />
                  <p className="text-sm text-gray-700 truncate flex-1">{d.name}</p>
                  <span className={`text-[10px] ${STATUS_TEXT[d.status] || 'text-gray-500'}`}>{d.status}</span>
                </div>
                <p className="text-xs text-gray-600 mt-0.5 pl-4">{d.size_slug} · {d.region}</p>
                {c && d.status === 'active' && <p className="text-[10px] text-gray-500 mt-0.5 pl-4">{money(c.cost)} so far</p>}
              </button>
            )
          })}
        </div>
      </div>

      {/* Right: detail / create */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {showCreate && <CreateDropletPanel onCreated={onCreated} onCancel={() => setShowCreate(false)} />}
        {!showCreate && !selected && (
          <div className="flex items-center justify-center h-full text-gray-600 text-sm">Select a droplet, or create one</div>
        )}
        {!showCreate && selected && (
          <DropletDetail droplet={selected} progress={progress} now={now} onDestroy={destroyDroplet} onDelete={deleteRecord} />
        )}
      </div>
    </div>
  )
}

// ── Create panel — mirrors DO's "Create GPU Droplet" (Region → Image → Platform → Plan) ─
function CreateDropletPanel({ onCreated, onCancel }: { onCreated: (d: GpuDroplet) => void; onCancel: () => void }) {
  const [token, setToken] = useState('')
  const [name, setName] = useState('')
  const [options, setOptions] = useState<DropletOptions | null>(null)
  const [loadingOpts, setLoadingOpts] = useState(false)
  const [optsError, setOptsError] = useState<string | null>(null)

  const [region, setRegion] = useState('')
  const [platform, setPlatform] = useState('')
  const [image, setImage] = useState('')
  const [useCustomImage, setUseCustomImage] = useState(false)
  const [customImage, setCustomImage] = useState('')
  const [sizeSlug, setSizeSlug] = useState('')
  const [useCustomSize, setUseCustomSize] = useState(false)
  const [customSize, setCustomSize] = useState('')

  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Catalog comes from the server's DO_API_TOKEN — NOT the per-droplet token below.
  const sizes = options?.sizes ?? FALLBACK_SIZES
  const regions = options?.regions ?? FALLBACK_REGIONS
  const images = options?.images ?? FALLBACK_IMAGES
  const isLive = options != null
  const regionName = (slug: string) => regions.find(r => r.slug === slug)?.name || slug

  // Some accounts (internal/staff) return empty `regions` on sizes — then we
  // can't constrain by region, so show all available regions / all plans.
  const sizesHaveRegions = sizes.some(s => s.regions.length > 0)
  let gpuRegions = regions.filter(r => r.available && (!sizesHaveRegions || sizes.some(s => s.regions.includes(r.slug))))
  if (!gpuRegions.length) gpuRegions = regions
  // GPU vendors present (NVIDIA first).
  const platforms = ([...new Set(sizes.map(s => s.gpu_platform).filter(Boolean))] as string[])
    .sort((a, b) => (a === 'NVIDIA' ? -1 : b === 'NVIDIA' ? 1 : a.localeCompare(b)))
  // Plans offered in the chosen region + platform. A plan with no region data is
  // shown everywhere; a plan we couldn't classify (gpu_platform null) is shown
  // under any vendor — never hide a real GPU on missing/unguessable metadata.
  const visibleSizes = sizes.filter(s =>
    (!region || !s.regions.length || s.regions.includes(region)) &&
    (!platform || !s.gpu_platform || s.gpu_platform === platform))

  const loadOptions = async () => {
    setLoadingOpts(true); setOptsError(null)
    try { setOptions(await api.droplets.options()) }
    catch (e) { setOptsError(e instanceof Error ? e.message : 'Failed to load DigitalOcean catalog') }
    finally { setLoadingOpts(false) }
  }
  useEffect(() => { loadOptions() }, [])

  // Defaults once data is present.
  useEffect(() => {
    if (!region && gpuRegions.length) setRegion(gpuRegions[0].slug)
  }, [gpuRegions.length])
  useEffect(() => {
    if (!platform && platforms.length) setPlatform(platforms[0])
  }, [platforms.join(',')])
  useEffect(() => {
    if (useCustomSize) return
    if (!visibleSizes.some(s => s.slug === sizeSlug)) setSizeSlug(visibleSizes[0]?.slug || '')
  }, [region, platform, options, useCustomSize])
  useEffect(() => {
    if (useCustomImage) return
    setImage(pickImage(images, sizes.find(s => s.slug === sizeSlug), options?.recommended_image ?? null))
  }, [sizeSlug, options, useCustomImage])
  // Suggest a valid name once a plan/region is chosen (only if user hasn't typed one).
  useEffect(() => {
    if (!name && !useCustomSize && sizeSlug && region) setName(suggestName(sizes.find(s => s.slug === sizeSlug), region))
  }, [sizeSlug, region])

  const effectiveSize = useCustomSize ? customSize.trim() : sizeSlug
  const effectiveImage = useCustomImage ? customImage.trim() : image
  const selectedSize = sizes.find(s => s.slug === sizeSlug)
  const selectedImageObj = images.find(i => i.value === image)
  const nameValid = NAME_RE.test(name)
  const noRecommendedImage = isLive && !images.some(i => i.recommended)

  const canCreate = !creating && !!token && nameValid && !!region && !!effectiveSize &&
    (!useCustomImage || !!effectiveImage)

  const create = async () => {
    if (!canCreate) { setError('Fill in the required fields above'); return }
    setCreating(true); setError(null)
    try {
      const d = await api.droplets.create({ name, region, size_slug: effectiveSize, image: effectiveImage, do_token: token })
      onCreated(d)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to create droplet')
    } finally { setCreating(false) }
  }

  const sectionTitle = (n: number, title: string, sub?: string) => (
    <div className="flex items-baseline gap-2">
      <span className="w-5 h-5 rounded-full bg-do-blue text-white text-[11px] font-bold flex items-center justify-center shrink-0">{n}</span>
      <h3 className="text-sm font-bold text-gray-800">{title}</h3>
      {sub && <span className="text-xs text-gray-500">{sub}</span>}
    </div>
  )

  return (
    <div className="max-w-3xl space-y-5">
      <div className="flex items-center justify-between">
        <h2 className="text-base font-bold text-gray-800">Create GPU Droplet</h2>
        <button onClick={onCancel} className="text-xs text-gray-500 hover:text-gray-700">Cancel</button>
      </div>

      {/* 1. Per-droplet DO token */}
      <div className="space-y-2">
        {sectionTitle(1, 'DigitalOcean API token', 'used to create & destroy this droplet — stored encrypted')}
        <input className="input" type="password" value={token} onChange={e => setToken(e.target.value)} placeholder="dop_v1_…" />
        <p className="text-[11px] text-gray-500">
          {isLive
            ? 'The catalog below is loaded from the server token; this token is what actually provisions and destroys the droplet.'
            : <>Catalog couldn't load{optsError ? ` (${optsError})` : ''} — showing reference plans. Set <code>DO_API_TOKEN</code> on the server for live GPU plans, regions, and pricing.{' '}
                <button onClick={loadOptions} disabled={loadingOpts} className="text-do-blue hover:underline">{loadingOpts ? 'Loading…' : '↻ Retry'}</button></>}
        </p>
      </div>

      {/* 2. Region */}
      <div className="space-y-2">
        {sectionTitle(2, 'Choose a datacenter region')}
        <div className="flex flex-wrap gap-2">
          {gpuRegions.length === 0 && <p className="text-xs text-gray-500">No GPU-capable regions found.</p>}
          {gpuRegions.map(r => {
            const hasPlan = sizes.some(s => (!s.regions.length || s.regions.includes(r.slug)) && (!platform || !s.gpu_platform || s.gpu_platform === platform))
            return (
              <button key={r.slug} onClick={() => setRegion(r.slug)}
                title={hasPlan ? '' : `No ${platform || 'GPU'} plans here`}
                className={`px-3 py-1.5 rounded-md border text-xs text-left ${region === r.slug ? 'border-do-blue bg-blue-50 text-do-blue font-semibold' : 'border-do-grey-200 text-gray-700 hover:border-do-grey-400'} ${!hasPlan ? 'opacity-50' : ''}`}>
                {r.name}
                <span className="block text-[10px] text-gray-400 uppercase">{r.slug}</span>
              </button>
            )
          })}
        </div>
      </div>

      {/* 3. Image — default AI/ML Ready, or a custom image ID */}
      <div className="space-y-2">
        {sectionTitle(3, 'Choose an image', 'AI/ML Ready bundles GPU drivers')}
        {!useCustomImage && (
          <select className="input" value={image} onChange={e => setImage(e.target.value)}>
            {images.map(im => (
              <option key={im.value} value={im.value}>
                {im.recommended ? '★ ' : ''}{im.label}{im.kind === 'ai-ml' ? ' (recommended)' : im.kind === 'inference' ? ' (inference optimized)' : ''}
              </option>
            ))}
          </select>
        )}
        {useCustomImage && (
          <input className="input" value={customImage} onChange={e => setCustomImage(e.target.value)}
            placeholder="Image ID or slug — e.g. your AI/ML Ready image" />
        )}
        <button onClick={() => setUseCustomImage(v => !v)} className="text-[11px] text-do-blue hover:underline">
          {useCustomImage ? '← Back to image list' : 'Advanced: enter a custom image ID'}
        </button>
        {noRecommendedImage && !useCustomImage && (
          <p className="text-[11px] text-amber-600">
            No AI/ML Ready image was found in the catalog for this token. Pick it via a custom image ID, or check the
            image list (see notes) to find its id.
          </p>
        )}
        {!useCustomImage && selectedImageObj && !selectedImageObj.recommended && (
          <p className="text-[11px] text-amber-600">
            Heads up: this isn't the AI/ML Ready image — it provisions fine, but GPU drivers/Docker won't be
            preinstalled (the deploy step would need to install them). The AI/ML Ready image avoids that.
          </p>
        )}
      </div>

      {/* 4. GPU platform + plan */}
      <div className="space-y-2">
        {sectionTitle(4, 'Choose a GPU plan')}
        {!useCustomSize && platforms.length > 1 && (
          <div className="flex gap-1">
            {platforms.map(p => (
              <button key={p} onClick={() => setPlatform(p)}
                className={`px-3 py-1 rounded-md text-xs ${platform === p ? 'bg-do-blue text-white font-semibold' : 'text-gray-600 hover:bg-do-grey-100'}`}>
                {p}
              </button>
            ))}
          </div>
        )}
        {!useCustomSize && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {visibleSizes.length === 0 && <p className="text-xs text-gray-500">No {platform || 'GPU'} plans available in {regionName(region)}.</p>}
            {visibleSizes.map(s => {
              const sel = sizeSlug === s.slug
              const title = s.gpu_count && s.gpu_model
                ? `${s.gpu_count}× ${s.gpu_model}`
                : s.description
              return (
                <button key={s.slug} onClick={() => setSizeSlug(s.slug)}
                  className={`text-left p-3 rounded-lg border transition-colors ${sel ? 'border-do-blue ring-1 ring-do-blue bg-blue-50' : 'border-do-grey-200 hover:border-do-grey-400'}`}>
                  <div className="flex items-center justify-between">
                    <p className="text-sm font-bold text-gray-800">{title}</p>
                    {s.gpu_vram_gb != null && <span className="text-[10px] px-1.5 py-0.5 rounded bg-do-purple/10 text-do-purple font-semibold">{s.gpu_vram_gb} GB VRAM</span>}
                  </div>
                  <p className="text-[11px] text-gray-500 mt-1">{s.vcpus ?? '—'} vCPUs · {s.memory_gb ?? '—'} GB RAM · {s.disk_gb ?? '—'} GB disk</p>
                  <div className="flex items-baseline justify-between mt-2">
                    <p className="text-sm font-bold text-gray-900">
                      {s.price_per_gpu_hourly != null ? `${money(s.price_per_gpu_hourly)}/GPU/hr` : <span className="text-xs font-normal text-gray-400">pricing via token</span>}
                    </p>
                    {s.price_hourly != null && <p className="text-[10px] text-gray-400">{money(s.price_hourly)}/hr total</p>}
                  </div>
                  <p className="text-[10px] text-gray-400 mt-1 font-mono">{s.slug}</p>
                </button>
              )
            })}
          </div>
        )}
        {useCustomSize && (
          <div>
            <input className="input" value={customSize} onChange={e => setCustomSize(e.target.value)} placeholder="e.g. s-1vcpu-1gb (cheap — for testing the provisioning flow)" />
            <p className="text-[11px] text-gray-500 mt-1">Any valid DO size slug, bypassing the GPU catalog. A tiny standard droplet (~$0.009/hr) is handy to validate create→destroy without GPU cost.</p>
          </div>
        )}
        <button onClick={() => setUseCustomSize(v => !v)} className="text-[11px] text-do-blue hover:underline">
          {useCustomSize ? '← Back to GPU plans' : 'Advanced: enter a custom size slug'}
        </button>
      </div>

      {/* 5. Finalize */}
      <div className="space-y-2">
        {sectionTitle(5, 'Finalize')}
        <input className="input" value={name} onChange={e => setName(e.target.value)} placeholder="Droplet name, e.g. bench-h100-1" />
        {name && !nameValid && <p className="text-[11px] text-red-600">Name may only contain letters, numbers, dashes, and periods (and must start/end alphanumeric).</p>}
      </div>

      {/* Summary */}
      {selectedSize && !useCustomSize && (
        <div className="card flex items-center justify-between">
          <div>
            <p className="text-[10px] text-gray-500 uppercase tracking-wider">Summary</p>
            <p className="text-sm font-semibold text-gray-800">{selectedSize.gpu_count}× {selectedSize.gpu_model} · {regionName(region)}</p>
            <p className="text-[11px] text-gray-500">{selectedSize.vcpus} vCPU · {selectedSize.memory_gb} GB RAM · {selectedSize.disk_gb} GB disk</p>
          </div>
          <div className="text-right">
            <p className="text-lg font-bold text-gray-900">{selectedSize.price_hourly != null ? `${money(selectedSize.price_hourly)}/hr` : '—'}</p>
            {selectedSize.price_per_gpu_hourly != null && <p className="text-[10px] text-gray-400">{money(selectedSize.price_per_gpu_hourly)}/GPU/hr</p>}
          </div>
        </div>
      )}

      {error && <p className="text-xs text-red-600">{error}</p>}
      <div className="flex gap-2 pt-1">
        <button onClick={create} disabled={!canCreate} className="btn-primary text-sm disabled:opacity-50">
          {creating ? 'Provisioning…' : 'Create GPU Droplet'}
        </button>
        <button onClick={onCancel} className="btn-secondary text-sm">Cancel</button>
      </div>
    </div>
  )
}

function DropletDetail({ droplet: d, progress, now, onDestroy, onDelete }: {
  droplet: GpuDroplet
  progress: DropletProgress | null
  now: number
  onDestroy: (d: GpuDroplet) => void
  onDelete: (d: GpuDroplet) => void
}) {
  const c = costToDate(d)
  const runningMs = d.created_at
    ? (d.destroyed_at ? new Date(d.destroyed_at).getTime() : now) - new Date(d.created_at).getTime()
    : 0
  const events = progress?.events ?? []

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className={`w-3 h-3 rounded-full ${STATUS_COLOR[d.status] || 'bg-gray-400'} ${d.status === 'provisioning' || d.status === 'destroying' ? 'animate-pulse' : ''}`} />
          <div>
            <h2 className="text-base font-bold text-gray-800">{d.name}</h2>
            <p className={`text-sm font-semibold ${STATUS_TEXT[d.status] || 'text-gray-600'}`}>
              {d.status.charAt(0).toUpperCase() + d.status.slice(1)}{d.status_detail ? ` — ${d.status_detail}` : ''}
            </p>
          </div>
        </div>
        <div className="flex gap-2">
          {(d.status === 'active' || d.status === 'provisioning') && (
            <button onClick={() => onDestroy(d)} className="btn-danger text-xs">Destroy</button>
          )}
          {(d.status === 'destroyed' || d.status === 'failed') && (
            <button onClick={() => onDelete(d)} className="text-xs text-red-500 hover:text-red-400 px-2">Remove record</button>
          )}
        </div>
      </div>

      {d.status === 'failed' && (
        <div className="rounded-lg border border-red-300 bg-red-50 p-3">
          <p className="text-sm font-semibold text-red-700">✗ Failed</p>
          <p className="text-xs text-red-600 mt-1 whitespace-pre-wrap break-words">
            {d.status_detail || progress?.status_detail || 'No error detail was reported.'}
          </p>
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="card"><p className="text-[10px] text-gray-500 uppercase tracking-wider">GPU Plan</p><p className="text-sm font-semibold text-gray-800 mt-0.5">{d.size_slug}</p></div>
        <div className="card"><p className="text-[10px] text-gray-500 uppercase tracking-wider">Region</p><p className="text-sm font-semibold text-gray-800 mt-0.5">{d.region}</p></div>
        <div className="card"><p className="text-[10px] text-gray-500 uppercase tracking-wider">Public IP</p><p className="text-sm font-semibold text-gray-800 mt-0.5">{d.ip || '—'}</p></div>
        <div className="card"><p className="text-[10px] text-gray-500 uppercase tracking-wider">Hourly</p><p className="text-sm font-semibold text-gray-800 mt-0.5">{d.hourly_price_usd != null ? `${money(d.hourly_price_usd)}/hr` : '—'}</p></div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="card">
          <p className="text-[10px] text-gray-500 uppercase tracking-wider">{d.destroyed_at ? 'Ran For' : 'Running Since'}</p>
          <p className="text-lg font-bold text-gray-800 mt-0.5">{fmtDuration(runningMs)}</p>
          {d.created_at && <p className="text-[10px] text-gray-500">{new Date(d.created_at).toLocaleString()}</p>}
        </div>
        <div className="card">
          <p className="text-[10px] text-gray-500 uppercase tracking-wider">Estimated Cost{d.destroyed_at ? '' : ' to Date'}</p>
          <p className={`text-lg font-bold mt-0.5 ${d.status === 'active' ? 'text-do-red' : 'text-gray-800'}`}>{c ? money(c.cost) : '—'}</p>
          {c && <p className="text-[10px] text-gray-500">{c.hours.toFixed(2)} GPU-hours</p>}
        </div>
      </div>

      {events.length > 0 && (
        <div className="card">
          <p className="text-xs font-semibold text-gray-600 uppercase tracking-wider mb-2">Activity</p>
          <div className="space-y-1 max-h-64 overflow-y-auto">
            {[...events].reverse().map((ev, i) => (
              <div key={i} className="flex items-start gap-2 text-xs">
                <span className="text-gray-500 shrink-0 font-mono">{new Date(ev.ts).toLocaleTimeString()}</span>
                <span className={`${ev.event === 'droplet_failed' ? 'text-red-600' : ev.event === 'droplet_ready' || ev.event === 'droplet_destroyed' ? 'text-green-600' : 'text-gray-600'}`}>
                  {ev.event}{ev.error ? `: ${String(ev.error)}` : ''}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
