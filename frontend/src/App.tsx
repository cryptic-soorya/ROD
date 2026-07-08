import { Navigate, Route, Routes } from 'react-router-dom';
import { AuthProvider } from './auth/AuthContext';
import LoginPage from './auth/LoginPage';
import AppShell from './components/AppShell';
import RequireAuth from './components/RequireAuth';
import InvestigationsListPage from './pages/InvestigationsListPage';
import NewInvestigationPage from './pages/NewInvestigationPage';
import InvestigationDetailPage from './pages/InvestigationDetailPage';
import ReportPage from './pages/ReportPage';
import CapabilitiesPage from './pages/CapabilitiesPage';
import KnowledgeAdminPage from './pages/KnowledgeAdminPage';

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />

        <Route
          element={
            <RequireAuth>
              <AppShell />
            </RequireAuth>
          }
        >
          <Route path="/investigations" element={<InvestigationsListPage />} />
          <Route path="/investigations/new" element={<NewInvestigationPage />} />
          <Route path="/investigations/:id" element={<InvestigationDetailPage />} />
          <Route path="/investigations/:id/report" element={<ReportPage />} />
          <Route path="/capabilities" element={<CapabilitiesPage />} />
          <Route
            path="/knowledge"
            element={
              <RequireAuth scope="write:knowledge">
                <KnowledgeAdminPage />
              </RequireAuth>
            }
          />
        </Route>

        <Route path="*" element={<Navigate to="/investigations" replace />} />
      </Routes>
    </AuthProvider>
  );
}
