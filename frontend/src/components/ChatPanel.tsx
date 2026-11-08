"use client";

import { type FormEvent, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { formatMoney, formatQuantity } from "@/lib/format";
import type { ChatActions, ChatMessage, ToolCallRecord } from "@/lib/types";

/** A short label for one lookup, e.g. "NVDA indicators (1d)". */
export function describeLookup(call: ToolCallRecord): string {
  const ticker = typeof call.arguments.ticker === "string" ? call.arguments.ticker.toUpperCase() : "";
  const timeframe = typeof call.arguments.timeframe === "string" ? call.arguments.timeframe : "1d";
  const label =
    {
      get_indicators: `${ticker} indicators (${timeframe})`,
      get_bars: `${ticker} prices (${timeframe})`,
      get_portfolio_risk: "portfolio risk",
      get_correlations: "correlations",
    }[call.name] ?? call.name;
  return call.status === "ok" ? label : `${label}, unavailable`;
}

function describeActions(actions: ChatActions | null): { text: string; failed: boolean }[] {
  if (!actions) return [];
  const trades = actions.trades.map((t) => ({
    failed: t.status === "failed",
    text:
      t.status === "ok"
        ? `${t.side === "buy" ? "Bought" : "Sold"} ${formatQuantity(t.quantity)} ${t.ticker} at ${formatMoney(t.price)}`
        : `Didn't ${t.side} ${formatQuantity(t.quantity)} ${t.ticker}`,
  }));
  const changes = actions.watchlist_changes.map((c) => ({
    failed: c.status === "failed",
    text:
      c.status === "ok"
        ? `${c.action === "add" ? "Added" : "Removed"} ${c.ticker} ${c.action === "add" ? "to" : "from"} watchlist`
        : `Didn't ${c.action} ${c.ticker}`,
  }));
  return [...changes, ...trades];
}

export function Message({ message }: { message: ChatMessage }) {
  const mine = message.role === "user";
  return (
    <li data-testid={`chat-${message.role}`} className={mine ? "border-l-2 border-primary pl-2" : ""}>
      <p className="whitespace-pre-wrap">{message.content}</p>
      {message.actions?.tool_calls && message.actions.tool_calls.length > 0 && (
        <p data-testid="chat-lookups" className="mt-1 text-xs text-muted">
          Analysis used: {message.actions.tool_calls.map(describeLookup).join(" · ")}
        </p>
      )}
      {describeActions(message.actions).map((action) => (
        <p
          key={action.text}
          data-testid="chat-action"
          className={`mt-1 text-sm ${action.failed ? "text-down" : "text-up"}`}
        >
          {action.failed ? "✕" : "✓"} {action.text}
        </p>
      ))}
    </li>
  );
}

interface Props {
  open: boolean;
  onToggle: () => void;
  onActions: (actions: ChatActions) => Promise<void>;
}

export function ChatPanel({ open, onToggle, onActions }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [waiting, setWaiting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.chatHistory().then(setMessages).catch(() => undefined);
  }, []);

  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "end" });
  }, [messages, waiting, open]);

  const send = async (event: FormEvent) => {
    event.preventDefault();
    const text = draft.trim();
    if (!text || waiting) return;
    setError(null);
    setWaiting(true);
    setDraft("");
    setMessages((list) => [...list, { role: "user", content: text, actions: null }]);
    try {
      const { message, ...actions } = await api.chat(text);
      setMessages((list) => [...list, { role: "assistant", content: message, actions }]);
      await onActions(actions);
    } catch (e) {
      // The server stored nothing, so hand the text back for another try
      setMessages((list) => list.slice(0, -1));
      setDraft(text);
      setError(e instanceof Error ? e.message : "The assistant didn't respond.");
    } finally {
      setWaiting(false);
    }
  };

  if (!open) {
    return (
      <aside aria-label="AI assistant" className="hidden border-l border-line lg:block">
        <button
          type="button"
          aria-expanded={false}
          onClick={onToggle}
          className="h-full w-full text-sm text-muted [writing-mode:vertical-rl] hover:bg-raised hover:text-ink"
        >
          Open assistant
        </button>
      </aside>
    );
  }

  return (
    <aside
      aria-label="AI assistant"
      className="flex max-h-[32rem] min-h-0 flex-col border-t border-line md:col-span-2 lg:col-span-1 lg:max-h-none lg:border-t-0 lg:border-l"
    >
      <div className="flex items-center justify-between px-3 pt-2 pb-1">
        <h2 className="text-sm font-medium text-muted">Assistant</h2>
        <button
          type="button"
          aria-expanded
          onClick={onToggle}
          className="hidden text-sm text-muted hover:text-ink lg:block"
        >
          Hide
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2" aria-live="polite">
        {messages.length === 0 && !waiting && (
          <p className="text-muted">
            Ask about your portfolio, or tell me what to do: &ldquo;Buy 5 AAPL&rdquo; or
            &ldquo;Add PYPL to my watchlist.&rdquo; Trades run immediately.
          </p>
        )}
        <ul className="space-y-3">
          {messages.map((message, index) => (
            <Message key={index} message={message} />
          ))}
        </ul>
        {waiting && (
          <p data-testid="chat-loading" className="mt-3 text-muted motion-safe:animate-pulse">
            Working on it…
          </p>
        )}
        <div ref={end} />
      </div>
      {error && (
        <p role="alert" className="px-3 pb-1 text-sm text-down">
          {error}
        </p>
      )}
      <form onSubmit={send} className="flex gap-2 border-t border-line p-2">
        <input
          aria-label="Message the assistant"
          placeholder="Message the assistant"
          value={draft}
          maxLength={4000}
          onChange={(event) => setDraft(event.target.value)}
          className="min-w-0 flex-1 border border-line bg-canvas px-2 py-1 placeholder:text-muted"
        />
        <button
          type="submit"
          disabled={waiting || draft.trim() === ""}
          className="bg-submit px-3 py-1 font-semibold text-white hover:brightness-110"
        >
          Send
        </button>
      </form>
    </aside>
  );
}
