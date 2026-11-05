import fs from 'node:fs';
import path from 'node:path';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import * as setupApi from '../../src/api/setup';
import * as systemApi from '../../src/api/system';
import type { SystemBootstrapResponse } from '../../src/api/types/bootstrap';
import { forgetQueryClients, queryClientFor } from '../../src/app/backends/backendQueryClients';
import type { ComponentSelection, DetectResponse } from '../../src/api/webui';
import { SetupWizardPage } from '../../src/features/setup-wizard/SetupWizardPage';
import {
  CARD_RULES_BY_COMPUTE,
  DEFAULT_COMPONENTS,
  ERROR_MESSAGES,
  applyComputeChoice,
  computeChoice,
  getCardRules,
  validateComponents,
} from '../../src/features/setup-wizard/lib/componentRules';

interface SharedRulesFixture {
  error_messages: Record<string, string>;
  card_rules: Record<string, unknown>;
  combinations: Array<{
    backend: ComponentSelection['backend'];
    worker: ComponentSelection['worker'];
    postgres: ComponentSelection['postgres'];
    redis: ComponentSelection['redis'];
    webui: ComponentSelection['webui'];
    valid: boolean;
    error_code: string | null;
  }>;
}

function makeDetectResponse(overrides: Partial<DetectResponse> = {}): DetectResponse {
  return {
    facts: {
      architecture: 'amd64',
      os_name: 'Ubuntu 24.04',
      user: 'deploy',
      home: '/home/deploy',
      hostname: 'devbox',
      docker_version: '27.0.0',
      compose_version: '2.28.0',
      docker_needs_sudo: false,
      sudo_mode: 'none',
      memory_mb: 16384,
      home_free_mb: 122880,
      listening_ports: [],
      existing_projects: [],
      existing_install: null,
      services: {},
      local_images: [],
      warnings: [],
      ...(overrides.facts ?? {}),
    },
    recommended_components: {
      backend: 'install',
      worker: 'install',
      postgres: 'install',
      redis: 'install',
      webui: 'reuse',
      ...(overrides.recommended_components ?? {}),
    },
    needs_sudo_for: overrides.needs_sudo_for ?? [],
    recommended_image_source: overrides.recommended_image_source ?? 'registry',
    recommended_version: overrides.recommended_version ?? '0.1.0',
  };
}

describe('Shared component_rules.json fixture parity', () => {
  it('matches every combination and error message in installer/component_rules.json', () => {
    const fixturePath = path.resolve(
      __dirname,
      '../../../ultima_webui_server/installer/component_rules.json',
    );
    const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf-8')) as SharedRulesFixture;

    expect(ERROR_MESSAGES).toEqual(fixture.error_messages);
    expect(fixture.combinations.length).toBe(72);

    for (const entry of fixture.combinations) {
      const selection: ComponentSelection = {
        backend: entry.backend,
        worker: entry.worker,
        postgres: entry.postgres,
        redis: entry.redis,
        webui: entry.webui,
      };
      const result = validateComponents(selection);
      expect(result.valid).toBe(entry.valid);
      expect(result.error_code).toBe(entry.error_code);

      const cardRules = getCardRules(selection);
      expect(cardRules.backend.allowed.length).toBeGreaterThan(0);
      expect(cardRules.webui.allowed).toEqual(['reuse', 'install']);
    }
  });

  it('matches the per-card rules in installer/component_rules.json', () => {
    const fixturePath = path.resolve(
      __dirname,
      '../../../ultima_webui_server/installer/component_rules.json',
    );
    const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf-8')) as SharedRulesFixture;

    expect(CARD_RULES_BY_COMPUTE).toEqual(fixture.card_rules);
  });
});

describe('Backend card choices', () => {
  it('maps each choice to the backend and worker containers', () => {
    const backend = applyComputeChoice(DEFAULT_COMPONENTS, 'backend');
    const worker = applyComputeChoice(DEFAULT_COMPONENTS, 'worker');
    const none = applyComputeChoice(DEFAULT_COMPONENTS, 'none');

    expect([backend.backend, backend.worker]).toEqual(['install', 'install']);
    expect([worker.backend, worker.worker, worker.postgres, worker.redis]).toEqual([
      'none',
      'install',
      'existing',
      'existing',
    ]);
    expect([none.backend, none.worker]).toEqual(['none', 'none']);
    expect([computeChoice(backend), computeChoice(worker), computeChoice(none)]).toEqual(['backend', 'worker', 'none']);
    // Back to a full backend: the existing stores stay chosen; they are still allowed.
    const again = applyComputeChoice(worker, 'backend');
    expect([again.postgres, again.redis]).toEqual(['existing', 'existing']);
  });
});

