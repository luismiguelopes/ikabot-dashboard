// Shared helpers and types for the dispatch/farm/history panels (P11.5 split of DispatchTab).

export interface MilitaryUnit {
  name: string
  amount: number
}

export interface CityMilitary {
  cityId: string
  troops: Record<string, MilitaryUnit>
  fleet:  Record<string, MilitaryUnit>
}

export interface MilitaryData {
  lastUpdated: number
  byCityName:  Record<string, CityMilitary>
}

export interface FarmTarget {
  target_city_id:   string
  target_city_name: string
  target_player:    string
  enabled:          boolean
  interval_hours:   number
  min_loot:         number
  max_enemy_ships:  number
  respy_every:      number
  fleet_lead_min:   number
  disperse_min:     number
  is_fleet_target:  number
  state:            string
  next_run_at:      number
  last_loot:        number
  last_troop_journey: number
  total_raids:      number
  total_loot:       number
}

export function selectClass(extra = '') {
  return `w-full border border-slate-200 rounded-lg px-3 py-2 text-sm bg-white shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-400 text-slate-700 ${extra}`
}

export function btnClass(variant: 'primary' | 'danger' | 'ghost', extra = '') {
  const base = 'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors '
  if (variant === 'primary') return base + 'bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-40 ' + extra
  if (variant === 'danger')  return base + 'bg-red-500 text-white hover:bg-red-600 ' + extra
  return base + 'text-slate-500 hover:bg-slate-100 ' + extra
}

// Mirror of the bot's _calc_travel_secs model: same island ≈ 10 min; otherwise
// 1200s × distance for warships/transports, troops on transports ≈ 2/3 of that.
export function travelSecs(ox: number, oy: number, tx: number, ty: number, mission: 'army' | 'fleet'): number {
  if (ox === tx && oy === ty) return 600
  const dist = Math.sqrt((ox - tx) ** 2 + (oy - ty) ** 2)
  const fleet = Math.ceil(1200 * dist)
  return mission === 'army' ? Math.round(fleet * 2 / 3) : fleet
}
