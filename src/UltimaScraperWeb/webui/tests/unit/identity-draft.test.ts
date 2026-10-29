import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { useIdentityDraft } from '../../src/features/user-profile/hooks/useIdentityDraft';
import {
  EMPTY_IDENTITY_DRAFT,
  identityDraftFromPreset,
  identityDraftFromUser,
  parseIdentityDraft,
} from '../../src/features/user-profile/lib/identityDraft';
import { IDENTITY_PRESETS } from '../../src/features/user-profile/lib/userProfileUtils';

describe('identity draft conversions', () => {
  it('maps missing user values to unset fields', () => {
    expect(
      identityDraftFromUser({ sex: 0, gender: null, profile_type: 1, partner_sex: undefined }),
    ).toEqual({ ...EMPTY_IDENTITY_DRAFT, sex: '0', profileType: '1' });
  });

  it('round-trips a preset into API values', () => {
    const couple = IDENTITY_PRESETS.find((preset) => preset.category === 'couple')!;
    const parsed = parseIdentityDraft(identityDraftFromPreset(couple));

    expect(parsed).toEqual({
      ok: true,
      values: {
        sex: couple.sex,
        gender: couple.gender,
        profile_type: couple.profileType,
        sexual_content: couple.sexualContent,
        partner_sex: couple.partnerSex,
        partner_gender: couple.partnerGender,
      },
    });
  });

  it('reports the first invalid sex or gender field', () => {
    expect(parseIdentityDraft({ ...EMPTY_IDENTITY_DRAFT, gender: '7', partnerSex: '9' })).toEqual({
      ok: false,
      error: 'Invalid gender value',
    });
    expect(parseIdentityDraft({ ...EMPTY_IDENTITY_DRAFT, partnerGender: '3' })).toEqual({
      ok: false,
      error: 'Invalid partner gender value',
    });
    expect(parseIdentityDraft(EMPTY_IDENTITY_DRAFT)).toEqual({
      ok: true,
      values: {
        sex: null,
        gender: null,
        profile_type: null,
        sexual_content: null,
        partner_sex: null,
        partner_gender: null,
      },
    });
  });
});

describe('useIdentityDraft', () => {
  it('exposes field props that edit the draft and apply presets', () => {
    const { result } = renderHook(() => useIdentityDraft());

    act(() => result.current.fields.onEditSexChange('1'));
    act(() => result.current.fields.onEditPartnerGenderChange('2'));
    expect(result.current.fields.editSex).toBe('1');
    expect(result.current.draft).toEqual({ ...EMPTY_IDENTITY_DRAFT, sex: '1', partnerGender: '2' });

    const solo = IDENTITY_PRESETS.find((preset) => preset.category === 'solo')!;
    act(() => result.current.fields.onApplyIdentityPreset(solo));
    expect(result.current.draft).toEqual(identityDraftFromPreset(solo));
  });
});
