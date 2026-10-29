import React, { type ComponentType } from 'react';
import type { ActivePluginWebUI } from '../../../api/types/plugins';

export const PLUGIN_SLOTS = [
  'users.card.badges', 'users.table.identity_extra', 'users.edit_modal.top',
  'user.profile.panels', 'navigation.pages',
] as const;
export type PluginSlotName = typeof PLUGIN_SLOTS[number];
export type PluginContext = Record<string, unknown>;
export type PluginTransport = (pluginId: string, operation: 'invoke' | 'jobs', taskType: string,
  payload: PluginContext, signal: AbortSignal) => Promise<unknown>;

interface Registration {
  id: string; pluginId: string; component: ComponentType<PluginContext>; order: number;
}
interface Installation {
  descriptor: ActivePluginWebUI; controller: AbortController; generation: symbol;
}
export interface ScopedPluginApi {
  version: string;
  pluginId: string;
  React: typeof React;
  signal: AbortSignal;
  registerSlot: (name: PluginSlotName, component: ComponentType<PluginContext>, options?: { id?: string; order?: number }) => () => void;
  unregisterSlot: (name: PluginSlotName, component: ComponentType<PluginContext>) => void;
  registerHook: (name: string, handler: (...args: unknown[]) => unknown) => () => void;
  triggerHook: (name: string, ...args: unknown[]) => unknown[];
  invoke: (taskType: string, payload: PluginContext) => Promise<unknown>;
  submitTask: (taskType: string, payload: PluginContext) => Promise<unknown>;
}

export class PluginRegistry {
  private installations = new Map<string, Installation>();
  private slots = new Map<PluginSlotName, Registration[]>();
  private hooks = new Map<string, { pluginId: string; handler: (...args: unknown[]) => unknown }[]>();
  private listeners = new Set<() => void>();
  private revision = 0;
  private nextId = 0;
  private transport?: PluginTransport;

  setTransport(transport: PluginTransport): void { this.transport = transport; }

  activate(descriptor: ActivePluginWebUI): ScopedPluginApi {
    this.deactivate(descriptor.plugin_id);
    this.installations.set(descriptor.plugin_id, {
      descriptor, controller: new AbortController(), generation: Symbol(descriptor.plugin_id),
    });
    this.notify();
    return this.forPlugin(descriptor.plugin_id);
  }

  deactivate(pluginId: string): void {
    this.installations.get(pluginId)?.controller.abort();
    this.installations.delete(pluginId);
    for (const [name, registrations] of this.slots) {
      this.slots.set(name, registrations.filter((item) => item.pluginId !== pluginId));
    }
    for (const [name, hooks] of this.hooks) {
      this.hooks.set(name, hooks.filter((item) => item.pluginId !== pluginId));
    }
    this.notify();
  }

  descriptor(pluginId: string): ActivePluginWebUI | undefined {
    return this.installations.get(pluginId)?.descriptor;
  }

