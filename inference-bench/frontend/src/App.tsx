import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import ModelCatalog from './pages/ModelCatalog'
import NewEvaluation from './pages/NewEvaluation'
import EvalProgress from './pages/EvalProgress'
import EvalResults from './pages/EvalResults'
import Compare from './pages/Compare'
import ValidatePage from './pages/ValidatePage'
import Probe from './pages/Probe'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/models" element={<ModelCatalog />} />
          <Route path="/new" element={<NewEvaluation />} />
          <Route path="/progress/:runId" element={<EvalProgress />} />
          <Route path="/results/:runId" element={<EvalResults />} />
          <Route path="/compare" element={<Compare />} />
          <Route path="/validate/:modelId" element={<ValidatePage />} />
          <Route path="/probe" element={<Probe />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
