import { useCallback, useEffect, useState } from 'react'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

// Meme mecanique de chargement que dans HelloAsso.jsx (etat loading/error/data).
function useFfstFetch(path) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  const fetchData = useCallback(async () => {
    try {
      const response = await fetch(`${API_URL}${path}`)
      if (!response.ok) throw new Error(`GET ${path} a échoué (${response.status})`)
      setData(await response.json())
      setError(null)
    } catch (err) {
      setError(err.message)
    }
  }, [path])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  return { data, error, refetch: fetchData }
}

export function LicencesTable() {
  const { data: licences, error, refetch } = useFfstFetch('/ffst/licences')

  return (
    <section>
      <div className="section-header">
        <h2>Licenciés FFST ({licences?.length ?? '…'})</h2>
        <button onClick={refetch}>Rafraîchir</button>
      </div>

      {error && <p className="error">{error}</p>}

      {licences && (
        <div className="table-wrapper">
          <table>
            <thead>
              <tr>
                <th>Nom et Prénom</th>
                <th className="col-secondary">Né(e) le</th>
                <th className="col-secondary">Type</th>
                <th className="col-secondary">Licence n°</th>
              </tr>
            </thead>
            <tbody>
              {licences.map((l, i) => (
                <tr key={i}>
                  <td>{l['Nom et Prénom']}</td>
                  <td className="col-secondary">{l['Né(e) le']}</td>
                  <td className="col-secondary">{l['Type']}</td>
                  <td className="col-secondary">{l['Licence n°']}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

export function DemandesTable() {
  const { data: demandes, error, refetch } = useFfstFetch('/ffst/demandes')

  return (
    <section>
      <div className="section-header">
        <h2>Demandes de licences FFST en cours ({demandes?.length ?? '…'})</h2>
        <button onClick={refetch}>Rafraîchir</button>
      </div>

      {error && <p className="error">{error}</p>}

      {demandes && (demandes.length === 0 ? (
        <p className="empty-state">Aucune demande en cours 🎉</p>
      ) : (
        <div className="table-wrapper">
          <table>
            <thead>
              <tr>
                <th>Nom et Prénom</th>
                <th className="col-secondary">Né(e) le</th>
                <th className="col-secondary">Type</th>
                <th className="col-secondary">Licence n°</th>
                <th className="col-secondary">N° demande</th>
                <th>Etat</th>
              </tr>
            </thead>
            <tbody>
              {demandes.map((d, i) => (
                <tr key={i}>
                  <td>{d['Nom et Prénom']}</td>
                  <td className="col-secondary">{d['Né(e) le']}</td>
                  <td className="col-secondary">{d['Type']}</td>
                  <td className="col-secondary">{d['Licence n°']}</td>
                  <td className="col-secondary">{d['IDDemande']}</td>
                  <td>{d['Etat']}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </section>
  )
}

