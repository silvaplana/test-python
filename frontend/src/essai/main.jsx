import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './essai.css'
import EssaiPage from './EssaiPage.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <EssaiPage />
  </StrictMode>,
)
