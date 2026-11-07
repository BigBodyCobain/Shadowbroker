import React from 'react';
import { render, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import WikiImage from '@/components/WikiImage';
import { fetchWikipediaSummary } from '@/lib/wikimediaClient';

vi.mock('@/lib/wikimediaClient', () => ({ fetchWikipediaSummary: vi.fn().mockResolvedValue(null) }));

describe('operator portrait article titles', () => {
  it('decodes the article slug before sending it to the summary API', async () => {
    render(<WikiImage wikiUrl="https://en.wikipedia.org/wiki/Fran%C3%A7ois_Pinault" />);
    await waitFor(() => expect(fetchWikipediaSummary).toHaveBeenCalledWith('Fran\u00e7ois_Pinault'));
  });
});
