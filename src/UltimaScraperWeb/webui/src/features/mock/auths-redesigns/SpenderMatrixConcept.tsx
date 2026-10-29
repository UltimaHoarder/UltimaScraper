import { useState } from 'react';
import type { AuthsMockModel } from './authsMockModel';

interface SpenderMatrixConceptProps {
  model: AuthsMockModel;
}

export function SpenderMatrixConcept({ model }: SpenderMatrixConceptProps) {
  const { sortedAuths, stats, toggleActive, deleteAuth, updateAuth, setEditingAuth, setTestingAuth } = model;
  const [selectedIds, setSelectedIds] = useState<number[]>([101, 103]);

  const allSelected = sortedAuths.length > 0 && selectedIds.length === sortedAuths.length;

  const toggleSelectAll = (checked: boolean) => {
    setSelectedIds(checked ? sortedAuths.map((a) => a.id) : []);
  };

  const toggleSelectRow = (id: number) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((i) => i !== id) : [...prev, id]
    );
  };

  const handleToggleSpenderForRow = (id: number, currentSpend: boolean) => {
    updateAuth(id, {
      spend: !currentSpend,
      spender_type: !currentSpend ? 'paid' : null,
    });
  };

  return (
    <section className="arm-concept arm-spender-matrix" aria-label="Performer Account Matrix and Spender Fortress">
      {/* Top Banner Toolbar */}
      <div className="arm-command-banner">
        <div>
          <span className="arm-eyebrow">FLEET DATA SPREADSHEET // SPENDER FORTRESS</span>
          <h3>Multi-Account Matrix &amp; Financial Safeguard Deck</h3>
        </div>

        <div className="arm-command-shortcuts">
          <button
            type="button"
            className="arm-btn arm-btn--secondary"
            onClick={() => model.handleUpdateSubscriptions()}
          >
            🔄 Sync All Subscriptions
          </button>
          <button
            type="button"
            className="arm-btn arm-btn--primary"
            onClick={() => model.setShowAddModal(true)}
          >
            + Add Credential
          </button>
        </div>
      </div>

      {/* Spender Fortress Telemetry Bar */}
      <div className="arm-kpi-bar">
        <div className="arm-kpi-card">
          <span className="arm-kpi-label">TOTAL ACCOUNTS</span>
          <strong className="arm-kpi-value">{stats.total}</strong>
          <small>{stats.active} operational in cluster</small>
        </div>
        <div className="arm-kpi-card">
          <span className="arm-kpi-label">SPENDER AUTHORIZED</span>
          <strong className="arm-kpi-value is-warn">{stats.spenders} Accounts</strong>
          <small>Authorized to deduct wallet balances</small>
        </div>
        <div className="arm-kpi-card">
          <span className="arm-kpi-label">PROTECTED FINANCIAL SHIELD</span>
          <strong className="arm-kpi-value is-green">{stats.total - stats.spenders} Accounts</strong>
          <small>Zero financial spend permitted (100% Locked)</small>
        </div>
        <div className="arm-kpi-card">
          <span className="arm-kpi-label">MONTHLY SPEND CEILING</span>
          <strong className="arm-kpi-value is-cyan">$450.00 Max</strong>
          <small>Automated circuit breaker active</small>
        </div>
      </div>

      {/* Sticky Bulk Selection Dock */}
      {selectedIds.length > 0 && (
        <div className="arm-batch-dock">
          <span className="arm-batch-label">
            ⚡ {selectedIds.length} CREDENTIALS SELECTED:
          </span>
          <button
            type="button"
            className="arm-mini-btn arm-btn--secondary"
            onClick={() => model.batchTest(selectedIds)}
          >
            Test Selected
          </button>
          <button
            type="button"
            className="arm-mini-btn arm-btn--secondary"
            onClick={() => model.batchToggleActive(selectedIds, true)}
          >
            Enable Selected
          </button>
          <button
            type="button"
            className="arm-mini-btn arm-btn--secondary"
            onClick={() => model.batchToggleActive(selectedIds, false)}
          >
            Disable Selected
          </button>
          <button
            type="button"
            className="arm-mini-btn arm-btn--quiet"
            onClick={() => setSelectedIds([])}
          >
            Clear Selection
          </button>
        </div>
      )}

      {/* High Density Table */}
      <div className="arm-table-wrap arm-card">
        <table className="arm-table" aria-label="Credential Workload Matrix">
          <thead>
            <tr>
              <th style={{ width: '40px', textAlign: 'center' }}>
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={(e) => toggleSelectAll(e.target.checked)}
                  aria-label="Select all rows"
                />
              </th>
              <th>Account / Performer</th>
              <th>Platform</th>
              <th>Health Status</th>
              <th>Network Proxy</th>
              <th>Worker Shard</th>
              <th>Spender Safeguard</th>
              <th>Active Fleet</th>
              <th className="is-center" style={{ width: '110px' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {sortedAuths.map((auth) => {
              const isSelected = selectedIds.includes(auth.id);
              return (
                <tr key={auth.id} className={isSelected ? 'is-selected-row' : ''}>
                  <td style={{ textAlign: 'center' }}>
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => toggleSelectRow(auth.id)}
                      aria-label={`Select ${auth.username || auth.id}`}
                    />
                  </td>

                  <td>
                    <div className="arm-table-performer">
                      <strong>@{auth.username || `User #${auth.user_id}`}</strong>
                      <small>UID {auth.user_id} · ID #{auth.id}</small>
                    </div>
                  </td>

                  <td>
                    <span className={`arm-platform-badge is-${auth.site.toLowerCase()}`}>
                      {auth.site}
                    </span>
                  </td>

                  <td>
                    <span className={`arm-status-pill is-${auth.status}`}>
                      {auth.status.toUpperCase()}
                    </span>
                  </td>

                  <td>
                    {auth.proxy_id ? (
                      <span className="arm-proxy-tag">🌐 {auth.proxy_id}</span>
                    ) : (
                      <span className="arm-direct-tag">Direct</span>
                    )}
                  </td>

                  <td>
                    {auth.worker_shard !== null ? (
                      <code className="arm-shard-tag">SHARD 0{auth.worker_shard}</code>
                    ) : (
                      <span className="arm-muted">None</span>
                    )}
                  </td>

                  <td>
                    <div className="arm-spender-cell">
                      <button
                        type="button"
                        className={`arm-spend-toggle-btn ${auth.spend ? 'is-spending' : 'is-locked'}`}
                        onClick={() => handleToggleSpenderForRow(auth.id, auth.spend)}
                        title="Click to toggle financial spending privilege"
                      >
                        {auth.spend ? '💰 SPENDER' : '🔒 LOCKED'}
                      </button>
                      {auth.spend && (
                        <span className="arm-spend-type-chip">
                          {auth.spender_type?.toUpperCase() || 'ALL'}
                        </span>
                      )}
                    </div>
                  </td>

                  <td>
                    <label className="arm-toggle-switch">
                      <input
                        type="checkbox"
                        checked={auth.active}
                        onChange={() => toggleActive(auth.id)}
                      />
                      <span className="arm-slider" />
                    </label>
                  </td>

                  <td className="is-center">
                    <div className="arm-table-row-actions">
                      <button
                        type="button"
                        className="arm-mini-action-btn"
                        onClick={() => setTestingAuth(auth)}
                        title="Run health diagnostic probe"
                      >
                        🧪
                      </button>
                      <button
                        type="button"
                        className="arm-mini-action-btn"
                        onClick={() => setEditingAuth(auth)}
                        title="Edit credentials and parameters"
                      >
                        ⚙️
                      </button>
                      <button
                        type="button"
                        className="arm-mini-del-btn"
                        onClick={() => deleteAuth(auth.id)}
                        title="Delete credential"
                      >
                        ✕
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
