import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { UserProfileEditModal } from '../../src/features/user-profile/components/UserProfileEditModal';
import { UsersEditModal } from '../../src/features/users/components/UsersEditModal';
import { pluginRegistry } from '../../src/features/plugins/lib/pluginHost';

describe('user edit modals', () => {
  it('renders alias input in the users edit modal', () => {
    const onEditAliasChange = vi.fn();

    render(
      <UsersEditModal
        isOpen
        targetUser={{
          id: 10,
          user_id: 10,
          username: 'alice',
          name: 'Alice',
          sex: null,
          gender: 1,
          description: null,
          avatar_url: null,
          header_url: null,
          price: 0,
          post_count: 0,
          media_count: 0,
          image_count: 0,
          video_count: 0,
          favorite: false,
          is_active: true,
          is_subscribed: false,
          is_pending_order: false,
          site: 'onlyfans',
          downloaded_at: null,
          last_checked_at: null,
        }}
        editName=""
        editAlias=""
        editDescription=""
        editProfileType=""
        editSexualContent=""
        editSex=""
        editGender="1"
        editPartnerSex=""
        editPartnerGender=""
        isSaving={false}
        onClose={vi.fn()}
        onEditNameChange={vi.fn()}
        onEditAliasChange={onEditAliasChange}
        onEditDescriptionChange={vi.fn()}
        onEditProfileTypeChange={vi.fn()}
        onEditSexualContentChange={vi.fn()}
        onEditSexChange={vi.fn()}
        onEditGenderChange={vi.fn()}
        onEditPartnerSexChange={vi.fn()}
        onEditPartnerGenderChange={vi.fn()}
        onApplyIdentityPreset={vi.fn()}
        onSave={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText('Alias'), {
      target: { value: 'shadow_name' },
    });

    expect(onEditAliasChange).toHaveBeenCalledWith('shadow_name');
  });

  it('renders gender input in the users edit modal', () => {
    const onEditGenderChange = vi.fn();

    render(
      <UsersEditModal
        isOpen
        targetUser={{
          id: 10,
          user_id: 10,
          username: 'alice',
          name: 'Alice',
          sex: null,
          gender: null,
          description: null,
          avatar_url: null,
          header_url: null,
          price: 0,
          post_count: 0,
          media_count: 0,
          image_count: 0,
          video_count: 0,
          favorite: false,
          is_active: true,
          is_subscribed: false,
          is_pending_order: false,
          site: 'onlyfans',
          downloaded_at: null,
          last_checked_at: null,
        }}
        editName=""
        editAlias=""
        editDescription=""
        editProfileType=""
        editSexualContent=""
        editSex=""
        editGender=""
        editPartnerSex=""
        editPartnerGender=""
        isSaving={false}
        onClose={vi.fn()}
        onEditNameChange={vi.fn()}
        onEditAliasChange={vi.fn()}
        onEditDescriptionChange={vi.fn()}
        onEditProfileTypeChange={vi.fn()}
        onEditSexualContentChange={vi.fn()}
        onEditSexChange={vi.fn()}
        onEditGenderChange={onEditGenderChange}
        onEditPartnerSexChange={vi.fn()}
        onEditPartnerGenderChange={vi.fn()}
        onApplyIdentityPreset={vi.fn()}
        onSave={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText('Gender'), {
      target: { value: '2' },
    });

    expect(onEditGenderChange).toHaveBeenCalledWith('2');
  });

  it('renders plugin components registered in users.edit_modal.top slot', () => {
    const api = pluginRegistry.activate({ plugin_id: 'modal-test', display_name: 'Modal Test', plugin_version: '1', entry: '', styles: [], mode: 'native' });
    const unregister = api.registerSlot('users.edit_modal.top', () => (
      <div data-testid="plugin-identity-banner">
        <span>Suggested Identity: <strong>Trans Woman</strong></span>
      </div>
    ));

    try {
      render(
        <UsersEditModal
          isOpen
          targetUser={{
            id: 10,
            user_id: 10,
            username: 'daisy',
            name: 'Daisy',
            sex: null,
            gender: null,
            description: 'Proud trans girl 🏳️‍⚧️',
            avatar_url: null,
            header_url: null,
            price: 0,
            post_count: 0,
            media_count: 0,
            image_count: 0,
            video_count: 0,
            favorite: false,
            is_active: true,
            is_subscribed: false,
            is_pending_order: false,
            site: 'onlyfans',
            downloaded_at: null,
            last_checked_at: null,
          }}
          editName="Daisy"
          editAlias=""
          editDescription="Proud trans girl 🏳️‍⚧️"
          editProfileType="0"
          editSexualContent="4"
          editSex="1"
          editGender="0"
          editPartnerSex=""
          editPartnerGender=""
          isSaving={false}
          onClose={vi.fn()}
          onEditNameChange={vi.fn()}
          onEditAliasChange={vi.fn()}
          onEditDescriptionChange={vi.fn()}
          onEditProfileTypeChange={vi.fn()}
          onEditSexualContentChange={vi.fn()}
          onEditSexChange={vi.fn()}
          onEditGenderChange={vi.fn()}
          onEditPartnerSexChange={vi.fn()}
          onEditPartnerGenderChange={vi.fn()}
          onApplyIdentityPreset={vi.fn()}
          onSave={vi.fn()}
        />,
      );

      expect(screen.getByTestId('plugin-identity-banner')).toBeInTheDocument();
      expect(screen.getByText(/Suggested Identity:/)).toBeInTheDocument();
      expect(screen.getAllByText('Trans Woman').length).toBeGreaterThanOrEqual(2);
    } finally {
      unregister();
      pluginRegistry.deactivate('modal-test');
    }
  });

  it('renders alias input in the profile edit modal', () => {
    const onEditAliasChange = vi.fn();

    render(
      <UserProfileEditModal
        isOpen
        username="alice"
        editName="Alice"
        editAlias=""
        editDescription=""
        editSex=""
        editGender=""
        isSaving={false}
        onClose={vi.fn()}
        onEditNameChange={vi.fn()}
        onEditAliasChange={onEditAliasChange}
        onEditDescriptionChange={vi.fn()}
        onEditSexChange={vi.fn()}
        onEditGenderChange={vi.fn()}
        onSave={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText('Alias'), {
      target: { value: 'night_shift' },
    });

    expect(onEditAliasChange).toHaveBeenCalledWith('night_shift');
  });
});