describe('SetupWizardPage', () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('auto-detects the local host on load, preselects detected services, and shows disabled mode reasons', async () => {
    const detectPayload = makeDetectResponse({
      facts: {
        ...makeDetectResponse().facts,
        services: {
          postgres: { detected: true, host: '127.0.0.1', port: 5432, listening: true },
        },
      },
      recommended_components: {
        backend: 'install',
        worker: 'install',
        postgres: 'existing',
        redis: 'install',
        webui: 'reuse',
      },
    });

    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/connections') || url.endsWith('/deployments')) {
        return new Response('[]', { status: 200 });
      }
      if (url.endsWith('/installs/environment')) {
        return new Response(
          JSON.stringify({
            version: '0.1.0',
            in_container: false,
            local_available: true,
            copy_available: false,
            releases: [],
          }),
          { status: 200 },
        );
      }
      if (url.endsWith('/installs/detect')) {
        return new Response(JSON.stringify(detectPayload), { status: 200 });
      }
      return new Response('{}', { status: 200 });
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<SetupWizardPage />);
    await createCluster();
    fireEvent.click(await screen.findByRole('radio', { name: /Local/ }));

    // Host facts appear automatically from local detection
    expect(await screen.findByText('devbox')).toBeInTheDocument();
    expect(screen.getByText('Docker group (no sudo)')).toBeInTheDocument();
    expect(screen.getByText('postgres (:5432)')).toBeInTheDocument();

    // Advance to Step 2: Components
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }));

    const pgCard = screen.getByTestId('card-postgres');
    const existingBtn = within(pgCard).getByRole('button', { name: 'Use existing (devbox)' });
    expect(existingBtn).toHaveClass('is-selected');

    // Disabled "Not here" mode shows its reason on PostgreSQL and Redis cards
    const pgNoneBtn = within(pgCard).getByRole('button', { name: 'Not here' });
    expect(pgNoneBtn).toBeDisabled();
    expect(within(pgCard).getByText('Not here: Backend needs PostgreSQL')).toBeInTheDocument();

    const redisCard = screen.getByTestId('card-redis');
    const redisNoneBtn = within(redisCard).getByRole('button', { name: 'Not here' });
    expect(redisNoneBtn).toBeDisabled();
    expect(within(redisCard).getByText('Not here: Backend needs Redis')).toBeInTheDocument();
  });

  it('shows the sudo password field in Review & Install only when needs_sudo_for is non-empty and sudo_mode is password', async () => {
    const detectNeedsSudo = makeDetectResponse({
      facts: {
        ...makeDetectResponse().facts,
        docker_version: null,
        compose_version: null,
        sudo_mode: 'password',
      },
      needs_sudo_for: ['install Docker'],
    });

    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith('/connections') || url.endsWith('/deployments')) {
          return new Response('[]', { status: 200 });
        }
        if (url.endsWith('/installs/environment')) {
          return new Response(
            JSON.stringify({
              version: '0.1.0',
              in_container: false,
              local_available: true,
              copy_available: false,
              releases: [],
            }),
            { status: 200 },
          );
        }
        if (url.endsWith('/installs/detect')) {
          return new Response(JSON.stringify(detectNeedsSudo), { status: 200 });
        }
        return new Response('{}', { status: 200 });
      }),
    );

    render(<SetupWizardPage />);
    await createCluster();
    fireEvent.click(await screen.findByRole('radio', { name: /Local/ }));
    expect(await screen.findByText('devbox')).toBeInTheDocument();

    // Step 1 -> Step 2 -> Step 4 (Connections step skipped since PG & Redis are 'install')
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }));

    expect(await screen.findByLabelText('sudo password')).toBeInTheDocument();
    expect(screen.getByText(/Needed for: install Docker/)).toBeInTheDocument();
  });

  it('completes the full install and inline backend configuration with database: null and redis: null', async () => {
    const detectPayload = makeDetectResponse();
    vi.spyOn(setupApi, 'getSetupStatus').mockResolvedValue({
      is_configured: false,
      has_config: true,
      has_database: true,
      redis_target: 'redis:6379',
      data_directory: '/data',
      startup_id: 'startup-1',
      backend_id: 'devbox',
    });
    let configured = false;
    const bootstrapSpy = vi.spyOn(systemApi, 'getSystemBootstrap').mockImplementation(
      async () =>
        ({
          backend_id: 'devbox',
          version: '0.1.0',
          setup: {
            is_configured: configured,
            has_config: true,
            has_database: true,
            data_directory: '/data',
            startup_id: 'startup-1',
          },
        }) as SystemBootstrapResponse,
    );
    const completeSetupSpy = vi.spyOn(setupApi, 'completeSetup').mockImplementation(async () => {
      configured = true;
      return { success: true, is_configured: true, message: 'Setup complete', auth_errors: [] };
    });

    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/connections') || url.endsWith('/deployments')) {
        return new Response('[]', { status: 200 });
      }
      if (url.endsWith('/installs/environment')) {
        return new Response(
          JSON.stringify({
            version: '0.1.0',
            in_container: false,
            local_available: true,
            copy_available: false,
            releases: [],
          }),
          { status: 200 },
        );
      }
      if (url.endsWith('/installs/detect')) {
        return new Response(JSON.stringify(detectPayload), { status: 200 });
      }
      if (url.endsWith('/installs') && init?.method === 'POST') {
        return new Response(JSON.stringify({ id: 'run-1' }), { status: 202 });
      }
      if (url.includes('/installs/run-1')) {
        return new Response(
          JSON.stringify({
            id: 'run-1',
            name: 'devbox',
            target: 'this machine',
            state: 'succeeded',
            connection_id: 'devbox',
            operation: 'install',
            deployment_id: 'dep-1',
            events: [{ seq: 1, at: 0, kind: 'done', message: 'devbox is ready.' }],
          }),
          { status: 200 },
        );
      }
      return new Response('{}', { status: 200 });
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<SetupWizardPage />);
    await createCluster();
    await chooseLocal();
    // Step 2 (Components) -> Step 4 (Review & Install)
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }));

    // Sudo password field should NOT be rendered when needs_sudo_for is empty
    expect(screen.queryByLabelText('sudo password')).not.toBeInTheDocument();

    // Start install
    fireEvent.click(screen.getByRole('button', { name: 'Install' }));

    // Automatically transitions to Step 5: Configure Backend (Storage & Network)
    expect(await screen.findByRole('heading', { name: 'Storage & Network' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }));

    // DRM step -> Skip
    expect(await screen.findByRole('heading', { name: 'DRM Configuration' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Skip' }));

    // Auths step -> Continue
    expect(await screen.findByRole('heading', { name: 'Authentication' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }));

    // Review & Complete -> Complete Setup
    expect(await screen.findByRole('heading', { name: 'Review & Complete' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Complete Setup' }));

    await waitFor(() => expect(completeSetupSpy).toHaveBeenCalledTimes(1));
    expect(completeSetupSpy.mock.calls[0][0]).toMatchObject({
      database: null,
      redis: null,
    });

    // Step 6: Done
    const openLink = await screen.findByRole('link', { name: 'Open devbox' });
    expect(openLink).toHaveAttribute('href', '/b/devbox/');

    // Opening the backend reuses its query cache: it must already say
    // "configured", or the backend's own setup page flashes before the dashboard.
    expect(bootstrapSpy.mock.invocationCallOrder.at(-1)).toBeGreaterThan(
      completeSetupSpy.mock.invocationCallOrder[0],
    );
    const cached = queryClientFor('devbox').getQueryData<SystemBootstrapResponse>(['system-bootstrap']);
    expect(cached?.setup.is_configured).toBe(true);
    forgetQueryClients();
  });

  it('sends an existing Redis host and port as separate fields', async () => {
    const detectPayload = makeDetectResponse({
      facts: {
        ...makeDetectResponse().facts,
        services: { redis: { detected: true, host: 'localhost', port: 6379, listening: true } },
      },
      recommended_components: { redis: 'existing' } as DetectResponse['recommended_components'],
    });
    const { fetchMock } = mockWizardApi({ detect: detectPayload });

    render(<SetupWizardPage />);
    await createCluster();
    // Redis found on this machine: Host stays to show it.
    fireEvent.click(await screen.findByRole('radio', { name: /Local/ }));
    expect(await screen.findByText('redis (:6379)')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }));

    fireEvent.change(await screen.findByLabelText(/^Port/, { selector: '#setup-redis-port' }), {
      target: { value: '6380' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Check Redis' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Continue' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Install' }));

    await waitFor(() => expect(installBody(fetchMock)).not.toBeNull());
    expect(installBody(fetchMock)).toMatchObject({ redis_host: 'localhost', redis_port: 6380 });
  });

  it('finishes a repair at Done without the first-time backend configuration', async () => {
    const detectPayload = makeDetectResponse({
      facts: {
        ...makeDetectResponse().facts,
        existing_install: {
          project: 'usr-devbox',
          version: '0.1.0',
          install_dir: '/home/deploy/ultimascraper',
        },
        existing_projects: ['usr-devbox'],
      },
    });
    mockWizardApi({
      detect: detectPayload,
      deployments: [
        {
          id: 'dep-1',
          name: 'devbox',
          target: 'this machine',
          details: { kind: 'local', project: 'usr-devbox', install_dir: '/home/deploy/ultimascraper' },
          connection_id: 'devbox',
        },
      ],
      run: { connection_id: 'devbox', operation: 'repair' },
    });
    const getSetupStatus = vi.spyOn(setupApi, 'getSetupStatus');

    render(<SetupWizardPage />);
    await createCluster();
    fireEvent.click(await screen.findByRole('radio', { name: /Local/ }));
    fireEvent.click(await screen.findByRole('button', { name: 'Repair' }));

    expect(await screen.findByRole('link', { name: 'Open devbox' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Storage & Network' })).not.toBeInTheDocument();
    expect(getSetupStatus).not.toHaveBeenCalled();
  });

  it('shows how other hosts connect after a store-only install', async () => {
    mockWizardApi({
      detect: makeDetectResponse(),
      run: {
        connection_id: null,
        store_connection: {
          host: 'storage-box',
          install_dir: '/home/deploy/ultimascraper',
          postgres: { port: 5433, name: 'ultima_archive', user: 'ultimascraper', password: 'pg-secret' },
          redis: { port: 6380, password: 'redis-secret' },
        },
      },
    });

    render(<SetupWizardPage />);
    await createCluster();
    await chooseLocal();
    fireEvent.click(within(screen.getByTestId('card-backend')).getByRole('button', { name: 'Not here' }));
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Install' }));

    const details = await screen.findByTestId('store-connection');
    expect(details).toHaveTextContent('ultimascraper@storage-box:5433/ultima_archive');
    expect(details).toHaveTextContent('pg-secret');
    expect(details).toHaveTextContent('storage-box:6380');
    expect(details).toHaveTextContent('redis-secret');
  });

  it('lists unpublished database containers as not reusable instead of preselecting them', async () => {
    mockWizardApi({
      detect: makeDetectResponse({
        facts: {
          ...makeDetectResponse().facts,
          services: {
            postgres: { detected: false, listening: false, unreachable_containers: ['usr-other-postgres-1'] },
          },
        },
      }),
    });

    render(<SetupWizardPage />);
    await createCluster();
    fireEvent.click(await screen.findByRole('radio', { name: /Local/ }));
    expect(await screen.findByText(/usr-other-postgres-1 \(port not published on devbox\)/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }));

    const pgCard = screen.getByTestId('card-postgres');
    expect(within(pgCard).getByRole('button', { name: 'Install here' })).toHaveClass('is-selected');
    expect(within(pgCard).queryByRole('button', { name: 'Use existing (devbox)' })).not.toBeInTheDocument();
  });
  it('switches a registry install to this WebUI release instead of a local-only tag', async () => {
    const { fetchMock } = mockWizardApi({
      detect: makeDetectResponse({
        facts: {
          ...makeDetectResponse().facts,
          architecture: 'arm64',
          local_images: [{ version: 'acceptance-arm64', architecture: 'arm64', names: ['ultimascraper'] }],
        },
        recommended_image_source: 'target',
        recommended_version: 'acceptance-arm64',
      }),
    });

    render(<SetupWizardPage />);
    await createCluster();
    await chooseLocal();
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }));

    const versionInput = await screen.findByLabelText('Version');
    expect(versionInput).toHaveValue('acceptance-arm64');
    fireEvent.change(screen.getByLabelText('Image source'), { target: { value: 'registry' } });
    expect(versionInput).toHaveValue('0.1.0');
    fireEvent.change(screen.getByLabelText('Image source'), { target: { value: 'target' } });
    expect(versionInput).toHaveValue('acceptance-arm64');

    fireEvent.change(screen.getByLabelText('Image source'), { target: { value: 'registry' } });
    fireEvent.click(screen.getByRole('button', { name: 'Install' }));
    await waitFor(() => expect(installBody(fetchMock)).not.toBeNull());
    expect(installBody(fetchMock)).toMatchObject({ image_source: 'registry', version: '0.1.0' });
  });
  it('shows Backend and Worker as one card, with worker-only for extra hosts', async () => {
    mockWizardApi({
      detect: makeDetectResponse(),
      connections: [{ id: 'alpha', name: 'alpha', base_url: 'http://127.0.0.1:21121' }],
    });

    render(<SetupWizardPage />);
    await createCluster();
    await chooseLocal();

    expect(screen.queryByTestId('card-worker')).not.toBeInTheDocument();
    const card = screen.getByTestId('card-backend');
    expect(within(card).getByRole('button', { name: 'Install here' })).toHaveClass('is-selected');
    expect(within(card).queryByLabelText('Backend connection to join')).not.toBeInTheDocument();

    fireEvent.click(within(card).getByRole('button', { name: 'Worker only' }));
    expect(within(card).getByRole('button', { name: 'Worker only' })).toHaveClass('is-selected');
    expect(within(card).getByLabelText('Backend connection to join')).toHaveValue('alpha');
    // A worker for another backend uses that backend's stores.
    expect(within(screen.getByTestId('card-postgres')).getByRole('button', { name: /Use existing/ })).toHaveClass('is-selected');
    expect(within(screen.getByTestId('card-redis')).getByRole('button', { name: /Use existing/ })).toHaveClass('is-selected');
  });


  it('adds a host to a cluster with its PostgreSQL and Redis, checked from that host', async () => {
    const clusterStores = {
      available: true,
      cluster_id: 'c-1',
      database: { host: '192.168.50.40', port: 30432, name: 'ultima_archive', username: 'ultimascraper', password: 'pw' },
      redis: { host: '192.168.50.40', port: 30059, db: 0, password: 'rp' },
      source_backend_name: 'hoarder01',
    };
    const { fetchMock } = mockWizardApi({
      detect: makeDetectResponse(),
      connections: [{ id: 'dev', name: 'hoarder01', base_url: 'http://127.0.0.1:21121' }],
      clusterStores,
    });
    const onDone = vi.fn();

    render(
      <SetupWizardPage layout="modal" cluster={{ clusterId: 'c-1', connectionId: 'dev', name: 'Home' }} onDone={onDone} />,
    );
    // In a modal: no page heading.
    expect(screen.queryByRole('heading', { name: 'Set up UltimaScraper' })).not.toBeInTheDocument();
    await chooseLocal();

    // Workers for this cluster by default, without asking which backend.
    const card = screen.getByTestId('card-backend');
    expect(within(card).getByRole('button', { name: 'Worker only' })).toHaveClass('is-selected');
    expect(within(card).queryByLabelText('Backend connection to join')).not.toBeInTheDocument();
    expect(within(card).getByText('Runs jobs for Home.')).toBeInTheDocument();
    // PostgreSQL and Redis are shown, on the cluster's own.
    expect(within(screen.getByTestId('card-postgres')).getByRole('button', { name: "This cluster's" })).toHaveClass('is-selected');
    expect(within(screen.getByTestId('card-redis')).getByRole('button', { name: "This cluster's" })).toHaveClass('is-selected');
    expect(await screen.findByTestId('cluster-postgres')).toHaveTextContent("Home's: 192.168.50.40:30432/ultima_archive");
    expect(screen.getByTestId('cluster-redis')).toHaveTextContent("Home's: 192.168.50.40:30059");

    // Straight to Review, which checks the host reaches them.
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
    expect(await screen.findByText(/Reachable from devbox \(192.168.50.40:30432\)/)).toBeInTheDocument();
    expect(screen.queryByLabelText('Cluster name')).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole('button', { name: 'Install' }));

    await waitFor(() => expect(installBody(fetchMock)).not.toBeNull());
    expect(installBody(fetchMock)).toMatchObject({
      components: { backend: 'none', worker: 'install', postgres: 'existing', redis: 'existing' },
      join_connection_id: 'dev',
      redis_host: '192.168.50.40',
    });
    fireEvent.click(await screen.findByRole('button', { name: 'Close' }));
    expect(onDone).toHaveBeenCalled();
  });

  it('asks the cluster name when a backend gets its own new database', async () => {
    mockWizardApi({ detect: makeDetectResponse() });

    render(<SetupWizardPage />);
    await createCluster();
    await chooseLocal();
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }));

    expect(await screen.findByLabelText(/^Cluster name/)).toHaveValue('Home');
  });

  it('does not revert to current machine when user switches to Another host (SSH) while initial detection is in flight', async () => {
    let resolveDetect!: (value: Response) => void;
    const detectPromise = new Promise<Response>((resolve) => {
      resolveDetect = resolve;
    });

    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/connections')) return new Response('[]', { status: 200 });
      if (url.includes('/installs/cluster-stores')) return new Response(JSON.stringify({ available: false }), { status: 200 });
      if (url.endsWith('/deployments')) return new Response('[]', { status: 200 });
      if (url.endsWith('/installs/environment')) {
        return new Response(
          JSON.stringify({
            version: '0.1.0',
            in_container: false,
            local_available: true,
            copy_available: false,
            releases: [],
          }),
          { status: 200 },
        );
      }
      if (url.endsWith('/installs/detect')) {
        return detectPromise;
      }
      return new Response('{}', { status: 200 });
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<SetupWizardPage />);
    await createCluster();

    // Click "Another host (SSH) →" before detect resolves
    const anotherHostBtn = await screen.findByRole('radio', { name: /Remote/ });
    fireEvent.click(anotherHostBtn);

    // Verify we are now on SSH host view
    expect(screen.getByLabelText('Host')).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /Remote/ })).toHaveAttribute('aria-checked', 'true');

    // Now resolve the in-flight local detect request
    resolveDetect(new Response(JSON.stringify(makeDetectResponse({ facts: { ...makeDetectResponse().facts, hostname: 'local-current-host' } })), { status: 200 }));

    await new Promise((r) => setTimeout(r, 50));

    // Must still be on SSH host view, NOT reverted to local-current-host
    expect(screen.getByLabelText('Host')).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /Remote/ })).toHaveAttribute('aria-checked', 'true');
    expect(screen.queryByText('local-current-host')).not.toBeInTheDocument();
  });

  it('does not override remote SSH host with host.docker.internal if environment check resolves after user chooses another host', async () => {
    let resolveEnv!: (value: Response) => void;
    const envPromise = new Promise<Response>((resolve) => {
      resolveEnv = resolve;
    });

    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/connections')) return new Response('[]', { status: 200 });
      if (url.includes('/installs/cluster-stores')) return new Response(JSON.stringify({ available: false }), { status: 200 });
      if (url.endsWith('/deployments')) return new Response('[]', { status: 200 });
      if (url.endsWith('/installs/environment')) {
        return envPromise;
      }
      if (url.endsWith('/installs/detect')) {
        return new Response(JSON.stringify(makeDetectResponse()), { status: 200 });
      }
      return new Response('{}', { status: 200 });
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<SetupWizardPage />);
    await createCluster();

    const anotherHostBtn = await screen.findByRole('radio', { name: /Remote/ });
    fireEvent.click(anotherHostBtn);

    const hostInput = screen.getByLabelText('Host');
    fireEvent.change(hostInput, { target: { value: 'remote-server.lan' } });
    expect(hostInput).toHaveValue('remote-server.lan');

    // Environment resolves as running inside container
    resolveEnv(new Response(
      JSON.stringify({
        version: '0.1.0',
        in_container: true,
        local_available: false,
        copy_available: false,
        releases: [],
      }),
      { status: 200 },
    ));

    await new Promise((r) => setTimeout(r, 50));

    // Value should still be remote-server.lan, NOT host.docker.internal
    expect(screen.getByLabelText('Host')).toHaveValue('remote-server.lan');
  });

  it('displays the target hostname in component headers, hints, and toggles instead of ambiguous "this host"', async () => {
    const clusterStores = {
      available: true,
      cluster_id: 'c-1',
      database: { host: '192.168.50.40', port: 30432, name: 'ultima_archive', username: 'ultimascraper', password: 'dp' },
      redis: { host: '192.168.50.40', port: 30059, db: 0, password: 'rp' },
      source_backend_name: 'hoarder01',
    };
    mockWizardApi({
      detect: makeDetectResponse({
        facts: {
          ...makeDetectResponse().facts,
          hostname: 'alpha',
          services: {
            redis: { detected: true, host: '127.0.0.1', port: 6379, listening: true },
          },
        },
      }),
      connections: [{ id: 'dev', name: 'hoarder01', base_url: 'http://127.0.0.1:21121' }],
      clusterStores,
    });

    render(
      <SetupWizardPage
        layout="modal"
        cluster={{ clusterId: 'c-1', connectionId: 'dev', name: 'Home' }}
      />,
    );

    fireEvent.click(await screen.findByRole('radio', { name: /Local/ }));
    expect(await screen.findByText('alpha')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }));

    // Step 2 Components: the header names alpha
    expect(screen.getByText('Choose which parts to install on alpha and which to reuse.')).toBeInTheDocument();
    // In a cluster, existing PostgreSQL and Redis are the cluster's, shown by default.
    const redisCard = screen.getByTestId('card-redis');
    expect(within(redisCard).getByRole('button', { name: "This cluster's" })).toHaveClass('is-selected');
    expect(within(redisCard).getByRole('button', { name: 'Install here' })).toBeInTheDocument();
  });
});

