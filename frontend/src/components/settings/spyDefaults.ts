// Default origin city and agent count for manual spy dispatches, kept in the browser.
const SPY_ORIGIN_KEY = 'spy_default_origin_city'
const SPY_AGENTS_KEY = 'spy_default_agents'

export function loadSpyDefaults(): { originCityId: string; numAgents: number } {
  try {
    return {
      originCityId: localStorage.getItem(SPY_ORIGIN_KEY) || '',
      numAgents: parseInt(localStorage.getItem(SPY_AGENTS_KEY) || '1') || 1,
    }
  } catch {
    return { originCityId: '', numAgents: 1 }
  }
}

export function saveSpyDefaults(originCityId: string, numAgents: number) {
  try {
    localStorage.setItem(SPY_ORIGIN_KEY, originCityId)
    localStorage.setItem(SPY_AGENTS_KEY, String(numAgents))
  } catch { /* storage blocked — the defaults just don't persist */ }
}
