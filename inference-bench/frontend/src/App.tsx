import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import ModelCatalog from './pages/ModelCatalog'
import NewEvaluation from './pages/NewEvaluation'
import EvalProgress from './pages/EvalProgress'
import EvalResults from './pages/EvalResults'
import Compare from './pages/Compare'

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
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
