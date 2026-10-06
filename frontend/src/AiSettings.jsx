// Reglages de l'IA d'un calcul (Bilan financier, Assemblees generales) :
// prompt, modele et cout cumule, dans une zone qui se plie d'un clic sur son
// titre. Repliee, le titre rappelle le modele et le cout. L'etat plie ou
// deplie est retenu en base par l'ecran (onToggle).
export function AiSettings({ open, onToggle, summary, children }) {
  return (
    <div className="trial-form-wide reports-settings">
      <div className="reports-settings-header">
        <button
          type="button"
          className="forecasts-collapse"
          aria-expanded={open}
          title={open ? 'Replier' : 'Déplier'}
          onClick={onToggle}
        >
          <span aria-hidden="true">{open ? '▾' : '▸'}</span> Réglages de l'IA
        </button>
        {!open && <span className="reports-result-meta">{summary}</span>}
      </div>
      {open && <div className="trial-form-grid reports-settings-body">{children}</div>}
    </div>
  )
}
