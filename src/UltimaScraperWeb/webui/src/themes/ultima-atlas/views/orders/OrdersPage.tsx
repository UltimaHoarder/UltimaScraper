import { useMemo, useState } from 'react';

import type { OrderItemInfo, OrderSummary } from '../../../../api/types/orders';
import { OrdersTable } from '../../../../features/orders/components/OrdersTable';
import { OrdersToast } from '../../../../features/orders/components/OrdersToast';
import { useOrdersPageController } from '../../../../features/orders/hooks/useOrdersPageController';
import { ConfirmDialog } from '../../../../shared/ui/ConfirmDialog';
import {
  OperationsNotice,
  OperationsState,
} from '../../patterns/OperationsChrome';
import { WorkspacePageHeader } from '../../../../shared/ui/WorkspacePageHeader';
import './OrdersPage.css';

type OrderConfirmState =
  | { kind: 'item'; item: OrderItemInfo }
  | { kind: 'all-users'; order: OrderSummary }
  | { kind: 'order'; order: OrderSummary };

export function OrdersPage() {
  const controller = useOrdersPageController();
  const [confirmState, setConfirmState] = useState<OrderConfirmState | null>(null);
  const orderBadges = useMemo(() => {
    const statusCounts = controller.filteredOrders.reduce<Record<string, number>>((acc, order) => {
      acc[order.status] = (acc[order.status] ?? 0) + 1;
      return acc;
    }, {});

    return [
      { label: 'Visible', value: String(controller.filteredOrders.length), tone: 'neutral' as const },
      { label: 'Pending', value: String(statusCounts.pending ?? 0), tone: 'accent' as const },
      { label: 'Running', value: String(statusCounts.running ?? 0), tone: 'warning' as const },
      {
        label: 'Failed',
        value: String(statusCounts.failed ?? 0),
        tone: (statusCounts.failed ?? 0) > 0 ? ('danger' as const) : ('neutral' as const),
      },
    ];
  }, [controller.filteredOrders]);

  return (
    <div className="orders-page orders-page-v2">
      <OrdersToast
        toast={controller.toast}
        onDismiss={controller.handleDismissToast}
      />

      <WorkspacePageHeader
        eyebrow="Jobs"
        title="Orders"
        subtitle="Review pending purchases, inspect order composition, and execute fulfillment work from a single queue view."
        badges={orderBadges}
        icon="≡"
      />

      {controller.statusFilter || controller.searchQuery ? (
        <OperationsNotice tone="info" title="Filtered order view">
          {controller.statusFilter
            ? `Status: ${controller.statusFilter}. `
            : ''}
          {controller.searchQuery
            ? `Search: ${controller.searchQuery}. `
            : ''}
          Clear the toolbar inputs to return to the full queue.
        </OperationsNotice>
      ) : null}

      <section className="orders-toolbar">
        <h2>Orders</h2>
        <div className="orders-toolbar-controls">
          <select
            className="filter-select"
            value={controller.statusFilter}
            onChange={(event) => controller.setStatusFilter(event.target.value)}
          >
            <option value="">All</option>
            <option value="pending">Pending</option>
            <option value="running">Running</option>
            <option value="completed">Completed</option>
            <option value="incomplete">Incomplete</option>
            <option value="failed">Failed</option>
          </select>
          <input
            type="text"
            className="orders-search"
            placeholder="Search orders"
            value={controller.searchQuery}
            onChange={(event) => controller.setSearchQuery(event.target.value)}
          />
        </div>
      </section>

      <main className="orders-main orders-table-main">
        {controller.isLoading && (
          <OperationsState
            variant="loading"
            title="Loading orders"
            description="Refreshing current order state and detail rows."
            compact
          />
        )}
        {controller.hasError && (
          <OperationsState
            variant="error"
            title="Failed to load orders"
            description={controller.ordersLoadErrorMessage}
            compact
          />
        )}
        {!controller.isLoading &&
          !controller.hasError &&
          controller.filteredOrders.length === 0 && (
            <OperationsState
              title="No matching orders"
              description="Adjust the status filter or search query to widen the result set."
              compact
            />
          )}

        {!controller.isLoading &&
          !controller.hasError &&
          controller.filteredOrders.length > 0 && (
            <OrdersTable
              assignPending={controller.assignPending}
              calcData={controller.calcData}
              calculatePending={controller.calculatePending}
              checkPending={controller.checkPending}
              createPending={controller.createPending}
              deleteAllPending={controller.deleteAllPending}
              deleteItemPending={controller.deleteItemPending}
              deleteOrderPending={controller.deleteOrderPending}
              displayItems={controller.displayItems}
              executePending={controller.executePending}
              filteredOrders={controller.filteredOrders}
              formPrice={controller.formPrice}
              formSite={controller.formSite}
              formUserId={controller.formUserId}
              formUsername={controller.formUsername}
              onAddUser={controller.handleAddUser}
              onAssignSpender={controller.onAssignSpender}
              onCalculateOrder={controller.onCalculateOrder}
              onCheckOrder={controller.onCheckOrder}
              onDeleteAllUsers={(order) => setConfirmState({ kind: 'all-users', order })}
              onDeleteItem={(item) => setConfirmState({ kind: 'item', item })}
              onDeleteOrder={(order) => setConfirmState({ kind: 'order', order })}
              onExecuteOrder={controller.onExecuteOrder}
              onFormPriceChange={controller.setFormPrice}
              onFormSiteChange={controller.setFormSite}
              onFormUserIdChange={controller.setFormUserId}
              onFormUsernameChange={controller.setFormUsername}
              onSelectOrder={controller.handleSelectOrder}
              onToggleAddForm={() =>
                controller.setShowAddForm(!controller.showAddForm)
              }
              selectedOrder={controller.selectedOrder}
              selectedOrderId={controller.selectedOrderId}
              showAddForm={controller.showAddForm}
              spenders={controller.spenders}
            />
          )}
      </main>

      <ConfirmDialog
        isOpen={confirmState !== null}
        title={
          confirmState?.kind === 'item'
            ? 'Remove user from order?'
            : confirmState?.kind === 'all-users'
              ? 'Clear all users from this order?'
              : confirmState?.kind === 'order'
                ? 'Delete order?'
                : ''
        }
        description={
          confirmState?.kind === 'item'
            ? `Remove @${confirmState.item.username || confirmState.item.user_id} from the current order.`
            : confirmState?.kind === 'all-users'
              ? `Remove every pending user from order #${confirmState.order.id}. Completed purchases remain in the historical record.`
              : confirmState?.kind === 'order'
                ? `Delete order #${confirmState.order.id}. This removes the workspace record and any remaining queued users.`
                : ''
        }
        confirmLabel={
          confirmState?.kind === 'item'
            ? 'Remove user'
            : confirmState?.kind === 'all-users'
              ? 'Clear users'
              : 'Delete order'
        }
        isPending={
          controller.deleteItemPending ||
          controller.deleteAllPending ||
          controller.deleteOrderPending
        }
        onClose={() => setConfirmState(null)}
        onConfirm={() => {
          if (!confirmState) {
            return;
          }
          if (confirmState.kind === 'item') {
            controller.onDeleteItem(confirmState.item.id);
          } else if (confirmState.kind === 'all-users') {
            controller.onDeleteAllUsers(confirmState.order.id);
          } else {
            controller.onDeleteOrder(confirmState.order.id);
          }
          setConfirmState(null);
        }}
      />
    </div>
  );
}
