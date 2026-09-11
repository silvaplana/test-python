import './App.css'
import { CampaignTitle, MembersHistoryTable, MembersTable, NewMembersBadge, UnpaidTable } from './HelloAsso.jsx'
import { LicencesTable, DemandesTable, DraftTable } from './Ffst.jsx'
import { FinancialBalance } from './FinancialBalance.jsx'
import { Profile } from './Profile.jsx'
import Navigation from './Navigation.jsx'

function App() {
  return (
    <div className="app">
      <Navigation
        header={<CampaignTitle />}
        sections={[
          {
            key: 'helloasso',
            label: 'HelloAsso',
            // Badge "nouveaux adherents non consultes" (voir HelloAsso.jsx) :
            // sur la section, pas sur l'outil "Adherents" precis, pour rester
            // visible dans la sidebar/bottom-nav (1er niveau de navigation)
            // sans avoir a ouvrir la section au prealable.
            badge: <NewMembersBadge />,
            tools: [
              { label: 'Adhérents', content: (active) => <MembersTable active={active} /> },
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
