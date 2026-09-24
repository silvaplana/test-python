import './App.css'
import { AuthGate, useAuth } from './Auth.jsx'
import { BankAccounts, hasBankCallback } from './BankAccounts.jsx'
import { CampaignTitle, MembersHistoryTable, MembersTable, NewMembersBadge, UnpaidTable } from './HelloAsso.jsx'
import { LicencesTable, DemandesTable, DraftTable } from './Ffst.jsx'
import { FinancialBalance } from './FinancialBalance.jsx'
import { Profile } from './Profile.jsx'
import Navigation from './Navigation.jsx'

// Contenu de l'appli, monte seulement une fois authentifie (dans AuthGate) :
// c'est ici que useAuth() est disponible pour connaitre le niveau d'acces.
function AppContent() {
  const { canViewAccounts } = useAuth()
  return (
    <Navigation
      // Retour de la banque (voir BankAccounts.jsx) : ouvre directement
      // Finances/Comptes (section 3, outil 2), sinon l'accueil habituel.
      initialSection={hasBankCallback && canViewAccounts ? 2 : 0}
      initialTool={hasBankCallback && canViewAccounts ? 1 : 0}
      header={<CampaignTitle />}
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
          key: 'finances',
          label: 'Finances',
          alwaysShowTabs: true,
          tools: [
            { label: 'Bilan financier', content: () => <FinancialBalance /> },
            // "Comptes" (donnees bancaires) : uniquement avec le mot de
            // passe "comptes" -- masque sinon (confort d'affichage, le
            // backend refuse de toute facon avec un 403).
            ...(canViewAccounts ? [{ label: 'Comptes', content: () => <BankAccounts /> }] : []),
          ],
        },
        {
          key: 'profil',
          label: 'Profil',
          tools: [{ label: 'Profil', content: () => <Profile /> }],
        },
      ]}
    />
  )
}

function App() {
  return (
    <div className="app">
      <AuthGate>
        <AppContent />
      </AuthGate>
    </div>
  )
}

export default App
