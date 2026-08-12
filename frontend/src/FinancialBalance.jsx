import { useState } from 'react'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export function FinancialBalance() {
  const [file, setFile] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [status, setStatus] = useState(null) // { ok: bool, message }

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
    } catch (err) {
      setStatus({ ok: false, message: err.message })
    } finally {
      setUploading(false)
    }
  }

  return (
    <section>
      <div className="section-header">
        <h2>Bilan financier</h2>
      </div>

      <p>
        Pour établir le bilan financier, envoie une archive <strong>.zip</strong> contenant
        tous les relevés de compte (compte courant et Livret bleu).
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
    </section>
  )
}
