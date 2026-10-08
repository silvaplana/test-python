import { useCallback, useEffect, useRef, useState } from 'react'
import { showToast } from './Toast.jsx'

// Onglet Messagerie > Mail : la boite Gmail de l'association (adresse
// CONTACT_ASSOCIATION), lue et envoyee par le backend (/webmail/..., voir
// backend/src/webmail). Liste a gauche, message a droite sur grand ecran ;
// sur telephone, l'un puis l'autre.

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

async function callApi(path, options) {
  const response = await fetch(`${API_URL}${path}`, { credentials: 'include', ...options })
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(body?.detail || `Échec (${response.status})`)
  return body
}

function jsonOptions(method, body) {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
}

// Pastille des non lus (onglets Messagerie et Mail) : une seule releve pour
// toutes les pastilles, toutes les 2 minutes, et aussitot apres une lecture
// dans l'ecran (notifyUnreadChanged).
const unread = { count: 0, listeners: new Set(), timer: null }

function refreshUnread() {
  if (document.hidden) return
  callApi('/webmail/unread')
    .then((body) => {
      unread.count = body.unread
      unread.listeners.forEach((listener) => listener(body.unread))
    })
    .catch(() => {})
}

function notifyUnreadChanged() {
  refreshUnread()
}

function subscribeUnread(listener) {
  unread.listeners.add(listener)
  if (unread.listeners.size === 1) {
    refreshUnread()
    unread.timer = setInterval(refreshUnread, 120000)
    document.addEventListener('visibilitychange', refreshUnread)
  }
  return () => {
    unread.listeners.delete(listener)
    if (unread.listeners.size === 0) {
      clearInterval(unread.timer)
      document.removeEventListener('visibilitychange', refreshUnread)
    }
  }
}

export function MailUnreadBadge() {
  const [count, setCount] = useState(unread.count)
  useEffect(() => subscribeUnread(setCount), [])
  if (!count) return null
  return <span className="nav-badge">{count}</span>
}

// --- Mise en forme ----------------------------------------------------------

function formatListDate(iso) {
  if (!iso) return ''
  const date = new Date(iso)
  const now = new Date()
  if (date.toDateString() === now.toDateString()) {
    return date.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
  }
  if (date.getFullYear() === now.getFullYear()) {
    return date.toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' })
  }
  return date.toLocaleDateString('fr-FR')
}

