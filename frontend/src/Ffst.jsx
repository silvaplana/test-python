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

function LicencesTable() {
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

function Ffst() {
  return (
    <div className="ffst">
      <LicencesTable />
    </div>
  )
}

export default Ffst
