/**
 * Public viewer stand-in.
 *
 * In the full app this module holds the "send a message" form and the mesh
 * channel feed shown in a radio node's popup. The viewer never transmits and
 * never shows people's channel messages, so both render nothing and the
 * sending code is not part of the public build.
 */

export function SigintSendForm(_props: {
  destination: string;
  source: string;
  region?: string;
  channel?: string;
}) {
  return null;
}

export function MeshtasticChannelFeed(_props: { region: string; channel: string }) {
  return null;
}