function formatFullDate(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleString('fr-FR', {
    weekday: 'short',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatSize(bytes) {
  if (bytes == null) return ''
  if (bytes < 1024) return `${bytes} o`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} Ko`
  return `${(bytes / 1024 / 1024).toFixed(1).replace('.', ',')} Mo`
}

function personLabel(person) {
  return person ? person.name || person.address : ''
}

// Adresse prete pour un champ "A" : "Nom" <adresse>.
function addressField(person) {
  if (!person.name) return person.address
  return `"${person.name.replaceAll('"', '')}" <${person.address}>`
}

// Adresse affichee dans un en-tete : Nom <adresse>.
function addressLabel(person) {
  return person.name ? `${person.name} <${person.address}>` : person.address
}

function quoteText(text) {
  return (text || '')
    .replace(/\s+$/, '')
    .split('\n')
    .map((line) => `> ${line}`)
    .join('\n')
}

function withPrefix(prefix, subject) {
  const clean = subject || ''
  return new RegExp(`^${prefix}\\s*:`, 'i').test(clean) ? clean : `${prefix}: ${clean}`
}

// Brouillon d'une reponse, d'une reponse a tous ou d'un transfert.
function draftFrom(mode, message, ownAddress) {
  const own = (ownAddress || '').toLowerCase()
  const isOwn = (person) => person.address.toLowerCase() === own
  const sender = message.replyTo?.[0] || message.from?.[0]
  const fromMe = message.from?.some(isOwn)
  const who = sender ? addressField(sender) : 'Quelqu’un'
  const header = message.date ? `Le ${formatFullDate(message.date)}, ${who} a écrit :` : `${who} a écrit :`
  if (mode === 'forward') {
    const lines = [
      '',
      '',
      '---------- Message transféré ----------',
      `De : ${(message.from || []).map(addressField).join(', ')}`,
      `Date : ${formatFullDate(message.date)}`,
      `Objet : ${message.subject || ''}`,
      `À : ${(message.to || []).map(addressField).join(', ')}`,
      ...(message.cc?.length ? [`Cc : ${message.cc.map(addressField).join(', ')}`] : []),
      '',
      message.text || '',
    ]
    return {
      mode,
      to: '',
      cc: '',
      subject: withPrefix('Fwd', message.subject),
      body: lines.join('\n'),
      forward: { folder: message.folder, uid: message.uid },
      forwardAttachments: message.attachments || [],
    }
  }
  // Repondre a un mail envoye par l'association : on ecrit a ses
  // destinataires, pas a soi-meme.
  const main = fromMe ? message.to || [] : sender ? [sender] : []
  let cc = []
  if (mode === 'replyAll') {
    const seen = new Set(main.map((person) => person.address.toLowerCase()))
    cc = [...(fromMe ? [] : message.to || []), ...(message.cc || [])].filter((person) => {
      const key = person.address.toLowerCase()
      if (key === own || seen.has(key)) return false
      seen.add(key)
      return true
    })
  }
  return {
    mode,
    to: main.map(addressField).join(', '),
    cc: cc.map(addressField).join(', '),
    subject: withPrefix('Re', message.subject),
    body: `\n\n${header}\n${quoteText(message.text)}`,
    inReplyTo: message.messageId,
    references: message.references,
    answered: { folder: message.folder, uid: message.uid },
  }
}

// Hauteur des volets : jusqu'en bas de l'ecran (barre du bas comprise sur
// telephone), chacun avec sa propre barre de defilement.
function useFillHeight(dependency) {
  const ref = useRef(null)
  useEffect(() => {
    function fit() {
      const el = ref.current
      if (!el) return
      const top = el.getBoundingClientRect().top + window.scrollY
      const bottomNav = document.querySelector('.bottom-nav')
      const reserved = (bottomNav && getComputedStyle(bottomNav).display !== 'none' ? bottomNav.offsetHeight : 0) + 16
      el.style.height = `${Math.max(360, window.innerHeight - top - reserved)}px`
    }
    fit()
    window.addEventListener('resize', fit)
    return () => window.removeEventListener('resize', fit)
  }, [dependency])
  return ref
}

// --- Ecran ------------------------------------------------------------------

export function Webmail({ active }) {
  const [settings, setSettings] = useState(null)
  const [folders, setFolders] = useState([])
  const [folder, setFolder] = useState('inbox')
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('')
  const [list, setList] = useState(null)
  const [listError, setListError] = useState(null)
  const [loading, setLoading] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [selected, setSelected] = useState(null)
  const [draft, setDraft] = useState(null)
  const panes = useFillHeight(settings?.configured && active)

  useEffect(() => {
    callApi('/webmail/settings')
      .then(setSettings)
      .catch((err) => setSettings({ configured: false, error: err.message }))
  }, [])

  useEffect(() => {
    if (!settings?.configured) return
    callApi('/webmail/folders')
      .then((body) => setFolders(body.folders))
      .catch(() => {})
  }, [settings])

  const loadList = useCallback(
    async ({ silent = false } = {}) => {
      if (!silent) setLoading(true)
      try {
        const params = new URLSearchParams({ folder })
        if (query) params.set('q', query)
        const body = await callApi(`/webmail/messages?${params}`)
        setList((current) => {
          // Rafraichissement en fond : on garde les pages plus anciennes deja chargees.
          if (silent && current && current.folder === folder && current.query === query && current.messages.length > body.messages.length) {
            const oldest = body.messages.at(-1)?.uid ?? Infinity
            return { ...current, messages: [...body.messages, ...current.messages.filter((m) => m.uid < oldest)] }
          }
          return { ...body, query }
        })
        setListError(null)
      } catch (err) {
        if (!silent) setListError(err.message)
      } finally {
        if (!silent) setLoading(false)
      }
    },
    [folder, query],
  )

  useEffect(() => {
    if (!settings?.configured) return
    loadList()
  }, [settings, loadList])

  // Nouveaux mails : liste relue chaque minute tant que l'onglet est affiche.
  useEffect(() => {
    if (!settings?.configured || !active) return
    const timer = setInterval(() => {
      if (!document.hidden) loadList({ silent: true })
    }, 60000)
    return () => clearInterval(timer)
  }, [settings, active, loadList])

  async function loadMore() {
    if (!list?.messages.length) return
    setLoadingMore(true)
    try {
      const params = new URLSearchParams({ folder, before: list.messages.at(-1).uid })
      if (query) params.set('q', query)
      const body = await callApi(`/webmail/messages?${params}`)
      setList((current) => ({ ...current, messages: [...current.messages, ...body.messages], hasMore: body.hasMore }))
    } catch (err) {
      showToast(err.message, 'error')
    } finally {
      setLoadingMore(false)
    }
  }

  function chooseFolder(key) {
    setFolder(key)
    setSelected(null)
    setSearch('')
    setQuery('')
    setList(null)
  }

  function submitSearch(event) {
    event.preventDefault()
    setSelected(null)
    setQuery(search.trim())
  }

  function patchMessage(uid, changes) {
    setList((current) =>
      current ? { ...current, messages: current.messages.map((m) => (m.uid === uid ? { ...m, ...changes } : m)) } : current,
    )
  }

  function removeMessage(uid) {
    setList((current) => (current ? { ...current, messages: current.messages.filter((m) => m.uid !== uid) } : current))
    setSelected(null)
    notifyUnreadChanged()
  }

  async function toggleStar(message, event) {
    event?.stopPropagation()
    const starred = !message.starred
    patchMessage(message.uid, { starred })
    try {
      await callApi(`/webmail/messages/${folder}/${message.uid}/flags`, jsonOptions('PUT', { starred }))
      if (folder === 'starred' && !starred) removeMessage(message.uid)
    } catch (err) {
      patchMessage(message.uid, { starred: !starred })
      showToast(err.message, 'error')
    }
  }

  if (!settings) return <p>Chargement…</p>
  if (!settings.configured) {
    return (
      <section className="webmail-setup">
        <h2>Mail</h2>
        {settings.error ? (
          <p className="error">{settings.error}</p>
        ) : (
          <>
            <p>
              La boîte <strong>{settings.address || "de l'association"}</strong> n'est pas encore branchée.
            </p>
            <p className="reports-hint">
              Il faut un mot de passe d'application Google (compte avec validation en deux étapes), à mettre dans
              WEBMAIL_APP_PASSWORD du fichier .env du serveur.
            </p>
          </>
        )}
      </section>
    )
  }

  const folderLabel = folders.find((f) => f.key === folder)?.label || 'Boîte de réception'
  const showRecipients = folder === 'sent' || folder === 'drafts'

  return (
    <section className={`webmail${selected ? ' webmail-reading' : ''}`}>
      <div className="webmail-toolbar">
        <button type="button" className="webmail-compose-button" onClick={() => setDraft({ mode: 'new', to: '', cc: '', subject: '', body: '' })}>
          <PenIcon /> Nouveau message
        </button>
        <select className="webmail-folder-select" value={folder} onChange={(e) => chooseFolder(e.target.value)} aria-label="Dossier">
          {(folders.length ? folders : [{ key: 'inbox', label: 'Boîte de réception' }]).map((f) => (
            <option key={f.key} value={f.key}>
              {f.label}
            </option>
          ))}
        </select>
        <form className="webmail-search" onSubmit={submitSearch} role="search">
          <input
            type="search"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value)
              if (!e.target.value && query) setQuery('')
            }}
            placeholder="Rechercher dans les mails"
            aria-label="Rechercher dans les mails"
          />
        </form>
        <button type="button" className="webmail-icon-button" onClick={() => loadList()} title="Actualiser" aria-label="Actualiser" disabled={loading}>
          <RefreshIcon />
        </button>
      </div>
      {/* Rappel de la recherche en cours (l'adresse de la boite n'est pas affichee). */}
      {query ? (
        <p className="webmail-address">
          Recherche « {query} » dans {folderLabel}
        </p>
      ) : (
        <div className="webmail-toolbar-gap" />
      )}

      <div className="webmail-panes" ref={panes}>
        <div className="webmail-list">
          {listError && <p className="error webmail-list-note">{listError}</p>}
          {!list && !listError && <p className="webmail-list-note">Chargement…</p>}
          {list && list.messages.length === 0 && (
            <p className="webmail-list-note">{query ? 'Aucun mail trouvé.' : 'Aucun mail dans ce dossier.'}</p>
          )}
          {list?.messages.map((message) => (
            <div
              key={message.uid}
              role="button"
              tabIndex={0}
              className={[
                'webmail-row',
                message.seen ? '' : 'webmail-row-unread',
                selected?.uid === message.uid ? 'webmail-row-selected' : '',
              ].join(' ')}
              onClick={() => {
                setSelected({ folder, uid: message.uid })
                if (!message.seen) patchMessage(message.uid, { seen: true })
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter') e.currentTarget.click()
              }}
            >
              <button
                type="button"
                className={`webmail-star${message.starred ? ' webmail-star-on' : ''}`}
                onClick={(e) => toggleStar(message, e)}
                title={message.starred ? 'Ne plus suivre' : 'Suivre'}
                aria-label={message.starred ? 'Ne plus suivre' : 'Suivre'}
              >
                <StarIcon filled={message.starred} />
              </button>
              <div className="webmail-row-main">
                <div className="webmail-row-top">
                  <span className="webmail-row-from">
                    {showRecipients
                      ? `À : ${message.to.map(personLabel).join(', ') || '(personne)'}`
                      : message.from.map(personLabel).join(', ') || '(inconnu)'}
                  </span>
                  {message.hasAttachments && <ClipIcon />}
                  <span className="webmail-row-date">{formatListDate(message.date)}</span>
                </div>
                <div className="webmail-row-subject">{message.subject || '(sans objet)'}</div>
                <div className="webmail-row-snippet">{message.snippet}</div>
              </div>
            </div>
          ))}
          {list?.hasMore && (
            <button type="button" className="webmail-more" onClick={loadMore} disabled={loadingMore}>
              {loadingMore ? 'Chargement…' : 'Messages plus anciens'}
            </button>
          )}
        </div>

        <div className="webmail-reader">
          {selected ? (
            <MessageView
              key={`${selected.folder}-${selected.uid}`}
              folder={selected.folder}
              uid={selected.uid}
              folders={folders}
              ownAddress={settings.address}
              onBack={() => setSelected(null)}
              onDraft={setDraft}
              onRemoved={removeMessage}
              onFlags={(changes) => patchMessage(selected.uid, changes)}
              onLoaded={notifyUnreadChanged}
            />
          ) : (
            <div className="webmail-empty">
              <MailOpenIcon />
              <p>Choisis un mail dans la liste.</p>
            </div>
          )}
        </div>
      </div>

      {draft && (
        <ComposeDialog
          draft={draft}
          from={settings.address}
          onClose={() => setDraft(null)}
          onSent={() => {
            setDraft(null)
            if (folder === 'sent') loadList({ silent: true })
            if (draft.answered && draft.answered.folder === folder) patchMessage(draft.answered.uid, { answered: true })
          }}
        />
      )}
    </section>
  )
}

