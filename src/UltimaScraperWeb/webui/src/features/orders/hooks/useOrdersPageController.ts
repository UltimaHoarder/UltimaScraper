import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';

import {
  assignOrderedPerformerSpender,
  calculateOrder,
  checkOrder,
  createOrderedPerformer,
  deleteOrderedPerformer,
  deleteOrder,
  deleteOrderPerformers,
  executeOrder,
  getOrder,
  listOrders,
} from '../../../api/orders';
import type {
  AssignSpenderRequest,
  CalculateOrderResponse,
  OrderDetailResponse,
  OrderItemInfo,
  OrderListResponse,
  SpenderAssignment,
} from '../../../api/types/orders';
import { isTypingTarget } from '../../../shared/lib/keyboard';
import {
  formatPrice,
  ORDERS_LIVE_REFRESH_MS,
  statusOrder,
} from '../lib/ordersUtils';

function updateCalculatedSpenderAssignment(
  current: CalculateOrderResponse | null,
  performerId: number,
  spenderUserId: number | null,
): CalculateOrderResponse | null {
  if (!current) {
    return current;
  }

  const nextItems = current.items.map((item) => {
    if (item.id !== performerId) {
      return item;
    }

    const spenderUsername =
      spenderUserId !== null
        ? current.spenders.find((spender) => spender.auth_id === spenderUserId)?.username ?? null
        : null;

    return {
      ...item,
      spender_user_id: spenderUserId,
      spender_username: spenderUsername,
    };
  });

  const nextSpenders = current.spenders.map((spender) => {
    const assignedItems = nextItems.filter(
      (item) => item.status !== 'completed' && item.spender_user_id === spender.auth_id,
    );
    const assignedCost = assignedItems.reduce(
      (total, item) => total + (typeof item.price === 'number' ? item.price : 0),
      0,
    );

    return {
      ...spender,
      assigned_count: assignedItems.length,
      assigned_cost: assignedCost,
    };
  });

  const totalCost = nextItems.reduce((total, item) => {
    if (item.status === 'completed' || item.spender_user_id === null) {
      return total;
    }
    return total + (typeof item.price === 'number' ? item.price : 0);
  }, 0);

  const unassignedCount = nextItems.filter(
    (item) => item.status !== 'completed' && item.spender_user_id === null,
  ).length;

  return {
    ...current,
    items: nextItems,
    spenders: nextSpenders,
    total_cost: totalCost,
    unassigned_count: unassignedCount,
  };
}

