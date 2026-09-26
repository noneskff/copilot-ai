import { BrowserRouter, Routes, Route } from 'react-router-dom'
import HomePage from './pages/HomePage'
import AnalysisPage from './pages/AnalysisPage'
import ReportPage from './pages/ReportPage'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/analysis/:repoId" element={<AnalysisPage />} />
        <Route path="/report/:repoId" element={<ReportPage />} />
      </Routes>
    </BrowserRouter>
  )
}
