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
import Playground from './pages/Playground'
import Datasets from './pages/Datasets'
import Monitor from './pages/Monitor'
import Schedules from './pages/Schedules'
import Integrations from './pages/Integrations'
import CostAnalytics from './pages/CostAnalytics'
import Alerts from './pages/Alerts'
import Intelligence from './pages/Intelligence'
import AbTests from './pages/AbTests'
import Home from './pages/Home'
import Droplets from './pages/Droplets'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Home />} />
          <Route path="/home" element={<Home />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/models" element={<ModelCatalog />} />
          <Route path="/new" element={<NewEvaluation />} />
          <Route path="/progress/:runId" element={<EvalProgress />} />
          <Route path="/results/:runId" element={<EvalResults />} />
          <Route path="/compare" element={<Compare />} />
          <Route path="/validate/:modelId" element={<ValidatePage />} />
          <Route path="/probe" element={<Probe />} />
          <Route path="/probe/results/:probeId" element={<Probe />} />
          <Route path="/playground" element={<Playground />} />
          <Route path="/datasets" element={<Datasets />} />
          <Route path="/monitor" element={<Monitor />} />
          <Route path="/schedules" element={<Schedules />} />
          <Route path="/integrations" element={<Integrations />} />
          <Route path="/cost" element={<CostAnalytics />} />
          <Route path="/alerts" element={<Alerts />} />
          <Route path="/intelligence" element={<Intelligence />} />
          <Route path="/ab-tests" element={<AbTests />} />
          <Route path="/benchmark/droplets" element={<Droplets />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
