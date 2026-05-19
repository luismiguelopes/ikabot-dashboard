export interface Material {
  pt: string
  en: string
  icon: string
  color: string
}

export interface AlertThresholds {
  wineWarning: number
  wineCritical: number
  storageWarning: number
}

export interface StatusSummary {
  ships: { available: number; total: number }
  resources: { available: number[]; production: number[] }
  housing: { space: number; citizens: number }
  gold: { total: number; production: number }
  wine_consumption: number
}

export type CityBuildings = Record<string, string | number>

export type EmpireData = Record<string, CityBuildings>

export interface CityResources {
  Wood: number
  Wine: number
  Marble: number
  Crystal: number
  Sulfur: number
  storageCapacity: number
  wineConsumptionPerHour: number
  wineProductionPerHour: number
  wineRunsOutIn: number
}

export type ResourcesData = Record<string, CityResources>

export interface ApiData {
  empireData: EmpireData
  statusSummary: StatusSummary
  resourcesData: ResourcesData
  lastUpdated: string
  lastUpdatedTs: number
  nextCycleAt: number | null
  lastAlive: number | null
}

export interface MovementResource {
  resource: string
  amount: string
}

export interface Movement {
  origin: string
  destination: string
  direction: string
  mission: string
  timeLeft: number
  arrivalTime: number
  isHostile: boolean
  isOwn: boolean
  isSameAlliance: boolean
  resources: MovementResource[]
  troops?: number
  fleets?: number
}

export interface InProgressItem {
  building: string
  position: number
  fromLevel: number
  toLevel?: number
  startedAt: number
  eta: number
}

export interface QueueItem {
  building: string
  targetLevel: number
  addedAt: number
}

export interface TransportError {
  failedAt: number
  origin: string
  resource: string
}

export interface BuildingQueue {
  queues: Record<string, QueueItem[]>
  inProgress: Record<string, InProgressItem>
  transportErrors?: Record<string, TransportError>
  enabled?: boolean
  activeHours?: { start: number; end: number }
  resourceBuffer?: number[]
}

export interface BuildingCostEntry {
  currentLevel: number
  costs: Record<string, Record<string, number>>
}

export interface BuildingCostsData {
  lastUpdated: number
  cities: Record<string, Record<string, BuildingCostEntry>>
}

export interface WorldScanPlayer {
  playerId: string
  cityId?: string
  islandId?: string
  playerName: string
  allyTag?: string
  state: string
  cityName: string
  islandName: string
  islandX: number
  islandY: number
  nearestOwnCity: string
  distance: number
  scores?: { building?: string; research?: string; army?: string; trader?: string; rank?: string }
  mark: string
  markNote?: string
  markUpdatedAt?: number
  markActions?: Array<{ ts: number; text: string }>
  isNew: boolean
}

export interface OwnCity {
  name: string
  cityId: number
  x: number
  y: number
}

export interface WorldScanIsland {
  islandId: string
  islandName: string
  x: number
  y: number
  resourceType: number
  woodLevel?: string
  luxuryLevel?: string
  wonder?: string
  wonderLevel?: string
  freeSlots: number
  totalSlots: number
  hasOwnCity: boolean
  nearestOwnCity: string
  distance: number
}

export interface WorldScanData {
  lastUpdated: number
  scanRadius: number
  ownCities: Array<{ name: string; x: number; y: number }>
  players: WorldScanPlayer[]
  islands?: WorldScanIsland[]
}

export interface ScanStatus {
  status: string
  phase: string
  progress: number
  total: number
  message: string
}
