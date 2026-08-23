import { describe, expect, it } from 'vitest';

import { isPublicReadOnlyHost } from '@/lib/publicRuntime';

describe('public runtime boundary', () => {
  it('marks only the public ShadowBroker host as read-only', () => {
    expect(isPublicReadOnlyHost('shadow.qdev.run')).toBe(true);
    expect(isPublicReadOnlyHost('LOCALHOST')).toBe(false);
  });
});
