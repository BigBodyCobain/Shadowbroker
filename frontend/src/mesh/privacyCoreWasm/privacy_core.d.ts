/* tslint:disable */
/* eslint-disable */

export function wasm_gate_decrypt(group_handle: bigint, ciphertext: Uint8Array): Uint8Array;

export function wasm_gate_encrypt(group_handle: bigint, plaintext: Uint8Array): Uint8Array;

export function wasm_gate_export_state(identity_handles_json: string, group_handles_json: string): Uint8Array;

export function wasm_gate_import_state(data: Uint8Array): string;

export function wasm_release_group(handle: bigint): boolean;

export function wasm_release_identity(handle: bigint): boolean;

export function wasm_reset_all_state(): boolean;

export type InitInput = RequestInfo | URL | Response | BufferSource | WebAssembly.Module;

export interface InitOutput {
    readonly memory: WebAssembly.Memory;
    readonly privacy_core_add_member: (a: bigint, b: bigint) => bigint;
    readonly privacy_core_commit_joined_group_handle: (a: bigint, b: number) => bigint;
    readonly privacy_core_commit_message_bytes: (a: number, b: bigint) => void;
    readonly privacy_core_commit_welcome_message_bytes: (a: number, b: bigint, c: number) => void;
    readonly privacy_core_create_dm_session: (a: bigint, b: bigint) => bigint;
    readonly privacy_core_create_group: (a: bigint) => bigint;
    readonly privacy_core_create_identity: () => bigint;
    readonly privacy_core_decrypt_group_message: (a: number, b: bigint, c: number, d: number) => void;
    readonly privacy_core_dm_decrypt: (a: bigint, b: number, c: number, d: number, e: number) => bigint;
    readonly privacy_core_dm_encrypt: (a: bigint, b: number, c: number, d: number, e: number) => bigint;
    readonly privacy_core_dm_session_welcome: (a: bigint, b: number, c: number) => bigint;
    readonly privacy_core_encrypt_group_message: (a: number, b: bigint, c: number, d: number) => void;
    readonly privacy_core_export_dm_state: (a: number, b: number) => bigint;
    readonly privacy_core_export_gate_state: (a: number, b: number, c: number, d: number, e: number, f: number) => bigint;
    readonly privacy_core_export_key_package: (a: number, b: bigint) => void;
    readonly privacy_core_export_public_bundle: (a: number, b: bigint) => void;
    readonly privacy_core_free_buffer: (a: number) => void;
    readonly privacy_core_handle_stats: (a: number, b: number) => bigint;
    readonly privacy_core_import_dm_state: (a: number, b: number, c: number, d: number) => bigint;
    readonly privacy_core_import_gate_state: (a: number, b: number, c: number, d: number) => bigint;
    readonly privacy_core_import_key_package: (a: number, b: number) => bigint;
    readonly privacy_core_join_dm_session: (a: bigint, b: number, c: number) => bigint;
    readonly privacy_core_last_error_message: (a: number) => void;
    readonly privacy_core_release_commit: (a: bigint) => number;
    readonly privacy_core_release_dm_session: (a: bigint) => number;
    readonly privacy_core_release_group: (a: bigint) => number;
    readonly privacy_core_release_identity: (a: bigint) => number;
    readonly privacy_core_release_key_package: (a: bigint) => number;
    readonly privacy_core_remove_member: (a: bigint, b: number) => bigint;
    readonly privacy_core_reset_all_state: () => number;
    readonly privacy_core_version: (a: number) => void;
    readonly wasm_gate_decrypt: (a: bigint, b: number, c: number) => [number, number, number, number];
    readonly wasm_gate_encrypt: (a: bigint, b: number, c: number) => [number, number, number, number];
    readonly wasm_gate_export_state: (a: number, b: number, c: number, d: number) => [number, number, number, number];
    readonly wasm_gate_import_state: (a: number, b: number) => [number, number, number, number];
    readonly wasm_release_group: (a: bigint) => number;
    readonly wasm_release_identity: (a: bigint) => number;
    readonly wasm_reset_all_state: () => number;
    readonly __wbindgen_exn_store: (a: number) => void;
    readonly __externref_table_alloc: () => number;
    readonly __wbindgen_externrefs: WebAssembly.Table;
    readonly __wbindgen_malloc: (a: number, b: number) => number;
    readonly __externref_table_dealloc: (a: number) => void;
    readonly __wbindgen_free: (a: number, b: number, c: number) => void;
    readonly __wbindgen_realloc: (a: number, b: number, c: number, d: number) => number;
    readonly __wbindgen_start: () => void;
}

export type SyncInitInput = BufferSource | WebAssembly.Module;

/**
 * Instantiates the given `module`, which can either be bytes or
 * a precompiled `WebAssembly.Module`.
 *
 * @param {{ module: SyncInitInput }} module - Passing `SyncInitInput` directly is deprecated.
 *
 * @returns {InitOutput}
 */
export function initSync(module: { module: SyncInitInput } | SyncInitInput): InitOutput;

/**
 * If `module_or_path` is {RequestInfo} or {URL}, makes a request and
 * for everything else, calls `WebAssembly.instantiate` directly.
 *
 * @param {{ module_or_path: InitInput | Promise<InitInput> }} module_or_path - Passing `InitInput` directly is deprecated.
 *
 * @returns {Promise<InitOutput>}
 */
export default function __wbg_init (module_or_path?: { module_or_path: InitInput | Promise<InitInput> } | InitInput | Promise<InitInput>): Promise<InitOutput>;
