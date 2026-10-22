/**
 * Frontend entry point. Wires the providers (Redux, React Query, MUI theme,
 * router, toast) around the application routes and mounts everything once.
 *
 * The product is Arabic-first, so the document direction and the Emotion cache
 * are both RTL. Latin text remains readable because Cairo ships a matching
 * Latin subset.
 */
import '@fontsource/cairo/arabic-400.css';
import '@fontsource/cairo/arabic-600.css';
import '@fontsource/cairo/arabic-700.css';
import '@fontsource/cairo/arabic-800.css';
import '@fontsource/cairo/latin-400.css';
import '@fontsource/cairo/latin-700.css';
import '@fontsource/tajawal/arabic-400.css';
import '@fontsource/tajawal/arabic-700.css';
import '@/styles.css';

import createCache from '@emotion/cache';
import { CacheProvider } from '@emotion/react';
import CssBaseline from '@mui/material/CssBaseline';
import { ThemeProvider } from '@mui/material/styles';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { Provider } from 'react-redux';
import { BrowserRouter } from 'react-router-dom';
import { Toaster } from 'react-hot-toast';
import { prefixer } from 'stylis';
import rtlPlugin from 'stylis-plugin-rtl';

import { App } from '@/App';
import { store } from '@/store';
import { theme } from '@/theme';

document.documentElement.lang = 'ar';
document.documentElement.dir = 'rtl';

const rtlCache = createCache({
  key: 'humint-rtl',
  stylisPlugins: [prefixer, rtlPlugin],
  prepend: true,
});

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 15_000,
    },
  },
});

const container = document.getElementById('root');
if (!container) {
  throw new Error('Root element #root was not found in index.html');
}

createRoot(container).render(
  <StrictMode>
    <CacheProvider value={rtlCache}>
      <Provider store={store}>
        <QueryClientProvider client={queryClient}>
          <ThemeProvider theme={theme}>
            <CssBaseline />
            <BrowserRouter>
              <App />
            </BrowserRouter>
            <Toaster
              position="top-left"
              toastOptions={{
                style: {
                  background: 'rgba(21,30,50,0.96)',
                  color: '#E2E8F0',
                  border: '1px solid rgba(0,240,255,0.22)',
                  boxShadow: '0 18px 50px rgba(0,0,0,0.45)',
                  backdropFilter: 'blur(12px)',
                  fontFamily: 'Cairo, Tajawal, sans-serif',
                },
              }}
            />
          </ThemeProvider>
        </QueryClientProvider>
      </Provider>
    </CacheProvider>
  </StrictMode>,
);
