import { useState } from 'react';
import type { UsersMockModel } from './usersMockModel';

export function TaxonomyStudioConcept({ model }: { model: UsersMockModel }) {
  const { visibleUsers, selectedUser, selectedId, setSelectedId, updateUserIdentity } = model;
  const [filterMode, setFilterMode] = useState<'all' | 'unclassified' | 'ai'>('all');

  const filtered = visibleUsers.filter((u) => {
    if (filterMode === 'unclassified') {
      return (u.confidence ?? 1.0) < 0.85 || u.profile_type === -1 || u.gender === -1;
    }
    if (filterMode === 'ai') {
      return !!u.ai_assisted;
    }
    return true;
  });

  const activeUser = filtered.find((u) => u.id === selectedId) ?? filtered[0] ?? selectedUser;

  const applyPreset = (preset: {
    profile_type: number;
    gender: number;
    sex: number;
    sexual_content: number;
    ai_assisted?: boolean;
  }) => {
    if (!activeUser) return;
    updateUserIdentity(activeUser.id, preset);
  };

  return (
    <div className="um-taxonomy-layout">
      {/* Left Column: Classification Queue */}
      <aside className="um-taxonomy-queue" aria-label="Taxonomy Queue">
        <div className="um-queue-header">
          <span className="um-eyebrow">Curation Queue</span>
          <div className="um-queue-filters">
            <button
              type="button"
              className={filterMode === 'all' ? 'active' : ''}
              onClick={() => setFilterMode('all')}
            >
              All ({visibleUsers.length})
            </button>
            <button
              type="button"
              className={filterMode === 'unclassified' ? 'active' : ''}
              onClick={() => setFilterMode('unclassified')}
            >
              Needs Review
            </button>
            <button
              type="button"
              className={filterMode === 'ai' ? 'active' : ''}
              onClick={() => setFilterMode('ai')}
            >
              AI-Flagged
            </button>
          </div>
        </div>

        <div className="um-queue-list">
          {filtered.map((user) => {
            const isSelected = user.id === activeUser?.id;
            const confidence = Math.round((user.confidence ?? 0.9) * 100);
            const needsReview = confidence < 85 || user.profile_type === -1;

            return (
              <button
                type="button"
                key={user.id}
                className={`um-queue-item ${isSelected ? 'active' : ''}`}
                onClick={() => setSelectedId(user.id)}
              >
                <img src={user.avatar_url ?? ''} alt="" className="um-avatar-sm" />
                <div className="um-queue-item-body">
                  <div className="um-queue-item-row">
                    <strong>{user.name || user.username}</strong>
                    <span className={`um-confidence-pill ${confidence >= 90 ? 'high' : confidence >= 75 ? 'mid' : 'low'}`}>
                      {confidence}%
                    </span>
                  </div>
                  <div className="um-queue-item-tags">
                    <span className="um-handle-sm">@{user.username}</span>
                    {user.ai_assisted && <span className="um-mini-tag um-mini-tag--ai">AI</span>}
                    {needsReview && <span className="um-mini-tag um-mini-tag--warn">Audit</span>}
                  </div>
                </div>
              </button>
            );
          })}
          {filtered.length === 0 && (
            <div className="um-queue-empty">No creators in this review queue.</div>
          )}
        </div>
      </aside>

      {/* Right Column: Taxonomy Workbench */}
      {activeUser && (
        <main className="um-taxonomy-workbench" aria-label="Taxonomy Workbench">
          {/* Creator Profile Summary */}
          <div className="um-curate-hero">
            <img src={activeUser.avatar_url ?? ''} alt="" className="um-curate-avatar" />
            <div className="um-curate-meta">
              <div className="um-curate-title-row">
                <h2>{activeUser.name || activeUser.username}</h2>
                <span className={`um-badge um-badge--${activeUser.site}`}>{activeUser.site}</span>
                <span className="um-curate-score">
                  Confidence: <strong>{Math.round((activeUser.confidence ?? 0.9) * 100)}%</strong>
                </span>
              </div>
              <span className="um-curate-handle">@{activeUser.username}</span>
              {activeUser.description && (
                <p className="um-curate-bio">{activeUser.description}</p>
              )}
            </div>
          </div>

          {/* Quick-Action Stampers */}
          <section className="um-stamper-section">
            <h3>⚡ 1-Click Taxonomy Stampers</h3>
            <p className="um-muted-text">Instantly stamp common profile archetypes with 100% verified confidence.</p>
            <div className="um-stampers-grid">
              <button
                type="button"
                className="um-stamp-card"
                onClick={() => applyPreset({ profile_type: 0, gender: 0, sex: 0, sexual_content: 0 })}
              >
                <span className="um-stamp-icon">👩</span>
                <strong>Solo Woman (Hetero)</strong>
                <small>Female · Solo · B/G content</small>
              </button>
              <button
                type="button"
                className="um-stamp-card"
                onClick={() => applyPreset({ profile_type: 0, gender: 0, sex: 0, sexual_content: 1 })}
              >
                <span className="um-stamp-icon">👭</span>
                <strong>Solo Woman (Lesbian)</strong>
                <small>Female · Solo · G/G content</small>
              </button>
              <button
                type="button"
                className="um-stamp-card"
                onClick={() => applyPreset({ profile_type: 0, gender: 1, sex: 1, sexual_content: 2 })}
              >
                <span className="um-stamp-icon">👨</span>
                <strong>Solo Man (Gay)</strong>
                <small>Male · Solo · M/M content</small>
              </button>
              <button
                type="button"
                className="um-stamp-card"
                onClick={() => applyPreset({ profile_type: 1, gender: 0, sex: 0, sexual_content: 3 })}
              >
                <span className="um-stamp-icon">👫</span>
                <strong>Couple (Bisexual)</strong>
                <small>M/F Couple · Bi content</small>
              </button>
              <button
                type="button"
                className="um-stamp-card"
                onClick={() => applyPreset({ profile_type: 0, gender: 2, sex: 2, sexual_content: 4 })}
              >
                <span className="um-stamp-icon">⚧️</span>
                <strong>Queer / Non-Binary</strong>
                <small>Non-binary · Queer content</small>
              </button>
              <button
                type="button"
                className="um-stamp-card"
                onClick={() => applyPreset({ profile_type: 0, gender: 0, sex: 0, sexual_content: 0, ai_assisted: true })}
              >
                <span className="um-stamp-icon">🤖</span>
                <strong>AI / Virtual Model</strong>
                <small>Flagged as synthetic persona</small>
              </button>
            </div>
          </section>

          {/* Granular Field Controls */}
          <section className="um-fields-section">
            <h3>Manual Attribute Specification</h3>
            <div className="um-fields-grid">
              <label className="um-field-group">
                <span>Profile Composition</span>
                <select
                  value={activeUser.profile_type ?? -1}
                  onChange={(e) => updateUserIdentity(activeUser.id, { profile_type: Number(e.target.value) })}
                >
                  <option value={-1}>Unset / Unknown</option>
                  <option value={0}>Solo Performer</option>
                  <option value={1}>Couple</option>
                  <option value={2}>Group Collab</option>
                  <option value={3}>Other</option>
                </select>
              </label>

              <label className="um-field-group">
                <span>Performer Gender</span>
                <select
                  value={activeUser.gender ?? -1}
                  onChange={(e) => updateUserIdentity(activeUser.id, { gender: Number(e.target.value) })}
                >
                  <option value={-1}>Unset</option>
                  <option value={0}>Woman / Female</option>
                  <option value={1}>Man / Male</option>
                  <option value={2}>Non-Binary / Other</option>
                </select>
              </label>

              <label className="um-field-group">
                <span>Content Classification</span>
                <select
                  value={activeUser.sexual_content ?? -1}
                  onChange={(e) => updateUserIdentity(activeUser.id, { sexual_content: Number(e.target.value) })}
                >
                  <option value={-1}>Unset</option>
                  <option value={0}>Heterosexual (B/G)</option>
                  <option value={1}>Lesbian (G/G)</option>
                  <option value={2}>Gay (M/M)</option>
                  <option value={3}>Bisexual</option>
                  <option value={4}>Trans / Queer</option>
                  <option value={5}>Solo Showcase</option>
                </select>
              </label>

              <div className="um-field-group um-field-group--check">
                <label className="um-check-label">
                  <input
                    type="checkbox"
                    checked={!!activeUser.ai_assisted}
                    onChange={(e) => updateUserIdentity(activeUser.id, { ai_assisted: e.target.checked })}
                  />
                  <span>Synthetic / AI-Assisted Content</span>
                </label>
              </div>
            </div>

            <div className="um-fields-footer">
              <button
                type="button"
                className="um-btn um-btn--primary"
                onClick={() => updateUserIdentity(activeUser.id, { confidence: 1.0 })}
              >
                ✓ Confirm &amp; Lock Taxonomy (100% Verified)
              </button>
            </div>
          </section>
        </main>
      )}
    </div>
  );
}
