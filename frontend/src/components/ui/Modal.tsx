import { useEffect, useRef } from 'react'
import type { ReactNode } from 'react'
import { useT } from '../../i18n'

const FOCUSABLE =
  'a[href],button:not([disabled]),textarea:not([disabled]),input:not([disabled]),select:not([disabled]),[tabindex]:not([tabindex="-1"])'

function visibleFocusable(panel: HTMLElement): HTMLElement[] {
  return Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE))
    .filter(n => n.offsetParent !== null)
}

interface ModalProps {
  onClose: () => void
  children: ReactNode
  labelledBy?: string       // id of the heading that names the dialog
  className?: string        // panel classes (default: small white card)
}

// Accessible modal shell: closes on Escape and backdrop click, traps Tab focus inside,
// moves focus in on open and locks body scroll. Replaces the ad-hoc backdrop+panel divs
// that every modal used to hand-roll (none of which handled the keyboard).
export function Modal({ onClose, children, labelledBy, className }: ModalProps) {
  const panelRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const panel = panelRef.current
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.stopPropagation(); onClose(); return }
      if (e.key === 'Tab' && panel) {
        const nodes = visibleFocusable(panel)
        if (nodes.length === 0) { e.preventDefault(); return }
        const first = nodes[0], last = nodes[nodes.length - 1]
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
      }
    }
    document.addEventListener('keydown', onKey, true)

    // Move focus into the dialog (first field, else the panel itself).
    const firstField = panel ? visibleFocusable(panel)[0] : null
    ;(firstField ?? panel)?.focus()

    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey, true)
      document.body.style.overflow = prevOverflow
    }
  }, [onClose])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
        tabIndex={-1}
        onClick={e => e.stopPropagation()}
        className={className ?? 'bg-white rounded-2xl shadow-2xl p-6 w-full max-w-sm mx-4 focus:outline-none'}
      >
        {children}
      </div>
    </div>
  )
}

type ConfirmTone = 'indigo' | 'amber' | 'blue' | 'red'
const TONE: Record<ConfirmTone, string> = {
  indigo: 'bg-indigo-600 hover:bg-indigo-700',
  amber: 'bg-amber-500 hover:bg-amber-600',
  blue: 'bg-blue-500 hover:bg-blue-600',
  red: 'bg-red-600 hover:bg-red-700',
}

interface ConfirmModalProps {
  title: string
  body?: ReactNode
  confirmLabel?: string
  cancelLabel?: string
  tone?: ConfirmTone
  onConfirm: () => void
  onCancel: () => void
}

// Replaces native window.confirm() and the hand-rolled confirm dialogs with a consistent,
// keyboard-dismissable modal.
export function ConfirmModal({ title, body, confirmLabel, cancelLabel, tone = 'indigo', onConfirm, onCancel }: ConfirmModalProps) {
  const t = useT()
  return (
    <Modal onClose={onCancel} labelledBy="confirm-modal-title">
      <p id="confirm-modal-title" className="text-sm font-semibold text-slate-800 mb-1">{title}</p>
      {body && <div className="text-sm text-slate-500 mb-5">{body}</div>}
      <div className="flex gap-2 justify-end">
        <button
          onClick={onCancel}
          className="px-4 py-2 text-sm text-slate-600 bg-slate-100 hover:bg-slate-200 rounded-lg transition-colors"
        >
          {cancelLabel || t('cancel')}
        </button>
        <button
          onClick={onConfirm}
          className={`px-4 py-2 text-sm text-white rounded-lg transition-colors ${TONE[tone]}`}
        >
          {confirmLabel || t('confirm')}
        </button>
      </div>
    </Modal>
  )
}
