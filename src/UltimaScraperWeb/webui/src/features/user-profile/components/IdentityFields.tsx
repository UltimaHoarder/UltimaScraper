import type { CSSProperties } from 'react';

import { IDENTITY_PRESETS, type IdentityPreset } from '../lib/userProfileUtils';

export interface IdentityFieldsProps {
  editProfileType: string;
  editSexualContent: string;
  editSex: string;
  editGender: string;
  editPartnerSex: string;
  editPartnerGender: string;
  onEditProfileTypeChange: (value: string) => void;
  onEditSexualContentChange: (value: string) => void;
  onEditSexChange: (value: string) => void;
  onEditGenderChange: (value: string) => void;
  onEditPartnerSexChange: (value: string) => void;
  onEditPartnerGenderChange: (value: string) => void;
  onApplyIdentityPreset: (preset: IdentityPreset) => void;
}

const SOLO_PRESETS = IDENTITY_PRESETS.filter((preset) => preset.category === 'solo');
const COUPLE_PRESETS = IDENTITY_PRESETS.filter((preset) => preset.category === 'couple');

function presetHeadingStyle(marginTop: string): CSSProperties {
  return {
    fontSize: '11px',
    fontWeight: 600,
    textTransform: 'uppercase',
    letterSpacing: '0.04em',
    color: 'var(--text-muted, #888)',
    marginTop,
    marginBottom: '4px',
  };
}

function PresetButtons({
  presets,
  onApply,
}: {
  presets: readonly IdentityPreset[];
  onApply: (preset: IdentityPreset) => void;
}) {
  return (
    <div className="identity-preset-grid">
      {presets.map((preset) => (
        <button
          key={preset.id}
          type="button"
          className="btn-secondary identity-preset-btn"
          onClick={() => onApply(preset)}
        >
          {preset.label}
        </button>
      ))}
    </div>
  );
}

function SexOptions() {
  return (
    <>
      <option value="">Select sex</option>
      <option value="0">Female</option>
      <option value="1">Male</option>
      <option value="2">Other</option>
    </>
  );
}

function GenderOptions() {
  return (
    <>
      <option value="">Select gender</option>
      <option value="0">Woman</option>
      <option value="1">Man</option>
      <option value="2">Other</option>
    </>
  );
}

/** Identity presets plus profile type, sexual content, sex and gender selects. */
export function IdentityFields({
  editProfileType,
  editSexualContent,
  editSex,
  editGender,
  editPartnerSex,
  editPartnerGender,
  onEditProfileTypeChange,
  onEditSexualContentChange,
  onEditSexChange,
  onEditGenderChange,
  onEditPartnerSexChange,
  onEditPartnerGenderChange,
  onApplyIdentityPreset,
  presetsLabel = 'Quick Presets',
}: IdentityFieldsProps & { presetsLabel?: string }) {
  const isCoupleOrGroup = editProfileType === '1' || editProfileType === '2';

  return (
    <>
      <div className="edit-user-field">
        <span>{presetsLabel}</span>
        <div style={presetHeadingStyle('4px')}>Solo Performers</div>
        <PresetButtons presets={SOLO_PRESETS} onApply={onApplyIdentityPreset} />

        <div style={presetHeadingStyle('10px')}>Couples & Duos</div>
        <PresetButtons presets={COUPLE_PRESETS} onApply={onApplyIdentityPreset} />
      </div>

      <label className="edit-user-field">
        <span>Profile Type</span>
        <select
          value={editProfileType}
          onChange={(event) => onEditProfileTypeChange(event.target.value)}
        >
          <option value="">Unset</option>
          <option value="0">Solo</option>
          <option value="1">Couple</option>
          <option value="2">Group</option>
          <option value="3">Other</option>
        </select>
      </label>

      <label className="edit-user-field">
        <span>Sexual Content</span>
        <select
          value={editSexualContent}
          onChange={(event) => onEditSexualContentChange(event.target.value)}
        >
          <option value="">Unset</option>
          <option value="0">Heterosexual (Straight / B/G)</option>
          <option value="1">Lesbian (G/G)</option>
          <option value="2">Gay (M/M)</option>
          <option value="3">Bisexual</option>
          <option value="4">Trans / Queer</option>
          <option value="5">Solo</option>
          <option value="6">Other</option>
        </select>
      </label>

      <label className="edit-user-field">
        <span>{isCoupleOrGroup ? 'Primary Sex' : 'Sex'}</span>
        <select value={editSex} onChange={(event) => onEditSexChange(event.target.value)}>
          <SexOptions />
        </select>
      </label>

      <label className="edit-user-field">
        <span>{isCoupleOrGroup ? 'Primary Gender' : 'Gender'}</span>
        <select value={editGender} onChange={(event) => onEditGenderChange(event.target.value)}>
          <GenderOptions />
        </select>
      </label>

      {isCoupleOrGroup && (
        <>
          <label className="edit-user-field">
            <span>Partner Sex</span>
            <select
              value={editPartnerSex}
              onChange={(event) => onEditPartnerSexChange(event.target.value)}
            >
              <SexOptions />
            </select>
          </label>

          <label className="edit-user-field">
            <span>Partner Gender</span>
            <select
              value={editPartnerGender}
              onChange={(event) => onEditPartnerGenderChange(event.target.value)}
            >
              <GenderOptions />
            </select>
          </label>
        </>
      )}
    </>
  );
}