describe('SetupWizardPage: where and what', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('fetches a remote host key by itself and asks to confirm its fingerprint', async () => {
    const { fetchMock } = mockWizardApi({ detect: makeDetectResponse({ facts: { ...makeDetectResponse().facts, hostname: 'alpha' } }) });
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/installs/host-key')) {
        return new Response(JSON.stringify({ algorithm: 'ssh-ed25519', fingerprint: 'SHA256:abc', key: 'ssh-ed25519 AAAA' }));
      }
      if (url.endsWith('/installs/environment')) {
        return new Response(JSON.stringify({ version: '0.1.0', in_container: false, local_available: true, copy_available: false, releases: [] }));
      }
      if (url.endsWith('/installs/detect')) {
        const body = JSON.parse(String(init?.body));
        const hostname = body.target.kind === 'ssh' ? 'alpha' : 'devbox';
        return new Response(JSON.stringify(makeDetectResponse({ facts: { ...makeDetectResponse().facts, hostname } })));
      }
      return new Response(url.endsWith('/connections') || url.endsWith('/deployments') ? '[]' : '{}');
    });

    render(<SetupWizardPage />);
    await createCluster();
    fireEvent.click(await screen.findByRole('radio', { name: /Remote/ }));
    fireEvent.change(screen.getByLabelText('Host'), { target: { value: '192.168.50.120' } });
    fireEvent.change(screen.getByLabelText('User'), { target: { value: 'ultima' } });
    fireEvent.change(screen.getByLabelText('SSH password'), { target: { value: 'pw' } });

    // No button to press: the key is fetched once there is an address.
    expect(await screen.findByText('SHA256:abc', {}, { timeout: 3000 })).toBeInTheDocument();
    expect(screen.getByText(/Does its fingerprint match the host's own\?/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled();

    fireEvent.click(screen.getByRole('button', { name: 'Yes, it matches' }));
    expect(await screen.findByText('✓ Fingerprint confirmed')).toBeInTheDocument();
    // Then the host is inspected over SSH.
    await waitFor(() => expect(screen.getByRole('button', { name: 'Continue' })).toBeEnabled());
    const hostKeyCalls = fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/installs/host-key'));
    expect(JSON.parse(String(hostKeyCalls[0][1]?.body))).toEqual({ host: '192.168.50.120', port: 22 });
  });

  it('joins a cluster with an invite first, then installs for it', async () => {
    const clusterStores = {
      available: true,
      cluster_id: 'c-1',
      database: { host: '192.168.50.40', port: 30432, name: 'ultima_archive', username: 'ultimascraper', password: 'pw' },
      redis: { host: '192.168.50.40', port: 30059, db: 0, password: 'rp' },
      source_backend_name: 'hoarder01',
    };
    const { fetchMock } = mockWizardApi({ detect: makeDetectResponse(), clusterStores });
    const base = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/clusters/preview-invite')) {
        return new Response(
          JSON.stringify({
            cluster_id: null,
            name: 'A cluster',
            members: [],
            version: 2,
            entry_url: 'https://192.168.50.60:8443',
            fingerprint: 'FC:8A',
            verified: true,
            error: null,
          }),
        );
      }
      if (url.endsWith('/clusters/join')) {
        return new Response(
          JSON.stringify({
            cluster_id: 'c-1',
            name: 'Home',
            created: ['hoarder01'],
            skipped: [],
            members: [{ name: 'hoarder01', base_url: 'https://192.168.50.60:8443', connection_id: 'hoarder01', note: null }],
          }),
        );
      }
      return base(input, init);
    });

    render(<SetupWizardPage />);
    // Joining comes before anything is installed: it decides what Components offers.
    fireEvent.click(await screen.findByRole('radio', { name: /Join a cluster/ }));
    expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Cluster invite'), {
      target: { value: 'usr://cluster/usri_x@192.168.50.60:8443#FC:8A' },
    });
    expect(await screen.findByText(/Certificate verified/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Join' }));

    expect(await screen.findByText('Joined Home: 1 backend added.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Finish' })).toHaveAttribute('href', '/b/hoarder01/');
    fireEvent.click(screen.getByRole('button', { name: 'Install on a host' }));

    await chooseLocal();
    // Now the wizard adds a host to Home: workers for it, on its PostgreSQL and Redis.
    expect(within(screen.getByTestId('card-backend')).getByText('Runs jobs for Home.')).toBeInTheDocument();
    expect(within(screen.getByTestId('card-postgres')).getByRole('button', { name: "This cluster's" })).toHaveClass('is-selected');
    expect(await screen.findByTestId('cluster-postgres')).toHaveTextContent("Home's: 192.168.50.40:30432/ultima_archive");
  });

  it('has no way off to the Backends page', async () => {
    mockWizardApi({ detect: makeDetectResponse() });

    render(<SetupWizardPage />);

    expect(await screen.findByRole('radio', { name: /Create a cluster/ })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Backends' })).not.toBeInTheDocument();
  });

  it('shows nothing but the two choices until one is picked', async () => {
    mockWizardApi({ detect: makeDetectResponse() });

    render(<SetupWizardPage />);
    await createCluster();

    expect(await screen.findByRole('radio', { name: /Local/ })).toHaveAttribute('aria-checked', 'false');
    expect(screen.getByRole('radio', { name: /Remote/ })).toHaveAttribute('aria-checked', 'false');
    expect(screen.queryByLabelText('Host')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled();
  });

  it('draws the new cluster, its host and its services on Review', async () => {
    mockWizardApi({ detect: makeDetectResponse() });

    render(<SetupWizardPage />);
    await createCluster();
    await chooseLocal();
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }));

    const diagram = await screen.findByRole('figure', { name: 'The system after this install' });
    expect(diagram).toHaveTextContent('This WebUI');
    const cluster = within(diagram).getByRole('region', { name: 'Cluster Home' });
    for (const text of ['devbox', 'This install', 'Backend', 'Workers', 'PostgreSQL', 'on devbox']) {
      expect(cluster).toHaveTextContent(text);
    }
  });

  it('allows finishing setup when joining a cluster without installing any additional services on the local host', async () => {
    const clusterStores = {
      available: true,
      cluster_id: 'c-1',
      database: { host: '192.168.50.40', port: 30432, name: 'ultima_archive', username: 'ultimascraper', password: 'dp' },
      redis: { host: '192.168.50.40', port: 30059, db: 0, password: 'rp' },
      source_backend_name: 'hoarder01',
    };
    mockWizardApi({
      detect: makeDetectResponse({ facts: { ...makeDetectResponse().facts, hostname: 'hoarder01' } }),
      connections: [{ id: 'dev', name: 'hoarder01', base_url: 'http://127.0.0.1:21121' }],
      clusterStores,
    });

    render(
      <SetupWizardPage
        layout="modal"
        cluster={{ clusterId: 'c-1', connectionId: 'dev', name: 'Home' }}
      />,
    );

    await chooseLocal();

    // User chooses "Not here" for backend/worker
    const backendCard = screen.getByTestId('card-backend');
    fireEvent.click(within(backendCard).getByRole('button', { name: 'Not here' }));

    // User should NOT see an error telling them to choose at least one component
    expect(screen.queryByText('Choose at least one component to install.')).not.toBeInTheDocument();
    expect(
      screen.getByText(/This WebUI is already connected to Home\. No additional services need to be installed on hoarder01\./),
    ).toBeInTheDocument();

    // Primary CTA is now Finish & Open Home instead of a disabled Continue button
    expect(screen.getByRole('link', { name: 'Finish & Open Home' })).toHaveAttribute('href', '/b/dev/');
  });
});

