import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { DesignLab } from './features/mock/DesignLab';
import './index.css';
import './themes/ultima-atlas/tokens.css';
import './themes/ultima-atlas/globals.css';
import './themes/ultima-atlas/workspaces.css';

// Local design preview: renders the same mocks without bootstrapping live services.
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <main className="atlas-main mock-preview-root"><DesignLab /></main>
    </BrowserRouter>
  </StrictMode>,
);
