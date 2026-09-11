import './App.css'
import { AppBadgeController, CampaignTitle, MembersHistoryTable, MembersTable, NewMembersBadge, UnpaidTable } from './HelloAsso.jsx'
import { LicencesTable, DemandesTable, DraftTable } from './Ffst.jsx'
import { FinancialBalance } from './FinancialBalance.jsx'
import { Profile } from './Profile.jsx'
import Navigation from './Navigation.jsx'

function App() {
  return (
    <div className="app">
      {/* Une seule instance, independante de la navigation (contrairement
          a NewMembersBadge, affiche a 2 endroits) : voir la docstring de
          useUnseenMembersCount dans HelloAsso.jsx. */}
      <AppBadgeController />
      <Navigation
        header={<CampaignTitle />}
        // TEMPORAIRE (test des notifications push/badge en conditions
        // reelles) : demarre sur Profil plutot que HelloAsso, sinon
        // MembersTable marque tout comme "vu" des le chargement et les
        // badges ci-dessous n'ont jamais l'occasion de s'afficher. A
        // remettre a 0 (HelloAsso, comportement normal) une fois valide.
        initialSection={3}
        sections={[
          {
            key: 'helloasso',
            label: 'HelloAsso',
            // Badge "nouveaux adherents non consultes" (voir HelloAsso.jsx) :
            // sur la section (sidebar/bottom-nav, visible sans avoir a ouvrir
            // la section) ET sur l'outil "Adherents" precis (sous-onglet, une
            // fois dans la section) -- les 2 s'effacent des que l'onglet
            // Adherents devient reellement actif.
            badge: <NewMembersBadge />,
            tools: [
              { label: 'Adhérents', badge: <NewMembersBadge />, content: (active) => <MembersTable active={active} /> },
              { label: 'Impayés', content: () => <UnpaidTable /> },
              { label: 'Historique', content: () => <MembersHistoryTable /> },
            ],
          },
          {
            key: 'ffst',
            label: 'FFST',
            tools: [
              { label: 'Demandes brouillon', shortLabel: 'Brouillon', content: () => <DraftTable /> },
              { label: 'Demandes validées', shortLabel: 'Validées', content: () => <DemandesTable /> },
              { label: 'Licenciés', content: () => <LicencesTable /> },
            ],
          },
          {
            key: 'bilan',
            label: 'Bilan financier',
            tools: [{ label: 'Bilan financier', content: () => <FinancialBalance /> }],
          },
          {
            key: 'profil',
            label: 'Profil',
            tools: [{ label: 'Profil', content: () => <Profile /> }],
          },
        ]}
      />
    </div>
  )
}

export default App
