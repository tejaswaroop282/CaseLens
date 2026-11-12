import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import AlertsPage from "./pages/AlertsPage";
import CasePage from "./pages/CasePage";
import DataPage from "./pages/DataPage";
import ScenarioDetailPage from "./pages/ScenarioDetailPage";
import ScenariosPage from "./pages/ScenariosPage";
import { EmptyState } from "./components/ui";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/scenarios" replace />} />
        <Route path="/scenarios" element={<ScenariosPage />} />
        <Route path="/scenarios/:id" element={<ScenarioDetailPage />} />
        <Route path="/alerts" element={<AlertsPage />} />
        <Route path="/cases/:caseId" element={<CasePage />} />
        <Route path="/data" element={<DataPage />} />
        <Route path="*" element={<EmptyState title="Page not found">Use the menu on the left.</EmptyState>} />
      </Route>
    </Routes>
  );
}