export function useOrdersPageController() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [statusFilter, setStatusFilter] = useState(() => searchParams.get('status') || '');
  const [searchQuery, setSearchQuery] = useState(() => searchParams.get('q') || '');
  const [formSite, setFormSite] = useState('onlyfans');
  const [formUsername, setFormUsername] = useState('');
  const [formUserId, setFormUserId] = useState('');
  const [formPrice, setFormPrice] = useState('');
  const [selectedOrderId, setSelectedOrderId] = useState<number | null>(() => {
    const raw = searchParams.get('order_id');
    return raw && /^\d+$/.test(raw) ? Number(raw) : null;
  });
  const [calcData, setCalcData] = useState<CalculateOrderResponse | null>(null);
  const [showAddForm, setShowAddForm] = useState(false);
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' } | null>(
    null,
  );
  const lastAutoCalcKeyRef = useRef<string | null>(null);
  const queryClient = useQueryClient();

  const showToast = (message: string, type: 'success' | 'error') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3500);
  };

  const ordersQuery = useQuery<OrderListResponse>({
    queryKey: ['orders', statusFilter],
    queryFn: async () => {
      const response = await listOrders({
        status: statusFilter || undefined,
        limit: 200,
        offset: 0,
      });
      if (!response.success) {
        throw new Error(response.error || 'Failed to load orders');
      }
      return response;
    },
    refetchInterval: ORDERS_LIVE_REFRESH_MS,
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
  });

  const orderDetailQuery = useQuery<OrderDetailResponse>({
    queryKey: ['order-detail', selectedOrderId],
    enabled: selectedOrderId !== null,
    queryFn: () => getOrder(selectedOrderId!),
    refetchInterval: selectedOrderId !== null ? ORDERS_LIVE_REFRESH_MS : false,
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
  });

  const createMutation = useMutation({
    mutationFn: createOrderedPerformer,
    onSuccess: (response) => {
      if (response.success) {
        showToast(
          response.message || `Added @${response.username || response.user_id} to order`,
          'success',
        );
        setFormUsername('');
        setFormUserId('');
        setFormPrice('');
        if (response.order_id) {
          setSelectedOrderId(response.order_id);
        }
        setCalcData(null);
        queryClient.invalidateQueries({ queryKey: ['orders'] });
        queryClient.invalidateQueries({ queryKey: ['order-detail'] });
      } else {
        showToast(response.error || 'Failed to add user', 'error');
      }
    },
    onError: (error: Error) => showToast(`Failed: ${error.message}`, 'error'),
  });

  const calculateMutation = useMutation({
    mutationFn: ({ id }: { id: number; silent?: boolean }) => calculateOrder(id),
    onSuccess: (response, vars) => {
      if (response.success) {
        setCalcData(response);
        if (!vars.silent) {
          showToast('Calculation complete', 'success');
        }
      } else {
        showToast(response.error || 'Failed to calculate', 'error');
      }
    },
    onError: (error: Error) => {
      const message = error.message.toLowerCase();
      if (message.includes('timeout')) {
        showToast(
          'Calculation is taking longer than expected. Backend may still be processing; refreshing order status...',
          'error',
        );
        queryClient.invalidateQueries({ queryKey: ['order-detail'] });
        queryClient.invalidateQueries({ queryKey: ['orders'] });
        return;
      }
      showToast(`Calculate failed: ${error.message}`, 'error');
    },
  });

  const executeMutation = useMutation({
    mutationFn: executeOrder,
    onSuccess: (response) => {
      if (response.success && response.order) {
        setCalcData(null);
        queryClient.invalidateQueries({ queryKey: ['order-detail', response.order.id] });
        const status = response.order.status;
        if (status === 'completed') {
          showToast('Order completed successfully', 'success');
        } else if (status === 'incomplete') {
          showToast('Order partially completed', 'success');
        } else if (status === 'failed') {
          showToast('Order failed — no items purchased', 'error');
        } else {
          showToast('Order processing', 'success');
        }
      } else {
        showToast(response.error || 'Execution failed', 'error');
      }
      queryClient.invalidateQueries({ queryKey: ['orders'] });
    },
    onError: (error: Error) => {
      const message = error.message.toLowerCase();
      if (message.includes('timeout')) {
        showToast(
          'Buy request timed out in UI. Backend may still be processing; refreshing order status...',
          'error',
        );
        queryClient.invalidateQueries({ queryKey: ['orders'] });
        queryClient.invalidateQueries({ queryKey: ['order-detail', selectedOrderId] });
        return;
      }
      showToast(`Execute failed: ${error.message}`, 'error');
    },
  });

  const checkMutation = useMutation({
    mutationFn: checkOrder,
    onSuccess: (response) => {
      if (response.success) {
        queryClient.invalidateQueries({ queryKey: ['order-detail'] });
        showToast('Prices refreshed', 'success');
      } else {
        showToast(response.error || 'Check failed', 'error');
      }
      queryClient.invalidateQueries({ queryKey: ['orders'] });
    },
    onError: (error: Error) => showToast(`Check failed: ${error.message}`, 'error'),
  });

  const deleteItemMutation = useMutation({
    mutationFn: deleteOrderedPerformer,
    onSuccess: (response) => {
      if (response.success) {
        setCalcData(null);
        queryClient.invalidateQueries({ queryKey: ['order-detail'] });
        showToast('User removed', 'success');
      } else {
        showToast(response.error || 'Failed to remove', 'error');
      }
      queryClient.invalidateQueries({ queryKey: ['orders'] });
    },
    onError: (error: Error) => showToast(`Delete failed: ${error.message}`, 'error'),
  });

  const deleteAllUsersMutation = useMutation({
    mutationFn: deleteOrderPerformers,
    onSuccess: (response) => {
      if (response.success) {
        setCalcData(null);
        queryClient.invalidateQueries({ queryKey: ['order-detail'] });
        showToast('All users removed', 'success');
      }
      queryClient.invalidateQueries({ queryKey: ['orders'] });
    },
    onError: (error: Error) => showToast(`Failed: ${error.message}`, 'error'),
  });

  const assignSpenderMutation = useMutation({
    mutationFn: ({
      performerId,
      request,
    }: {
      performerId: number;
      request: AssignSpenderRequest;
    }) => assignOrderedPerformerSpender(performerId, request),
    onSuccess: (response, vars) => {
      if (response.success) {
        setCalcData((current) =>
          updateCalculatedSpenderAssignment(
            current,
            vars.performerId,
            vars.request.spender_user_id,
          ),
        );

        const orderId = response.item?.order_id ?? selectedOrderId;
        if (orderId !== null) {
          queryClient.invalidateQueries({ queryKey: ['order-detail', orderId] });
        } else {
          queryClient.invalidateQueries({ queryKey: ['order-detail'] });
        }
      } else {
        showToast(response.error || 'Failed to assign spender', 'error');
      }
    },
    onError: (error: Error) => showToast(`Assign failed: ${error.message}`, 'error'),
  });

  const deleteOrderMutation = useMutation({
    mutationFn: deleteOrder,
    onSuccess: (response) => {
      if (response.success) {
        setSelectedOrderId(null);
        setCalcData(null);
        showToast('Order deleted', 'success');
      }
      queryClient.invalidateQueries({ queryKey: ['orders'] });
    },
    onError: (error: Error) => showToast(`Failed: ${error.message}`, 'error'),
  });

  const orders = useMemo(() => {
    const list = ordersQuery.data?.orders ?? [];
    return [...list].sort(
      (left, right) => (statusOrder[left.status] ?? 99) - (statusOrder[right.status] ?? 99),
    );
  }, [ordersQuery.data?.orders]);

  const selectedOrder = useMemo(
    () => orders.find((order) => order.id === selectedOrderId) ?? null,
    [orders, selectedOrderId],
  );
  const resolvedSelectedOrderId = selectedOrder?.id ?? null;

  useEffect(() => {
    const nextParams = new URLSearchParams(searchParams);
    if (statusFilter) nextParams.set('status', statusFilter);
    else nextParams.delete('status');
    if (searchQuery.trim()) nextParams.set('q', searchQuery.trim());
    else nextParams.delete('q');
    if (resolvedSelectedOrderId !== null) nextParams.set('order_id', String(resolvedSelectedOrderId));
    else nextParams.delete('order_id');

    if (nextParams.toString() !== searchParams.toString()) {
      setSearchParams(nextParams, { replace: true });
    }
  }, [resolvedSelectedOrderId, searchParams, searchQuery, setSearchParams, statusFilter]);

  const filteredOrders = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    if (!query) {
      return orders;
    }
    return orders.filter((order) => {
      return (
        String(order.id).includes(query) ||
        order.status.toLowerCase().includes(query) ||
        formatPrice(order.total_price).toLowerCase().includes(query)
      );
    });
  }, [orders, searchQuery]);

  const ordersLoadErrorMessage =
    ordersQuery.error instanceof Error ? ordersQuery.error.message : 'Failed to load orders';

  const effectiveCalcData = resolvedSelectedOrderId !== null ? calcData : null;
  const displayItems: OrderItemInfo[] =
    effectiveCalcData?.items ?? orderDetailQuery.data?.items ?? [];
  const spenders: SpenderAssignment[] = effectiveCalcData?.spenders ?? [];

  const handleAddUser = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const userId = formUserId.trim() ? Number(formUserId.trim()) : undefined;
    const price = formPrice.trim() ? Number(formPrice.trim()) : undefined;
    if (!formUsername.trim() && !userId) {
      showToast('Username or user ID is required', 'error');
      return;
    }
    createMutation.mutate({
      site: formSite,
      user_id: userId,
      username: formUsername.trim() || undefined,
      price: Number.isNaN(price) ? undefined : price,
      auto_execute: false,
    });
  };

  const canBuy = selectedOrder?.status === 'pending' || selectedOrder?.status === 'incomplete';
  const autoCalcKey = useMemo(() => {
    if (!selectedOrder || !canBuy) {
      return null;
    }
    const items = orderDetailQuery.data?.items ?? [];
    const itemSignature = items
      .map(
        (item) =>
          `${item.id}:${item.user_id}:${item.price}:${item.status}:${item.spender_user_id ?? ''}`,
      )
      .join('|');
    return `${selectedOrder.id}:${selectedOrder.status}:${items.length}:${itemSignature}`;
  }, [selectedOrder, canBuy, orderDetailQuery.data?.items]);

  useEffect(() => {
    if (!autoCalcKey || !selectedOrderId || calculateMutation.isPending) {
      return;
    }
    if (lastAutoCalcKeyRef.current === autoCalcKey) {
      return;
    }
    lastAutoCalcKeyRef.current = autoCalcKey;
    calculateMutation.mutate({ id: selectedOrderId, silent: true });
  }, [autoCalcKey, selectedOrderId, calculateMutation]);

  const handleSelectOrder = useCallback((orderId: number | null) => {
    setSelectedOrderId(orderId);
    setCalcData(null);
    if (orderId === null) {
      setShowAddForm(false);
    }
  }, []);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (
        event.defaultPrevented ||
        showAddForm ||
        isTypingTarget(event.target)
      ) {
        return;
      }

      if (event.key === 'Escape' && selectedOrderId !== null) {
        event.preventDefault();
        handleSelectOrder(null);
        return;
      }

      if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') {
        return;
      }

      if (!filteredOrders.length) {
        return;
      }

      event.preventDefault();
      const currentIndex =
        selectedOrderId === null
          ? -1
          : filteredOrders.findIndex((order) => order.id === selectedOrderId);
      const nextIndex =
        event.key === 'ArrowDown'
          ? Math.min(currentIndex + 1, filteredOrders.length - 1)
          : currentIndex === -1
            ? filteredOrders.length - 1
            : Math.max(currentIndex - 1, 0);

      handleSelectOrder(filteredOrders[nextIndex]?.id ?? null);
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [filteredOrders, handleSelectOrder, selectedOrderId, showAddForm]);

  const handleDismissToast = () => setToast(null);

  return {
    assignPending: assignSpenderMutation.isPending,
    calcData,
    calculatePending: calculateMutation.isPending,
    checkPending: checkMutation.isPending,
    createPending: createMutation.isPending,
    deleteAllPending: deleteAllUsersMutation.isPending,
    deleteItemPending: deleteItemMutation.isPending,
    deleteOrderPending: deleteOrderMutation.isPending,
    displayItems,
    executePending: executeMutation.isPending,
    filteredOrders,
    formPrice,
    formSite,
    formUserId,
    formUsername,
    handleAddUser,
    handleDismissToast,
    handleSelectOrder,
    isLoading: ordersQuery.isLoading,
    ordersLoadErrorMessage,
    setFormPrice,
    setFormSite,
    setFormUserId,
    setFormUsername,
    setSearchQuery,
    setShowAddForm,
    setStatusFilter,
    showAddForm,
    searchQuery,
    selectedOrder,
    selectedOrderId,
    spenders,
    statusFilter,
    toast,
    onAssignSpender: (performerId: number, request: AssignSpenderRequest) =>
      assignSpenderMutation.mutate({ performerId, request }),
    onCalculateOrder: (orderId: number, silent?: boolean) =>
      calculateMutation.mutate({ id: orderId, silent }),
    onCheckOrder: (orderId: number) => checkMutation.mutate(orderId),
    onDeleteAllUsers: (orderId: number) => deleteAllUsersMutation.mutate(orderId),
    onDeleteItem: (itemId: number) => deleteItemMutation.mutate(itemId),
    onDeleteOrder: (orderId: number) => deleteOrderMutation.mutate(orderId),
    onExecuteOrder: (orderId: number) => executeMutation.mutate(orderId),
    hasError: Boolean(ordersQuery.error),
  };
}
