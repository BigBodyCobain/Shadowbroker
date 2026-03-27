export interface CongressTrade {
  politician_name: string;
  chamber: string;
  filing_date: string;
  transaction_date?: string;
  ticker?: string;
  asset_name?: string;
  transaction_type?: string;
  amount_range?: string;
  owner_type?: string;
  party?: string;
}

export interface InsiderTransaction {
  name: string;
  ticker: string;
  share: number;
  change: number;
  filing_date: string;
  transaction_date?: string;
  transaction_code?: string;
  transaction_price: number;
}

export interface UWStatusResponse {
  ok: boolean;
  configured: boolean;
  source: string;
  attribution: string;
}

export interface UWCongressResponse {
  ok: boolean;
  source: string;
  attribution: string;
  trades: CongressTrade[];
}

export interface UWInsiderResponse {
  ok: boolean;
  source: string;
  attribution: string;
  transactions: InsiderTransaction[];
}
