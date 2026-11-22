// @ts-nocheck
'use client';

import { useEffect } from 'react';

export function useMeshIdentitySync(ctx: any) {
  const {
    clientHydrated, identityRefreshToken, wormholeEnabled, wormholeReadyState,
    getNodeIdentity, hasSovereignty, hydrateWormholeContacts, fetchWormholeIdentity,
    purgeBrowserSigningMaterial, purgeBrowserContactGraph, purgeBrowserDmState,
    setContacts, setIdentity,
  } = ctx;
  useEffect(() => {
    let alive = true;
    const syncIdentity = async () => {
      const localIdentity = getNodeIdentity();
      if (localIdentity && hasSovereignty()) {
        try {
          const hydratedContacts = await hydrateWormholeContacts(true);
          if (alive) setContacts(hydratedContacts);
        } catch {
          if (alive) setContacts(getContacts());
        }
        if (alive) setIdentity(localIdentity);
        return;
      }
      if (wormholeEnabled && wormholeReadyState) {
        try {
          const wormholeIdentity = await fetchWormholeIdentity();
          purgeBrowserSigningMaterial();
          purgeBrowserContactGraph();
          await purgeBrowserDmState();
          const hydratedContacts = await hydrateWormholeContacts(true);
          if (!alive) return;
          setContacts(hydratedContacts);
          setIdentity({
            publicKey: wormholeIdentity.public_key,
            privateKey: '',
            nodeId: wormholeIdentity.node_id,
          });
          return;
        } catch {
          /* ignore */
        }
      }
      if (alive) setIdentity(null);
    };
    void syncIdentity();
    return () => {
      alive = false;
    };
  }, [clientHydrated, identityRefreshToken, wormholeEnabled, wormholeReadyState]);
}
