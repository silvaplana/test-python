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

export function MembersTable() {
  const { data: members, error, refetch: refetchMembers } = useHelloAssoFetch('/helloasso/members')
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

  return (
    <section>
      <div className="section-header">
        <h2>Adhérents HelloAsso ({members?.length ?? '…'})</h2>
        <button onClick={refetchAll}>Rafraîchir</button>
      </div>

      {error && <p className="error">{error}</p>}

      {members && (
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
              {members.map((m, i) => {
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
