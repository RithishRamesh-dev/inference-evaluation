import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { useState, useEffect } from 'react'
import { api } from '../api'

const NAV_GROUPS = [
  {
    label: 'EVALUATE',
    items: [
      { to: '/',          icon: '⌂',  label: 'Home' },
      {
        label: 'Accuracy Evaluation',
        icon: '⊟',
        isDropdown: true,
        items: [
          { to: '/new',       icon: '＋', label: 'New Evaluation' },
          { to: '/dashboard', icon: '▦',  label: 'History' },
          { to: '/compare',   icon: '⇄',  label: 'Compare' },
          { to: '/datasets',  icon: '⊞',  label: 'Custom Datasets' },
          { to: '/ab-tests',  icon: '⚖',  label: 'A/B Tests' },
        ],
      },
      {
        label: 'Benchmarking Evaluation',
        icon: '▣',
        isDropdown: true,
        items: [
          { to: '/benchmark/droplets',    icon: '☁', label: 'Droplets' },
          { to: '/benchmark/deployments', icon: '⊡', label: 'Deployments' },
          { to: '/benchmark/runs',        icon: '◔', label: 'Benchmarks' },
          { to: '/benchmark/sla',         icon: '◇', label: 'SLA Analysis' },
          { to: '/benchmark/history',     icon: '▦', label: 'History' },
        ],
      },
    ],
  },
  {
    label: 'EXPLORE',
    items: [
      { to: '/models',       icon: '◈',  label: 'Model Catalog' },
      { to: '/intelligence', icon: '◉',  label: 'Intelligence' },
      { to: '/probe',        icon: '⊙',  label: 'Probe Endpoint' },
      { to: '/playground',   icon: '▷',  label: 'Playground' },
    ],
  },
  {
    label: 'MONITOR',
    items: [
      { to: '/monitor',   icon: '◎', label: 'Live Monitor' },
      { to: '/schedules', icon: '◷', label: 'Schedules' },
      { to: '/alerts',    icon: '△',  label: 'Alerts' },
    ],
  },
  {
    label: 'INSIGHTS',
    items: [
      { to: '/cost',         icon: '◉', label: 'Cost Analytics' },
      { to: '/integrations', icon: '⊕', label: 'Integrations' },
    ],
  },
]

const ROUTE_LABELS: Record<string, string> = {
  '/': 'Home',
  '/home': 'Home',
  '/new': 'New Evaluation',
  '/dashboard': 'History',
  '/compare': 'Compare',
  '/datasets': 'Custom Datasets',
  '/ab-tests': 'A/B Tests',
  '/models': 'Model Catalog',
  '/intelligence': 'Intelligence',
  '/probe': 'Probe Endpoint',
  '/playground': 'Playground',
  '/monitor': 'Live Monitor',
  '/schedules': 'Schedules',
  '/alerts': 'Alerts',
  '/cost': 'Cost Analytics',
  '/integrations': 'Integrations',
  '/benchmark/droplets': 'GPU Droplets',
  '/benchmark/deployments': 'Deployments',
  '/benchmark/runs': 'Benchmarks',
  '/benchmark/sla': 'SLA Analysis',
  '/benchmark/history': 'Benchmark History',
}

