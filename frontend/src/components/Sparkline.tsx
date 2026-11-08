import type { PricePoint } from "@/lib/types";

const WIDTH = 64;
const HEIGHT = 22;
const MAX_POINTS = 60; // The last hour of one-minute closes

export function Sparkline({ points }: { points: PricePoint[] | undefined }) {
  const recent = points?.slice(-MAX_POINTS) ?? [];
  if (recent.length < 2) return <svg aria-hidden width={WIDTH} height={HEIGHT} />;

  const values = recent.map((point) => point.value);
  const low = Math.min(...values);
  const range = Math.max(...values) - low || 1;
  const path = values
    .map((value, index) => {
      const x = (index / (values.length - 1)) * WIDTH;
      const y = HEIGHT - 2 - ((value - low) / range) * (HEIGHT - 4);
      return `${index === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(" ");
  const rising = values[values.length - 1] >= values[0];

  return (
    <svg aria-hidden width={WIDTH} height={HEIGHT} data-testid="sparkline">
      <path d={path} fill="none" strokeWidth={1.5} className={rising ? "stroke-up" : "stroke-down"} />
    </svg>
  );
}
