"use client";

import { useEffect, useRef } from "react";
import { ColorType, createChart, type CandlestickData, type UTCTimestamp } from "lightweight-charts";

type Candle = { time: number; open: string; high: string; low: string; close: string };

export function CandleChart({ candles }: { candles: Candle[] }) {
  const host = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const node = host.current;
    if (!node || candles.length === 0) return;
    const style = getComputedStyle(document.documentElement);
    const read = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback;
    const chart = createChart(node, {
      height: node.clientHeight || 280,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: read("--muted", "#9aa3ad") },
      grid: {
        vertLines: { color: read("--line", "#2c343d") },
        horzLines: { color: read("--line", "#2c343d") },
      },
      timeScale: { timeVisible: true, secondsVisible: false, borderColor: read("--line", "#2c343d") },
      rightPriceScale: { borderColor: read("--line", "#2c343d") },
    });
    const series = chart.addCandlestickSeries({
      upColor: read("--profit", "#3dbe86"),
      downColor: read("--loss", "#ff6b7d"),
      borderVisible: false,
      wickUpColor: read("--profit", "#3dbe86"),
      wickDownColor: read("--loss", "#ff6b7d"),
    });
    const rows: CandlestickData[] = candles.map((bar) => ({
      time: bar.time as UTCTimestamp,
      open: Number(bar.open),
      high: Number(bar.high),
      low: Number(bar.low),
      close: Number(bar.close),
    }));
    series.setData(rows);
    chart.timeScale().fitContent();
    const resize = () => chart.applyOptions({ width: node.clientWidth, height: node.clientHeight || 280 });
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(node);
    return () => {
      observer.disconnect();
      chart.remove();
    };
  }, [candles]);

  if (candles.length === 0) return <p className="text-sm text-muted h-full grid place-items-center">No points for this diagram yet.</p>;
  return <div ref={host} className="h-full w-full" />;
}
