import { useState, useMemo } from 'react';
import type { JobCreatorMockModel, SupportedSite, IntervalUnit, ScheduleType } from './jobCreatorMockModel';

interface MatrixRowItem {
  id: string;
  username: string;
  site: SupportedSite;
  scrapeUser: boolean;
  downloadMedia: boolean;
  scrapePaid: boolean;
  verifyChecksums: boolean;
  authId: number | 'all';
  selected: boolean;
}

const INITIAL_ROWS: MatrixRowItem[] = [
  {
    id: 'row-1',
    username: 'luna_archive',
    site: 'OnlyFans',
    scrapeUser: true,
    downloadMedia: true,
    scrapePaid: true,
    verifyChecksums: false,
    authId: 'all',
    selected: true,
  },
  {
    id: 'row-2',
    username: 'sarah_sky',
    site: 'OnlyFans',
    scrapeUser: true,
    downloadMedia: true,
    scrapePaid: false,
    verifyChecksums: false,
    authId: 1,
    selected: true,
  },
  {
    id: 'row-3',
    username: 'nova_star',
    site: 'OnlyFans',
    scrapeUser: true,
    downloadMedia: true,
    scrapePaid: true,
    verifyChecksums: true,
    authId: 'all',
    selected: false,
  },
  {
    id: 'row-4',
    username: 'aurora_sky',
    site: 'Fansly',
    scrapeUser: true,
    downloadMedia: false,
    scrapePaid: false,
    verifyChecksums: false,
    authId: 'all',
    selected: false,
  },
];

