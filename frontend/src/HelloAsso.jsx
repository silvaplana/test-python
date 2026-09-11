import { useCallback, useEffect, useState } from 'react'
import clubLogo from './assets/club-logo.png'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

function euros(amount) {
  return `${amount.toFixed(2)} €`
}

// Libelle d'action en cours (ex: "Envoi en cours") : italique + 3 points
// animes en boucle (voir .loading-label/.loading-dots dans App.css),
// plutot qu'un simple "..." statique.
function LoadingLabel({ text }) {
  return (
    <span className="loading-label">
      {text}
      <span className="loading-dots">
        <span>.</span>
        <span>.</span>
        <span>.</span>
      </span>
    </span>
  )
}

// Tableau simple avec etat loading/error/data, factorise pour les 2 tableaux
// (membres, impayes) qui ont la meme mecanique de chargement.
function useHelloAssoFetch(path) {
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

// Identifiant normalise (nom + prenom, insensible a la casse et aux
// espaces superflus) pour comparer un adherent HelloAsso (lastName +
// firstName separes) a une ligne FFST ("Nom et Prénom" combine).
function memberIdentifier(lastName, firstName) {
  return `${lastName} ${firstName}`.replace(/\s+/g, ' ').trim().toUpperCase()
}

// Ensemble des identifiants (voir memberIdentifier) presents dans une liste
// FFST (licences ou demandes), pour un test d'appartenance en O(1).
function ffstIdentifiers(ffstRows) {
  return new Set(
    (ffstRows ?? []).map((row) => (row['Nom et Prénom'] || '').replace(/\s+/g, ' ').trim().toUpperCase())
  )
}

// Texte normalise (sans accents, insensible a la casse) pour la recherche
// textuelle des adherents : "é"/"e" ou "Denane"/"denane" doivent matcher
// pareil.
function normaliserTexte(text) {
  return (text || '')
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
}

// Date de naissance HelloAsso (customFields['date de naissance'], format
// JJ/MM/AAAA) -> objet Date, ou null si absente/mal formee (filtre
// Juniors/Seniors non applicable pour cet adherent dans ce cas, voir
// MembersTable).
function parserDateNaissance(value) {
  const match = (value || '').match(/^(\d{2})\/(\d{2})\/(\d{4})$/)
  if (!match) return null
  const [, jour, mois, annee] = match
  return new Date(Number(annee), Number(mois) - 1, Number(jour))
}

// Age en annees revolues a la date du jour, a partir d'une date de
// naissance deja parsee (voir parserDateNaissance).
function calculerAge(birthDate) {
  const today = new Date()
  let years = today.getFullYear() - birthDate.getFullYear()
  const anniversairePasse =
    today.getMonth() > birthDate.getMonth() ||
    (today.getMonth() === birthDate.getMonth() && today.getDate() >= birthDate.getDate())
  if (!anniversairePasse) years -= 1
  return years
}

// Puces de filtre par age (barre de filtres façon WhatsApp, voir
// MembersTable) : Juniors/Seniors (mineur/majeur) + des tranches de 10
// ans plus fines, toutes mutuellement exclusives entre elles (un seul
// filtre actif a la fois, "tous" par defaut). "test" absent pour "tous"
// (aucune condition, y compris pour les adherents sans date de naissance
// exploitable).
const AGE_FILTERS = [
  { value: 'tous', label: 'Tous' },
  { value: 'juniors', label: 'Juniors', test: (age) => age < 18 },
  { value: 'seniors', label: 'Seniors', test: (age) => age >= 18 },
  { value: '-10', label: '-10', test: (age) => age < 10 },
  { value: '10-20', label: '10-20', test: (age) => age >= 10 && age < 20 },
  { value: '20-30', label: '20-30', test: (age) => age >= 20 && age < 30 },
  { value: '30-40', label: '30-40', test: (age) => age >= 30 && age < 40 },
  { value: '40-50', label: '40-50', test: (age) => age >= 40 && age < 50 },
  { value: '50+', label: '50+', test: (age) => age >= 50 },
]

// Badge "nouveaux adherents non consultes" (façon WhatsApp), voir
// NewMembersBadge et App.jsx. Identifie les adherents par leur id
// HelloAsso (voir helloasso.py:get_members), stable et unique --
// beaucoup plus fiable qu'un rapprochement par nom (cf. l'historique de
// bugs whitespace/payeur-vs-adherent sur ce genre de rapprochement dans
// ce fichier). Stocke en localStorage : un badge "par appareil", pas
// partage entre les utilisateurs du club.
const SEEN_MEMBER_IDS_KEY = 'helloasso-seen-member-ids'
// Les composants montes ailleurs dans l'arbre (le badge de la nav, monte
// dans App.jsx) ne peuvent pas savoir qu'un autre composant (MembersTable)
// vient d'ecrire dans le localStorage -- cet evenement custom les
// previent pour qu'ils se recalculent, sans avoir besoin d'un store
// partage (React context, etc.) pour un besoin aussi ponctuel.
const SEEN_CHANGED_EVENT = 'helloasso-seen-members-changed'

// null = jamais initialise (1ere visite de l'appli sur cet appareil,
// distinct d'un tableau vide) : voir NewMembersBadge, qui memorise alors
// silencieusement l'etat actuel comme point de depart plutot que de
// compter tous les adherents existants comme "nouveaux".
function readSeenMemberIds() {
  try {
    const raw = localStorage.getItem(SEEN_MEMBER_IDS_KEY)
    return raw === null ? null : new Set(JSON.parse(raw))
  } catch {
    return null
  }
}

// Marque des adherents comme "vus" (efface le badge pour eux). Appele
// (a) silencieusement au tout premier chargement pour memoriser une
// base de depart (voir NewMembersBadge), et (b) quand l'onglet Adherents
// devient reellement actif (prop "active" de MembersTable, voir
// Navigation.jsx) -- pas juste monte une fois, sinon un adherent arrive
// pendant qu'on est sur un autre onglet ne serait jamais marque comme vu
// en y revenant (l'onglet reste monte en permanence apres sa 1ere
// visite).
function markMembersSeen(members) {
  const ids = (members ?? []).map((m) => m.id).filter((id) => id != null)
  if (ids.length === 0) return
  const seen = readSeenMemberIds() ?? new Set()
  ids.forEach((id) => seen.add(id))
  try {
    localStorage.setItem(SEEN_MEMBER_IDS_KEY, JSON.stringify([...seen]))
  } catch {
    // Stockage indisponible (navigation privee stricte, quota...) : le
    // badge ne se souviendra simplement pas d'une visite a l'autre, pas
    // grave pour cette fonctionnalite de confort.
  }
  window.dispatchEvent(new Event(SEEN_CHANGED_EVENT))
}

// Badge affiche a cote du libelle "HelloAsso" dans la navigation (voir
// App.jsx, section.badge) : nombre d'adherents jamais vus sur cet
// appareil. Fetch independant de MembersTable (comme le reste de
// l'appli, ex: /ffst/licences deja fetche a plusieurs endroits) : reste
// a jour meme si on n'a jamais ouvert l'onglet Adherents.
export function NewMembersBadge() {
  const { data: members } = useHelloAssoFetch('/helloasso/members')
  // Sert juste a forcer un nouveau rendu quand SEEN_CHANGED_EVENT est
  // recu (ex: MembersTable vient de marquer des adherents comme vus) :
  // readSeenMemberIds() est relu a chaque rendu, pas garde en state.
  const [, forceRerender] = useState(0)

  useEffect(() => {
    const onSeenChanged = () => forceRerender((n) => n + 1)
    window.addEventListener(SEEN_CHANGED_EVENT, onSeenChanged)
    return () => window.removeEventListener(SEEN_CHANGED_EVENT, onSeenChanged)
  }, [])

  // 1ere visite de l'appli sur cet appareil (voir readSeenMemberIds) :
  // memorise l'etat actuel sans afficher de badge, plutot que de compter
  // tous les adherents existants comme "nouveaux".
  useEffect(() => {
    if (members && readSeenMemberIds() === null) markMembersSeen(members)
  }, [members])

  const seen = readSeenMemberIds()
  const count = seen === null ? 0 : (members ?? []).filter((m) => m.id != null && !seen.has(m.id)).length

  // Badge sur l'icone de l'appli (PWA installee) : API Badging, prise en
  // charge Chrome/Edge (Android + desktop) mais pas Safari/iOS a ce jour
  // -- feature-detection, pas de degradation geree pour iOS au-dela du
  // badge dans l'appli elle-meme (ci-dessous) et des notifications push.
  useEffect(() => {
    if (!('setAppBadge' in navigator)) return
    if (count > 0) navigator.setAppBadge(count).catch(() => {})
    else navigator.clearAppBadge?.().catch(() => {})
  }, [count])

  if (count === 0) return null
  return <span className="nav-badge">{count}</span>
}

// Codes promo type "ANCIEN_N" (ex: ANCIEN_2) : le seul type de code promo
// verifie pour l'instant. N = anciennete minimum requise (en saisons
// precedentes, "Nouvelle saison" comprise) -- valide aussi pour une
// anciennete superieure a N, pas seulement egale.
const ANCIEN_CODE_RE = /^ANCIEN_(\d+)$/i

// Anciennete d'un adherent (nb de saisons precedentes, hors saison en
// cours) a partir de sa ligne dans l'historique (/members_history,
// colonne "Nb saisons" de l'onglet Historique) : la saison en cours ne
// doit pas compter, un adherent qui vient de la payer n'a par definition
// aucune anciennete pour elle. historyRow absent (jamais adherent avant)
// = 0.
function anciennete(historyRow, currentSeason) {
  if (!historyRow) return 0
  const count = historyRow.campaigns.length
  return currentSeason && historyRow.campaigns.includes(currentSeason) ? count - 1 : count
}

// Message d'incoherence entre un code promo et l'anciennete reelle de
// l'adherent (voir ANCIEN_CODE_RE), ou null si le code est absent, d'un
// autre type, ou coherent.
function promoCodeError(promoCode, seniority) {
  const match = promoCode?.match(ANCIEN_CODE_RE)
  if (!match) return null
  const required = Number(match[1])
  if (seniority >= required) return null
  return `Ancienneté insuffisante pour ${promoCode} : ${seniority} saison${seniority > 1 ? 's' : ''} trouvée${seniority > 1 ? 's' : ''} (${required}+ requise${required > 1 ? 's' : ''})`
}

export function MembersTable({ active }) {
  const { data: members, error, refetch: refetchMembers } = useHelloAssoFetch('/helloasso/members')
  // Efface le badge "nouveaux adherents" (voir NewMembersBadge) quand cet
  // onglet devient reellement actif (pas juste monte, voir markMembersSeen) :
  // c'est la definition de "consulte" donnee pour cette fonctionnalite.
  useEffect(() => {
    if (active && members) markMembersSeen(members)
  }, [active, members])
  // La colonne Statut FFST distingue 4 cas pour chaque adherent, par
  // ordre de priorite : licencie (payee), demande validee (a payer),
  // demande en brouillon (bouton pour la supprimer), ou aucun des 3
  // (bouton pour en faire une).
  const { data: licences, refetch: refetchLicences } = useHelloAssoFetch('/ffst/licences')
  const { data: validatedDemandes, refetch: refetchValidatedDemandes } = useHelloAssoFetch(
    '/ffst/demandes_validated'
  )
  const { data: draftDemandes, refetch: refetchDraftDemandes } = useHelloAssoFetch('/ffst/demandes_draft')
  const { data: fonctions } = useHelloAssoFetch('/ffst/fonctions')
  const ffstDataLoaded = licences !== null && validatedDemandes !== null && draftDemandes !== null
  const licenceIdentifiers = ffstIdentifiers(licences)
  const validatedIdentifiers = ffstIdentifiers(validatedDemandes)
  const draftIdentifiers = ffstIdentifiers(draftDemandes)
  // Anciennete (colonne "Ancienneté" + verification du code promo, voir
  // promoCodeError) : l'historique donne le "Nb saisons" par PAYEUR (pas
  // par adherent -- un mineur inscrit par un parent n'y apparait jamais
  // sous son propre nom, voir payerIdentifier plus bas), la campagne en
  // cours donne la saison a en exclure (voir anciennete()). Le titre de
  // la campagne contient toujours la saison au format "20XX-20YY" (ex:
  // "... pour la saison 2026-2027"), au meme format que les libelles de
  // saison de l'historique -- pas besoin d'une 2e source pour ca.
  const { data: campaign } = useHelloAssoFetch('/helloasso/campaign')
  const { data: history } = useHelloAssoFetch('/members_history')
  const currentSeason = campaign?.title?.match(/20\d{2}-20\d{2}/)?.[0] ?? null
  const historyByIdentifier = new Map(
    (history ?? []).map((h) => [memberIdentifier(h.lastName, h.firstName), h])
  )
  // Etat des actions FFST en cours, par adherent (identifier) : en cours
  // (pilote un vrai navigateur cote backend, plusieurs secondes) et
  // erreur eventuelle (ex: aucun ancien licencie correspondant trouve).
  const [pendingIdentifiers, setPendingIdentifiers] = useState(new Set())
  const [actionErrors, setActionErrors] = useState({})
  // Avertissements non bloquants renvoyes par le backend (ex: commune de
  // naissance de repli utilisee pour une fonction autre que pratiquant) :
  // la demande est bien enregistree, mais l'utilisateur doit le savoir.
  const [actionWarnings, setActionWarnings] = useState({})
  // Identifiant de l'adherent pour lequel le selecteur de role ("Autre
  // rôle") est ouvert (un seul a la fois) + role choisi dans ce selecteur,
  // valides seulement au clic sur "Valider" (jamais soumis directement).
  const [roleFormIdentifier, setRoleFormIdentifier] = useState(null)
  const [selectedFonction, setSelectedFonction] = useState('')

  // Rafraichit les 4 sources (adherents + les 3 listes FFST utilisees pour
  // la colonne Statut FFST) : sinon un changement fait a la main sur le
  // site FFST (ex: demande validee) resterait invisible tant qu'on ne
  // recharge pas toute la page.
  function refetchAll() {
    refetchMembers()
    refetchLicences()
    refetchValidatedDemandes()
    refetchDraftDemandes()
  }

  async function appelerFfst(identifier, method, path, body) {
    setPendingIdentifiers((prev) => new Set(prev).add(identifier))
    setActionErrors((prev) => ({ ...prev, [identifier]: null }))
    setActionWarnings((prev) => ({ ...prev, [identifier]: null }))
    try {
      const response = await fetch(`${API_URL}${path}`, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const responseBody = await response.json().catch(() => null)
      if (!response.ok) {
        throw new Error(responseBody?.detail || `Échec (${response.status})`)
      }
      if (responseBody?.warnings?.length) {
        setActionWarnings((prev) => ({ ...prev, [identifier]: responseBody.warnings.join(' ') }))
      }
      refetchDraftDemandes()
    } catch (err) {
      setActionErrors((prev) => ({ ...prev, [identifier]: err.message }))
    } finally {
      setPendingIdentifiers((prev) => {
        const next = new Set(prev)
        next.delete(identifier)
        return next
      })
    }
  }

  function creerDemande(member, identifier, fonction) {
    // gender/birthDate/etc. ne servent que si l'adherent n'a pas
    // d'ancienne licence renouvelable (chemin "nouvelle demande" cote
    // backend) : on les envoie systematiquement, au cas ou.
    const fields = member.customFields || {}
    appelerFfst(identifier, 'POST', '/ffst/demandes_renouvellement', {
      lastName: member.lastName,
      firstName: member.firstName,
      fonction,
      gender: fields['Genre(H/F)'],
      birthDate: fields['date de naissance'],
      addressLine1: fields['Adresse'],
      postalCode: fields['code postal'],
      city: fields['Ville'],
      phone: fields['Numéro de téléphone'],
      email: member.email,
    })
  }

  function supprimerDemande(member, identifier) {
    appelerFfst(identifier, 'DELETE', '/ffst/demandes_draft', {
      lastName: member.lastName,
      firstName: member.firstName,
    })
  }

  // Ouvre le selecteur de role pour un adherent (bouton "Autre rôle") :
  // pre-selectionne le premier role de la liste, valide seulement au clic
  // explicite sur "Valider" (jamais de soumission directe).
  function ouvrirChoixRole(identifier) {
    setRoleFormIdentifier(identifier)
    setSelectedFonction(fonctions?.[0] || '')
  }

  function annulerChoixRole() {
    setRoleFormIdentifier(null)
    setSelectedFonction('')
  }

  function validerChoixRole(member, identifier) {
    creerDemande(member, identifier, selectedFonction)
    setRoleFormIdentifier(null)
    setSelectedFonction('')
  }

  // Filtres façon WhatsApp (barre de recherche + puces d'age, voir
  // AGE_FILTERS) : recherche textuelle sur nom/prénom/email, + une puce
  // d'age (mutuellement exclusives entre elles, comme les puces
  // WhatsApp). S'appuient sur la date de naissance HelloAsso : un
  // adherent sans date de naissance exploitable n'apparait dans aucune
  // (mais reste visible dans "Tous").
  const [recherche, setRecherche] = useState('')
  const [filtreAge, setFiltreAge] = useState('tous')

  const membresVisibles = (members ?? []).filter((m) => {
    const filtre = AGE_FILTERS.find((f) => f.value === filtreAge)
    if (filtre?.test) {
      const birthDate = parserDateNaissance(m.customFields?.['date de naissance'])
      if (!birthDate || !filtre.test(calculerAge(birthDate))) return false
    }
    if (recherche.trim()) {
      const cible = normaliserTexte(`${m.lastName} ${m.firstName} ${m.email}`)
      if (!cible.includes(normaliserTexte(recherche))) return false
    }
    return true
  })

  return (
    <section>
      <div className="section-header">
        <h2>Adhérents ({members?.length ?? '…'})</h2>
        <button onClick={refetchAll}>Rafraîchir</button>
      </div>

      {error && <p className="error">{error}</p>}

      {members && (
        <>
          <div className="member-filters">
            <label className="member-search">
              <span aria-hidden="true">🔍</span>
              <input
                type="search"
                name="member-search"
                placeholder="Rechercher un adhérent..."
                value={recherche}
                onChange={(e) => setRecherche(e.target.value)}
              />
            </label>
            {/* Puces (pas un menu deroulant, essaye puis explicitement
                rejete) : toutes affichees sur une seule ligne, celles qui
                ne tiennent pas defilent horizontalement (voir
                overflow-x sur .filter-chips) plutot que de passer a la
                ligne. */}
            <div className="filter-chips" role="group" aria-label="Filtrer par âge">
              {AGE_FILTERS.map(({ value, label }) => (
                <button
                  key={value}
                  className={filtreAge === value ? 'filter-chip filter-chip-active' : 'filter-chip'}
                  aria-pressed={filtreAge === value}
                  onClick={() => setFiltreAge(value)}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {membresVisibles.length === 0 ? (
            <p className="empty-state">Aucun adhérent ne correspond à ces critères</p>
          ) : (
            <div className="table-wrapper">
              <table>
                <thead>
                  <tr>
                    <th>Nom</th>
                    <th>Prénom</th>
                    <th>Email</th>
                    <th>Montant</th>
                    <th>Code promo</th>
                    <th className="col-secondary">Ancienneté</th>
                    <th className="col-secondary">Statut HelloAsso</th>
                    <th>Statut FFST</th>
                    <th>Actions FFST</th>
                  </tr>
                </thead>
                <tbody>
                  {membresVisibles.map((m, i) => {
                    const identifier = memberIdentifier(m.lastName, m.firstName)
                    const pending = pendingIdentifiers.has(identifier)
                    const ffstStatus = licenceIdentifiers.has(identifier)
                      ? 'Licence créée'
                      : validatedIdentifiers.has(identifier)
                        ? 'Validée, à payer'
                        : draftIdentifiers.has(identifier)
                          ? 'Brouillon'
                          : 'Inconnu'
                    // L'historique liste le payeur (souvent un parent), pas
                    // l'adherent (ex: un mineur inscrit par lui) -- l'un peut
                    // avoir plusieurs saisons d'anciennete que l'autre n'a
                    // pas. On recherche donc l'identite du payeur, pas celle
                    // de l'adherent (repli sur celle-ci si le payeur n'a pas
                    // de nom, ex: tres vieilles commandes).
                    const payerIdentifier = memberIdentifier(
                      m.payerLastName || m.lastName,
                      m.payerFirstName || m.firstName
                    )
                    const seniority = anciennete(historyByIdentifier.get(payerIdentifier), currentSeason)
                    const promoError = history ? promoCodeError(m.promoCode, seniority) : null
                    return (
                      <tr key={i}>
                        <td>{m.lastName}</td>
                        <td>{m.firstName}</td>
                        <td>{m.email}</td>
                        <td>{euros(m.amount)}</td>
                        <td className={promoError ? 'promo-code-error' : undefined}>
                          {m.promoCode || '—'}
                          {promoError && (
                            <span className="promo-code-warning" title={promoError}>
                              {' '}
                              ⚠️ {seniority} saison{seniority > 1 ? 's' : ''}
                            </span>
                          )}
                        </td>
                        <td className="col-secondary">{history ? `${seniority} saison${seniority > 1 ? 's' : ''}` : '…'}</td>
                        <td className="col-secondary">{m.state}</td>
                        <td>{ffstDataLoaded ? ffstStatus : '…'}</td>
                        <td>
                          {ffstDataLoaded && (
                            <>
                              {ffstStatus === 'Inconnu' && (
                                <>
                                  <button
                                    onClick={() => creerDemande(m, identifier, '005-PRATIQUANT')}
                                    disabled={pending}
                                  >
                                    {pending ? <LoadingLabel text="Envoi en cours" /> : 'Faire la demande Pratiquant'}
                                  </button>
                                  {roleFormIdentifier === identifier ? (
                                    <span className="ffst-role-picker">
                                      <select
                                        value={selectedFonction}
                                        onChange={(e) => setSelectedFonction(e.target.value)}
                                        disabled={pending}
                                      >
                                        {(fonctions || []).map((f) => (
                                          <option key={f} value={f}>
                                            {f}
                                          </option>
                                        ))}
                                      </select>
                                      <button
                                        onClick={() => validerChoixRole(m, identifier)}
                                        disabled={pending || !selectedFonction}
                                      >
                                        Valider
                                      </button>
                                      <button onClick={annulerChoixRole} disabled={pending}>
                                        Annuler
                                      </button>
                                    </span>
                                  ) : (
                                    <button onClick={() => ouvrirChoixRole(identifier)} disabled={pending}>
                                      Faire la demande Autre rôle
                                    </button>
                                  )}
                                </>
                              )}
                              {ffstStatus === 'Brouillon' && (
                                <button onClick={() => supprimerDemande(m, identifier)} disabled={pending}>
                                  {pending ? <LoadingLabel text="Suppression en cours" /> : 'Supprimer la demande'}
                                </button>
                              )}
                              {pending && (
                                <p className="pending-hint">
                                  ⏳ Le portail FFST est piloté automatiquement (vrai navigateur) : ça peut prendre
                                  jusqu'à 30 secondes, merci de patienter sans recharger la page.
                                </p>
                              )}
                              {actionErrors[identifier] && <p className="error">{actionErrors[identifier]}</p>}
                              {actionWarnings[identifier] && <p className="warning">{actionWarnings[identifier]}</p>}
                            </>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  )
}

export function UnpaidTable() {
  const { data: unpaid, error, refetch } = useHelloAssoFetch('/helloasso/unpaid')

  return (
    <section>
      <div className="section-header">
        <h2>Impayés HelloAsso ({unpaid?.length ?? '…'})</h2>
        <button onClick={refetch}>Rafraîchir</button>
      </div>

      {error && <p className="error">{error}</p>}

      {unpaid && (unpaid.length === 0 ? (
        <p className="empty-state">Aucun impayé 🎉</p>
      ) : (
        <div className="table-wrapper">
          <table>
            <thead>
              <tr>
                <th>Nom</th>
                <th>Prénom</th>
                <th>Email</th>
                <th className="col-secondary">Total</th>
                <th>Impayé</th>
                <th className="col-secondary">Échéances refusées</th>
              </tr>
            </thead>
            <tbody>
              {unpaid.map((m, i) => (
                <tr key={i}>
                  <td>{m.lastName}</td>
                  <td>{m.firstName}</td>
                  <td>{m.email}</td>
                  <td className="col-secondary">{euros(m.totalAmount)}</td>
                  <td className="unpaid-amount">{euros(m.unpaidAmount)}</td>
                  <td className="col-secondary">
                    {m.refusedPayments.map((p) => (p.date || '').slice(0, 10)).join(', ')}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </section>
  )
}

export function MembersHistoryTable() {
  const { data: history, error, refetch } = useHelloAssoFetch('/members_history')

  return (
    <section>
      <div className="section-header">
        <h2>
          Historique des adhérents HelloAsso ({history?.length ?? '…'}) (/!\ liste provisoire, peut contenir des
          erreurs)
        </h2>
        <button onClick={refetch}>Rafraîchir</button>
      </div>

      {error && <p className="error">{error}</p>}

      {history && (
        <div className="table-wrapper">
          <table>
            <thead>
              <tr>
                <th>Nom payeur</th>
                <th>Prénom payeur</th>
                <th>Nb saisons</th>
                <th>Saisons</th>
              </tr>
            </thead>
            <tbody>
              {history.map((m, i) => (
                <tr key={i}>
                  <td>{m.lastName}</td>
                  <td>{m.firstName}</td>
                  <td>{m.campaignCount}</td>
                  <td className="campaigns-cell">
                    {m.campaigns.map((c) => (
                      <span key={c} className="campaign-tag">
                        {c}
                      </span>
                    ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

export function CampaignTitle() {
  // Nom du club plutot que le titre (variable d'une saison a l'autre) du
  // formulaire d'adhesion HelloAsso : plus de fetch necessaire ici. Logo
  // recupere manuellement depuis le tableau de bord HelloAsso du club
  // (pas accessible via l'API, page admin necessitant une connexion).
  return (
    <h1 className="campaign-title">
      <img src={clubLogo} alt="" className="club-logo" />
      Alliance Sambo Combat La Ciotat
    </h1>
  )
}
