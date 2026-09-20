// Shared across StrategiesSection/LiveActivity/DetailModal so "is this
// crypto or something else" reads identically everywhere a strategy
// shows up -- one small color map, not three copies of it.
const ASSET_CLASS_COLOR: Record<string, string> = {
  crypto: 'border-amber-500/60 text-amber-700 dark:text-amber-400',
  etf: 'border-emerald-500/60 text-emerald-700 dark:text-emerald-400',
};

export function assetClassBadgeClass(assetClass: string | null): string {
  return assetClass
    ? (ASSET_CLASS_COLOR[assetClass] ?? 'border-border text-muted-foreground')
    : 'border-border text-muted-foreground';
}

export function assetClassLabel(assetClass: string | null): string {
  return assetClass ?? 'unknown';
}
