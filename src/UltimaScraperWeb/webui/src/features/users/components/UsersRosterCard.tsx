import type { ComponentProps } from 'react';
import { UserCard } from '../../../components/users/UserCard';
import type { UserInfo } from '../../../api/types/users';
import { formatUserNumber, formatUserPrice } from '../lib/usersUtils';

type Props = Omit<ComponentProps<typeof UserCard<UserInfo>>,
  'rootClassName' | 'inactiveLabel' | 'formatNumber' | 'formatPrice' | 'extraActions' | 'extraMenuActions' | 'showViewButton'> & {
  isSubscribePending: boolean;
  isUpdatePending: boolean;
  onSubscribeUser: (user: UserInfo) => void;
  onEditUser: (user: UserInfo) => void;
};

/** The same roster card, including its action row, on Users and Favourites. */
export function UsersRosterCard({ isSubscribePending, isUpdatePending, onSubscribeUser, onEditUser, ...props }: Props) {
  return <UserCard {...props} rootClassName="user-card" inactiveLabel="Inactive"
    formatNumber={formatUserNumber} formatPrice={formatUserPrice} showViewButton={false}
    extraActions={[{ key: 'subscribe', label: isSubscribePending ? 'Subscribing...' : 'Subscribe',
      title: 'Buy subscription using best spender', className: 'btn-subscribe',
      disabled: isSubscribePending, onClick: () => onSubscribeUser(props.item) }]}
    extraMenuActions={[{ key: 'edit-user', label: 'Edit User', title: 'Edit user profile fields',
      disabled: isUpdatePending, onClick: () => onEditUser(props.item) }]} />;
}
