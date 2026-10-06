import './App.css'
import { AuthGate, useAuth } from './Auth.jsx'
import { BankAccounts, hasBankCallback } from './BankAccounts.jsx'
import { requestStatementImport } from './BankHistory.jsx'
import { CampaignTitle, MembersHistoryTable, MembersTable, NewMembersBadge, UnpaidTable } from './HelloAsso.jsx'
import { LicencesTable, DemandesTable, DraftTable } from './Ffst.jsx'
import { FinancialBalance } from './FinancialBalance.jsx'
import { FinancialReports } from './FinancialReports.jsx'
import { Forecast, GeneralAssemblies } from './Finances.jsx'
import { Profile } from './Profile.jsx'
import { Seasons } from './Seasons.jsx'
import { TrialsTable, hasTrialCheckin } from './Trials.jsx'
import Navigation from './Navigation.jsx'
import { Toasts } from './Toast.jsx'

// Contenu de l'appli, monte seulement une fois authentifie (dans AuthGate) :
// c'est ici que useAuth() est disponible pour connaitre le niveau d'acces.
function AppContent() {
  const { canViewAccounts } = useAuth()
  return (
    <Navigation
      // Retour de la banque (voir BankAccounts.jsx) : ouvre directement
      // Finances/Comptes (section 4, 1er outil) ; QR code d'un eleve scanne
      // avec l'appareil photo (voir Trials.jsx) : l'onglet Essai (section 3) ;
      // sinon l'accueil habituel.
      initialSection={hasBankCallback && canViewAccounts ? 3 : hasTrialCheckin ? 2 : 0}
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
          key: 'essai',
          label: 'Essai',
          tools: [{ label: "Élèves à l'essai", content: () => <TrialsTable /> }],
        },
        {
          key: 'finances',
          label: 'Finances',
          alwaysShowTabs: true,
          tools: [
            // "Comptes" (donnees bancaires), en premier : uniquement avec le
            // mot de passe "comptes" -- masque sinon (confort d'affichage, le
            // backend refuse de toute facon avec un 403).
            ...(canViewAccounts
              ? [
                  {
                    label: 'Comptes',
                    content: (active) => <BankAccounts active={active} />,
                    menu: [{ label: 'Importer relevés', onSelect: requestStatementImport }],
                  },
                  // Saisons (voir Seasons.jsx) : affiche les soldes des
                  // comptes, meme mot de passe que Comptes.
                  { label: 'Saisons', content: (active) => <Seasons active={active} /> },
                  // Bilans financiers par saison (voir FinancialReports.jsx),
                  // meme mot de passe que Comptes.
                  {
                    label: 'Bilan financier',
                    shortLabel: 'Bilan',
                    content: (active) => <FinancialReports active={active} />,
                  },
                ]
              : []),
            // A venir (voir Finances.jsx) : pour l'instant des ecrans "En
            // cours de dev".
            { label: 'Assemblées générales', shortLabel: 'AG', content: () => <GeneralAssemblies /> },
            { label: 'Prévisionnel', content: () => <Forecast /> },
            // Ancien "Bilan financier" (analyse IA des releves deposes),
            // remplace par l'historique de l'onglet Comptes : garde pour
            // l'instant, sous le nom "Deprecated".
            { label: 'Deprecated', content: () => <FinancialBalance /> },
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
      <Toasts />
    </div>
  )
}

export default App
