import './App.css'
import { CampaignTitle, MembersTable, UnpaidTable } from './HelloAsso.jsx'
import { LicencesTable, DemandesTable, DraftTable } from './Ffst.jsx'
import { FinancialBalance } from './FinancialBalance.jsx'
import Navigation from './Navigation.jsx'

function App() {
  return (
    <div className="app">
      <CampaignTitle />
      <Navigation
        sections={[
          {
            key: 'helloasso',
            label: 'HelloAsso',
            tools: [
              { label: 'Adhérents', content: <MembersTable /> },
              { label: 'Impayés', content: <UnpaidTable /> },
            ],
          },
          {
            key: 'ffst',
            label: 'FFST',
            tools: [
              { label: 'Licenciés', content: <LicencesTable /> },
              { label: 'Demandes validées', content: <DemandesTable /> },
              { label: 'Demandes brouillon', content: <DraftTable /> },
            ],
          },
          {
            key: 'bilan',
            label: 'Bilan financier',
            tools: [{ label: 'Bilan financier', content: <FinancialBalance /> }],
          },
        ]}
      />
    </div>
  )
}

export default App
