import { PluginSlot } from '../../plugins/components/PluginSlot';
import { IdentityFields, type IdentityFieldsProps } from '../../user-profile/components/IdentityFields';
import type { UserInfo } from '../lib/usersUtils';

interface UsersEditModalProps extends IdentityFieldsProps {
  isOpen: boolean;
  targetUser: UserInfo | null;
  editName: string;
  editAlias: string;
  editDescription: string;
  isSaving: boolean;
  onClose: () => void;
  onEditNameChange: (value: string) => void;
  onEditAliasChange: (value: string) => void;
  onEditDescriptionChange: (value: string) => void;
  onSave: () => void;
}

export function UsersEditModal({
  isOpen,
  targetUser,
  editName,
  editAlias,
  editDescription,
  editProfileType,
  editSexualContent,
  editSex,
  editGender,
  editPartnerSex,
  editPartnerGender,
  isSaving,
  onClose,
  onEditNameChange,
  onEditAliasChange,
  onEditDescriptionChange,
  onEditProfileTypeChange,
  onEditSexualContentChange,
  onEditSexChange,
  onEditGenderChange,
  onEditPartnerSexChange,
  onEditPartnerGenderChange,
  onApplyIdentityPreset,
  onSave,
}: UsersEditModalProps) {
  if (!isOpen || !targetUser) {
    return null;
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-dialog" onClick={(event) => event.stopPropagation()}>
        <h3>Edit User @{targetUser.username}</h3>
        <PluginSlot
          name="users.edit_modal.top"
          context={{
            user: targetUser,
            formValues: {
              name: editName,
              alias: editAlias,
              description: editDescription,
              profileType: editProfileType,
              sexualContent: editSexualContent,
              sex: editSex,
              gender: editGender,
              partnerSex: editPartnerSex,
              partnerGender: editPartnerGender,
            },
            setFieldValue: (field: string, value: string) => {
              if (field === 'name') onEditNameChange(value);
              else if (field === 'alias') onEditAliasChange(value);
              else if (field === 'description') onEditDescriptionChange(value);
              else if (field === 'profileType') onEditProfileTypeChange(value);
              else if (field === 'sexualContent') onEditSexualContentChange(value);
              else if (field === 'sex') onEditSexChange(value);
              else if (field === 'gender') onEditGenderChange(value);
              else if (field === 'partnerSex') onEditPartnerSexChange(value);
              else if (field === 'partnerGender') onEditPartnerGenderChange(value);
            },
            setValues: (values: Record<string, string>) => {
              if ('name' in values) onEditNameChange(values.name);
              if ('alias' in values) onEditAliasChange(values.alias);
              if ('description' in values) onEditDescriptionChange(values.description);
              if ('profileType' in values) onEditProfileTypeChange(values.profileType);
              if ('sexualContent' in values) onEditSexualContentChange(values.sexualContent);
              if ('sex' in values) onEditSexChange(values.sex);
              if ('gender' in values) onEditGenderChange(values.gender);
              if ('partnerSex' in values) onEditPartnerSexChange(values.partnerSex);
              if ('partnerGender' in values) onEditPartnerGenderChange(values.partnerGender);
            },
          }}
        />
        <div className="edit-user-form">
          <label className="edit-user-field">
            <span>Name</span>
            <input
              type="text"
              value={editName}
              onChange={(event) => onEditNameChange(event.target.value)}
              placeholder="Display name"
            />
          </label>
          <label className="edit-user-field">
            <span>Alias</span>
            <input
              type="text"
              value={editAlias}
              onChange={(event) => onEditAliasChange(event.target.value)}
              placeholder="Add alias username"
            />
          </label>

          <IdentityFields
            presetsLabel="Quick Identity Presets"
            editProfileType={editProfileType}
            editSexualContent={editSexualContent}
            editSex={editSex}
            editGender={editGender}
            editPartnerSex={editPartnerSex}
            editPartnerGender={editPartnerGender}
            onEditProfileTypeChange={onEditProfileTypeChange}
            onEditSexualContentChange={onEditSexualContentChange}
            onEditSexChange={onEditSexChange}
            onEditGenderChange={onEditGenderChange}
            onEditPartnerSexChange={onEditPartnerSexChange}
            onEditPartnerGenderChange={onEditPartnerGenderChange}
            onApplyIdentityPreset={onApplyIdentityPreset}
          />

          <label className="edit-user-field">
            <span>Description</span>
            <textarea
              value={editDescription}
              onChange={(event) => onEditDescriptionChange(event.target.value)}
              rows={4}
              placeholder="Bio/description"
            />
          </label>
        </div>
        <div className="modal-actions">
          <button className="btn-cancel" onClick={onClose}>
            Cancel
          </button>
          <button className="btn-confirm" onClick={onSave} disabled={isSaving}>
            {isSaving ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}
