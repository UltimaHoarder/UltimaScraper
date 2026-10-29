import type { IdentityPreset } from './userProfileUtils';

/** Form state for identity selects; '' means unset. */
export interface IdentityDraft {
  profileType: string;
  sexualContent: string;
  sex: string;
  gender: string;
  partnerSex: string;
  partnerGender: string;
}

export interface IdentityValues {
  sex: number | null;
  gender: number | null;
  profile_type: number | null;
  sexual_content: number | null;
  partner_sex: number | null;
  partner_gender: number | null;
}

interface IdentitySource {
  sex?: number | null;
  gender?: number | null;
  profile_type?: number | null;
  sexual_content?: number | null;
  partner_sex?: number | null;
  partner_gender?: number | null;
}

export const EMPTY_IDENTITY_DRAFT: IdentityDraft = {
  profileType: '',
  sexualContent: '',
  sex: '',
  gender: '',
  partnerSex: '',
  partnerGender: '',
};

const draftValue = (value: number | null | undefined) => (value == null ? '' : String(value));
const parsedValue = (value: string) => (value === '' ? null : Number(value));

export function identityDraftFromUser(user: IdentitySource): IdentityDraft {
  return {
    profileType: draftValue(user.profile_type),
    sexualContent: draftValue(user.sexual_content),
    sex: draftValue(user.sex),
    gender: draftValue(user.gender),
    partnerSex: draftValue(user.partner_sex),
    partnerGender: draftValue(user.partner_gender),
  };
}

export function identityDraftFromPreset(preset: IdentityPreset): IdentityDraft {
  return {
    profileType: String(preset.profileType),
    sexualContent: String(preset.sexualContent),
    sex: String(preset.sex),
    gender: String(preset.gender),
    partnerSex: draftValue(preset.partnerSex),
    partnerGender: draftValue(preset.partnerGender),
  };
}

const SEX_OR_GENDER_VALUES = [0, 1, 2];

/** Converts a draft to API values, or returns the first validation error. */
export function parseIdentityDraft(
  draft: IdentityDraft,
): { ok: true; values: IdentityValues } | { ok: false; error: string } {
  const values: IdentityValues = {
    sex: parsedValue(draft.sex),
    gender: parsedValue(draft.gender),
    profile_type: parsedValue(draft.profileType),
    sexual_content: parsedValue(draft.sexualContent),
    partner_sex: parsedValue(draft.partnerSex),
    partner_gender: parsedValue(draft.partnerGender),
  };
  const checks: Array<[number | null, string]> = [
    [values.sex, 'Invalid sex value'],
    [values.gender, 'Invalid gender value'],
    [values.partner_sex, 'Invalid partner sex value'],
    [values.partner_gender, 'Invalid partner gender value'],
  ];
  for (const [value, error] of checks) {
    if (value !== null && !SEX_OR_GENDER_VALUES.includes(value)) return { ok: false, error };
  }
  return { ok: true, values };
}
