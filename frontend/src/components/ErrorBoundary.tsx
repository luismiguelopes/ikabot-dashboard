import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props { children: ReactNode; label?: string }
interface State { error: Error | null }

/**
 * Catches a render crash in the subtree and shows what broke with a way back, instead of
 * leaving the whole dashboard blank (an unexpected response reaching `.map` / `.filter` used
 * to take the entire page down, with nothing on screen). Give it a `key` (e.g. the current
 * page) so moving elsewhere clears the error.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[ErrorBoundary]', this.props.label ?? '', error, info.componentStack)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div className="max-w-xl mx-auto mt-10 bg-white border border-red-200 rounded-xl shadow-sm p-6">
        <div className="flex items-center gap-2 text-red-700 font-semibold">
          <i className="fa-solid fa-triangle-exclamation" />
          Esta página encontrou um erro
        </div>
        <p className="text-sm text-slate-500 mt-2">
          Os dados recebidos não tinham o formato esperado. O resto do painel continua a funcionar.
        </p>
        <pre className="mt-3 text-xs text-slate-500 bg-slate-50 border border-slate-200 rounded-lg p-3 overflow-x-auto">
          {this.state.error.message}
        </pre>
        <div className="mt-4 flex gap-2">
          <button
            onClick={() => this.setState({ error: null })}
            className="px-3 py-2 rounded-lg text-sm font-medium bg-indigo-600 text-white hover:bg-indigo-700"
          >
            <i className="fa-solid fa-rotate-right mr-1.5" />Tentar de novo
          </button>
          <button
            onClick={() => location.reload()}
            className="px-3 py-2 rounded-lg text-sm font-medium bg-white text-slate-600 border border-slate-200 hover:bg-slate-50"
          >
            Recarregar o painel
          </button>
        </div>
      </div>
    )
  }
}
