import { readFileSync } from 'fs';
import path from 'path';
import { buildSignaturePayload, type JsonValue } from '@/mesh/meshProtocol';

type Fixture = {
  name: string;
  event_type: string;
  node_id: string;
  sequence: number;
  payload: Record<string, JsonValue>;
  expected: string;
};

describe('mesh canonical signature payloads', () => {
  const cwd = process.cwd();
  const fixturePath = cwd.endsWith('frontend')
    ? path.resolve(cwd, '..', 'docs', 'mesh', 'mesh-canonical-fixtures.json')
    : path.resolve(cwd, 'docs', 'mesh', 'mesh-canonical-fixtures.json');
  const fixtures = JSON.parse(readFileSync(fixturePath, 'utf-8')) as Fixture[];

  for (const fixture of fixtures) {
    it(`matches fixture: ${fixture.name}`, () => {
      const result = buildSignaturePayload({
        eventType: fixture.event_type,
        nodeId: fixture.node_id,
        sequence: fixture.sequence,
        payload: fixture.payload,
      });
      expect(result).toBe(fixture.expected);
    });
  }
});
