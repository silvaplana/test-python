// Saison choisie dans Finances (Saisons, Bilan financier, Assemblees
// generales, Previsionnel) : retenue sur l'appareil et commune aux quatre
// ecrans, pour retrouver la meme saison en passant de l'un a l'autre et a la
// reouverture de l'appli.
const KEY = 'finances-season'

// Identifiant de la saison retenue, ou null si aucune ou si elle n'existe plus.
export function readSeasonChoice(seasons) {
  try {
    const id = Number(localStorage.getItem(KEY))
    return seasons.some((s) => s.id === id) ? id : null
  } catch {
    return null
  }
}

export function writeSeasonChoice(id) {
  try {
    localStorage.setItem(KEY, String(id))
  } catch {
    // Stockage indisponible : la saison ne sera juste pas retenue.
  }
}
