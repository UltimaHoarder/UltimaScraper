import { AppProviders } from './app/AppProviders';
import { AppRouter } from './app/AppRouter';
import { WebUIServerApp } from './features/connections/WebUIServerApp';
import './App.css';
import './pages/VideoPage.css';

/**
 * The WebUI as the WebUI server serves it: its sign-in and Backends page, and
 * one app per backend under /b/{connection}/.
 */
function App() {
  return (
    <WebUIServerApp
      renderBackend={(connectionId, basename) => (
        <AppProviders key={connectionId} connectionId={connectionId}>
          <AppRouter basename={basename} />
        </AppProviders>
      )}
    />
  );
}

export default App;
