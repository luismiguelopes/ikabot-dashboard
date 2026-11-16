import type { Material, AlertThresholds } from './types'

export const MATERIALS: Material[] = [
  { pt: 'Madeira',  en: 'Wood',    icon: 'fa-tree',        color: 'text-green-500',  hex: '#22c55e' },
  { pt: 'Vinho',    en: 'Wine',    icon: 'fa-wine-bottle', color: 'text-red-400',    hex: '#f87171' },
  { pt: 'Mármore',  en: 'Marble',  icon: 'fa-mountain',    color: 'text-slate-400',  hex: '#94a3b8' },
  { pt: 'Cristal',  en: 'Crystal', icon: 'fa-gem',         color: 'text-cyan-400',   hex: '#22d3ee' },
  { pt: 'Enxofre',  en: 'Sulfur',  icon: 'fa-flask',       color: 'text-yellow-400', hex: '#facc15' },
]

export const AUTO_REFRESH_SECONDS = 300

export const ALERT_DEFAULTS: AlertThresholds = {
  wineWarning: 8,
  wineCritical: 2,
  storageWarning: 95,
}

export const COST_KEYS = ['wood', 'wine', 'marble', 'glass', 'sulfur']

export const RESOURCE_ICONS  = ['', 'fa-wine-bottle', 'fa-mountain', 'fa-gem', 'fa-flask']
export const RESOURCE_COLORS = ['', 'text-red-400', 'text-slate-400', 'text-cyan-400', 'text-yellow-400']
