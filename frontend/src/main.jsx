import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

// Enregistre le service worker (voir public/sw.js) : rend le site
// installable (PWA) et permet les notifications push (onglet Profil).
// import.meta.env.BASE_URL (pas un chemin en dur) : reste correct que
// l'app soit servie a la racine (dev) ou sous /sambo-admin/ (prod, voir
// vite.config.js) -- un service worker enregistre avec le mauvais scope
// ne recevrait jamais les evenements push de cette appli.
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    const base = import.meta.env.BASE_URL
    navigator.serviceWorker.register(`${base}sw.js`, { scope: base }).catch((err) => {
      console.error('Échec d’enregistrement du service worker :', err)
    })
  })
}
