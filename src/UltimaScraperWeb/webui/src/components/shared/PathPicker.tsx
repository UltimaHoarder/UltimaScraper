import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import { browseFilesystem } from '../../api/setup';
import './PathPicker.css';

type PathPickerMode = 'directory' | 'file';

interface PathPickerModalProps {
  mode: PathPickerMode;
  title: string;
  initialPath: string;
  onSelect: (path: string) => void;
  onClose: () => void;
}

function startingDirectory(mode: PathPickerMode, initialPath: string): string {
  const trimmed = initialPath.trim();
  if (!trimmed.startsWith('/')) return '/';
  if (mode === 'directory') return trimmed;
  // A file path starts browsing in its folder.
  return trimmed.slice(0, trimmed.lastIndexOf('/')) || '/';
}

/** Browses the backend's own filesystem, which on Docker is the container's. */
export function PathPickerModal({ mode, title, initialPath, onSelect, onClose }: PathPickerModalProps) {
  const [path, setPath] = useState(() => startingDirectory(mode, initialPath));
  const [typedPath, setTypedPath] = useState(path);
  const listing = useQuery({
    queryKey: ['filesystem', path, mode],
    queryFn: () => browseFilesystem(path, mode === 'file'),
    retry: false,
  });

  const openFolder = (folder: string) => {
    setPath(folder);
    setTypedPath(folder);
  };

  const currentPath = listing.data?.path ?? path;
  const errorMessage =
    listing.error instanceof Error ? listing.error.message : listing.error ? 'Could not list this folder.' : null;

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" aria-label={title}>
      <div className="modal path-picker">
        <div className="modal-header">
          <h2 className="modal-title">{title}</h2>
          <button className="modal-close" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
        <div className="modal-body">
          <form
            className="path-picker-location"
            onSubmit={(event) => {
              event.preventDefault();
              openFolder(typedPath.trim() || '/');
            }}
          >
            <button
              type="button"
              className="path-picker-up"
              onClick={() => listing.data?.parent && openFolder(listing.data.parent)}
              disabled={!listing.data?.parent}
              title="Go to the parent folder"
            >
              ↑
            </button>
            <input
              aria-label="Folder path"
              value={typedPath}
              onChange={(event) => setTypedPath(event.target.value)}
              spellCheck={false}
            />
            <button type="submit" title="Open the typed path">
              Go
            </button>
          </form>

          {errorMessage && <div className="path-picker-error">{errorMessage}</div>}
          {listing.isLoading && <div className="path-picker-empty">Loading…</div>}
          {listing.data && (
            <ul className="path-picker-list">
              {listing.data.entries.length === 0 && (
                <li className="path-picker-empty">This folder is empty.</li>
              )}
              {listing.data.entries.map((entry) => (
                <li key={entry.path}>
                  <button
                    type="button"
                    className={entry.is_dir ? 'is-dir' : 'is-file'}
                    onClick={() => (entry.is_dir ? openFolder(entry.path) : onSelect(entry.path))}
                    title={entry.is_dir ? `Open ${entry.path}` : `Use ${entry.path}`}
                  >
                    <span aria-hidden="true">{entry.is_dir ? '📁' : '📄'}</span>
                    {entry.name}
                  </button>
                </li>
              ))}
              {listing.data.truncated && (
                <li className="path-picker-empty">Only the first entries are shown.</li>
              )}
            </ul>
          )}
          {mode === 'directory' && listing.data && !listing.data.writable && (
            <div className="path-picker-warning">
              The backend cannot write to this folder. Pick another, or fix its permissions.
            </div>
          )}
        </div>
        <div className="modal-footer">
          <button type="button" className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          {mode === 'directory' && (
            <button
              type="button"
              className="btn-primary"
              onClick={() => onSelect(currentPath)}
              disabled={!listing.data}
            >
              Use this folder
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

interface PathFieldProps {
  mode: PathPickerMode;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  label: string;
}

/** A path input with a Browse button that opens {@link PathPickerModal}. */
export function PathField({ mode, value, onChange, placeholder, label }: PathFieldProps) {
  const [picking, setPicking] = useState(false);
  return (
    <div className="path-field">
      <input
        type="text"
        className="setup-form-input"
        aria-label={label}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        spellCheck={false}
      />
      <button
        type="button"
        className="btn-secondary path-field-browse"
        onClick={() => setPicking(true)}
        title={mode === 'directory' ? 'Choose a folder on the server' : 'Choose a file on the server'}
      >
        Browse…
      </button>
      {picking && (
        <PathPickerModal
          mode={mode}
          title={label}
          initialPath={value}
          onSelect={(path) => {
            onChange(path);
            setPicking(false);
          }}
          onClose={() => setPicking(false)}
        />
      )}
    </div>
  );
}