// --- Lecture d'un mail ------------------------------------------------------

function MessageView({ folder, uid, folders, ownAddress, onBack, onDraft, onRemoved, onFlags, onLoaded }) {
  const [message, setMessage] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    callApi(`/webmail/messages/${folder}/${uid}`)
      .then((body) => {
        setMessage(body)
        onLoaded()
      })
      .catch((err) => setError(err.message))
    // onLoaded change a chaque rendu du parent : seul le message compte.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [folder, uid])

  async function setFlags(changes) {
    setBusy(true)
    try {
      await callApi(`/webmail/messages/${folder}/${uid}/flags`, jsonOptions('PUT', changes))
      setMessage((current) => ({ ...current, ...changes }))
      onFlags(changes)
      if (changes.seen === false) {
        onLoaded()
        onBack()
      }
    } catch (err) {
      showToast(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  async function move(to, done) {
    setBusy(true)
    try {
      await callApi(`/webmail/messages/${folder}/${uid}/move`, jsonOptions('POST', { to }))
      showToast(done, 'success')
      onRemoved(uid)
    } catch (err) {
      showToast(err.message, 'error')
      setBusy(false)
    }
  }

  async function destroy() {
    if (!window.confirm('Supprimer définitivement ce mail ? Il ne pourra pas être récupéré.')) return
    setBusy(true)
    try {
      await callApi(`/webmail/messages/${folder}/${uid}`, { method: 'DELETE' })
      showToast('Mail supprimé définitivement', 'success')
      onRemoved(uid)
    } catch (err) {
      showToast(err.message, 'error')
      setBusy(false)
    }
  }

  async function download(attachment) {
    try {
      const response = await fetch(`${API_URL}/webmail/messages/${folder}/${uid}/attachments/${attachment.index}`, {
        credentials: 'include',
      })
      if (!response.ok) {
        const body = await response.json().catch(() => null)
        throw new Error(body?.detail || `Échec (${response.status})`)
      }
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = attachment.filename
      link.click()
      setTimeout(() => URL.revokeObjectURL(url), 10000)
    } catch (err) {
      showToast(err.message, 'error')
    }
  }

  const has = (key) => folders.some((f) => f.key === key)

  return (
    <article className="webmail-message">
      {/* Telephone : "Retour" reste en haut du mail pendant qu'on le fait defiler. */}
      <div className="webmail-back-bar">
        <button type="button" className="webmail-back" onClick={onBack}>
          ← Retour
        </button>
      </div>
      <div className="webmail-message-actions">
        {message && (
          <>
            <button type="button" onClick={() => onDraft(draftFrom('reply', message, ownAddress))} disabled={busy}>
              Répondre
            </button>
            <button type="button" onClick={() => onDraft(draftFrom('replyAll', message, ownAddress))} disabled={busy}>
              Répondre à tous
            </button>
            <button type="button" onClick={() => onDraft(draftFrom('forward', message, ownAddress))} disabled={busy}>
              Transférer
            </button>
            <span className="webmail-actions-gap" />
            <button type="button" onClick={() => setFlags({ starred: !message.starred })} disabled={busy}>
              {message.starred ? '★ Suivi' : '☆ Suivre'}
            </button>
            <button type="button" onClick={() => setFlags({ seen: false })} disabled={busy}>
              Non lu
            </button>
            {folder === 'inbox' && has('all') && (
              <button type="button" onClick={() => move('archive', 'Mail archivé')} disabled={busy}>
                Archiver
              </button>
            )}
            {folder !== 'trash' && folder !== 'spam' && has('spam') && folder !== 'sent' && (
              <button type="button" onClick={() => move('spam', 'Mail mis dans le spam')} disabled={busy}>
                Spam
              </button>
            )}
            {(folder === 'trash' || folder === 'spam') && (
              <button type="button" onClick={() => move('inbox', 'Mail remis dans la boîte de réception')} disabled={busy}>
                {folder === 'spam' ? 'Pas un spam' : 'Restaurer'}
              </button>
            )}
            {folder === 'trash' || folder === 'spam' ? (
              <button type="button" className="webmail-danger" onClick={destroy} disabled={busy}>
                Supprimer définitivement
              </button>
            ) : (
              has('trash') && (
                <button type="button" className="webmail-danger" onClick={() => move('trash', 'Mail mis à la corbeille')} disabled={busy}>
                  Corbeille
                </button>
              )
            )}
          </>
        )}
      </div>

      {error && <p className="error">{error}</p>}
      {!message && !error && <p>Chargement…</p>}
      {message && (
        <>
          <h3 className="webmail-message-subject">{message.subject || '(sans objet)'}</h3>
          <div className="webmail-message-headers">
            <div>
              <strong>{message.from.map(personLabel).join(', ')}</strong>
              {message.from[0]?.name && <span className="webmail-address-small"> &lt;{message.from[0].address}&gt;</span>}
            </div>
            <div className="webmail-message-meta">
              À : {message.to.map(addressLabel).join(', ') || '—'}
              {message.cc.length > 0 && <> · Cc : {message.cc.map(addressLabel).join(', ')}</>}
            </div>
            <div className="webmail-message-meta">{formatFullDate(message.date)}</div>
          </div>
          {message.html ? <HtmlBody html={message.html} /> : <pre className="webmail-text">{message.text}</pre>}
          {message.attachments.length > 0 && (
            <div className="webmail-attachments">
              {message.attachments.map((attachment) => (
                <button type="button" key={attachment.index} className="webmail-attachment" onClick={() => download(attachment)}>
                  <ClipIcon />
                  <span className="webmail-attachment-name">{attachment.filename}</span>
                  <span className="webmail-attachment-size">{formatSize(attachment.size)}</span>
                </button>
              ))}
            </div>
          )}
          <div className="webmail-message-footer">
            <button type="button" onClick={() => onDraft(draftFrom('reply', message, ownAddress))}>
              Répondre
            </button>
            <button type="button" onClick={() => onDraft(draftFrom('forward', message, ownAddress))}>
              Transférer
            </button>
          </div>
        </>
      )}
    </article>
  )
}

// Corps HTML dans un cadre isole : aucun script (sandbox sans allow-scripts),
// liens ouverts dans un nouvel onglet. allow-same-origin sert seulement a
// mesurer la hauteur du contenu depuis l'appli (sans scripts, le mail ne
// peut rien en faire).
//
// Fond sombre, comme le reste de l'appli : les mails sont ecrits pour un fond
// clair, donc leurs couleurs sont inversees (clair <-> sombre, teintes
// gardees) et les images remises a l'endroit. "Fond clair" montre le mail tel
// qu'il a ete ecrit, pour ceux que l'inversion rendrait mal ; le choix est
// retenu sur l'appareil.
const LIGHT_MAIL_KEY = 'webmail-light-mails'
const BASE_STYLE =
  'html,body{margin:0}body{font:14px/1.5 Arial,Helvetica,sans-serif;overflow-wrap:anywhere}img{max-width:100%;height:auto}table{max-width:100%}'
// Fond clair : une marge, pour que le texte ne colle pas au bord du cadre blanc.
const LIGHT_STYLE = 'html,body{background:#fff;color:#202124}body{padding:16px}'
// #e7e8f0 inverse puis tourne de 180 degres donne le fond de l'appli (#16171d).
const DARK_STYLE =
  'html{background:#16171d}body{background:#e7e8f0;color:#202124;filter:invert(1) hue-rotate(180deg)}img,video,picture,svg{filter:invert(1) hue-rotate(180deg)}picture img{filter:none}'

function readLightMails() {
  try {
    return localStorage.getItem(LIGHT_MAIL_KEY) === '1'
  } catch {
    return false
  }
}

function HtmlBody({ html }) {
  const frame = useRef(null)
  const [light, setLight] = useState(readLightMails)
  const document_ = `<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data: https: http:; style-src 'unsafe-inline' https:; font-src https: data:">
<base target="_blank">
<style>${BASE_STYLE}${light ? LIGHT_STYLE : DARK_STYLE}</style>
</head><body>${html}</body></html>`

  function fit() {
    const el = frame.current
    const body = el?.contentDocument?.body
    if (!body) return
    // Hauteur du contenu lui-meme (pas celle du cadre, qui ne retrecit jamais).
    el.style.height = `${Math.max(body.offsetHeight, body.scrollHeight) + 4}px`
  }

  useEffect(() => {
    // Images chargees apres coup : la hauteur change.
    const timers = [400, 1500, 4000].map((delay) => setTimeout(fit, delay))
    return () => timers.forEach(clearTimeout)
  }, [html, light])

  function toggle() {
    const next = !light
    setLight(next)
    try {
      localStorage.setItem(LIGHT_MAIL_KEY, next ? '1' : '0')
    } catch {
      // Stockage indisponible : le choix vaut pour ce mail seulement.
    }
  }

  return (
    <div className="webmail-html-wrap">
      <button type="button" className="webmail-link webmail-html-toggle" onClick={toggle}>
        {light ? 'Fond sombre' : 'Fond clair'}
      </button>
      <iframe
        ref={frame}
        className={`webmail-html${light ? ' webmail-html-light' : ''}`}
        title="Contenu du mail"
        sandbox="allow-same-origin allow-popups allow-popups-to-escape-sandbox"
        srcDoc={document_}
        onLoad={fit}
      />
    </div>
  )
}

// --- Nouveau message, reponse, transfert ----------------------------------

function ComposeDialog({ draft, from, onClose, onSent }) {
  const dialogRef = useRef(null)
  const [to, setTo] = useState(draft.to)
  const [cc, setCc] = useState(draft.cc)
  const [bcc, setBcc] = useState('')
  const [showCopies, setShowCopies] = useState(Boolean(draft.cc))
  const [subject, setSubject] = useState(draft.subject)
  const [body, setBody] = useState(draft.body)
  const [files, setFiles] = useState([])
  const [sending, setSending] = useState(false)
  const [error, setError] = useState(null)
  const bodyRef = useRef(null)

  useEffect(() => {
    dialogRef.current.showModal()
    // Reponse : curseur tout en haut, au-dessus du message cite.
    if (draft.mode !== 'new' && draft.mode !== 'forward') {
      bodyRef.current?.focus()
      bodyRef.current?.setSelectionRange(0, 0)
    }
  }, [draft.mode])

  const titles = { new: 'Nouveau message', reply: 'Répondre', replyAll: 'Répondre à tous', forward: 'Transférer' }
  const total = files.reduce((sum, file) => sum + file.size, 0)

  async function send(event) {
    event.preventDefault()
    setError(null)
    if (!to.trim() && !cc.trim()) {
      setError('Indique au moins un destinataire')
      return
    }
    if (!subject.trim() && !window.confirm('Envoyer ce mail sans objet ?')) return
    setSending(true)
    try {
      const form = new FormData()
      form.set('to', to)
      form.set('cc', cc)
      form.set('bcc', bcc)
      form.set('subject', subject)
      form.set('body', body)
      if (draft.inReplyTo) form.set('inReplyTo', draft.inReplyTo)
      if (draft.references) form.set('references', draft.references)
      if (draft.answered) {
        form.set('answeredFolder', draft.answered.folder)
        form.set('answeredUid', draft.answered.uid)
      }
      if (draft.forward) {
        form.set('forwardFolder', draft.forward.folder)
        form.set('forwardUid', draft.forward.uid)
      }
      files.forEach((file) => form.append('files', file))
      await callApi('/webmail/send', { method: 'POST', body: form })
      showToast('Mail envoyé', 'success')
      onSent()
    } catch (err) {
      setError(err.message)
      setSending(false)
    }
  }

  return (
    <dialog ref={dialogRef} className="trial-dialog webmail-compose" onClose={onClose} onCancel={(e) => sending && e.preventDefault()}>
      <div className="trial-scan-header">
        <h3>{titles[draft.mode]}</h3>
        <button
          type="button"
          className="trial-scan-close"
          onClick={() => dialogRef.current.close()}
          disabled={sending}
          aria-label="Fermer"
          title="Fermer"
        >
          ✕
        </button>
      </div>
      <form onSubmit={send} className="webmail-compose-form">
        <div className="webmail-compose-line">
          <span>De</span>
          <span className="webmail-compose-from">{from}</span>
        </div>
        <label className="webmail-compose-line">
          <span>À</span>
          <input value={to} onChange={(e) => setTo(e.target.value)} placeholder="adresse@exemple.fr, autre@exemple.fr" autoFocus={draft.mode === 'new' || draft.mode === 'forward'} />
          {!showCopies && (
            <button type="button" className="webmail-link" onClick={() => setShowCopies(true)}>
              Cc / Cci
            </button>
          )}
        </label>
        {showCopies && (
          <>
            <label className="webmail-compose-line">
              <span>Cc</span>
              <input value={cc} onChange={(e) => setCc(e.target.value)} />
            </label>
            <label className="webmail-compose-line">
              <span>Cci</span>
              <input value={bcc} onChange={(e) => setBcc(e.target.value)} />
            </label>
          </>
        )}
        <label className="webmail-compose-line">
          <span>Objet</span>
          <input value={subject} onChange={(e) => setSubject(e.target.value)} />
        </label>
        <textarea ref={bodyRef} className="webmail-compose-body" value={body} onChange={(e) => setBody(e.target.value)} rows={12} />

        {(draft.forwardAttachments?.length > 0 || files.length > 0) && (
          <div className="webmail-attachments">
            {draft.forwardAttachments?.map((attachment) => (
              <span key={`f${attachment.index}`} className="webmail-attachment" title="Pièce jointe du mail transféré">
                <ClipIcon />
                <span className="webmail-attachment-name">{attachment.filename}</span>
                <span className="webmail-attachment-size">{formatSize(attachment.size)}</span>
              </span>
            ))}
            {files.map((file, i) => (
              <span key={`${file.name}-${i}`} className="webmail-attachment">
                <ClipIcon />
                <span className="webmail-attachment-name">{file.name}</span>
                <span className="webmail-attachment-size">{formatSize(file.size)}</span>
                <button
                  type="button"
                  className="webmail-attachment-remove"
                  onClick={() => setFiles((current) => current.filter((_, j) => j !== i))}
                  aria-label={`Retirer ${file.name}`}
                  title="Retirer"
                >
                  ✕
                </button>
              </span>
            ))}
          </div>
        )}
        {total > 18 * 1024 * 1024 && <p className="warning">Pièces jointes trop lourdes : 18 Mo au total au maximum.</p>}
        {error && <p className="error">{error}</p>}

        <div className="trial-dialog-actions webmail-compose-actions">
          <label className="webmail-attach-button">
            <ClipIcon /> Joindre
            <input
              type="file"
              multiple
              onChange={(e) => {
                const picked = [...e.target.files]
                setFiles((current) => [...current, ...picked])
                e.target.value = ''
              }}
            />
          </label>
          <button type="submit" className="trial-save" disabled={sending || total > 18 * 1024 * 1024}>
            {sending ? 'Envoi…' : 'Envoyer'}
          </button>
        </div>
      </form>
    </dialog>
  )
}

// --- Icones (traits Lucide, licence ISC) -----------------------------------

function Icon({ children, className = 'webmail-icon' }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {children}
    </svg>
  )
}

function StarIcon({ filled }) {
  return (
    <svg className="webmail-icon" viewBox="0 0 24 24" fill={filled ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="2" strokeLinejoin="round" aria-hidden="true">
      <path d="M11.5 2.3a.5.5 0 0 1 1 0l2.3 4.7a2 2 0 0 0 1.6 1.1l5.2.8a.5.5 0 0 1 .3.9l-3.8 3.7a2 2 0 0 0-.6 1.9l.9 5.2a.5.5 0 0 1-.8.5l-4.6-2.5a2 2 0 0 0-1.9 0l-4.6 2.5a.5.5 0 0 1-.8-.5l.9-5.2a2 2 0 0 0-.6-1.9L2.2 9.8a.5.5 0 0 1 .3-.9l5.2-.8a2 2 0 0 0 1.6-1.1z" />
    </svg>
  )
}

function ClipIcon() {
  return (
    <Icon>
      <path d="m21.4 11.1-9.2 9.2a6 6 0 0 1-8.5-8.5l8.6-8.6a4 4 0 0 1 5.7 5.7l-8.6 8.6a2 2 0 0 1-2.9-2.9l8.5-8.5" />
    </Icon>
  )
}

function PenIcon() {
  return (
    <Icon>
      <path d="M12 20h9" />
      <path d="M16.4 3.6a2.1 2.1 0 1 1 3 3L7 19l-4 1 1-4Z" />
    </Icon>
  )
}

function RefreshIcon() {
  return (
    <Icon>
      <path d="M3 12a9 9 0 0 1 9-9 9.8 9.8 0 0 1 6.7 2.7L21 8" />
      <path d="M21 3v5h-5" />
      <path d="M21 12a9 9 0 0 1-9 9 9.8 9.8 0 0 1-6.7-2.7L3 16" />
      <path d="M8 16H3v5" />
    </Icon>
  )
}

function MailOpenIcon() {
  return (
    <Icon className="webmail-empty-icon">
      <path d="M21.2 8.4c.5.38.8.97.8 1.6v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V10a2 2 0 0 1 .8-1.6l8-6a2 2 0 0 1 2.4 0l8 6Z" />
      <path d="m22 10-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 10" />
    </Icon>
  )
}
