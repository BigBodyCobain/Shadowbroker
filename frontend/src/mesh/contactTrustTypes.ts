export type ContactTrustSeverity = 'danger' | 'warn' | 'good' | 'info';
export type ContactRootDistributionState =
  | 'none'
  | 'internal_only'
  | 'single_witness'
  | 'quorum_witnessed'
  | 'witness_policy_not_met';
export type ContactRootWitnessProvenanceState =
  | 'none'
  | 'internal_only'
  | 'single_witness'
  | 'witness_policy_not_met'
  | 'local_quorum'
  | 'independent_quorum';

export type ContactTrustRecommendedAction =
  | 'none'
  | 'import_invite'
  | 'verify_sas'
  | 'show_sas'
  | 'reverify';

export interface ContactTrustSummary {
  state: string;
  label: string;
  severity: ContactTrustSeverity;
  detail: string;
  verifiedFirstContact: boolean;
  recommendedAction: ContactTrustRecommendedAction;
  legacyLookup: boolean;
  inviteAttested: boolean;
  rootAttested?: boolean;
  rootWitnessed?: boolean;
  rootDistributionState?: ContactRootDistributionState;
  rootWitnessPolicyFingerprint?: string;
  rootWitnessCount?: number;
  rootWitnessThreshold?: number;
  rootWitnessQuorumMet?: boolean;
  rootWitnessProvenanceState?: ContactRootWitnessProvenanceState;
  rootWitnessDomainCount?: number;
  rootWitnessIndependentQuorumMet?: boolean;
  rootManifestGeneration?: number;
  rootRotationProven?: boolean;
  rootMismatch?: boolean;
  registryMismatch: boolean;
  transparencyConflict: boolean;
}
