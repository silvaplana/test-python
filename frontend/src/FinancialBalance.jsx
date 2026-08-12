import { useRef, useState } from 'react'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export function FinancialBalance() {
  const [file, setFile] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [status, setStatus] = useState(null) // { ok: bool, message }
  const [analyzing, setAnalyzing] = useState(false)
  // Progression indicative (pas un vrai pourcentage : on ne connaît pas la
  // durée totale à l'avance) — avance à chaque évènement reçu de l'IA,
  // plafonnée avant le résultat final pour ne jamais sembler "bloquée à 100%".
  const [progress, setProgress] = useState(0)
  const [progressLabel, setProgressLabel] = useState('')
  const [analysis, setAnalysis] = useState(null) // { summary, accounts: [...], consolidated }
  const [analysisError, setAnalysisError] = useState(null)
  const [saving, setSaving] = useState(false)
  const [saveStatus, setSaveStatus] = useState(null) // { ok: bool, message }
  const [loadingSaved, setLoadingSaved] = useState(false)
  const eventSourceRef = useRef(null)

  const runAnalysis = () => {
    setAnalyzing(true)
    setProgress(10)
    setProgressLabel('Chargement des relevés...')
    setAnalysis(null)
    setAnalysisError(null)
    setSaveStatus(null)

    // Ferme un flux précédent éventuel avant d'en ouvrir un nouveau.
    eventSourceRef.current?.close()
    const es = new EventSource(`${API_URL}/financialbalance/analysis`)
    eventSourceRef.current = es

    es.onmessage = (e) => {
      const event = JSON.parse(e.data)
      if (event.type === 'progress') {
        setProgress((p) => Math.min(p + 15, 90))
        setProgressLabel(event.message)
      } else if (event.type === 'result') {
        setProgress(100)
        setAnalysis(event.data)
        setAnalyzing(false)
        es.close()
      } else if (event.type === 'error') {
        setAnalysisError(event.message)
        setAnalyzing(false)
        es.close()
      }
    }
    es.onerror = () => {
      // EventSource déclenche onerror aussi à la fin normale du flux côté
      // serveur : on ne montre un message que si on n'a reçu ni résultat ni
      // erreur explicite (vraie coupure réseau).
      setAnalysisError((prev) => prev ?? "La connexion au serveur a été interrompue pendant l'analyse.")
      setAnalyzing(false)
      es.close()
    }
  }

  const handleUpload = async () => {
    if (!file) return
    setUploading(true)
    setStatus(null)
    try {
      const formData = new FormData()
      formData.append('file', file)
      const response = await fetch(`${API_URL}/financialbalance/archives`, {
        method: 'POST',
        body: formData,
      })
      const data = await response.json().catch(() => null)
      if (!response.ok) {
        throw new Error(data?.detail || `Envoi échoué (${response.status})`)
      }
      setStatus({
        ok: true,
        message: `Archive reçue : ${data.filename} (${(data.size / 1024).toFixed(0)} Ko)`,
      })
      setFile(null)
      runAnalysis()
    } catch (err) {
      setStatus({ ok: false, message: err.message })
    } finally {
      setUploading(false)
    }
  }

  const handleSave = async () => {
    if (!analysis) return
    setSaving(true)
    setSaveStatus(null)
    try {
      const response = await fetch(`${API_URL}/financialbalance/analyses`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(analysis),
      })
      const data = await response.json().catch(() => null)
      if (!response.ok) {
        throw new Error(data?.detail || `Sauvegarde échouée (${response.status})`)
      }
      setSaveStatus({ ok: true, message: 'Bilan sauvegardé ✅' })
    } catch (err) {
      setSaveStatus({ ok: false, message: err.message })
    } finally {
      setSaving(false)
    }
  }

  const handleLoadSaved = async () => {
    setLoadingSaved(true)
    setAnalysisError(null)
    setSaveStatus(null)
    try {
      const response = await fetch(`${API_URL}/financialbalance/analyses/latest`)
      const data = await response.json().catch(() => null)
      if (!response.ok) {
        throw new Error(
          response.status === 404
            ? 'Aucun bilan sauvegardé pour le moment.'
            : data?.detail || `Chargement échoué (${response.status})`
        )
      }
      setAnalysis(data)
    } catch (err) {
      setAnalysisError(err.message)
    } finally {
      setLoadingSaved(false)
    }
  }

  return (
    <section>
      <div className="section-header">
        <h2>Bilan financier</h2>
        <button onClick={handleLoadSaved} disabled={loadingSaved}>
          {loadingSaved ? 'Chargement…' : '📂 Voir le dernier bilan sauvegardé'}
        </button>
      </div>

      <p>
        Pour établir un nouveau bilan financier, envoie une archive <strong>.zip</strong>{' '}
        contenant tous les relevés de compte (compte courant et Livret bleu). L'analyse par IA
        se lance automatiquement après l'envoi.
      </p>

      <div className="upload-row">
        <input
          type="file"
          accept=".zip"
          onChange={(e) => setFile(e.target.files[0] || null)}
        />
        <button onClick={handleUpload} disabled={!file || uploading}>
          {uploading ? 'Envoi…' : 'Envoyer'}
        </button>
      </div>

      {status && <p className={status.ok ? 'success-state' : 'error'}>{status.message}</p>}

      {analyzing && (
        <div className="analysis-progress">
          <div className="progress-bar">
            <div className="progress-bar-fill" style={{ width: `${progress}%` }} />
          </div>
          <p className="progress-label">{progressLabel || 'Analyse en cours…'}</p>
        </div>
      )}

      {analysisError && <p className="error">{analysisError}</p>}

      {analysis && (
        <div className="analysis-result">
          <div className="section-header">
            <h3 className="analysis-result-title">Résumé</h3>
            <button onClick={handleSave} disabled={saving}>
              {saving ? 'Sauvegarde…' : '💾 Sauvegarder ce bilan'}
            </button>
          </div>
          {saveStatus && (
            <p className={saveStatus.ok ? 'success-state' : 'error'}>{saveStatus.message}</p>
          )}
          <p className="analysis-summary">{analysis.summary}</p>

          {analysis.accounts?.map((account, i) => (
            <BalanceBlock
              key={i}
              title={account.name}
              periodStart={account.period_start}
              periodEnd={account.period_end}
              balance={account}
            />
          ))}

          {analysis.consolidated && (
            <BalanceBlock
              title="Tous comptes confondus"
              note="Virements internes entre comptes neutralisés (comptés une seule fois)."
              balance={analysis.consolidated}
            />
          )}
        </div>
      )}
    </section>
  )
}

