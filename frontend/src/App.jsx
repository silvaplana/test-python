import './App.css'
import { AuthGate, useAuth } from './Auth.jsx'
import { BankAccounts, hasBankCallback } from './BankAccounts.jsx'
import { requestStatementImport } from './BankHistory.jsx'
import { requestSentMails, SentMails } from './MemberContact.jsx'
import { MembersSummary, requestMembersSummary } from './MembersSummary.jsx'
import { CampaignTitle, MembersHistoryTable, MembersTable, NewMembersBadge, UnpaidTable } from './HelloAsso.jsx'
import { LicencesTable, DemandesTable, DraftTable } from './Ffst.jsx'
import { FinancialReports } from './FinancialReports.jsx'
import { Forecasts } from './Forecasts.jsx'
import { GeneralAssemblies } from './GeneralAssemblies.jsx'
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
      // Finances/Comptes (section 4, outil "Comptes") ; QR code d'un eleve scanne
      // avec l'appareil photo (voir Trials.jsx) : l'onglet Essai (section 3) ;
      // sinon le dernier ecran affiche sur cet appareil (voir Navigation.jsx).
      forcedSection={hasBankCallback && canViewAccounts ? 3 : hasTrialCheckin ? 2 : null}
      forcedTool={hasBankCallback && canViewAccounts ? 'Comptes' : null}
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
            {
              label: 'Adhérents',
              badge: <NewMembersBadge />,
              content: (active) => (
                <>
                  <MembersTable active={active} />
                  <MembersSummary />
                  <SentMails />
                </>
              ),
              menu: [
                { label: 'Chiffres des adhérents', onSelect: requestMembersSummary },
                { label: 'Mails envoyés', onSelect: requestSentMails },
              ],
            },
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
            // Outils des finances (donnees bancaires) : uniquement avec le mot
            // de passe "comptes" -- masques sinon (confort d'affichage, le
            // backend refuse de toute facon avec un 403).
            ...(canViewAccounts
              ? [
                  // Saisons (voir Seasons.jsx), en premier : l'unite de temps du
                  // club ; affiche les soldes des comptes.
                  { label: 'Saisons', content: (active) => <Seasons active={active} /> },
                  {
                    label: 'Comptes',
                    content: (active) => <BankAccounts active={active} />,
                    menu: [{ label: 'Importer relevés', onSelect: requestStatementImport }],
                  },
                  // Bilans financiers par saison (voir FinancialReports.jsx),
                  // meme mot de passe que Comptes.
                  {
                    label: 'Bilan financier',
                    shortLabel: 'Bilan',
                    content: (active) => <FinancialReports active={active} />,
                  },
                  // PPT des assemblees generales par saison (voir
                  // GeneralAssemblies.jsx), meme mot de passe que Comptes.
                  {
                    label: 'Assemblées générales',
                    shortLabel: 'AG',
                    content: (active) => <GeneralAssemblies active={active} />,
                  },
                  // Previsionnels du solde par saison (voir Forecasts.jsx),
                  // meme mot de passe que Comptes.
                  { label: 'Prévisionnel', content: (active) => <Forecasts active={active} /> },
                ]
              : [
                  // Sans le mot de passe "comptes" : rien a afficher.
                  {
                    label: 'Finances',
                    content: () => (
                      <p className="empty-state">
                        Les finances sont réservées au mot de passe « comptes » : déconnecte-toi (onglet Profil), puis
                        reconnecte-toi avec ce mot de passe.
                      </p>
                    ),
                  },
                ]),
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
