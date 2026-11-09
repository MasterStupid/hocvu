import { type ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Route, Switch, useLocation, Router as WouterRouter } from 'wouter';
import { ErrorBoundary } from '@/components/error-boundary';
import { Toaster } from '@/components/ui/toaster';
import { TooltipProvider } from '@/components/ui/tooltip';
import { AppShell } from '@/components/app-shell';
import { AdminAuthProvider } from '@/lib/admin-auth';
import { PrefsProvider } from '@/lib/prefs';
import ChatPage from '@/pages/chat';
import LibraryPage from '@/pages/library';
import DocumentsPage from '@/pages/documents';
import SettingsPage from '@/pages/settings';
import NotFound from '@/pages/not-found';

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false, staleTime: 15_000 } },
});

function Routes() {
  return (
    <RoutedErrorBoundary>
      <Switch>
        <Route path="/" component={ChatPage} />
        <Route path="/library" component={LibraryPage} />
        <Route path="/documents" component={DocumentsPage} />
        <Route path="/documents.html" component={DocumentsPage} />
        <Route path="/settings" component={SettingsPage} />
        <Route component={NotFound} />
      </Switch>
    </RoutedErrorBoundary>
  );
}

function RoutedErrorBoundary({ children }: { children: ReactNode }) {
  const [location] = useLocation();
  return <ErrorBoundary resetKey={location}>{children}</ErrorBoundary>;
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <PrefsProvider>
        <AdminAuthProvider>
          <TooltipProvider>
            <WouterRouter base={import.meta.env.BASE_URL.replace(/\/$/, '')}>
              <AppShell>
                <Routes />
              </AppShell>
            </WouterRouter>
            <Toaster />
          </TooltipProvider>
        </AdminAuthProvider>
      </PrefsProvider>
    </QueryClientProvider>
  );
}

export default App;
