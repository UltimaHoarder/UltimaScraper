import { useSearchParams } from 'react-router-dom';
import { useUsersMockModel } from './usersMockModel';
import { DossierConcept } from './DossierConcept';
import { RosterMatrixConcept } from './RosterMatrixConcept';
import { VisualShowcaseConcept } from './VisualShowcaseConcept';
import { SyncRadarConcept } from './SyncRadarConcept';
import { TaxonomyStudioConcept } from './TaxonomyStudioConcept';
import './UsersRedesignsMock.css';

const CONCEPTS = [
  {
    id: 'dossier',
    name: 'Creator Dossier',
    note: 'A focused split-pane inspector pairing a searchable creator list with a rich media vault and identity dossier.',
  },
  {
    id: 'matrix',
    name: 'Roster Matrix',
    note: 'High-density tabular workbench with multi-row checkboxes, sticky batch command dock, and fast inline operations.',
  },
  {
    id: 'showcase',
    name: 'Visual Showcase',
    note: 'Visual creator discovery cards featuring backdrop banners, media ratio bars, price tags, and quick hover actions.',
  },
  {
    id: 'radar',
    name: 'Sync Radar',
    note: 'Freshness lifecycle swimlanes grouping creators by archive recency with 1-click bulk catch-up triggers.',
  },
  {
    id: 'taxonomy',
    name: 'Taxonomy Studio',
    note: 'Dedicated classification workbench for auditing creator identity, synthetic content flags, and 1-click preset stamping.',
  },
] as const;

type ConceptId = typeof CONCEPTS[number]['id'];

