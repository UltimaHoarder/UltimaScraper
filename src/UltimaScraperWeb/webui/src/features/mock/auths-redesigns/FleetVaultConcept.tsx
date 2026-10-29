import { useMemo } from 'react';
import type { AuthCredential } from '../../../api/types/auths';
import type { AuthsMockModel } from './authsMockModel';

interface FleetVaultConceptProps {
  model: AuthsMockModel;
}

interface UserGroup {
  key: string;
  site: string;
  userId: number;
  username: string;
  auths: AuthCredential[];
}

export function FleetVaultConcept({ model }: FleetVaultConceptProps) {
  const { sortedAuths, stats, toggleActive, deleteAuth, setEditingAuth, setTestingAuth, setVerifyingAuth } = model;

  // Group auths by site + userId to clearly show multi-auth accounts
  const groups = useMemo(() => {
    const map = new Map<string, UserGroup>();
    for (const auth of sortedAuths) {
      const key = `${auth.site}-${auth.user_id}`;
      let group = map.get(key);
      if (!group) {
        group = {
          key,
          site: auth.site,
          userId: auth.user_id,
          username: auth.username || `u${auth.user_id}`,
          auths: [],
        };
        map.set(key, group);
      }
      group.auths.push(auth);
    }
    return Array.from(map.values());
  }, [sortedAuths]);

  return (
    <section className="arm-concept arm-fleet-vault" aria-label="Fleet Credential Vault">
      {/* Top Telemetry KPI Bar */}
      <div className="arm-kpi-bar">
        <div className="arm-kpi-card">
          <span className="arm-kpi-label">TOTAL SESSIONS</span>
          <strong className="arm-kpi-value">{stats.total}</strong>
          <small>{stats.active} active · {stats.disabled} disabled</small>
        </div>
        <div className="arm-kpi-card">
          <span className="arm-kpi-label">FLEET HEALTH</span>
          <strong className="arm-kpi-value is-green">{stats.validRate}%</strong>
          <small>{stats.valid} operational · {stats.challenges} challenges</small>
        </div>
        <div className="arm-kpi-card">
          <span className="arm-kpi-label">PROXY ATTACH RATE</span>
          <strong className="arm-kpi-value is-cyan">{stats.proxyRate}%</strong>
          <small>{stats.withProxy} routed through residential nodes</small>
        </div>
        <div className="arm-kpi-card">
          <span className="arm-kpi-label">SPENDER SHIELD</span>
          <strong className="arm-kpi-value is-warn">{stats.spenders} Spenders</strong>
          <small>{stats.total - stats.spenders} accounts financial lock</small>
        </div>
      </div>

      {/* Filter & Action Bar */}
      <div className="arm-vault-toolbar">
        <div className="arm-search-box">
          <input
            type="text"
            value={model.searchTerm}
            onChange={(e) => model.setSearchTerm(e.target.value)}
            placeholder="Search credentials by handle, UID, site, or proxy node..."
          />
        </div>

        <div className="arm-filter-cluster">
          <select
            value={model.siteFilter}
            onChange={(e) => model.setSiteFilter(e.target.value)}
            className="arm-select"
          >
            <option value="">All Platforms</option>
            <option value="onlyfans">OnlyFans</option>
            <option value="fansly">Fansly</option>
          </select>

          <select
            value={model.stateFilter}
            onChange={(e) => model.setStateFilter(e.target.value as typeof model.stateFilter)}
            className="arm-select"
          >
            <option value="all">All States</option>
            <option value="active">Active Only</option>
            <option value="disabled">Disabled Only</option>
          </select>

          <select
            value={model.statusFilter}
            onChange={(e) => model.setStatusFilter(e.target.value as typeof model.statusFilter)}
            className="arm-select"
          >
            <option value="all">All Health</option>
            <option value="valid">Valid / OK</option>
            <option value="challenge">Challenges</option>
            <option value="expired">Expired</option>
          </select>
        </div>

        <div className="arm-toolbar-right">
          <button
            type="button"
            className="arm-btn arm-btn--secondary"
            onClick={() => model.handleUpdateSubscriptions()}
          >
            🔄 Sync All Subs
          </button>
          <button
            type="button"
            className="arm-btn arm-btn--primary"
            onClick={() => model.setShowAddModal(true)}
          >
            + Onboard Account
          </button>
        </div>
      </div>

      {/* Groups List */}
      <div className="arm-vault-groups">
        {groups.length === 0 ? (
          <div className="arm-empty-state">
            <p>No credentials match the active filters or search terms.</p>
            <button
              type="button"
              className="arm-btn arm-btn--quiet"
              onClick={model.resetAll}
            >
              Reset Filters
            </button>
          </div>
        ) : (
          groups.map((group) => (
            <div key={group.key} className="arm-group-card">
              {/* Performer Group Header */}
              <header className="arm-group-header">
                <div className="arm-group-title">
                  <span className={`arm-platform-badge is-${group.site.toLowerCase()}`}>
                    {group.site}
                  </span>
                  <h4>@{group.username}</h4>
                  <span className="arm-mono-tag">UID: {group.userId}</span>
                  {group.auths.length > 1 && (
                    <span className="arm-multi-badge">
                      ⚡ {group.auths.length} Multi-Session Tokens
                    </span>
                  )}
                </div>
                <div className="arm-group-actions">
                  <span className="arm-eyebrow">CLUSTER ACTIVE</span>
                </div>
              </header>

              {/* Sessions Grid */}
              <div className="arm-cards-grid">
                {group.auths.map((auth) => (
                  <article
                    key={auth.id}
                    className={`arm-auth-card ${auth.active ? 'is-active' : 'is-disabled'} is-${auth.status}`}
                  >
                    {/* Card Top Row */}
                    <div className="arm-card-top">
                      <div className="arm-card-id-block">
                        <span className="arm-card-id">AUTH #{auth.id}</span>
                        <span className="arm-card-handle">@{auth.username || `u${auth.user_id}`}</span>
                        <span className={`arm-status-pill is-${auth.status}`}>
                          {auth.status.toUpperCase()}
                        </span>
                      </div>

                      <label className="arm-toggle-switch" title="Toggle active status in scraping fleet">
                        <input
                          type="checkbox"
                          checked={auth.active}
                          onChange={() => toggleActive(auth.id)}
                        />
                        <span className="arm-slider" />
                      </label>
                    </div>

                    {/* Metric Rows */}
                    <div className="arm-metric-matrix">
                      <div className="arm-metric-row">
                        <span className="arm-metric-name">Network Gateway</span>
                        <span className="arm-metric-val">
                          {auth.proxy_id ? (
                            <span className="arm-proxy-tag">🌐 {auth.proxy_id}</span>
                          ) : (
                            <span className="arm-direct-tag">Local Direct</span>
                          )}
                        </span>
                      </div>

                      <div className="arm-metric-row">
                        <span className="arm-metric-name">Worker Shard</span>
                        <span className="arm-metric-val">
                          {auth.worker_shard !== null ? (
                            <code className="arm-shard-tag">SHARD 0{auth.worker_shard}</code>
                          ) : (
                            <span className="arm-muted">Unassigned</span>
                          )}
                        </span>
                      </div>

                      <div className="arm-metric-row">
                        <span className="arm-metric-name">Spender Policy</span>
                        <span className="arm-metric-val">
                          {auth.spend ? (
                            <span className="arm-spend-tag is-spend">
                              💰 SPENDER ({auth.spender_type?.toUpperCase() || 'ALL'})
                            </span>
                          ) : (
                            <span className="arm-spend-tag is-locked">🔒 LOCKED</span>
                          )}
                        </span>
                      </div>

                      <div className="arm-metric-row">
                        <span className="arm-metric-name">Session Token</span>
                        <code className="arm-cookie-snippet">
                          {auth.cookie_preview || 'sess=not_configured'}
                        </code>
                      </div>
                    </div>

                    {/* Age / ID Verification Alert Banner if needed */}
                    {auth.age_verification_required && (
                      <div className="arm-card-alert is-warn">
                        <span>🔞 Age verification challenge active</span>
                        <button
                          type="button"
                          className="arm-mini-link"
                          onClick={() => setVerifyingAuth({ auth, kind: 'age' })}
                        >
                          Resolve →
                        </button>
                      </div>
                    )}

                    {/* Action Footer */}
                    <footer className="arm-card-footer">
                      <div className="arm-card-btn-cluster">
                        <button
                          type="button"
                          className="arm-btn arm-btn--secondary arm-btn--sm"
                          onClick={() => setTestingAuth(auth)}
                          title="Run 2-stage network and API probe"
                        >
                          🧪 Test
                        </button>
                        <button
                          type="button"
                          className="arm-btn arm-btn--quiet arm-btn--sm"
                          onClick={() => model.handleUpdateSubscriptions(auth.id)}
                          title="Sync active subscriptions"
                        >
                          🔄 Subs
                        </button>
                        <button
                          type="button"
                          className="arm-btn arm-btn--quiet arm-btn--sm"
                          onClick={() => model.handleScrapePaidContent(auth.id)}
                          title="Queue paid post crawler"
                        >
                          💎 PPV
                        </button>
                        <button
                          type="button"
                          className="arm-btn arm-btn--secondary arm-btn--sm"
                          onClick={() => setEditingAuth(auth)}
                          title="Manage parameters and cURL refresh"
                        >
                          ⚙️ Manage
                        </button>
                      </div>

                      <button
                        type="button"
                        className="arm-del-icon-btn"
                        onClick={() => deleteAuth(auth.id)}
                        title="Delete credential"
                        aria-label="Delete credential"
                      >
                        ✕
                      </button>
                    </footer>
                  </article>
                ))}
              </div>
            </div>
          ))
        )}
      </div>
    </section>
  );
}
