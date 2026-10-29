import { useMemo, useState } from 'react';

import type { IdentityFieldsProps } from '../components/IdentityFields';
import {
  EMPTY_IDENTITY_DRAFT,
  identityDraftFromPreset,
  type IdentityDraft,
} from '../lib/identityDraft';

/** Identity select state plus ready-to-spread props for `IdentityFields`. */
export function useIdentityDraft() {
  const [draft, setDraft] = useState<IdentityDraft>(EMPTY_IDENTITY_DRAFT);

  const fields = useMemo((): IdentityFieldsProps => {
    const update = (key: keyof IdentityDraft) => (value: string) =>
      setDraft((current) => ({ ...current, [key]: value }));
    return {
      editProfileType: draft.profileType,
      editSexualContent: draft.sexualContent,
      editSex: draft.sex,
      editGender: draft.gender,
      editPartnerSex: draft.partnerSex,
      editPartnerGender: draft.partnerGender,
      onEditProfileTypeChange: update('profileType'),
      onEditSexualContentChange: update('sexualContent'),
      onEditSexChange: update('sex'),
      onEditGenderChange: update('gender'),
      onEditPartnerSexChange: update('partnerSex'),
      onEditPartnerGenderChange: update('partnerGender'),
      onApplyIdentityPreset: (preset) => setDraft(identityDraftFromPreset(preset)),
    };
  }, [draft]);

  return { draft, setDraft, fields };
}
