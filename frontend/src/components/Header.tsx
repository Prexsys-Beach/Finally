import { formatMoney, formatSignedMoney, trendClass } from "@/lib/format";
import type { ConnectionStatus, DataMode, Portfolio } from "@/lib/types";

const CONNECTION: Record<ConnectionStatus, { label: string; color: string }> = {
  connected: { label: "Connected", color: "bg-up" },
  reconnecting: { label: "Reconnecting", color: "bg-accent" },
  disconnected: { label: "Disconnected", color: "bg-down" },
};

const MODE: Record<DataMode, string> = {
  simulated: "Simulated prices",
  live: "Market data",
  eod: "End-of-day closes",
};

function Figure({ label, value, className = "" }: { label: string; value: string; className?: string }) {
  return (
    <div>
      <div className="text-xs text-muted">{label}</div>
      <div className={`text-base leading-tight font-medium ${className}`}>{value}</div>
    </div>
  );
}

interface Props {
  portfolio: Portfolio | null;
  status: ConnectionStatus;
  mode: DataMode | null;
}

export function Header({ portfolio, status, mode }: Props) {
  const connection = CONNECTION[status];
  return (
    <header className="flex flex-wrap items-center gap-x-8 gap-y-2 border-b border-line px-4 py-2">
      <h1 className="text-lg font-bold text-accent">FinAlly</h1>
      <div data-testid="total-value">
        <div className="text-xs text-muted">Portfolio value</div>
        <div className="text-2xl leading-tight font-semibold">
          {formatMoney(portfolio?.total_value ?? null)}
        </div>
      </div>
      <div data-testid="cash-balance">
        <Figure label="Cash" value={formatMoney(portfolio?.cash_balance ?? null)} />
      </div>
      <Figure
        label="Unrealized P&L"
        value={formatSignedMoney(portfolio?.unrealized_pnl ?? null)}
        className={trendClass(portfolio?.unrealized_pnl ?? null)}
      />
      <div className="ml-auto flex items-center gap-4 text-sm text-muted">
        {mode && <span data-testid="data-mode">{MODE[mode]}</span>}
        <span className="flex items-center gap-1.5" data-testid="connection-status" data-status={status}>
          <span aria-hidden className={`size-2 rounded-full ${connection.color}`} />
          {connection.label}
        </span>
      </div>
    </header>
  );
}
