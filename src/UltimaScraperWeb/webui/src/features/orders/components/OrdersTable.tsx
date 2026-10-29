import { Fragment, type FormEvent } from 'react';

import type {
  AssignSpenderRequest,
  CalculateOrderResponse,
  OrderItemInfo,
  OrderSummary,
  SpenderAssignment,
} from '../../../api/types/orders';
import { formatDate, formatPrice } from '../lib/ordersUtils';
import { appUrl } from '../../../api/http';

interface OrdersTableProps {
  calcData: CalculateOrderResponse | null;
  calculatePending: boolean;
  checkPending: boolean;
  createPending: boolean;
  deleteAllPending: boolean;
  deleteItemPending: boolean;
  deleteOrderPending: boolean;
  executePending: boolean;
  assignPending: boolean;
  displayItems: OrderItemInfo[];
  filteredOrders: OrderSummary[];
  formPrice: string;
  formSite: string;
  formUserId: string;
  formUsername: string;
  onAddUser: (event: FormEvent<HTMLFormElement>) => void;
  onAssignSpender: (performerId: number, request: AssignSpenderRequest) => void;
  onCalculateOrder: (orderId: number, silent?: boolean) => void;
  onCheckOrder: (orderId: number) => void;
  onDeleteAllUsers: (order: OrderSummary) => void;
  onDeleteItem: (item: OrderItemInfo) => void;
  onDeleteOrder: (order: OrderSummary) => void;
  onExecuteOrder: (orderId: number) => void;
  onFormPriceChange: (value: string) => void;
  onFormSiteChange: (value: string) => void;
  onFormUserIdChange: (value: string) => void;
  onFormUsernameChange: (value: string) => void;
  onSelectOrder: (orderId: number | null) => void;
  onToggleAddForm: () => void;
  selectedOrder: OrderSummary | null;
  selectedOrderId: number | null;
  showAddForm: boolean;
  spenders: SpenderAssignment[];
}

