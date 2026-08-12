import './App.css'
import { CampaignTitle, MembersTable, UnpaidTable } from './HelloAsso.jsx'
import { LicencesTable, DemandesTable } from './Ffst.jsx'
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
          { label: 'Demandes FFST', content: <DemandesTable /> },
        ]}
      />
    </div>
  )
}

export default App
