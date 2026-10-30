// Shared types for the world-scan pages, extracted from MundoPage (P6.10 split).
export interface CitySpyCounts { available: number | null; inDefense: number | null; inTraining: number | null; deployed: number | null }

export interface FarmTarget {
  target_city_id: string; enabled: boolean; state: string; next_run_at: number
  interval_hours: number; total_raids: number; last_loot: number; respy_every: number
  mode?: string; low_raids?: number
  // Identity fields (from farm_list SELECT *) — needed to render farm-only targets in the
  // unified world/target list even when they are not in the current world scan (Phase 3).
  target_city_name?: string; target_player?: string
  island_id?: string | number; island_x?: number; island_y?: number
  last_troop_journey?: number  // round-trip basis for the loot/hour queue score
}
export interface LootStat {
  from_player: string; raids: number; last_ts: number; total: number
  wood: number; wine: number; marble: number; crystal: number; sulfur: number
}

export interface SpyMissionResult { success: boolean; targetCityName: string | null; resources: Record<string, number> | null; troops?: Record<string, number> | null; reportedAt: number }
export interface SpyGarrisonResult { success?: boolean; targetCityName?: string | null; troops: Record<string, number> | null; reportedAt?: number; error?: string }
export interface SpyMission {
  originCityId: string | null; targetCityId: string; targetPlayerName: string; targetCityName: string
  islandX: number; islandY: number; numAgents: number
  state: 'TRAVELING' | 'WAITING_AT_CITY' | 'EXECUTING' | 'EXECUTING_WAREHOUSE' | 'WAITING_FOR_GARRISON' | 'EXECUTING_GARRISON' | 'DONE' | 'FAILED' | 'RECALLED'
  dispatchedAt: number; arrivedAt: number | null; executedAt: number | null
  garrisonExecuteAfter: number | null; garrisonExecutedAt: number | null
  missionType: string | null; result: SpyMissionResult | null; garrisonResult: SpyGarrisonResult | null; error?: string
}
