import { useEffect, useState } from 'react'
import './App.css'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

function App() {
  const [motorValue, setMotorValue] = useState('')
  const [inputValue, setInputValue] = useState('')
  const [error, setError] = useState(null)

  const fetchMotor = async () => {
    try {
      const response = await fetch(`${API_URL}/motor`)
      if (!response.ok) throw new Error(`GET /motor a échoué (${response.status})`)
      const data = await response.json()
      setMotorValue(data)
      setError(null)
    } catch (err) {
      setError(err.message)
    }
  }

  useEffect(() => {
    fetchMotor()
  }, [])

  const handleSend = async () => {
    try {
      const response = await fetch(`${API_URL}/motor`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ motorName: inputValue }),
      })
      if (!response.ok) throw new Error(`POST /motor a échoué (${response.status})`)
      await fetchMotor()
      setError(null)
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <div className="app">
      <h1>Motor</h1>

      <p>
        Moteur courant : <strong>{motorValue}</strong>
      </p>

      <div className="form-row">
        <input
          type="text"
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          placeholder="Nom du moteur"
        />
        <button onClick={handleSend}>Envoyer moteur</button>
      </div>

      {error && <p className="error">{error}</p>}
    </div>
  )
}

export default App
