import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect } from 'vitest';
import { JobCreatorRedesignsMock } from '../../src/features/mock/job-creator-redesigns/JobCreatorRedesignsMock';
import { DesignLab } from '../../src/features/mock/DesignLab';

describe('JobCreatorRedesignsMock', () => {
  it('renders all 5 concepts in the navigation header', () => {
    render(
      <MemoryRouter initialEntries={['/?category=create-job']}>
        <JobCreatorRedesignsMock />
      </MemoryRouter>
    );

    expect(screen.getByRole('button', { name: /01.*Dual-Mode Studio/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /02.*Pipeline Blueprint/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /03.*Rapid Command Terminal/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /04.*Recipe & Template Runway/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /05.*Matrix Batch Dispatcher/i })).toBeInTheDocument();
  });

  it('renders in DesignLab when category=create-job is selected', () => {
    render(
      <MemoryRouter initialEntries={['/?category=create-job']}>
        <DesignLab />
      </MemoryRouter>
    );

    expect(screen.getByRole('button', { name: /Create Job.*5 concepts/i })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: /01.*Dual-Mode Studio/i })).toBeInTheDocument();
  });

  it('renders Concept 1 (Dual-Mode Studio) and supports building tasks and creating templates', () => {
    render(
      <MemoryRouter initialEntries={['/?category=create-job&concept=studio']}>
        <JobCreatorRedesignsMock />
      </MemoryRouter>
    );

    expect(screen.getByRole('region', { name: /Dual-Mode Studio/i })).toBeInTheDocument();

    // Verify task builder mode is active initially
    expect(screen.getByText(/Job Details & Template Export/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Add Task to Queue/i })).toBeInTheDocument();

    // Verify inline "Save as Template" checkbox
    const saveAsTmplCheckbox = screen.getByLabelText(/Save this configuration as a reusable Template/i);
    fireEvent.click(saveAsTmplCheckbox);

    expect(screen.getByText(/Template Name/i)).toBeInTheDocument();

    // Switch to dedicated "Create Template Studio" tab
    const tmplLabTab = screen.getByRole('tab', { name: /Create Template Studio/i });
    fireEvent.click(tmplLabTab);

    expect(screen.getByText(/Create & Register New Template/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Save to Template Library/i })).toBeInTheDocument();
  });

  it('renders Concept 2 (Pipeline Blueprint Architect) and supports exporting blueprint as template', () => {
    render(
      <MemoryRouter initialEntries={['/?category=create-job&concept=blueprint']}>
        <JobCreatorRedesignsMock />
      </MemoryRouter>
    );

    expect(screen.getByRole('region', { name: /Pipeline Blueprint Architect/i })).toBeInTheDocument();

    // Open Save Pipeline as Template modal
    const savePipelineBtn = screen.getByRole('button', { name: /Save Pipeline as Template/i });
    fireEvent.click(savePipelineBtn);

    expect(screen.getByText(/Save Current Pipeline as Reusable Template/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Confirm & Save Template/i })).toBeInTheDocument();
  });

  it('renders Concept 3 (Rapid Command Terminal) and supports quick task injection and live JSON payload', () => {
    render(
      <MemoryRouter initialEntries={['/?category=create-job&concept=terminal']}>
        <JobCreatorRedesignsMock />
      </MemoryRouter>
    );

    expect(screen.getByRole('region', { name: /Rapid Command Terminal/i })).toBeInTheDocument();
    expect(screen.getByText(/Active Task Queue & Payloads/i)).toBeInTheDocument();

    // Quick add Scrape task
    const addScrapeBtn = screen.getByRole('button', { name: /\+ Scrape User Posts/i });
    fireEvent.click(addScrapeBtn);

    // Open Save Queue as Template modal
    const saveQueueBtn = screen.getByRole('button', { name: /Save Queue as Template/i });
    fireEvent.click(saveQueueBtn);

    expect(screen.getByRole('heading', { name: /Save Task Queue as Named Template/i })).toBeInTheDocument();
  });

  it('renders Concept 4 (Recipe & Template Runway) and supports template inspection and authoring', () => {
    render(
      <MemoryRouter initialEntries={['/?category=create-job&concept=recipe']}>
        <JobCreatorRedesignsMock />
      </MemoryRouter>
    );

    expect(screen.getByRole('region', { name: /Recipe and Template Runway/i })).toBeInTheDocument();
    expect(screen.getByText(/Standardized Archetypes/i)).toBeInTheDocument();

    // Clone as New Template button exists
    expect(screen.getByRole('button', { name: /Clone as New Template/i })).toBeInTheDocument();

    // Switch to Create Template Authoring Studio
    const createTemplateBtn = screen.getByRole('button', { name: /\+ Create Template/i });
    fireEvent.click(createTemplateBtn);

    expect(screen.getByRole('heading', { name: /Create New Reusable Template/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Save Template to Catalog/i })).toBeInTheDocument();
  });

  it('renders Concept 5 (Matrix Batch Dispatcher) and supports saving matrix grid as template', () => {
    render(
      <MemoryRouter initialEntries={['/?category=create-job&concept=matrix']}>
        <JobCreatorRedesignsMock />
      </MemoryRouter>
    );

    expect(screen.getByRole('region', { name: /Matrix Batch Dispatcher/i })).toBeInTheDocument();
    expect(screen.getByRole('table', { name: /Creator workload matrix/i })).toBeInTheDocument();

    // Batch dock is active because rows are selected
    expect(screen.getByRole('toolbar', { name: /Batch operations for selected creators/i })).toBeInTheDocument();

    // Click Save Grid as Template
    const saveGridBtn = screen.getByRole('button', { name: /Save Grid as Template/i });
    fireEvent.click(saveGridBtn);

    expect(screen.getByRole('heading', { name: /Save Grid Configuration as Named Template/i })).toBeInTheDocument();
  });

  it('supports resetting preview to baseline', () => {
    render(
      <MemoryRouter initialEntries={['/?category=create-job&concept=studio']}>
        <JobCreatorRedesignsMock />
      </MemoryRouter>
    );

    const resetBtn = screen.getByRole('button', { name: /Reset preview/i });
    fireEvent.click(resetBtn);

    expect(screen.getByRole('status')).toHaveTextContent(/Reset preview to default state/i);
  });
});