function BalanceBlock({ title, periodStart, periodEnd, note, balance }) {
  const eur = (n) => (n != null ? `${n.toFixed(2)} €` : '—')

  return (
    <div className="analysis-account">
      <h3>{title}</h3>

      {(periodStart || periodEnd) && (
        <p className="analysis-period">
          Période : du <strong>{periodStart}</strong> au <strong>{periodEnd}</strong>
        </p>
      )}
      {note && <p className="analysis-period">{note}</p>}

      <div className="analysis-totals">
        <div>
          <span className="analysis-totals-label">Solde début de période</span>
          <span className="analysis-totals-value">{eur(balance.opening_balance)}</span>
        </div>
        <div>
          <span className="analysis-totals-label">Solde fin de période</span>
          <span className="analysis-totals-value">{eur(balance.closing_balance)}</span>
        </div>
        <div>
          <span className="analysis-totals-label">Total recettes</span>
          <span className="analysis-totals-value success-state">{eur(balance.total_income)}</span>
        </div>
        <div>
          <span className="analysis-totals-label">Total dépenses</span>
          <span className="analysis-totals-value unpaid-amount">{eur(balance.total_expense)}</span>
        </div>
      </div>

      {balance.categories?.length > 0 && (
        <div className="table-wrapper">
          <table>
            <thead>
              <tr>
                <th>Catégorie</th>
                <th>Recettes</th>
                <th>Dépenses</th>
              </tr>
            </thead>
            <tbody>
              {balance.categories.map((c, i) => (
                <tr key={i}>
                  <td>{c.category}</td>
                  <td>{c.income ? eur(c.income) : '—'}</td>
                  <td>{c.expense ? eur(c.expense) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