export default function Layout() {
  const { pathname } = useLocation()
  const [expandedDropdowns, setExpandedDropdowns] = useState<Record<string, boolean>>({})
  const [liveDroplets, setLiveDroplets] = useState(0)

  const pageLabel = ROUTE_LABELS[pathname] ?? 'Crest'

  // Live (costly) droplet count — surface a forgotten droplet from anywhere.
  useEffect(() => {
    const refresh = () =>
      api.droplets.list()
        .then(ds => setLiveDroplets(ds.filter(d => d.status === 'active' || d.status === 'provisioning').length))
        .catch(() => {})
    refresh()
    const t = setInterval(refresh, 30000)
    return () => clearInterval(t)
  }, [pathname])

  const toggleDropdown = (label: string) => {
    setExpandedDropdowns(prev => ({
      ...prev,
      [label]: !prev[label]
    }))
  }

  const isDropdownExpanded = (label: string) => expandedDropdowns[label] ?? true // Default expanded

  const renderNavItem = (item: any, isNested = false) => {
    if (item.isDropdown) {
      const isExpanded = isDropdownExpanded(item.label)
      return (
        <div key={item.label}>
          <button
            onClick={() => toggleDropdown(item.label)}
            className="w-full flex items-center gap-2.5 px-3 py-1.5 rounded text-sm transition-colors hover:text-white"
            style={{ color: 'rgba(255,255,255,0.55)' }}
          >
            <span className="text-sm w-4 text-center">{item.icon}</span>
            <span className="flex-1 text-left">{item.label}</span>
            <span className={`text-xs transition-transform ${isExpanded ? 'rotate-180' : ''}`}>▼</span>
          </button>
          {isExpanded && (
            <div className="space-y-0.5 pl-4 mt-0.5">
              {item.items.map((subItem: any) => (
                <NavLink
                  key={subItem.to}
                  to={subItem.to}
                  className={({ isActive }) =>
                    `flex items-center gap-2.5 px-3 py-1.5 rounded text-sm transition-colors ${
                      isActive
                        ? 'text-white font-medium'
                        : 'hover:text-white'
                    }`
                  }
                  style={({ isActive }) => isActive ? { backgroundColor: 'rgba(0,128,255,0.25)' } : { color: 'rgba(255,255,255,0.55)' }}
                >
                  <span className="text-sm w-4 text-center">{subItem.icon}</span>
                  <span className="flex-1">{subItem.label}</span>
                  {subItem.to === '/benchmark/droplets' && liveDroplets > 0 && (
                    <span className="text-[10px] font-bold px-1.5 py-0.5 rounded-full bg-do-green text-white">{liveDroplets}</span>
                  )}
                </NavLink>
              ))}
            </div>
          )}
        </div>
      )
    }

    return (
      <NavLink
        key={item.to}
        to={item.to}
        className={({ isActive }) =>
          `flex items-center gap-2.5 px-3 py-1.5 rounded text-sm transition-colors ${
            isActive
              ? 'text-white font-medium'
              : 'hover:text-white'
          }`
        }
        style={({ isActive }) => isActive ? { backgroundColor: 'rgba(0,128,255,0.25)' } : { color: 'rgba(255,255,255,0.55)' }}
      >
        <span className="text-sm w-4 text-center">{item.icon}</span>
        <span>{item.label}</span>
      </NavLink>
    )
  }

  return (
    <div className="flex h-screen overflow-hidden">
      <aside className="w-56 flex flex-col shrink-0 overflow-y-auto" style={{ backgroundColor: '#1B2A4A' }}>
        <div className="px-4 py-5" style={{ borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
          <div className="flex items-center gap-2.5">
            <span className="text-xl text-white">≋</span>
            <div>
              <h1 className="text-sm font-bold text-white tracking-wide">Crest</h1>
              <p className="text-xs" style={{ color: 'rgba(255,255,255,0.45)' }}>by DigitalOcean</p>
            </div>
          </div>
        </div>

        <nav className="flex-1 px-2 py-3 space-y-4">
          {NAV_GROUPS.map(group => (
            <div key={group.label}>
              <p className="px-3 mb-1 text-[10px] font-semibold uppercase tracking-wider" style={{ color: 'rgba(255,255,255,0.3)' }}>
                {group.label}
              </p>
              <div className="space-y-0.5">
                {group.items.map((item) => renderNavItem(item))}
              </div>
            </div>
          ))}
        </nav>

        <div className="px-4 py-3" style={{ borderTop: '1px solid rgba(255,255,255,0.08)' }}>
          <p className="text-[10px]" style={{ color: 'rgba(255,255,255,0.25)' }}>Crest v2.0 · DigitalOcean</p>
        </div>
      </aside>

      <div className="flex-1 flex flex-col overflow-hidden">
        <header className="h-14 bg-white border-b border-do-grey-200 flex items-center justify-between px-6 shrink-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-gray-800">{pageLabel}</span>
          </div>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1.5">
              <span className="inline-block w-2 h-2 rounded-full bg-do-green"></span>
              <span className="text-xs text-do-grey-400">All systems operational</span>
            </div>
            <button className="w-8 h-8 flex items-center justify-center rounded hover:bg-do-grey-100 text-do-grey-400 hover:text-gray-600 transition-colors">
              <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
              </svg>
            </button>
          </div>
        </header>

        <main className="flex-1 overflow-y-auto" style={{ backgroundColor: '#F6F8FA' }}>
          <Outlet />
        </main>
      </div>
    </div>
  )
}