/** First run, step 0: a new cluster rather than joining one. */
async function createCluster() {
  fireEvent.click(await screen.findByRole('radio', { name: /Create a cluster/ }));
  fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
}

/** Install where: the Local tile, which goes on to Components once this machine is detected. */
async function chooseLocal() {
  fireEvent.click(await screen.findByRole('radio', { name: /Local/ }));
  await screen.findByRole('heading', { name: 'Components' });
}

function mockWizardApi({
  detect,
  deployments = [],
  run = {},
  connections = [],
  clusterStores = { available: false, cluster_id: null, database: null, redis: null, source_backend_name: null },
}: {
  detect: DetectResponse;
  deployments?: unknown[];
  run?: Record<string, unknown>;
  connections?: unknown[];
  clusterStores?: unknown;
}) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith('/connections')) return new Response(JSON.stringify(connections), { status: 200 });
    if (url.includes('/installs/cluster-stores')) return new Response(JSON.stringify(clusterStores), { status: 200 });
    if (url.endsWith('/deployments')) return new Response(JSON.stringify(deployments), { status: 200 });
    if (url.endsWith('/installs/environment')) {
      return new Response(
        JSON.stringify({
          version: '0.1.0',
          in_container: false,
          local_available: true,
          copy_available: false,
          releases: [],
        }),
        { status: 200 },
      );
    }
    if (url.endsWith('/installs/detect')) return new Response(JSON.stringify(detect), { status: 200 });
    if (url.endsWith('/installs/check-service')) {
      const body = JSON.parse(String(init?.body));
      return new Response(
        JSON.stringify({ reachable: true, kind: body.kind, host: body.host, port: body.port, message: 'ok' }),
        { status: 200 },
      );
    }
    if ((url.endsWith('/installs') || url.endsWith('/operations')) && init?.method === 'POST') {
      return new Response(JSON.stringify({ id: 'run-1' }), { status: 202 });
    }
    if (url.includes('/installs/run-1')) {
      return new Response(
        JSON.stringify({
          id: 'run-1',
          name: 'devbox',
          target: 'this machine',
          state: 'succeeded',
          connection_id: null,
          operation: 'install',
          deployment_id: 'dep-1',
          events: [{ seq: 1, at: 0, kind: 'done', message: 'done' }],
          ...run,
        }),
        { status: 200 },
      );
    }
    return new Response('{}', { status: 200 });
  });
  vi.stubGlobal('fetch', fetchMock);
  return { fetchMock };
}

function installBody(fetchMock: ReturnType<typeof vi.fn>): Record<string, unknown> | null {
  const call = fetchMock.mock.calls.find(
    ([input, init]) => String(input).endsWith('/installs') && (init as RequestInit | undefined)?.method === 'POST',
  );
  return call ? JSON.parse(String((call[1] as RequestInit).body)) : null;
}
