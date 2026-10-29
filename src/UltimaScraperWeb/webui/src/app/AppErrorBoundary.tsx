import { Component, type ErrorInfo, type ReactNode } from 'react';
import './AppErrorBoundary.css';

export class AppErrorBoundary extends Component<
  { children: ReactNode },
  { error: Error | null }
> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('Uncaught error:', error, errorInfo);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <main className="app-incident" aria-label="Application incident" role="alert">
        <header className="app-incident__identity">
          <strong>ULTIMASCRAPER</strong>
          <span>SYSTEM RECORD // US-CT</span>
        </header>
        <div className="app-incident__report">
          <span className="app-incident__status">INTERFACE FAULT</span>
          <h1>Application unavailable</h1>
          <pre className="app-incident__message">{error.message}</pre>
          <button type="button" onClick={() => window.location.reload()}>Reload application</button>
          <details className="app-incident__details">
            <summary>Error details</summary>
            <pre>{error.stack ?? error.toString()}</pre>
          </details>
        </div>
      </main>
    );
  }
}