export function UsersRedesignsMock() {
  const model = useUsersMockModel();
  const [params, setParams] = useSearchParams();
  const activeId = (params.get('concept') as ConceptId) || CONCEPTS[0].id;
  const active = CONCEPTS.find((c) => c.id === activeId) ?? CONCEPTS[0];

  function selectConcept(id: string) {
    setParams((current) => {
      const next = new URLSearchParams(current);
      next.set('category', 'users');
      next.set('concept', id);
      return next;
    });
    window.scrollTo({ top: 0, behavior: 'instant' });
  }

  return (
    <div className="um-lab">
      {/* Top Concept Switcher Navigation */}
      <div className="um-lab-controls">
        <nav className="um-concepts" aria-label="Users design concepts">
          {CONCEPTS.map((concept, index) => (
            <button
              type="button"
              key={concept.id}
              aria-pressed={active.id === concept.id}
              onClick={() => selectConcept(concept.id)}
            >
              <span>0{index + 1}</span>
              {concept.name}
            </button>
          ))}
        </nav>
        <label className="um-concept-select">
          <span>Design</span>
          <select
            aria-label="Users design concept"
            value={active.id}
            onChange={(e) => selectConcept(e.target.value)}
          >
            {CONCEPTS.map((concept, index) => (
              <option key={concept.id} value={concept.id}>
                0{index + 1} · {concept.name}
              </option>
            ))}
          </select>
        </label>
        <button type="button" className="um-btn um-btn--quiet" onClick={model.reset}>
          Reset preview
        </button>
      </div>

      <p className="um-concept-note">{active.note}</p>

      {/* Main Mock Stage */}
      <section className={`um-stage um-stage--${active.id}`} aria-label={`${active.name} workspace`}>
        {/* Stage Workspace Header */}
        <header className="um-workspace-header">
          <div className="um-workspace-title">
            <span className="um-workspace-symbol">👥</span>
            <div>
              <h2>{active.name}</h2>
              <p>Roster management, creator archives &amp; metadata intelligence</p>
            </div>
          </div>
          <div className="um-header-status">
            <span className="um-dot um-dot--live" />
            <span>{model.users.length} Creators in Roster</span>
            <span className="um-header-divider" />
            <span>{model.activeCount} Active</span>
          </div>
        </header>

        {/* Global Metrics Bar */}
        <div className="um-metrics">
          <div>
            <span>Total Creators</span>
            <strong>{String(model.users.length).padStart(2, '0')}</strong>
            <small>Across all platforms</small>
          </div>
          <div>
            <span>Live Watched</span>
            <strong className="um-accent">{String(model.watchedKeys.size).padStart(2, '0')}</strong>
            <small>Webhook listeners</small>
          </div>
          <div>
            <span>Overdue / Unscraped</span>
            <strong className={model.unscrapedCount > 0 ? 'um-warning' : ''}>
              {String(model.unscrapedCount).padStart(2, '0')}
            </strong>
            <small>Needs archive sync</small>
          </div>
          <div>
            <span>Average Rate</span>
            <strong>${model.avgPrice.toFixed(2)}</strong>
            <small>Paid subscriptions</small>
          </div>
        </div>

        {/* Universal Search & Filter Toolbar */}
        <div className="um-toolbar">
          <label className="um-search">
            <span aria-hidden="true">🔍</span>
            <input
              aria-label="Search by identifier"
              placeholder="Search by identifier…"
              value={model.searchIdentifier}
              onChange={(e) => model.setSearchIdentifier(e.target.value)}
            />
            {model.searchIdentifier && (
              <button
                type="button"
                className="um-clear-search"
                onClick={() => model.setSearchIdentifier('')}
                aria-label="Clear identifier search"
              >
                ×
              </button>
            )}
          </label>

          <label className="um-search um-search--desc">
            <span aria-hidden="true">📝</span>
            <input
              aria-label="Search by description"
              placeholder="Search by description…"
              value={model.searchDescription}
              onChange={(e) => model.setSearchDescription(e.target.value)}
            />
            {model.searchDescription && (
              <button
                type="button"
                className="um-clear-search"
                onClick={() => model.setSearchDescription('')}
                aria-label="Clear description search"
              >
                ×
              </button>
            )}
          </label>

          <select
            aria-label="Filter by site"
            value={model.siteFilter}
            onChange={(e) => model.setSiteFilter(e.target.value)}
          >
            <option value="all">All Sites</option>
            <option value="onlyfans">OnlyFans</option>
            <option value="fansly">Fansly</option>
          </select>

          <select
            aria-label="Filter by status"
            value={model.statusFilter}
            onChange={(e) => model.setStatusFilter(e.target.value)}
          >
            <option value="all">All Statuses</option>
            <option value="subscribed">Subscribed</option>
            <option value="favorite">Favorites</option>
            <option value="watched">Watched</option>
            <option value="unscraped">Never Scraped</option>
            <option value="free">Free Only</option>
            <option value="paid">Paid Only</option>
          </select>

          <select
            aria-label="Sort roster"
            value={model.sortBy}
            onChange={(e) => model.setSortBy(e.target.value)}
          >
            <option value="posts">Sort: Post Count</option>
            <option value="media">Sort: Total Media</option>
            <option value="price_desc">Sort: Highest Price</option>
            <option value="price_asc">Sort: Lowest Price</option>
            <option value="name">Sort: Name (A-Z)</option>
            <option value="recent">Sort: Recently Checked</option>
          </select>

          <button
            type="button"
            className={`um-btn um-btn--toolbar ${model.activeFilterCount > 0 || Boolean(model.activeLoadoutName) ? 'um-btn--active' : ''}`}
            onClick={() => model.setIsFiltersModalOpen(true)}
            aria-label="Open advanced filters modal"
          >
            <span>⚙️</span>
            <span>Filters</span>
            {model.activeFilterCount > 0 && (
              <span className="um-btn-badge">{model.activeFilterCount}</span>
            )}
            {model.activeLoadoutName && (
              <span className="um-btn-pill" title={`Active: ${model.activeLoadoutName}`}>
                {model.activeLoadoutName}
              </span>
            )}
          </button>

          <span className="um-result-count">
            {model.visibleUsers.length} / {model.users.length} visible
          </span>
        </div>

        {/* Render Concept Body */}
        <div className="um-workspace-body">
          {active.id === 'dossier' && <DossierConcept model={model} />}
          {active.id === 'matrix' && <RosterMatrixConcept model={model} />}
          {active.id === 'showcase' && <VisualShowcaseConcept model={model} />}
          {active.id === 'radar' && <SyncRadarConcept model={model} />}
          {active.id === 'taxonomy' && <TaxonomyStudioConcept model={model} />}
        </div>

        {/* Stage Workspace Footer */}
        <footer className="um-workspace-footer">
          <span>
            Concept: <span>{active.name}</span> · Mode: Interactive Mock Preview
          </span>
          <span role="status">{model.notice || 'Interactive sample preview · changes persist in session'}</span>
        </footer>
      </section>

      {/* Global Lab Footer */}
      <footer className="um-lab-footer">
        <span className="um-preview-notice" role="status">
          {model.notice || 'Sample data · operations stay in this preview'}
        </span>
        <button type="button" className="um-btn um-btn--quiet" onClick={model.reset}>
          Reset mock state
        </button>
      </footer>

      {/* Loadouts Modal */}
      {model.isLoadoutModalOpen && (
        <div
          className="um-modal-backdrop"
          role="dialog"
          aria-modal="true"
          aria-labelledby="loadout-modal-title"
          onClick={() => model.setIsLoadoutModalOpen(false)}
        >
          <div className="um-modal" onClick={(e) => e.stopPropagation()}>
            <div className="um-modal-header">
              <div>
                <h3 id="loadout-modal-title">Saved Search Loadouts</h3>
                <p>Apply preset filter configurations to quickly inspect specific cohorts.</p>
              </div>
              <button
                type="button"
                className="um-modal-close"
                onClick={() => model.setIsLoadoutModalOpen(false)}
                aria-label="Close loadouts modal"
              >
                ✕
              </button>
            </div>

            <div className="um-modal-body">
              <div className="um-loadouts-grid">
                {model.loadouts.map((loadout) => {
                  const isActive = model.activeLoadoutName === loadout.name;
                  return (
                    <div
                      key={loadout.id}
                      className={`um-loadout-card ${isActive ? 'um-loadout-card--active' : ''}`}
                    >
                      <div className="um-loadout-info">
                        <strong>{loadout.name}</strong>
                        <div className="um-loadout-tags">
                          {loadout.site && <span className="um-tag">Site: {loadout.site}</span>}
                          {loadout.status && <span className="um-tag">Status: {loadout.status}</span>}
                          {loadout.minPrice && <span className="um-tag">Min ${loadout.minPrice}</span>}
                          {loadout.searchIdentifier && <span className="um-tag">ID: {loadout.searchIdentifier}</span>}
                          {loadout.searchDescription && <span className="um-tag">Bio: {loadout.searchDescription}</span>}
                        </div>
                      </div>
                      <button
                        type="button"
                        className={`um-btn ${isActive ? 'um-btn--primary' : 'um-btn--quiet'}`}
                        onClick={() => model.applyLoadout(loadout)}
                      >
                        {isActive ? 'Active' : 'Apply'}
                      </button>
                    </div>
                  );
                })}
              </div>
            </div>

            <div className="um-modal-footer">
              {model.activeLoadoutName && (
                <button
                  type="button"
                  className="um-btn um-btn--quiet"
                  onClick={model.clearLoadout}
                >
                  Clear Active Loadout
                </button>
              )}
              <button
                type="button"
                className="um-btn um-btn--primary"
                onClick={() => model.setIsLoadoutModalOpen(false)}
              >
                Done
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Advanced Filters Modal */}
      {model.isFiltersModalOpen && (
        <div
          className="um-modal-backdrop"
          role="dialog"
          aria-modal="true"
          aria-labelledby="filters-modal-title"
          onClick={() => model.setIsFiltersModalOpen(false)}
        >
          <div className="um-modal" onClick={(e) => e.stopPropagation()}>
            <div className="um-modal-header">
              <div>
                <h3 id="filters-modal-title">Advanced Creator Filters</h3>
                <p>Narrow roster by rate bracket, media volumes, and biography criteria.</p>
              </div>
              <button
                type="button"
                className="um-modal-close"
                onClick={() => model.setIsFiltersModalOpen(false)}
                aria-label="Close filters modal"
              >
                ✕
              </button>
            </div>

            <div className="um-modal-body">
              <form className="um-filters-form" onSubmit={(e) => e.preventDefault()}>
                <div className="um-form-group">
                  <label htmlFor="filter-loadout-select">Preset Search Loadouts</label>
                  <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                    <select
                      id="filter-loadout-select"
                      aria-label="Preset Search Loadouts"
                      value={model.activeLoadoutName}
                      onChange={(e) => {
                        const target = model.loadouts.find((l) => l.name === e.target.value);
                        if (target) model.applyLoadout(target);
                        else model.clearLoadout();
                      }}
                      style={{ flex: 1 }}
                    >
                      <option value="">Custom / None</option>
                      {model.loadouts.map((loadout) => (
                        <option key={loadout.id} value={loadout.name}>
                          {loadout.name}
                        </option>
                      ))}
                    </select>
                    {model.activeLoadoutName && (
                      <button
                        type="button"
                        className="um-btn um-btn--quiet"
                        onClick={model.clearLoadout}
                      >
                        Clear Preset
                      </button>
                    )}
                  </div>
                  <small>Quickly stamp predefined cohort filters into this form.</small>
                </div>

                <div className="um-form-group">
                  <label htmlFor="filter-desc">Search Description / Bio</label>
                  <input
                    id="filter-desc"
                    type="text"
                    placeholder="e.g. cosplay, travel, synth, weekly sets…"
                    value={model.searchDescription}
                    onChange={(e) => model.setSearchDescription(e.target.value)}
                  />
                  <small>Matches words found anywhere within creator profiles.</small>
                </div>

                <div className="um-form-row">
                  <div className="um-form-group">
                    <label htmlFor="filter-min-price">Min Price ($)</label>
                    <input
                      id="filter-min-price"
                      type="number"
                      step="0.01"
                      min="0"
                      placeholder="0.00"
                      value={model.minPrice}
                      onChange={(e) => model.setMinPrice(e.target.value)}
                    />
                  </div>
                  <div className="um-form-group">
                    <label htmlFor="filter-max-price">Max Price ($)</label>
                    <input
                      id="filter-max-price"
                      type="number"
                      step="0.01"
                      min="0"
                      placeholder="99.00"
                      value={model.maxPrice}
                      onChange={(e) => model.setMaxPrice(e.target.value)}
                    />
                  </div>
                </div>

                <div className="um-form-row um-form-row--3">
                  <div className="um-form-group">
                    <label htmlFor="filter-min-posts">Min Posts</label>
                    <input
                      id="filter-min-posts"
                      type="number"
                      min="0"
                      placeholder="e.g. 100"
                      value={model.minPostCount}
                      onChange={(e) => model.setMinPostCount(e.target.value)}
                    />
                  </div>
                  <div className="um-form-group">
                    <label htmlFor="filter-min-images">Min Images</label>
                    <input
                      id="filter-min-images"
                      type="number"
                      min="0"
                      placeholder="e.g. 500"
                      value={model.minImageCount}
                      onChange={(e) => model.setMinImageCount(e.target.value)}
                    />
                  </div>
                  <div className="um-form-group">
                    <label htmlFor="filter-min-videos">Min Videos</label>
                    <input
                      id="filter-min-videos"
                      type="number"
                      min="0"
                      placeholder="e.g. 20"
                      value={model.minVideoCount}
                      onChange={(e) => model.setMinVideoCount(e.target.value)}
                    />
                  </div>
                </div>
              </form>
            </div>

            <div className="um-modal-footer">
              <button
                type="button"
                className="um-btn um-btn--quiet"
                onClick={model.resetFilters}
              >
                Reset All Filters
              </button>
              <button
                type="button"
                className="um-btn um-btn--primary"
                onClick={() => model.setIsFiltersModalOpen(false)}
              >
                Apply &amp; Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
