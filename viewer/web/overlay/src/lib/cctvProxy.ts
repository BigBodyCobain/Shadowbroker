/**
 * Public viewer stand-in. The full app's version of this file talks to the
 * owner's server; the viewer has no server, so this one does nothing and
 * the original code is not part of the public build.
 */

/** The viewer has no camera proxy, so there is nothing to build a URL to. */
export function buildCctvProxyUrl(_rawUrl: string): string {
  return '';
}
