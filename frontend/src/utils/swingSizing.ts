/** Swing / day-trade paper sizing (USD capital). No real orders. */

export type SwingSettings = {
  capitalUsd: number;
  /** Fraction of capital risked per trade (e.g. 0.02 = 2%). */
  riskPct: number;
  /** Stop distance = ATR * atrMult. */
  atrMult: number;
  /** Reward:risk for target (e.g. 2 = 1:2). */
  rewardRisk: number;
  /** Annual return target as fraction (0.10 = 10%). */
  annualTargetPct: number;
  usdjpy: number;
  usdjpyManual: boolean;
  autoRefresh: boolean;
};

export const DEFAULT_SWING_SETTINGS: SwingSettings = {
  capitalUsd: 700,
  riskPct: 0.02,
  atrMult: 1.5,
  rewardRisk: 2,
  annualTargetPct: 0.1,
  usdjpy: 150,
  usdjpyManual: false,
  autoRefresh: true,
};

export const MAX_OPEN_POSITIONS = 2;

export type SwingSizing = {
  riskUsd: number;
  stopDistance: number;
  targetDistance: number;
  capitalShares: number;
  riskShares: number;
  recommended: number;
  notionalUsd: number;
};

export function annualTargetUsd(settings: SwingSettings): number {
  return settings.capitalUsd * settings.annualTargetPct;
}

export function riskBudgetUsd(settings: SwingSettings): number {
  return settings.capitalUsd * settings.riskPct;
}

export function computeSwingSizing(
  priceUsd: number | null | undefined,
  atr: number | null | undefined,
  settings: SwingSettings,
): SwingSizing | null {
  if (priceUsd == null || !(priceUsd > 0)) return null;
  const riskUsd = riskBudgetUsd(settings);
  const stopDistance =
    atr != null && atr > 0 ? atr * settings.atrMult : null;
  const capitalShares = Math.floor(settings.capitalUsd / priceUsd);
  let riskShares = capitalShares;
  if (stopDistance != null && stopDistance > 0) {
    riskShares = Math.floor(riskUsd / stopDistance);
  }
  const recommended = Math.max(0, Math.min(capitalShares, riskShares));
  const targetDistance =
    stopDistance != null ? stopDistance * settings.rewardRisk : 0;
  return {
    riskUsd,
    stopDistance: stopDistance ?? 0,
    targetDistance,
    capitalShares,
    riskShares,
    recommended,
    notionalUsd: recommended * priceUsd,
  };
}

export function suggestedStopTarget(
  side: "long" | "short",
  entry: number,
  atr: number | null | undefined,
  settings: SwingSettings,
): { stop: number; target: number } | null {
  if (!(entry > 0)) return null;
  const dist =
    atr != null && atr > 0 ? atr * settings.atrMult : entry * 0.03;
  const reward = dist * settings.rewardRisk;
  if (side === "long") {
    return { stop: entry - dist, target: entry + reward };
  }
  return { stop: entry + dist, target: entry - reward };
}
