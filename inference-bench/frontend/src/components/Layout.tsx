import { NavLink, Outlet } from 'react-router-dom'

const NAV_GROUPS = [
  {
    label: 'EVALUATE',
    items: [
      { to: '/new',       icon: '＋', label: 'New Evaluation' },
      { to: '/dashboard', icon: '📋', label: 'History' },
      { to: '/compare',   icon: '⬡',  label: 'Compare' },
      { to: '/datasets',  icon: '🗂',  label: 'Custom Datasets' },
    ],
  },
  {
    label: 'EXPLORE',
    items: [
      { to: '/models',     icon: '🤖', label: 'Model Catalog' },
      { to: '/probe',      icon: '🔬', label: 'Probe Endpoint' },
      { to: '/playground', icon: '🎮', label: 'Playground' },
    ],
  },
  {
    label: 'MONITOR',
    items: [
      { to: '/monitor',   icon: '📡', label: 'Live Monitor' },
      { to: '/schedules', icon: '🕐', label: 'Schedules' },
      { to: '/alerts',    icon: '⚠',  label: 'Alerts' },
    ],
  },
  {
    label: 'INSIGHTS',
    items: [
      { to: '/cost',         icon: '💰', label: 'Cost Analytics' },
      { to: '/integrations', icon: '🔗', label: 'Integrations' },
    ],
  },
]

export default function Layout() {
  return (
    <div className="flex h-screen overflow-hidden">
      {/* Sidebar */}
      <aside className="w-56 bg-gray-900 border-r border-gray-800 flex flex-col shrink-0 overflow-y-auto">
        {/* Logo */}
        <div className="px-4 py-5 border-b border-gray-800">
          <div className="flex items-center gap-2.5">
            <span className="text-xl">⚡</span>
            <div>
              <h1 className="text-sm font-bold text-white tracking-wide">Gauge</h1>
              <p className="text-xs text-gray-500">Inference intelligence</p>
            </div>
          </div>
        </div>

        {/* Nav groups */}
        <nav className="flex-1 px-2 py-3 space-y-4">
          {NAV_GROUPS.map(group => (
            <div key={group.label}>
              <p className="px-3 mb-1 text-[10px] font-semibold text-gray-600 uppercase tracking-wider">
                {group.label}
              </p>
              <div className="space-y-0.5">
                {group.items.map(({ to, icon, label }) => (
                  <NavLink
                    key={to}
                    to={to}
                    className={({ isActive }) =>
                      `flex items-center gap-2.5 px-3 py-1.5 rounded-lg text-sm transition-colors ${
                        isActive
                          ? 'bg-brand-600/20 text-brand-400 font-medium'
                          : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800'
                      }`
                    }
                  >
                    <span className="text-sm w-4 text-center">{icon}</span>
                    <span>{label}</span>
                  </NavLink>
                ))}
              </div>
            </div>
          ))}
        </nav>

        {/* Footer */}
        <div className="px-4 py-3 border-t border-gray-800">
          <p className="text-[10px] text-gray-600">Gauge v2.0 · DigitalOcean</p>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 overflow-y-auto bg-gray-950">
        <Outlet />
      </main>
    </div>
  )
}
