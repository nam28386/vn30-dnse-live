import { useEffect, useRef } from 'react';
import { createChart, ColorType, LineSeries, HistogramSeries, type IChartApi, type ISeriesApi, type Time } from 'lightweight-charts';
import type { Point } from './types';
export type LineKey = 'price'|'vwap'|'ma21'|'cvd'|'spread'|'depth'|'imbalance'|'basis'|'signed_volume'|'quantity';
export function MarketChart({points, lines, height=180, histogram=false}: {points: Point[]; lines:{key:LineKey;color:string}[];height?:number;histogram?:boolean}) {
  const container = useRef<HTMLDivElement>(null);
  const instance = useRef<{chart:IChartApi; series:ISeriesApi<'Line'|'Histogram'>[]} | null>(null);
  const fit = useRef(false);
  // Callers supply stable line definitions so streaming updates preserve pan/zoom.
  useEffect(() => {
    if (!container.current) return;
    const chart = createChart(container.current, {height, autoSize:true,
      layout:{background:{type:ColorType.Solid,color:'#111d1f'},textColor:'#83999a',fontFamily:'monospace',fontSize:10, attributionLogo:true},
      grid:{vertLines:{color:'#1b2a2c'},horzLines:{color:'#1b2a2c'}},
      rightPriceScale:{borderColor:'#29393a'}, timeScale:{borderColor:'#29393a',timeVisible:true,secondsVisible:false,tickMarkFormatter:(time:Time)=>typeof time==='number'?new Date(time*1000).toLocaleTimeString('en-GB',{timeZone:'Asia/Ho_Chi_Minh',hour:'2-digit',minute:'2-digit'}):null},
      localization:{timeFormatter:(time:number)=>new Date(time*1000).toLocaleTimeString('en-GB',{timeZone:'Asia/Ho_Chi_Minh',hour:'2-digit',minute:'2-digit'})},
      crosshair:{vertLine:{color:'#617677'},horzLine:{color:'#617677'}} });
    const series = lines.map((line,i) => histogram && i===0 ? chart.addSeries(HistogramSeries,{color:line.color, priceFormat:{type:'volume'}}) :
      chart.addSeries(LineSeries,{color:line.color,lineWidth:i===0?2:1,priceLineVisible:false,lastValueVisible:i===0}));
    instance.current={chart,series}; fit.current=false;
    return () => {chart.remove();instance.current=null;};
  }, [lines, height, histogram]);
  useEffect(()=>{
    if(!instance.current) return;
    lines.forEach((line,i)=>{
      const bySecond = new Map<number, Point>();
      points.forEach(p => bySecond.set(Math.floor(new Date(p.time).getTime()/1000), p));
      const data = [...bySecond.entries()].sort(([a],[b])=>a-b).map(([second,p]) => { const value=p[line.key]; const time = second as Time;
        return value==null?{time}:{time,value,...(histogram?{color:value>=0?'#57cbb299':'#ed8d8999'}:{})}; });
      instance.current!.series[i].setData(data);
    });
    if(!fit.current && points.length){instance.current.chart.timeScale().fitContent();fit.current=true;}
  },[points,lines,histogram]);
  return <div className="chart" ref={container} style={{height}} data-testid="market-chart"/>;
}
