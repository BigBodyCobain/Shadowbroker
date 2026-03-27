export type MeshTerminalSecurityState = {
  wormholeRequired: boolean;
  wormholeReady: boolean;
  anonymousMode: boolean;
  anonymousModeReady: boolean;
};

export function getMeshTerminalWriteLockReason(state: MeshTerminalSecurityState): string {
  if (state.anonymousMode) {
    if (!state.anonymousModeReady) {
      return 'Mesh Terminal write commands are disabled until Wormhole hidden transport is ready for Anonymous Infonet mode.';
    }
    return 'Mesh Terminal write commands are disabled while Anonymous Infonet mode is active. Use MeshChat for hardened public and private actions.';
  }
  if (state.wormholeRequired) {
    if (!state.wormholeReady) {
      return 'Mesh Terminal write commands are disabled until Wormhole secure mode is ready.';
    }
    return 'Mesh Terminal write commands are disabled while Wormhole secure mode is active. Use MeshChat for hardened private actions.';
  }
  return '';
}

export function isMeshTerminalWriteCommand(cmd: string, args: string[]): boolean {
  const command = String(cmd || '').trim().toLowerCase();
  const sub = String(args[0] || '').trim().toLowerCase();

  if (
    [
      'connect',
      'sovereignty',
      'sovereign',
      'activate',
      'join',
      'send',
      'vote',
      'say',
      'predict',
      'stake',
      'rotate',
      'revoke',
      'dm',
      'inbox',
    ].includes(command)
  ) {
    return true;
  }

  if (command === 'mesh' || command === 'radio') {
    return sub === 'send' || sub === 's';
  }

  if (command === 'gate') {
    return sub === 'create';
  }

  return false;
}
