import { useSearchParams } from 'react-router-dom';
import { useAuthsMockModel, type AuthScenarioPreset } from './authsMockModel';
import { FleetVaultConcept } from './FleetVaultConcept';
import { SentinelHealthConcept } from './SentinelHealthConcept';
import { CurlStudioConcept } from './CurlStudioConcept';
import { SpenderMatrixConcept } from './SpenderMatrixConcept';
import { VerificationRunwayConcept } from './VerificationRunwayConcept';
import { MockManageAuthModal } from './modals/MockManageAuthModal';
import { MockAuthTestModal } from './modals/MockAuthTestModal';
import { MockVerificationModal } from './modals/MockVerificationModal';
import { MockAddAuthModal } from './modals/MockAddAuthModal';
import './AuthsRedesignsMock.css';

export const AUTHS_CONCEPTS = [
  {
    id: 'vault',
    name: 'Fleet Credential Vault & Shard Deck',
    note: 'High-density industrial credential matrix with worker sharding & proxy routing topology, collapsible user group dossiers, and multi-session tokens.',
  },
  {
    id: 'sentinel',
    name: 'Session Sentinel & Health Triage',
    note: 'Real-time status monitoring, proactive token expiration alerts, rate-limit health, and automated 1-click remediation runbook.',
  },
  {
    id: 'studio',
    name: 'Rapid cURL Ingestion Studio & Token Inspector',
    note: 'Developer-focused session cockpit with live cURL/JSON parser, deep header inspector, and instant token patching.',
  },
  {
    id: 'matrix',
    name: 'Performer Account Matrix & Spender Fortress',
    note: 'Spreadsheet-style multi-account workbench with granular wallet/spending safeguards, proxy clustering, and batch multi-row operations.',
  },
  {
    id: 'runway',
    name: 'Identity & Verification Runway',
    note: 'Complete account compliance lifecycle manager: Age Verification (🔞), Identity Biometrics (🪪), OAuth flows, and subscription fleet management.',
  },
] as const;

export type AuthsConceptId = (typeof AUTHS_CONCEPTS)[number]['id'];

export function AuthsRedesignsMock() {
  const model = useAuthsMockModel();
  const [params, setParams] = useSearchParams();

  const requestedConcept = params.get('concept') as AuthsConceptId | null;
  const activeConcept =
    AUTHS_CONCEPTS.find((c) => c.id === requestedConcept) ?? AUTHS_CONCEPTS[0];

  const selectConcept = (id: string) => {
    setParams((current) => {
      const next = new URLSearchParams(current);
      next.set('category', 'auths');
      next.set('concept', id);
      return next;
    });
    window.scrollTo({ top: 0, behavior: 'instant' });
  };

  return (
    <div className="arm-lab" data-testid="auths-redesigns-mock">
      {/* Top Concept Switcher Navigation */}
      <div className="arm-lab-controls">
        <nav className="arm-concepts" aria-label="Auths design concepts">
          {AUTHS_CONCEPTS.map((concept, index) => (
            <button
              type="button"
              key={concept.id}
              aria-pressed={activeConcept.id === concept.id}
              onClick={() => selectConcept(concept.id)}
            >
              <span>0{index + 1}</span>
              {concept.name}
            </button>
          ))}
        </nav>

        <label className="arm-concept-select">
          <span>Design</span>
          <select
            aria-label="Auths design concept"
            value={activeConcept.id}
            onChange={(e) => selectConcept(e.target.value)}
          >
            {AUTHS_CONCEPTS.map((concept, index) => (
              <option key={concept.id} value={concept.id}>
                0{index + 1} · {concept.name}
              </option>
            ))}
          </select>
        </label>

        <div className="arm-lab-right-controls">
          <label style={{ fontSize: '11px', color: '#7d8d8f', display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span>Scenario:</span>
            <select
              className="arm-select"
              defaultValue="standard"
              onChange={(e) => model.applyScenario(e.target.value as AuthScenarioPreset)}
            >
              <option value="standard">Standard Fleet</option>
              <option value="all_healthy">100% Healthy</option>
              <option value="verification_alert">Verification Challenges</option>
              <option value="stale_tokens">Stale Tokens Alert</option>
              <option value="multi_account_stress">Multi-Account Stress (8)</option>
            </select>
          </label>

          <button type="button" className="arm-btn arm-btn--quiet" onClick={model.resetAll}>
            Reset preview
          </button>
        </div>
      </div>

      {/* Concept Pitch Note */}
      <p className="arm-concept-note">{activeConcept.note}</p>

      {/* Global Interactive Notification Toast */}
      {model.notification && (
        <div className={`arm-notification is-${model.notification.type}`} role="status">
          <span>⚡ {model.notification.message}</span>
          <small>Interactive preview feedback</small>
        </div>
      )}

      {/* Stage Workspace Header */}
      <header className="arm-workspace-header">
        <div>
          <span className="arm-eyebrow">US-CT // CREDENTIAL MANAGEMENT &amp; HEALTH</span>
          <h2>{activeConcept.name}</h2>
        </div>
        <div className="arm-workspace-meta">
          <span className="arm-pill is-running">FLEET READY</span>
          <code>NODE: backend_local</code>
        </div>
      </header>

      {/* Render Active Concept */}
      <div className="arm-stage">
        {activeConcept.id === 'vault' && <FleetVaultConcept model={model} />}
        {activeConcept.id === 'sentinel' && <SentinelHealthConcept model={model} />}
        {activeConcept.id === 'studio' && <CurlStudioConcept model={model} />}
        {activeConcept.id === 'matrix' && <SpenderMatrixConcept model={model} />}
        {activeConcept.id === 'runway' && <VerificationRunwayConcept model={model} />}
      </div>

      {/* Shared Modals */}
      {model.editingAuth && (
        <MockManageAuthModal
          auth={model.editingAuth}
          model={model}
          onClose={() => model.setEditingAuth(null)}
        />
      )}

      {model.testingAuth && (
        <MockAuthTestModal
          auth={model.testingAuth}
          model={model}
          onClose={() => model.setTestingAuth(null)}
        />
      )}

      {model.verifyingAuth && (
        <MockVerificationModal
          auth={model.verifyingAuth.auth}
          kind={model.verifyingAuth.kind}
          model={model}
          onClose={() => model.setVerifyingAuth(null)}
        />
      )}

      {model.showAddModal && (
        <MockAddAuthModal
          model={model}
          onClose={() => model.setShowAddModal(false)}
        />
      )}
    </div>
  );
}
