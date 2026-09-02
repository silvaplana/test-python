import './App.css'
import { CampaignTitle, MembersTable, UnpaidTable } from './HelloAsso.jsx'
import { LicencesTable, DemandesTable, DraftTable } from './Ffst.jsx'
import { FinancialBalance } from './FinancialBalance.jsx'
import Tabs from './Tabs.jsx'

function App() {
  return (
    <div className="app">
      <CampaignTitle />
      <Tabs
        tabs={[
          { label: 'Adhérents HelloAsso', content: <MembersTable /> },
          { label: 'Impayés HelloAsso', content: <UnpaidTable /> },
          { label: 'Licenciés FFST', content: <LicencesTable /> },
          { label: 'Demandes FFST validées', content: <DemandesTable /> },
          { label: 'Demandes FFST DRAFT', content: <DraftTable /> },
          { label: 'Bilan financier', content: <FinancialBalance /> },
        ]}
      />
    </div>
  )
}

export default App
