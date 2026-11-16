export type Quality = 'GOOD'|'INFERRED'|'STALE'|'MISSING'|'WARMUP'|'INVALID';
export interface Feature { value: number|null; quality: Quality; available_at: string }
export interface Point { time: string; available_at: string; price: number; quantity: number; side: string;
  vwap: number|null; ma21: number|null; cvd: number|null; signed_volume: number|null;
  spread: number|null; depth: number|null; imbalance: number|null; basis: number|null }
export interface Shock { event_id: string; status: string; quantity: number; direction: number|null; event_time: string;
  markout: number|null; impact_retention: number|null; spread_recovery_seconds: number|null;
  depth_recovery_seconds: number|null; transitions: {status: string; at: string; reason: string}[] }
export interface State { mode: 'MOCK'|'LIVE'; version: string; clock: string;
  instrument: { symbol: string; expiry: string|null };
  snapshot: { decision_time: string; session_id: string; values: Record<string, Feature> };
  history: Point[]; events: Shock[];
  health: { connected: boolean; quality: Quality; quote_age_seconds: number|null; index_age_seconds: number|null;
    rejected_records: number; reconnects: number; message: string; status?: string; reason?: string };
  market?: {best_bid:number|null;best_ask:number|null;index:number|null;last_source_at:string|null;last_received_at:string|null;trade_age_seconds:number|null;bid_depth_levels?:number|null;ask_depth_levels?:number|null} }
export const fmt = (value: number|null|undefined, digits=2) => value == null ? '—' : value.toLocaleString('en-US', {minimumFractionDigits:digits, maximumFractionDigits:digits});
export const clock = (value: string) => new Date(value).toLocaleTimeString('en-GB', {timeZone:'Asia/Ho_Chi_Minh', hour12:false});
