export function StatBadge({ icon, iconColor, label, value }: { icon: string; iconColor: string; label: string; value: string | number }) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-4 flex items-center gap-3">
      <div className={`w-10 h-10 rounded-lg flex items-center justify-center bg-slate-50 ${iconColor}`}>
        <i className={`fa-solid ${icon} text-base`} />
      </div>
      <div className="min-w-0">
        <p className="text-xs text-slate-400 leading-none mb-1 truncate">{label}</p>
        <p className="text-lg font-bold text-slate-800 font-mono leading-none">{value}</p>
      </div>
    </div>
  )
}
