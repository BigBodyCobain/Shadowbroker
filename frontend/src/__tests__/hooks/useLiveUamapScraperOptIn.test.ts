import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { useLiveUamapScraperOptIn } from '@/hooks/useLiveUamapScraperOptIn';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('useLiveUamapScraperOptIn', () => {
  it('never blocks Global Incidents when the operator declines LiveUAMap', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            platform_requires_opt_in: true,
            ui_opted_in: false,
            ui_choice_recorded: false,
            scraper_enabled: false,
            env_override: null,
            api_configured: false,
            enrichment_enabled: false,
            provider_mode: 'gdelt-only',
          }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            platform_requires_opt_in: true,
            ui_opted_in: false,
            ui_choice_recorded: true,
            scraper_enabled: false,
            env_override: null,
            api_configured: false,
            enrichment_enabled: false,
            provider_mode: 'gdelt-only',
          }),
          { status: 200 },
        ),
      );
    const confirmMock = vi.spyOn(window, 'confirm').mockReturnValue(false);

    const { result } = renderHook(() => useLiveUamapScraperOptIn());
    await waitFor(() => expect(result.current.status).not.toBeNull());

    let blocked = true;
    act(() => {
      blocked = result.current.needsConsentBeforeEnable('global_incidents', true);
    });

    expect(blocked).toBe(false);
    expect(confirmMock).toHaveBeenCalledOnce();
    await waitFor(
      () => {
        expect(fetchMock).toHaveBeenCalledTimes(2);
      },
      { timeout: 1000 },
    );
    const [, options] = fetchMock.mock.calls[1];
    expect(options?.method).toBe('POST');
    expect(options?.body).toBe(JSON.stringify({ opted_in: false }));
  });

  it('does not prompt when a supported API provider is configured', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          platform_requires_opt_in: true,
          ui_opted_in: false,
          ui_choice_recorded: false,
          scraper_enabled: false,
          env_override: null,
          api_configured: true,
          enrichment_enabled: true,
          provider_mode: 'api',
        }),
        { status: 200 },
      ),
    );
    const confirmMock = vi.spyOn(window, 'confirm').mockReturnValue(true);

    const { result } = renderHook(() => useLiveUamapScraperOptIn());
    await waitFor(() => expect(result.current.status?.api_configured).toBe(true));

    expect(result.current.needsConsentBeforeEnable('global_incidents', true)).toBe(false);
    expect(confirmMock).not.toHaveBeenCalled();
  });
});
