import type { ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import Layout from "./components/Layout";
import { EmptyState } from "./components/ui";
import { HOME, type Role, useAuth } from "./lib/auth";
import AlertsPage from "./pages/AlertsPage";
import CasePage from "./pages/CasePage";
import DataPage from "./pages/DataPage";
import { AnalystHome, OwnerHome } from "./pages/HomePages";
import LoginPage from "./pages/LoginPage";
import ScenarioDetailPage from "./pages/ScenarioDetailPage";
import ScenariosPage from "./pages/ScenariosPage";

/** Signed-in users only; optionally one role. The other role is sent to its own home. */
function Guard({ role, children }: { role?: Role; children: ReactNode }) {
  const { user } = useAuth();
  const loc = useLocation();
  if (!user) return <Navigate to="/login" replace state={{ from: loc.pathname }} />;
  if (role && user.role !== role) return <Navigate to={HOME[user.role]} replace />;
  return <>{children}</>;
}

function Home() {
  const { user } = useAuth();
  return <Navigate to={user ? HOME[user.role] : "/login"} replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<Guard><Layout /></Guard>}>
        <Route index element={<Home />} />
        {/* risk owner */}
        <Route path="/owner" element={<Guard role="owner"><OwnerHome /></Guard>} />
        <Route path="/scenarios" element={<Guard role="owner"><ScenariosPage /></Guard>} />
        <Route path="/scenarios/:id" element={<Guard role="owner"><ScenarioDetailPage /></Guard>} />
        <Route path="/data" element={<Guard role="owner"><DataPage /></Guard>} />
        {/* analyst */}
        <Route path="/analyst" element={<Guard role="analyst"><AnalystHome /></Guard>} />
        <Route path="/alerts" element={<Guard role="analyst"><AlertsPage /></Guard>} />
        <Route path="/cases/:caseId" element={<Guard role="analyst"><CasePage /></Guard>} />
        <Route path="*" element={<EmptyState title="Page not found">Use the menu on the left.</EmptyState>} />
      </Route>
    </Routes>
  );
}
