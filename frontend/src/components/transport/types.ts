export interface PendingTransport {
  id:             string
  originCityId:   string
  originCityName: string
  destCityId:     string
  destCityName:   string
  resources:      number[]
  ships:          number
  shipType:       string
  dispatchAfter:  number
}

export interface ConsolidateSettings {
  enabled:       boolean
  destCityId:    string
  destCityName:  string
  intervalHours: number
  minSendTotal:  number
  shipType:      'transporters' | 'freighters' | 'both'
  ignoreCityIds: string[]
  /** Resources never sent, by the bot's names: Wood, Wine, Marble, Crystal, Sulfur. */
  skipResources?: string[]
  /** Never send more than the destination warehouse can still hold (default on). */
  respectDestCap?: boolean
  lastRun?:      number
  lastSent?:     Record<string, number>
}

export interface WineSettings {
  enabled:        boolean
  thresholdHours: number
  targetHours:    number
  donorReserveHours: number
  reserveShipsFromFarm?: boolean
  reserveShips?:         number
}

export interface WineBuySettings {
  enabled:          boolean
  dryRun:           boolean
  targetHours:      number
  refillBelowHours: number
  criticalHours:    number
  maxPricePerUnit:  number
  goldFloor:        number
  maxSpendPerCycle: number
  ignoreCityIds:    string[]
}

export interface WineBuyStatus {
  now?: number
  dryRun?: boolean
  deficit?: number
  bought?: number
  spent?: number
  avgPrice?: number
  cheapest?: number | null
  gold?: number
  note?: string
  buys?: { seller: string; fromCity: string; toCity: string; amount: number; price: number; cost: number }[]
  topCities?: [string, number][]
  // the last purchase that really happened — a preview never replaces it (P13.48)
  lastPurchase?: { at: number; bought: number; spent: number; avgPrice: number }
}

export const SELECT_CLS = 'w-full border border-slate-200 rounded-lg px-3 py-2 text-sm bg-white shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-400 text-slate-700'
export const LABEL_CLS = 'block text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1'
export const FIELD_CLS = 'w-full'
