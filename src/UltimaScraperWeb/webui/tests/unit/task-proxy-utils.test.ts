import { describe, expect, it } from 'vitest';
import type { TaskDetail } from '../../src/api/types/jobs';
import type { NetworkProxy } from '../../src/api/types/network';
import {
  buildTaskRouteSequence,
  formatProxyHost,
  getTaskProxySummary,
  maskProxyUrl,
} from '../../src/features/jobs/lib/taskProxyUtils';

describe('taskProxyUtils', () => {
  describe('maskProxyUrl', () => {
    it('returns Direct for null, undefined, empty, or direct string', () => {
      expect(maskProxyUrl(null)).toBe('Direct');
      expect(maskProxyUrl(undefined)).toBe('Direct');
      expect(maskProxyUrl('')).toBe('Direct');
      expect(maskProxyUrl('   ')).toBe('Direct');
      expect(maskProxyUrl('direct')).toBe('Direct');
      expect(maskProxyUrl('DIRECT')).toBe('Direct');
    });

    it('masks username and password in proxy URLs', () => {
      expect(maskProxyUrl('http://alice:secret123@proxy.example.com:8080')).toBe(
        'http://***:***@proxy.example.com:8080',
      );
      expect(maskProxyUrl('socks5://user:pass@192.168.1.50:1080')).toBe(
        'socks5://***:***@192.168.1.50:1080',
      );
    });

    it('preserves URLs without credentials', () => {
      expect(maskProxyUrl('http://proxy.example.com:8080')).toBe(
        'http://proxy.example.com:8080',
      );
    });
  });

  describe('formatProxyHost', () => {
    it('formats host and port cleanly', () => {
      expect(formatProxyHost('http://user:pass@proxy.example.com:8080')).toBe(
        'proxy.example.com:8080',
      );
      expect(formatProxyHost('socks5://192.168.1.1:1080')).toBe('192.168.1.1:1080');
      expect(formatProxyHost(null)).toBe('Direct');
      expect(formatProxyHost('direct')).toBe('Direct');
    });
  });

  describe('buildTaskRouteSequence', () => {
    const mockProxies: NetworkProxy[] = [
      {
        id: 'p1',
        url: 'http://us.proxy.com:8080',
        username: null,
        max_connections: 10,
        assigned_auths: [101],
        group: 'US-East',
        geolocation: {
          ip: '1.2.3.4',
          success: true,
          country: 'United States',
          country_code: 'US',
          flag: { emoji: '🇺🇸' },
        },
      },
      {
        id: 'p2',
        url: 'http://de.proxy.com:8080',
        username: null,
        max_connections: 10,
        assigned_auths: [],
        group: 'EU-West',
        geolocation: {
          ip: '5.6.7.8',
          success: true,
          country: 'Germany',
          country_code: 'DE',
          flag: { emoji: '🇩🇪' },
        },
      },
    ];

    it('reconstructs ordered hops from payload fallbacks and direct index', () => {
      const task: TaskDetail = {
        started_at: null,
        completed_at: null,
        task_id: 'task-1',
        task_type: 'scrape_profile',
        status: 'completed',
        site: 'onlyfans',
        username: 'creator1',
        content_type: 'profile',
        progress: 1,
        items_processed: 1,
        items_total: 1,
        error: null,
        payload: {
          guest_proxy_url: 'http://us.proxy.com:8080',
          guest_fallback_proxy_urls: ['http://de.proxy.com:8080'],
          guest_direct_route_index: 2, // Direct placed as 3rd route (Hop 3)
        },
        proxy_hop_used: 1, // Succeeded on Hop 2 (DE)
      };

      const hops = buildTaskRouteSequence(task, mockProxies);
      expect(hops).toHaveLength(3);

      // Hop 1: US proxy (failed before fallback)
      expect(hops[0]).toMatchObject({
        hop_number: 1,
        role_label: 'Primary',
        is_direct: false,
        status: 'failed',
        country: 'United States',
        flag_emoji: '🇺🇸',
      });

      // Hop 2: DE proxy (used / succeeded)
      expect(hops[1]).toMatchObject({
        hop_number: 2,
        role_label: 'Fallback 1',
        is_direct: false,
        status: 'used',
        country: 'Germany',
        flag_emoji: '🇩🇪',
      });

      // Hop 3: Direct connection (untried because Hop 2 succeeded)
      expect(hops[2]).toMatchObject({
        hop_number: 3,
        role_label: 'Fallback 2 (Direct)',
        is_direct: true,
        status: 'untried',
        url: null,
      });
    });

    it('handles direct route as Hop 1 (direct placed at index 0)', () => {
      const task: TaskDetail = {
        started_at: null,
        completed_at: null,
        task_id: 'task-2',
        task_type: 'scrape_profile',
        status: 'completed',
        site: 'onlyfans',
        username: 'creator2',
        content_type: 'profile',
        progress: 1,
        items_processed: 1,
        items_total: 1,
        error: null,
        proxy_routes: [null, 'http://us.proxy.com:8080'],
        proxy_hop_used: 0, // Succeeded on Direct
      };

      const hops = buildTaskRouteSequence(task, mockProxies);
      expect(hops).toHaveLength(2);
      expect(hops[0]).toMatchObject({
        hop_number: 1,
        role_label: 'Primary (Direct)',
        is_direct: true,
        status: 'used',
      });
      expect(hops[1]).toMatchObject({
        hop_number: 2,
        role_label: 'Fallback 1',
        is_direct: false,
        status: 'untried',
      });
    });

    it('marks all hops as failed when task failed across all hops', () => {
      const task: TaskDetail = {
        started_at: null,
        completed_at: null,
        task_id: 'task-3',
        task_type: 'scrape_profile',
        status: 'failed',
        site: 'onlyfans',
        username: 'creator3',
        content_type: 'profile',
        progress: 0,
        items_processed: 0,
        items_total: 1,
        error: 'Failed across all 3 routes',
        proxy_routes: [
          'http://us.proxy.com:8080',
          'http://de.proxy.com:8080',
          null,
        ],
        proxy_hop_used: null,
      };

      const hops = buildTaskRouteSequence(task, mockProxies);
      expect(hops).toHaveLength(3);
      expect(hops[0].status).toBe('failed');
      expect(hops[1].status).toBe('failed');
      expect(hops[2].status).toBe('failed');
    });

    it('correctly maps invalid_user conclusive miss without falling back to direct connection', () => {
      const task: TaskDetail = {
        started_at: null,
        completed_at: null,
        task_id: 'task-inv-1',
        task_type: 'scrape_profile',
        status: 'completed',
        site: 'onlyfans',
        username: 'nonexistent',
        content_type: 'profile',
        progress: 1,
        items_processed: 0,
        items_total: 0,
        error: null,
        message: "User ID '22022776' not found via guest auth (attempted 2 proxy route(s)); recorded in invalid_users",
        proxy_routes: [
          'http://proxy1.com:8080',
          'http://proxy2.com:8080',
          'http://proxy3.com:8080',
        ],
        proxy_url: null,
        proxy_hop_used: null,
        result: {
          output: {
            invalid_user: true,
            user_id: 22022776,
            proxy_routes_attempted: [0, 1],
          },
        },
      };

      const hops = buildTaskRouteSequence(task);
      expect(hops).toHaveLength(3);
      expect(hops[0].is_direct).toBe(false);
      expect(hops[0].status).toBe('failed');
      expect(hops[1].is_direct).toBe(false);
      expect(hops[1].status).toBe('failed');
      expect(hops[2].is_direct).toBe(false);
      expect(hops[2].status).toBe('untried');
    });

    it('does not synthesize direct connection fallback when direct connection is disabled or task is invalid user', () => {
      const task: TaskDetail = {
        started_at: null,
        completed_at: null,
        task_id: 'task-inv-2',
        task_type: 'scrape_profile',
        status: 'completed',
        site: 'onlyfans',
        username: 'nonexistent',
        content_type: 'profile',
        progress: 1,
        items_processed: 0,
        items_total: 0,
        error: null,
        message: "User ID '22022776' not found via guest auth (attempted 3 proxy route(s)); recorded in invalid_users",
        proxy_url: null,
        result: {
          output: {
            invalid_user: true,
            user_id: 22022776,
          },
        },
      };

      const hops = buildTaskRouteSequence(task);
      expect(hops).toHaveLength(0); // Should not synthesize [null] (Direct Connection)!
    });
  });

  describe('getTaskProxySummary', () => {
    it('produces correct summary text and badge labels for multi-hop routes', () => {
      const task: TaskDetail = {
        started_at: null,
        completed_at: null,
        task_id: 'task-4',
        task_type: 'scrape_posts',
        status: 'completed',
        site: 'onlyfans',
        username: 'creator4',
        content_type: 'posts',
        progress: 1,
        items_processed: 50,
        items_total: 50,
        error: null,
        proxy_routes: [
          'http://us.proxy.com:8080',
          'http://de.proxy.com:8080',
        ],
        proxy_hop_used: 1,
      };

      const summary = getTaskProxySummary(task, [
        {
          id: 'p2',
          url: 'http://de.proxy.com:8080',
          username: null,
          max_connections: 10,
          assigned_auths: [],
          geolocation: {
            ip: '5.6.7.8',
            success: true,
            country: 'Germany',
            flag: { emoji: '🇩🇪' },
          },
        },
      ]);

      expect(summary.hasHops).toBe(true);
      expect(summary.hopCount).toBe(2);
      expect(summary.usedHopNumber).toBe(2);
      expect(summary.flagEmoji).toBe('🇩🇪');
      expect(summary.summaryText).toBe('Hop 2 of 2 · 🇩🇪 Germany');
      expect(summary.badgeLabel).toBe('🇩🇪 Hop 2/2');
    });

    it('produces correct summary text and badge label for invalid user conclusive miss without direct connection', () => {
      const task: TaskDetail = {
        started_at: null,
        completed_at: null,
        task_id: 'task-inv-summary',
        task_type: 'scrape_profile',
        status: 'completed',
        site: 'onlyfans',
        username: 'nonexistent',
        content_type: 'profile',
        progress: 1,
        items_processed: 0,
        items_total: 0,
        error: null,
        message: "User ID '22022776' not found via guest auth (attempted 2 proxy route(s)); recorded in invalid_users",
        proxy_routes: [
          'http://proxy1.com:8080',
          'http://proxy2.com:8080',
          'http://proxy3.com:8080',
        ],
        proxy_url: null,
        proxy_hop_used: null,
        result: {
          output: {
            invalid_user: true,
            user_id: 22022776,
            proxy_routes_attempted: [0, 1],
          },
        },
      };

      const summary = getTaskProxySummary(task);
      expect(summary.hasHops).toBe(true);
      expect(summary.hopCount).toBe(3);
      expect(summary.usedHopNumber).toBeNull();
      expect(summary.summaryText).toBe('2 routes checked · Profile not found (404)');
      expect(summary.badgeLabel).toBe('2 Hops Missed (404)');
    });
  });
});
