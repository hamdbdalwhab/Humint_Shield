/**
 * Application routes.
 *
 * The micro-learning page (`/training/:trackingUuid`) is public so that a
 * recipient arriving from a simulated email link never hits a login wall; every
 * other route is protected and rendered inside the administrative shell.
 */
import { Route, Routes } from 'react-router-dom';
import type { ReactNode } from 'react';

import { Layout } from '@/components/Layout';
import { ProtectedRoute } from '@/components/ProtectedRoute';
import { AssignmentsPage } from '@/pages/AssignmentsPage';
import { CampaignDetailPage } from '@/pages/CampaignDetailPage';
import { CampaignsPage } from '@/pages/CampaignsPage';
import { DashboardPage } from '@/pages/DashboardPage';
import { EmployeeDossierPage } from '@/pages/EmployeeDossierPage';
import { EmployeesPage } from '@/pages/EmployeesPage';
import { HackedPage } from '@/pages/HackedPage';
import { LoginPage } from '@/pages/LoginPage';
import { LiveBoardPage } from '@/pages/LiveBoardPage';
import { MyTrainingPage } from '@/pages/MyTrainingPage';
import { NewCampaignPage } from '@/pages/NewCampaignPage';
import { NotFoundPage } from '@/pages/NotFoundPage';
import { PhishingLandingPage } from '@/pages/PhishingLandingPage';
import { ReportInboxPage } from '@/pages/ReportInboxPage';
import { SettingsPage } from '@/pages/SettingsPage';
import { TemplatesPage } from '@/pages/TemplatesPage';
import { TrainingExperiencePage } from '@/pages/TrainingExperiencePage';
import { TrainingLibraryPage } from '@/pages/TrainingLibraryPage';

/** Wrap a page in the authenticated application shell. */
function Shell({ children }: { children: ReactNode }) {
  return (
    <ProtectedRoute>
      <Layout>{children}</Layout>
    </ProtectedRoute>
  );
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/phish/:trackingUuid" element={<PhishingLandingPage />} />
      <Route path="/hacked/:trackingUuid" element={<HackedPage />} />
      <Route path="/training-experience/:trackingUuid" element={<TrainingExperiencePage />} />
      <Route path="/training/:trackingUuid" element={<TrainingExperiencePage />} />

      <Route
        path="/"
        element={
          <Shell>
            <DashboardPage />
          </Shell>
        }
      />
      <Route
        path="/employees"
        element={
          <Shell>
            <EmployeesPage />
          </Shell>
        }
      />
      <Route
        path="/employees/:employeeId"
        element={
          <Shell>
            <EmployeeDossierPage />
          </Shell>
        }
      />
      <Route
        path="/templates"
        element={
          <Shell>
            <TemplatesPage />
          </Shell>
        }
      />
      <Route
        path="/campaigns"
        element={
          <Shell>
            <CampaignsPage />
          </Shell>
        }
      />
      <Route
        path="/campaigns/new"
        element={
          <Shell>
            <NewCampaignPage />
          </Shell>
        }
      />
      <Route
        path="/campaigns/:campaignId/live"
        element={
          <Shell>
            <LiveBoardPage />
          </Shell>
        }
      />
      <Route
        path="/campaigns/:campaignId"
        element={
          <Shell>
            <CampaignDetailPage />
          </Shell>
        }
      />

      <Route
        path="/training-library"
        element={
          <Shell>
            <TrainingLibraryPage />
          </Shell>
        }
      />
      <Route
        path="/assignments"
        element={
          <Shell>
            <AssignmentsPage />
          </Shell>
        }
      />
      <Route
        path="/my-training"
        element={
          <Shell>
            <MyTrainingPage />
          </Shell>
        }
      />
      <Route
        path="/report-inbox"
        element={
          <Shell>
            <ReportInboxPage />
          </Shell>
        }
      />
      <Route
        path="/settings"
        element={
          <Shell>
            <SettingsPage />
          </Shell>
        }
      />

      <Route
        path="*"
        element={
          <Shell>
            <NotFoundPage />
          </Shell>
        }
      />
    </Routes>
  );
}
