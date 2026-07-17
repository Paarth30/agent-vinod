import { useEffect, useState } from 'react'
import { api } from './api/client'
import { Stepper } from './components/Stepper'
import { InlineLoading } from './components/InlineLoading'
import { DiscoveryPage } from './pages/DiscoveryPage'
import { ResumeReviewPage } from './pages/ResumeReviewPage'
import { CoverLetterReviewPage } from './pages/CoverLetterReviewPage'
import { ContactsPage } from './pages/ContactsPage'
import { ApplyPage } from './pages/ApplyPage'

type PageKey = 'discover' | 'resumes' | 'letters' | 'contacts' | 'apply'

const STAGE_TO_PAGE: Record<string, PageKey> = {
  idle: 'discover',
  discovering: 'discover',
  selecting: 'discover',
  tailoring_resumes: 'resumes',
  reviewing_resumes: 'resumes',
  tailoring_letters: 'letters',
  reviewing_letters: 'letters',
  finding_contacts: 'contacts',
  reviewing_contacts: 'contacts',
  applying: 'apply',
  done: 'apply',
}

function App() {
  const [page, setPage] = useState<PageKey>('discover')
  const [stage, setStage] = useState('idle')
  const [ready, setReady] = useState(false)

  useEffect(() => {
    api.status.get().then((s) => {
      setStage(s.stage)
      setPage(STAGE_TO_PAGE[s.stage] ?? 'discover')
    }).catch(() => {}).finally(() => setReady(true))
  }, [])

  const refreshStage = () => api.status.get().then((s) => setStage(s.stage)).catch(() => {})

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>Agent Vinod</h1>
        <Stepper stage={stage} current={page} onNavigate={(key) => setPage(key as PageKey)} />
      </header>
      <main className="app-main">
        {!ready && <InlineLoading text="loading" />}
        {ready && page === 'discover' && (
          <DiscoveryPage onProceed={() => { setPage('resumes'); refreshStage() }} />
        )}
        {ready && page === 'resumes' && (
          <ResumeReviewPage onProceed={() => { setPage('letters'); refreshStage() }} />
        )}
        {ready && page === 'letters' && (
          <CoverLetterReviewPage onProceed={() => { setPage('contacts'); refreshStage() }} />
        )}
        {ready && page === 'contacts' && (
          <ContactsPage onProceed={() => { setPage('apply'); refreshStage() }} />
        )}
        {ready && page === 'apply' && (
          <ApplyPage />
        )}
      </main>
    </div>
  )
}

export default App
