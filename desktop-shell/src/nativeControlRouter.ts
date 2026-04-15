import type {
  DesktopControlCommand,
  DesktopControlPayloadMap,
} from '../../frontend/src/lib/desktopControlContract';
import {
  controlCommandCapability as resolveCommandCapability,
  extractGateTargetRef,
  sessionProfileCapabilities as capabilitiesForProfile,
} from '../../frontend/src/lib/desktopControlContract';
import { createSettingsHandlers } from './handlers/settingsHandlers';
import { createUpdateHandlers } from './handlers/updateHandlers';
import { createWormholeHandlers } from './handlers/wormholeHandlers';
import type {
  NativeControlExecutor,
  NativeControlHandlerContext,
  NativeControlHandlerMap,
  NativeControlInvokeMeta,
} from './types';

function createHandlerMap(): NativeControlHandlerMap {
  return {
    ...createWormholeHandlers(),
    ...createSettingsHandlers(),
    ...createUpdateHandlers(),
  };
}

export function createNativeControlRouter(
  ctx: NativeControlHandlerContext,
  exec: NativeControlExecutor,
) {
  const handlers = createHandlerMap();
  return {
    async invoke<C extends DesktopControlCommand>(
      command: C,
      payload: DesktopControlPayloadMap[C],
      meta?: NativeControlInvokeMeta,
    ): Promise<unknown> {
      const handler = handlers[command];
      if (!handler) {
        throw new Error(`native_control_handler_missing:${command}`);
      }
      const expectedCapability = resolveCommandCapability(command);
      const profile = ctx.sessionProfile;
      const profileCapabilities = profile ? capabilitiesForProfile(profile) : [];
      const profileAllows =
        !profile || profileCapabilities.length === 0 || profileCapabilities.includes(expectedCapability);
      const profileEnforced = Boolean((ctx.enforceSessionProfile || meta?.enforceProfileHint) && profile);
      const allowedCapabilitiesConfigured =
        Array.isArray(ctx.allowedCapabilities) && ctx.allowedCapabilities.length > 0;
      const capabilityDenied =
        allowedCapabilitiesConfigured && !ctx.allowedCapabilities!.includes(expectedCapability);
      const targetRef = extractGateTargetRef(command, payload);
      const auditBase = {
        command,
        expectedCapability,
        declaredCapability: meta?.capability,
        ...(targetRef ? { targetRef } : {}),
        sessionProfile: profile,
        sessionProfileHint: meta?.sessionProfileHint,
        enforceProfileHint: meta?.enforceProfileHint,
        profileAllows,
        allowedCapabilitiesConfigured,
        enforced: profileEnforced,
      } as const;
      if (meta?.capability && meta.capability !== expectedCapability) {
        ctx.auditControlUse?.({
          ...auditBase,
          outcome: 'capability_mismatch',
        });
        throw new Error(
          `native_control_capability_mismatch:${meta.capability}:${expectedCapability}`,
        );
      }
      if (capabilityDenied) {
        ctx.auditControlUse?.({
          ...auditBase,
          outcome: 'capability_denied',
        });
        throw new Error(`native_control_capability_denied:${expectedCapability}`);
      }
      if (!profileAllows) {
        const profileMessage = `native_control_profile_mismatch:${profile}:${expectedCapability}`;
        ctx.auditControlUse?.({
          ...auditBase,
          outcome: profileEnforced ? 'profile_denied' : 'profile_warn',
        });
        if (profileEnforced) {
          throw new Error(profileMessage);
        }
        console.warn(profileMessage, {
          command,
          sessionProfileHint: meta?.sessionProfileHint,
        });
      }
      if (profileAllows) {
        ctx.auditControlUse?.({
          ...auditBase,
          outcome: 'allowed',
        });
      }
      return handler(payload, ctx, exec);
    },
  };
}
