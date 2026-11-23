/**
 * Public viewer stand-in. The full app's version of this file talks to the
 * owner's server; the viewer has no server, so this one does nothing and
 * the original code is not part of the public build.
 */

export const SAR_CHOICE_KEY = 'shadowbroker_sar_mode_choice';
export type SarChoice = 'a_only' | 'b_active' | null;

function SarModeChooserModal(_props: {
  onClose: () => void;
  onChoiceMade: (choice: SarChoice) => void;
  [key: string]: unknown;
}) {
  return null;
}

export default SarModeChooserModal;
