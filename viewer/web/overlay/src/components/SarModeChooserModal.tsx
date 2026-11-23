'use client';

/**
 * Public viewer stand-in. The full app's version of this dialog asks the
 * owner to pick a radar mode and talks to the owner's server. The viewer has
 * no server and nothing to choose: the public collector already publishes
 * the radar layer. So when the app opens this dialog (the first time a
 * visitor switches the radar layer back on), it answers at once and closes.
 * The original dialog is not part of the public build.
 */

import { useEffect } from 'react';

export const SAR_CHOICE_KEY = 'shadowbroker_sar_mode_choice';
export type SarChoice = 'a_only' | 'b_active' | null;

function SarModeChooserModal({
  onClose,
  onChoiceMade,
}: {
  onClose: () => void;
  onChoiceMade: (choice: SarChoice) => void;
  [key: string]: unknown;
}) {
  useEffect(() => {
    onChoiceMade('b_active');
    onClose();
    // Runs once: the dialog is mounted only to be answered.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return null;
}

export default SarModeChooserModal;