export function MatrixDispatcherConcept({ model }: { model: JobCreatorMockModel }) {
  const {
    jobName,
    setJobName,
    templates,
    createNewTemplate,
    activeAuths,
    scheduleEnabled,
    setScheduleEnabled,
    scheduleType,
    setScheduleType,
    intervalValue,
    setIntervalValue,
    intervalUnit,
    setIntervalUnit,
    cronExpression,
    setCronExpression,
    ignoreSpaceRequirements,
    setIgnoreSpaceRequirements,
    showNotification,
  } = model;

  const [rows, setRows] = useState<MatrixRowItem[]>(INITIAL_ROWS);
  const [newCreatorInput, setNewCreatorInput] = useState('');
  const [isTemplateModalOpen, setIsTemplateModalOpen] = useState(false);
  const [templateNameInput, setTemplateNameInput] = useState('Fleet Matrix Blueprint');
  const [templateDescInput, setTemplateDescInput] = useState('Multi-performer standardized task grid');

  const selectedRows = rows.filter((r) => r.selected);
  const allSelected = rows.length > 0 && selectedRows.length === rows.length;

  // Calculate total tasks across selected rows
  const totalTasks = useMemo(() => {
    return selectedRows.reduce((sum, r) => {
      let count = 0;
      if (r.scrapeUser) count++;
      if (r.downloadMedia) count++;
      if (r.scrapePaid) count++;
      if (r.verifyChecksums) count++;
      const authMultiplier = r.authId === 'all' ? Math.max(activeAuths.length, 1) : 1;
      return sum + count * authMultiplier;
    }, 0);
  }, [selectedRows, activeAuths.length]);

  const toggleSelectRow = (id: string) => {
    setRows((prev) =>
      prev.map((r) => (r.id === id ? { ...r, selected: !r.selected } : r))
    );
  };

  const toggleSelectAll = (checked: boolean) => {
    setRows((prev) => prev.map((r) => ({ ...r, selected: checked })));
  };

  const handleAddRow = (e: React.FormEvent) => {
    e.preventDefault();
    const clean = newCreatorInput.replace(/^@/, '').trim();
    if (!clean) return;
    const newRow: MatrixRowItem = {
      id: `row-${Date.now()}`,
      username: clean,
      site: 'OnlyFans',
      scrapeUser: true,
      downloadMedia: true,
      scrapePaid: false,
      verifyChecksums: false,
      authId: 'all',
      selected: true,
    };
    setRows((prev) => [newRow, ...prev]);
    setNewCreatorInput('');
    showNotification(`Added @${clean} to fleet matrix`);
  };

  const handleBatchToggle = (field: 'scrapeUser' | 'downloadMedia' | 'scrapePaid' | 'verifyChecksums') => {
    setRows((prev) =>
      prev.map((r) => {
        if (!r.selected) return r;
        return { ...r, [field]: !r[field] };
      })
    );
    showNotification(`Toggled ${field} on ${selectedRows.length} selected performers`);
  };

  const handleApplyTemplateToSelected = (templateId: string) => {
    const tmpl = templates.find((t) => t.template_id === templateId);
    if (!tmpl) return;

    const hasScrape = tmpl.tasks.some((t) => t.task_type === 'scrape_user');
    const hasDownload = tmpl.tasks.some((t) => t.task_type === 'download_media');
    const hasPaid = tmpl.tasks.some((t) => t.task_type === 'scrape_paid_content');
    const hasChecksum = tmpl.tasks.some((t) => t.task_type === 'verify_checksums');

    setRows((prev) =>
      prev.map((r) => {
        if (!r.selected) return r;
        return {
          ...r,
          scrapeUser: hasScrape,
          downloadMedia: hasDownload,
          scrapePaid: hasPaid,
          verifyChecksums: hasChecksum,
        };
      })
    );
    showNotification(`Applied template "${tmpl.name}" tasks to ${selectedRows.length} rows`);
  };

  const handleSaveGridAsTemplate = (e: React.FormEvent) => {
    e.preventDefault();
    if (!templateNameInput.trim()) return;

    // Convert active columns into task templates
    const tasksToSave = [
      { task_type: 'scrape_user', params: { site: 'OnlyFans', username: '{username}' } },
      { task_type: 'download_media', params: { site: 'OnlyFans', username: '{username}' } },
    ];
    if (selectedRows.some((r) => r.scrapePaid)) {
      tasksToSave.push({
        task_type: 'scrape_paid_content',
        params: { site: 'OnlyFans', username: '{username}' },
      });
    }
    if (selectedRows.some((r) => r.verifyChecksums)) {
      tasksToSave.push({
        task_type: 'verify_checksums',
        params: { site: 'OnlyFans', username: '{username}' },
      });
    }

    createNewTemplate(templateNameInput, templateDescInput, tasksToSave);
    setIsTemplateModalOpen(false);
  };

  const handleDispatchMatrix = () => {
    if (selectedRows.length === 0) {
      showNotification('Please select at least one performer in the matrix.', 'error');
      return;
    }
    showNotification(
      `Dispatched fleet job "${jobName || 'Fleet Matrix Job'}" with ${selectedRows.length} creators (${totalTasks} total tasks)!`
    );
  };

  return (
    <section className="jcm-concept jcm-matrix-dispatcher" aria-label="Matrix Batch Dispatcher">
      {/* Top Banner Toolbar */}
      <div className="jcm-command-banner">
        <div>
          <span className="jcm-eyebrow">HIGH-DENSITY FLEET ORCHESTRATION // MATRIX ENGINE</span>
          <h3>Batch Creator Grid &amp; Template Dispatcher</h3>
        </div>
        <div className="jcm-command-shortcuts">
          <button
            type="button"
            className="jcm-btn jcm-btn--template"
            onClick={() => setIsTemplateModalOpen(true)}
            title="Save current grid column policy as a named template"
          >
            💾 Save Grid as Template
          </button>
          <button
            type="button"
            className="jcm-btn jcm-btn--launch"
            onClick={handleDispatchMatrix}
            disabled={selectedRows.length === 0}
          >
            ⚡ Dispatch Fleet ({totalTasks} Tasks)
          </button>
        </div>
      </div>

      {/* Quick Add Row & Template Application Bar */}
      <div className="jcm-matrix-top-bar jcm-card">
        <form onSubmit={handleAddRow} className="jcm-input-action-row">
          <input
            type="text"
            value={newCreatorInput}
            onChange={(e) => setNewCreatorInput(e.target.value)}
            placeholder="Add performer handle (e.g. @nova_star)..."
          />
          <button type="submit" className="jcm-btn jcm-btn--primary">
            + Add Performer
          </button>
        </form>

        <div className="jcm-template-apply-box">
          <label className="jcm-eyebrow">APPLY TEMPLATE TO SELECTED ROWS:</label>
          <select
            defaultValue=""
            onChange={(e) => {
              if (e.target.value) handleApplyTemplateToSelected(e.target.value);
            }}
          >
            <option value="" disabled>
              -- Select Template Archetype --
            </option>
            {templates.map((t) => (
              <option key={t.template_id} value={t.template_id}>
                {t.name} ({t.tasks.length} stages)
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Sticky Bulk Action Dock */}
      {selectedRows.length > 0 && (
        <div className="jcm-batch-dock" role="toolbar" aria-label="Batch operations for selected creators">
          <span className="jcm-batch-label">
            ⚡ <strong>{selectedRows.length} Performers Selected</strong> ({totalTasks} tasks queued):
          </span>
          <button
            type="button"
            className="jcm-mini-btn"
            onClick={() => handleBatchToggle('scrapeUser')}
          >
            Toggle Scrape
          </button>
          <button
            type="button"
            className="jcm-mini-btn"
            onClick={() => handleBatchToggle('downloadMedia')}
          >
            Toggle Downloads
          </button>
          <button
            type="button"
            className="jcm-mini-btn"
            onClick={() => handleBatchToggle('scrapePaid')}
          >
            Toggle PPV
          </button>
          <button
            type="button"
            className="jcm-mini-btn"
            onClick={() => handleBatchToggle('verifyChecksums')}
          >
            Toggle Hashes
          </button>
          <button
            type="button"
            className="jcm-mini-btn jcm-btn--quiet"
            onClick={() => toggleSelectAll(false)}
          >
            Clear Selection
          </button>
        </div>
      )}

      {/* High Density Table */}
      <div className="jcm-table-wrap jcm-card">
        <table className="jcm-table" aria-label="Creator workload matrix">
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
              <th>Creator / Performer</th>
              <th>Platform</th>
              <th className="is-center">Scrape Posts</th>
              <th className="is-center">Download Media</th>
              <th className="is-center">Scrape PPV</th>
              <th className="is-center">Verify Hashes</th>
              <th>Auth Session</th>
              <th className="is-center" style={{ width: '48px' }}>Action</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} className={row.selected ? 'is-selected-row' : ''}>
                <td style={{ textAlign: 'center' }}>
                  <input
                    type="checkbox"
                    checked={row.selected}
                    onChange={() => toggleSelectRow(row.id)}
                    aria-label={`Select ${row.username}`}
                  />
                </td>
                <td>
                  <strong>@{row.username}</strong>
                </td>
                <td>
                  <span className={`jcm-platform-tag is-${row.site.toLowerCase()}`}>{row.site}</span>
                </td>
                <td className="is-center">
                  <input
                    type="checkbox"
                    checked={row.scrapeUser}
                    onChange={() =>
                      setRows((prev) =>
                        prev.map((r) => (r.id === row.id ? { ...r, scrapeUser: !r.scrapeUser } : r))
                      )
                    }
                  />
                </td>
                <td className="is-center">
                  <input
                    type="checkbox"
                    checked={row.downloadMedia}
                    onChange={() =>
                      setRows((prev) =>
                        prev.map((r) =>
                          r.id === row.id ? { ...r, downloadMedia: !r.downloadMedia } : r
                        )
                      )
                    }
                  />
                </td>
                <td className="is-center">
                  <input
                    type="checkbox"
                    checked={row.scrapePaid}
                    onChange={() =>
                      setRows((prev) =>
                        prev.map((r) =>
                          r.id === row.id ? { ...r, scrapePaid: !r.scrapePaid } : r
                        )
                      )
                    }
                  />
                </td>
                <td className="is-center">
                  <input
                    type="checkbox"
                    checked={row.verifyChecksums}
                    onChange={() =>
                      setRows((prev) =>
                        prev.map((r) =>
                          r.id === row.id ? { ...r, verifyChecksums: !r.verifyChecksums } : r
                        )
                      )
                    }
                  />
                </td>
                <td>
                  <select
                    value={String(row.authId)}
                    onChange={(e) =>
                      setRows((prev) =>
                        prev.map((r) =>
                          r.id === row.id
                            ? {
                                ...r,
                                authId: e.target.value === 'all' ? 'all' : Number(e.target.value),
                              }
                            : r
                        )
                      )
                    }
                  >
                    <option value="all">⚡ All Sessions ({activeAuths.length})</option>
                    {activeAuths.map((a) => (
                      <option key={a.id} value={a.id}>{a.username}</option>
                    ))}
                  </select>
                </td>
                <td className="is-center">
                  <button
                    type="button"
                    className="jcm-mini-del"
                    onClick={() => {
                      setRows((prev) => prev.filter((r) => r.id !== row.id));
                      showNotification(`Removed @${row.username} from matrix`);
                    }}
                    title="Remove row"
                  >
                    ✕
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Global Scheduling & Storage Policy Bar */}
      <div className="jcm-policy-bar jcm-card" style={{ marginTop: '1rem' }}>
        <div className="jcm-field" style={{ minWidth: '220px' }}>
          <label>Job Fleet Name</label>
          <input
            type="text"
            value={jobName}
            onChange={(e) => setJobName(e.target.value)}
            placeholder="e.g. Global Fleet Harvest"
          />
        </div>

        <label className="jcm-checkbox-row">
          <input
            type="checkbox"
            checked={scheduleEnabled}
            onChange={(e) => setScheduleEnabled(e.target.checked)}
          />
          <span>Schedule Recurring Fleet Run</span>
        </label>

        {scheduleEnabled && (
          <div className="jcm-schedule-mini-row">
            <select
              value={scheduleType}
              onChange={(e) => setScheduleType(e.target.value as ScheduleType)}
            >
              <option value="interval">Repeat Every</option>
              <option value="cron">Cron Expression</option>
            </select>
            {scheduleType === 'interval' ? (
              <>
                <input
                  type="number"
                  min="1"
                  style={{ width: '60px' }}
                  value={intervalValue}
                  onChange={(e) => setIntervalValue(Number(e.target.value))}
                />
                <select
                  value={intervalUnit}
                  onChange={(e) => setIntervalUnit(e.target.value as IntervalUnit)}
                >
                  <option value="minutes">Minutes</option>
                  <option value="hours">Hours</option>
                  <option value="days">Days</option>
                </select>
              </>
            ) : (
              <input
                type="text"
                value={cronExpression}
                onChange={(e) => setCronExpression(e.target.value)}
                placeholder="0 0 * * *"
              />
            )}
          </div>
        )}

        <label className="jcm-checkbox-row">
          <input
            type="checkbox"
            checked={ignoreSpaceRequirements}
            onChange={(e) => setIgnoreSpaceRequirements(e.target.checked)}
          />
          <span>Ignore storage space checks</span>
        </label>
      </div>

      {/* Save Grid as Named Template Modal */}
      {isTemplateModalOpen && (
        <div className="jcm-modal-overlay" role="dialog" aria-modal="true">
          <div className="jcm-modal jcm-card">
            <header className="jcm-modal-header">
              <div>
                <span className="jcm-eyebrow">REUSABLE TEMPLATE AUTHORING</span>
                <h4>Save Grid Configuration as Named Template</h4>
              </div>
              <button
                type="button"
                className="jcm-close-btn"
                onClick={() => setIsTemplateModalOpen(false)}
              >
                ✕
              </button>
            </header>

            <form onSubmit={handleSaveGridAsTemplate}>
              <div className="jcm-field">
                <label>Template Name *</label>
                <input
                  type="text"
                  required
                  value={templateNameInput}
                  onChange={(e) => setTemplateNameInput(e.target.value)}
                  placeholder="e.g. Standard Fleet Grid Recipe"
                />
              </div>

              <div className="jcm-field">
                <label>Template Description</label>
                <textarea
                  rows={2}
                  value={templateDescInput}
                  onChange={(e) => setTemplateDescInput(e.target.value)}
                  placeholder="Describe the tasks configured in this grid..."
                />
              </div>

              <div className="jcm-modal-summary">
                <p>
                  Active columns will be mapped into parametric template tasks (<code>scrape_user</code>, <code>download_media</code>, and optional PPV / checksum verification) with <code>{'{username}'}</code> variable bindings.
                </p>
              </div>

              <div className="jcm-modal-actions">
                <button
                  type="button"
                  className="jcm-btn jcm-btn--quiet"
                  onClick={() => setIsTemplateModalOpen(false)}
                >
                  Cancel
                </button>
                <button type="submit" className="jcm-btn jcm-btn--primary">
                  Save Template to Library
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </section>
  );
}