  forPlugin(pluginId: string): ScopedPluginApi {
    const installation = this.installations.get(pluginId);
    if (!installation) throw new Error(`Plugin "${pluginId}" is inactive.`);
    const assertActive = () => {
      if (this.installations.get(pluginId)?.generation !== installation.generation) {
        throw new Error(`Plugin "${pluginId}" was disabled or replaced.`);
      }
    };
    const call = async (operation: 'invoke' | 'jobs', taskType: string, payload: PluginContext) => {
      assertActive();
      const access = installation.descriptor.access;
      if (access && !access.task_types.includes(taskType)) throw new Error('Task is outside the plugin scope.');
      if (!this.transport) throw new Error('Plugin transport is unavailable.');
      const result = await this.transport(pluginId, operation, taskType, payload, installation.controller.signal);
      assertActive();
      return result;
    };
    return {
      version: '1.0.0', pluginId, React, signal: installation.controller.signal,
      registerSlot: (name, component, options = {}) => {
        assertActive();
        if (!PLUGIN_SLOTS.includes(name)) throw new Error(`Unknown plugin slot "${name}".`);
        const id = options.id ?? String(++this.nextId);
        const registrations = this.slots.get(name) ?? [];
        if (registrations.some((item) => item.pluginId === pluginId && item.id === id)) throw new Error(`Duplicate plugin contribution "${id}".`);
        const registration = { id, pluginId, component, order: options.order ?? 0 };
        this.slots.set(name, [...registrations, registration]);
        this.notify();
        return () => {
          this.slots.set(name, (this.slots.get(name) ?? []).filter((item) => item !== registration));
          this.notify();
        };
      },
      unregisterSlot: (name, component) => {
        assertActive();
        this.slots.set(name, (this.slots.get(name) ?? []).filter((item) => item.pluginId !== pluginId || item.component !== component));
        this.notify();
      },
      registerHook: (name, handler) => {
        assertActive();
        const hook = { pluginId, handler };
        this.hooks.set(name, [...(this.hooks.get(name) ?? []), hook]);
        return () => this.hooks.set(name, (this.hooks.get(name) ?? []).filter((item) => item !== hook));
      },
      triggerHook: (name, ...args) => {
        assertActive();
        return (this.hooks.get(name) ?? []).filter((item) => item.pluginId === pluginId).map((item) => {
          try { return item.handler(...args); }
          catch (error) { console.error(`[PluginHost] ${pluginId} hook failed`, error); return undefined; }
        });
      },
      invoke: (taskType, payload) => call('invoke', taskType, payload),
      submitTask: (taskType, payload) => call('jobs', taskType, payload),
    };
  }

  getRegistrations(name: PluginSlotName): Registration[] {
    return [...(this.slots.get(name) ?? [])].sort((a, b) => a.order - b.order || a.pluginId.localeCompare(b.pluginId) || a.id.localeCompare(b.id));
  }

  contextFor(pluginId: string, context: PluginContext): PluginContext {
    const descriptor = this.descriptor(pluginId);
    if (!descriptor) return {};
    // Native extensions are explicitly trusted application code. Sandboxed
    // contributions receive only the declared profile-field projection.
    if (descriptor.mode === 'native' || !descriptor.access) return context;
    const fields = new Set(descriptor.access.profile_fields);
    const projected: PluginContext = {};
    for (const [key, value] of Object.entries(context)) {
      if ((key === 'user' || key === 'item') && value && typeof value === 'object') {
        projected[key] = Object.fromEntries(Object.entries(value).filter(([field]) => fields.has(field)));
      } else if (key === 'formValues' && descriptor.access.propose_profile_changes) projected[key] = value;
      else if (key === 'setFieldValue' && descriptor.access.propose_profile_changes && descriptor.mode === 'declarative') projected[key] = value;
    }
    return projected;
  }

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };
  getSnapshot = (): number => this.revision;
  private notify(): void { this.revision += 1; for (const listener of this.listeners) listener(); }
}

export const pluginRegistry = new PluginRegistry();
export interface UsrPluginApi extends Omit<ScopedPluginApi, 'pluginId' | 'signal'> {
  forPlugin: (pluginId: string) => ScopedPluginApi;
}
declare global { interface Window { USR?: UsrPluginApi } }

export function initPluginHost(): void {
  if (typeof window === 'undefined') return;
  const current = () => {
    const pluginId = (document.currentScript as HTMLScriptElement | null)?.dataset.usrPlugin;
    if (!pluginId) throw new Error('Use USR.forPlugin(pluginId) outside the plugin entry script.');
    return pluginRegistry.forPlugin(pluginId);
  };
  window.USR = {
    version: '1.0.0', React, forPlugin: (id) => pluginRegistry.forPlugin(id),
    registerSlot: (...args) => current().registerSlot(...args),
    unregisterSlot: (...args) => current().unregisterSlot(...args),
    registerHook: (...args) => current().registerHook(...args),
    triggerHook: (...args) => current().triggerHook(...args),
    invoke: (...args) => current().invoke(...args),
    submitTask: (...args) => current().submitTask(...args),
  };
}
