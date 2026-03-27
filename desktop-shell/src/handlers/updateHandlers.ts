import type { NativeControlHandlerMap } from '../types';

export function createUpdateHandlers(): Pick<NativeControlHandlerMap, 'system.update'> {
  return {
    'system.update': async (_payload, _ctx, exec) =>
      exec('/api/system/update', {
        method: 'POST',
      }),
  };
}
