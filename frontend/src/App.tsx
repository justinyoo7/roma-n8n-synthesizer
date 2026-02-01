import { Routes, Route } from 'react-router-dom'
import DescribePage from './pages/DescribePage'
import WorkflowPage from './pages/WorkflowPage'

function App() {
  return (
    <div className="min-h-screen bg-background">
      <Routes>
        <Route path="/" element={<DescribePage />} />
        <Route path="/workflow/:id" element={<WorkflowPage />} />
      </Routes>
    </div>
  )
}

export default App
