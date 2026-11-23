/**
 * Public viewer stand-in. The full app's version of this file talks to the
 * owner's server; the viewer has no server, so this one does nothing and
 * the original code is not part of the public build.
 */

import type {
  ShodanCountResponse,
  ShodanHostResponse,
  ShodanSearchResponse,
  ShodanStatusResponse,
} from '@/types/shodan';

function unavailable<T>(): Promise<T> {
  return Promise.reject(new Error('Not available in the public viewer'));
}

export function fetchShodanStatus(): Promise<ShodanStatusResponse> {
  return unavailable();
}

export function searchShodan(_query: string, _page = 1, _facets: string[] = []): Promise<ShodanSearchResponse> {
  return unavailable();
}

export function countShodan(_query: string, _facets: string[] = []): Promise<ShodanCountResponse> {
  return unavailable();
}

export function lookupShodanHost(_ip: string, _history = false): Promise<ShodanHostResponse> {
  return unavailable();
}