export function OrdersTable({
  calcData,
  calculatePending,
  checkPending,
  createPending,
  deleteAllPending,
  deleteItemPending,
  deleteOrderPending,
  executePending,
  assignPending,
  displayItems,
  filteredOrders,
  formPrice,
  formSite,
  formUserId,
  formUsername,
  onAddUser,
  onAssignSpender,
  onCalculateOrder,
  onCheckOrder,
  onDeleteAllUsers,
  onDeleteItem,
  onDeleteOrder,
  onExecuteOrder,
  onFormPriceChange,
  onFormSiteChange,
  onFormUserIdChange,
  onFormUsernameChange,
  onSelectOrder,
  onToggleAddForm,
  selectedOrder,
  selectedOrderId,
  showAddForm,
  spenders,
}: OrdersTableProps) {
  return (
    <div className="orders-table-wrap">
      <table className="orders-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>Status</th>
            <th>Users</th>
            <th>Total</th>
            <th>Created</th>
          </tr>
        </thead>
        <tbody>
          {filteredOrders.map((order) => {
            const isExpanded = selectedOrderId === order.id;
            const isCurrentOrder = selectedOrder?.id === order.id;
            const orderItems = isCurrentOrder ? displayItems : [];
            const orderSpenders = isCurrentOrder ? spenders : [];
            const orderCanBuy = isCurrentOrder
              ? selectedOrder?.status === 'pending' || selectedOrder?.status === 'incomplete'
              : false;
            const hasCalculatedSpenders = isCurrentOrder && calcData !== null;
            const hasAvailableSpenders =
              hasCalculatedSpenders &&
              orderItems.some(
                (item) => item.status !== 'completed' && item.spender_user_id !== null,
              );
            const buyDisabledReason = calculatePending
              ? 'Calculating spender availability'
              : !hasCalculatedSpenders
                ? 'Calculate spender availability before buying'
                : !hasAvailableSpenders
                  ? 'No available spenders for this order'
                  : undefined;

            return (
              <Fragment key={order.id}>
                <tr
                  className={`orders-row ${isExpanded ? 'expanded' : ''}`}
                  role="button"
                  tabIndex={0}
                  onClick={() => onSelectOrder(isExpanded ? null : order.id)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault();
                      onSelectOrder(isExpanded ? null : order.id);
                    }
                  }}
                >
                  <td data-label="Order">#{order.id}</td>
                  <td data-label="Status">
                    <span className={`status-pill status-${order.status}`}>{order.status}</span>
                  </td>
                  <td data-label="Users">{order.item_count}</td>
                  <td data-label="Total">{formatPrice(order.total_price)}</td>
                  <td data-label="Created">{formatDate(order.created_at)}</td>
                </tr>

                {isExpanded && (
                  <tr className="orders-expanded-row">
                    <td colSpan={5}>
                      <div className="orders-expanded-content">
                        <div className="main-header">
                          <div className="main-header-left">
                            <h3>Order #{order.id}</h3>
                            <span className={`status-pill status-${order.status}`}>
                              {order.status}
                            </span>
                            {calcData && (
                              <span className="header-chip accent">
                                Cost: {formatPrice(calcData.total_cost)}
                              </span>
                            )}
                            {calcData && calcData.unassigned_count > 0 && (
                              <span className="header-chip warn">
                                {calcData.unassigned_count} unassigned
                              </span>
                            )}
                          </div>
                          <div className="main-header-right">
                            <button
                              type="button"
                              className="btn btn-secondary btn-sm"
                              onClick={onToggleAddForm}
                            >
                              {showAddForm ? 'Cancel' : '+ Add User'}
                            </button>
                          </div>
                        </div>

                        {showAddForm && (
                          <form className="add-user-form" onSubmit={onAddUser}>
                            <select
                              value={formSite}
                              onChange={(event) => onFormSiteChange(event.target.value)}
                            >
                              <option value="onlyfans">OnlyFans</option>
                              <option value="fansly">Fansly</option>
                            </select>
                            <input
                              type="text"
                              placeholder="Username"
                              value={formUsername}
                              onChange={(event) => onFormUsernameChange(event.target.value)}
                            />
                            <input
                              type="text"
                              placeholder="User ID"
                              value={formUserId}
                              onChange={(event) => onFormUserIdChange(event.target.value)}
                            />
                            <input
                              type="text"
                              placeholder="Price"
                              value={formPrice}
                              onChange={(event) => onFormPriceChange(event.target.value)}
                            />
                            <button
                              type="submit"
                              className="btn btn-primary btn-sm"
                              disabled={createPending}
                            >
                              {createPending ? 'Adding…' : 'Add'}
                            </button>
                          </form>
                        )}

                        {orderSpenders.length > 0 && (
                          <div className="spenders-panel">
                            <h3>Spender Assignments</h3>
                            <div className="spenders-grid">
                              {orderSpenders.map((spender) => (
                                <div key={spender.auth_id} className="spender-card">
                                  <div className="spender-name">
                                    @{spender.username || spender.auth_id}
                                    <span
                                      className={`spender-type-badge type-${spender.spender_type}`}
                                    >
                                      {spender.spender_type}
                                    </span>
                                  </div>
                                  <div className="spender-stats">
                                    <span>Balance: {formatPrice(spender.balance)}</span>
                                    <span>Assigned: {spender.assigned_count} items</span>
                                    <span>Cost: {formatPrice(spender.assigned_cost)}</span>
                                  </div>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        <div className="items-section">
                          <table className="items-table">
                            <thead>
                              <tr>
                                <th>User</th>
                                <th>User ID</th>
                                <th>Price</th>
                                <th>Status</th>
                                {calcData && <th>Spender</th>}
                                <th>Error</th>
                                <th></th>
                              </tr>
                            </thead>
                            <tbody>
                              {orderItems.length === 0 && (
                                <tr>
                                  <td colSpan={calcData ? 7 : 6} className="table-empty">
                                    No users in this order
                                  </td>
                                </tr>
                              )}
                              {orderItems.map((item) => (
                                <tr
                                  key={item.id}
                                  className={
                                    !item.spender_user_id && calcData ? 'row-unassigned' : ''
                                  }
                                >
                                  <td className="cell-user" data-label="User">
                                    <a
                                      href={appUrl(`/users/${item.user_id}`)}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                      className="user-link"
                                    >
                                      @{item.username || item.user_id}
                                    </a>
                                  </td>
                                  <td data-label="User ID">{item.user_id}</td>
                                  <td data-label="Price">{formatPrice(item.price)}</td>
                                  <td data-label="Status">
                                    <span className={`status-pill status-${item.status}`}>
                                      {item.status}
                                    </span>
                                  </td>
                                  {calcData && (
                                    <td data-label="Spender">
                                      <select
                                        className="spender-select"
                                        value={item.spender_user_id ?? ''}
                                        disabled={item.status === 'completed' || assignPending}
                                        onChange={(event) => {
                                          const value = event.target.value;
                                          onAssignSpender(item.id, {
                                            spender_user_id:
                                              value === '' ? null : Number(value),
                                          });
                                        }}
                                      >
                                        <option value="">unassigned</option>
                                        {orderSpenders.map((spender) => (
                                          <option
                                            key={spender.auth_id}
                                            value={spender.auth_id}
                                          >
                                            @{spender.username || spender.auth_id}
                                          </option>
                                        ))}
                                      </select>
                                    </td>
                                  )}
                                  <td className="cell-error" data-label="Error">
                                    {item.error_message || '—'}
                                  </td>
                                  <td data-label="Actions">
                                    {item.status !== 'completed' && (
                                      <button
                                        type="button"
                                        className="btn-icon btn-danger-icon"
                                        title="Remove user"
                                        onClick={() => onDeleteItem(item)}
                                        disabled={deleteItemPending}
                                      >
                                        ×
                                      </button>
                                    )}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>

                        <div className="action-bar">
                          <div className="action-bar-left">
                            <button
                              type="button"
                              className="btn btn-secondary"
                              onClick={() => onCheckOrder(order.id)}
                              disabled={checkPending}
                            >
                              {checkPending ? 'Refreshing…' : 'Refresh Prices'}
                            </button>
                            <button
                              type="button"
                              className="btn btn-primary"
                              onClick={() => onCalculateOrder(order.id)}
                              disabled={calculatePending || !orderCanBuy}
                            >
                              {calculatePending ? 'Calculating…' : 'Calculate'}
                            </button>
                          </div>

                          <div className="action-bar-center">
                            {orderCanBuy && (
                              <button
                                type="button"
                                className="btn btn-buy"
                                title={buyDisabledReason}
                                onClick={() => onExecuteOrder(order.id)}
                                disabled={
                                  executePending ||
                                  calculatePending ||
                                  !hasCalculatedSpenders ||
                                  !hasAvailableSpenders
                                }
                              >
                                {executePending
                                  ? 'Buying…'
                                  : `Buy Order${calcData ? ` — ${formatPrice(calcData.total_cost)}` : ''}`}
                              </button>
                            )}
                          </div>

                          <div className="action-bar-right">
                            <button
                              type="button"
                              className="btn btn-danger-outline"
                              onClick={() => onDeleteAllUsers(order)}
                              disabled={deleteAllPending}
                            >
                              Clear Users
                            </button>
                            <button
                              type="button"
                              className="btn btn-danger-outline"
                              onClick={() => onDeleteOrder(order)}
                              disabled={deleteOrderPending}
                            >
                              Delete Order
                            </button>
                          </div>
                        </div>
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
