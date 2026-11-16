import { useEffect, useState } from 'react';
import { Activity, ArrowDownRight, ArrowUpRight, ChevronDown, CircleDot, Database, FlaskConical, Layers3, Radio, ScanLine, ShieldCheck, WifiOff } from 'lucide-react';
import { MarketChart } from './Chart';
import { clock, fmt, type State } from './types';
import './style.css';

const priceLines=[{key:'price' as const,color:'#7bd8c3'},{key:'vwap' as const,color:'#d7b774'},{key:'ma21' as const,color:'#9d9ce6'}];
const cvdLines=[{key:'cvd' as const,color:'#7bd8c3'}];
const spreadLines=[{key:'spread' as const,color:'#d7b774'}];
const basisLines=[{key:'basis' as const,color:'#9d9ce6'}];
const flowLines=[{key:'signed_volume' as const,color:'#7bd8c3'}];
const liveVolumeLines=[{key:'quantity' as const,color:'#7bd8c3'}];

export function isMarketState(value: unknown): value is State {
  if (!value || typeof value !== 'object') return false;
  const v = value as Partial<State>;
  return (v.mode === 'MOCK' || v.mode === 'LIVE') && !!v.instrument && typeof v.instrument.symbol === 'string' &&
    !!v.snapshot && typeof v.snapshot.decision_time === 'string' && !!v.snapshot.values &&
    typeof v.snapshot.values === 'object' && Object.values(v.snapshot.values).every(x =>
      !!x && typeof x === 'object' && typeof x.quality === 'string' && typeof x.available_at === 'string') &&
    !!v.health && typeof v.health.quality === 'string' && Array.isArray(v.history) &&
    v.history.every(x => !!x && typeof x === 'object' && typeof x.time === 'string' && typeof x.price === 'number') &&
    Array.isArray(v.events) && v.events.every(x => !!x && typeof x === 'object' &&
      typeof x.event_id === 'string' && typeof x.event_time === 'string' && Array.isArray(x.transitions));
}

function useMarket() {
  const [state,setState] = useState<State|null>(null);
  const [connected,setConnected] = useState(false);
  const [error,setError] = useState<string|null>(null);
  useEffect(()=>{
    let alive=true, socket:WebSocket|undefined, retry:ReturnType<typeof setTimeout>|undefined;
    let attempts=0;
    const controller=new AbortController();
    fetch('/api/state',{signal:controller.signal}).then(r=>{if(!r.ok) throw Error('Backend unavailable');return r.json();})
      .then(s=>{if(alive){if(isMarketState(s)) setState(s); else setError('Dữ liệu backend không hợp lệ');}}).catch(e=>{if(alive && e.name!=='AbortError')setError('Waiting for the research service');});
    const connect=()=>{
      socket=new WebSocket(`${location.protocol==='https:'?'wss:':'ws:'}//${location.host}/api/stream`);
      socket.onopen=()=>{if(alive){setConnected(true);setError(null);attempts=0;}};
      socket.onmessage=e=>{if(alive){try{const data=JSON.parse(e.data);if(!isMarketState(data))throw Error();setState(data);setError(null);}catch{setError('Dữ liệu backend không hợp lệ');}}};
      socket.onerror=()=>socket?.close();
      socket.onclose=()=>{if(alive){setConnected(false);setError('Feed disconnected · displayed values are frozen');retry=setTimeout(connect,Math.min(1000*2**attempts++,15000));}};
    };
    connect();
    return()=>{alive=false;controller.abort();clearTimeout(retry);socket?.close();};
  },[]);
  return {state,connected,error};
}

export function Workstation({state, connected, error}: {state:State|null;connected:boolean;error:string|null}) {
  const [tab,setTab] = useState('overview');
  const [selected,setSelected] = useState<string|null>(null);
  const [flowView,setFlowView] = useState<'cvd'|'volume'>('cvd');
  const f = state?.snapshot.values;
  const last = state?.history.at(-1);
  const first = state?.history[0];
  const change=last&&first?last.price-first.price:null;
  const event=state?.events.find(e=>e.event_id===selected);
  const live = state?.mode === 'LIVE';
  useEffect(()=>{if(live)setFlowView('volume');},[live]);
  const sourceStatus = !connected ? 'DISCONNECTED' : live ? (state?.health.status ?? 'BLOCKED') : 'REPLAY CONNECTED';
  const reasonLabels: Record<string,string> = {
    missing_credentials: 'Thiếu biến DNSE_API_KEY hoặc DNSE_API_SECRET trong backend.',
    network_blocked: 'Không kết nối được DNSE qua mạng/proxy; kiểm tra TLS và quyền truy cập.',
    authentication_or_authorization_rejected: 'DNSE từ chối xác thực hoặc quyền truy cập.',
    front_contract_not_found: 'Chưa xác định được hợp đồng VN30F từ metadata.',
    invalid_market_metadata: 'Metadata DNSE không hợp lệ.',
    invalid_market_message: 'Đã bỏ qua message thị trường không hợp lệ.',
    internal_error: 'Backend gặp lỗi; chạy doctor_local để kiểm tra.',
  };
  const liveReason = live ? reasonLabels[state?.health.reason ?? ''] : undefined;
  return <div className="shell">
    <aside className="sidebar"><div className="brandmark"><ScanLine size={25}/></div><div className="sidebar-divider"/>
      <button aria-label="Market overview" className={tab==='overview'?'nav-icon active':'nav-icon'} onClick={()=>setTab('overview')}><Activity size={21}/></button>
      <button aria-label="Event research" className={tab==='events'?'nav-icon active':'nav-icon'} onClick={()=>setTab('events')}><FlaskConical size={21}/></button>
      <button aria-label="Data quality" className={tab==='quality'?'nav-icon active':'nav-icon'} onClick={()=>setTab('quality')}><Database size={20}/></button>
      <div className="sidebar-bottom"><span className="avatar">N</span><span className="tiny">v0.1</span></div>
    </aside>
    <main><header><div className="title-lockup"><span className="eyebrow">PERSONAL RESEARCH WORKSPACE</span><h1>Market Observatory <span>/ VN30</span></h1></div>
      <div className="header-status"><span className="read-only"><ShieldCheck size={13}/> READ ONLY</span><span className="mock-badge"><i/> {state ? (live ? 'LIVE · '+sourceStatus : 'MOCK REPLAY') : 'CHỜ NGUỒN'}</span></div></header>
      <div className="workspace-bar"><div className="workspace-tabs">{[['overview','Overview'],['events','Event research'],['quality','Data quality']].map(([id,label])=><button key={id} className={tab===id?'selected':''} onClick={()=>setTab(id)}>{label}</button>)}</div><span className="market-time">{state?clock(state.snapshot.decision_time):'—'} <span>ICT · {state?(live?'real time':'simulated'):'chưa có dữ liệu'}</span></span></div>
      {error&&<div role="alert" className="connection-alert"><WifiOff size={15}/>{error}</div>}
      {liveReason && <div role="status" className="connection-alert"><WifiOff size={15}/>{liveReason}</div>}
      <div className="context-row"><div className="contract"><span className="contract-icon"><Layers3 size={19}/></span><div><h2>VN30 Futures <span className="instrument-tag">FRONT CONTRACT</span></h2><p>{state?.instrument.symbol??'Discovering instrument…'} <span>·</span> {state?.instrument.expiry??'—'} expiry <span>·</span> MBP data</p></div></div><div className="session"><i className={connected?'status-dot':'status-dot offline'}/>{connected?sourceStatus:'CONNECTING'}<span>{live?'DNSE Production':'10s market time / tick'}</span></div></div>
      <section className="metrics" aria-label="Market metrics">
        <div className="metric"><span>LAST PRICE <small>POINTS</small></span><strong>{fmt(last?.price,1)}</strong><p className={(change??0)>=0?'mint':'rose'}>{(change??0)>=0?<ArrowUpRight size={14}/>:<ArrowDownRight size={14}/>} {fmt(change,1)} <span>vs. first visible trade</span></p></div>
        <div className="metric"><span>SESSION VWAP</span><strong>{fmt(f?.vwap?.value)}</strong><p><i className="legend-dot gold"/>Volume weighted · session</p></div>
        <div className="metric"><span>FUTURES − SPOT BASIS</span><strong className="lavender">{fmt(f?.basis?.value)}</strong><p>VN30 official index <em>{f?.basis?.quality??'MISSING'}</em></p></div>
        <div className="metric"><span>CUMULATIVE VOLUME DELTA</span><strong className="mint">{fmt(f?.cvd?.value,0)} <small>contracts</small></strong><p><i className="legend-dot mint-bg"/>Inferred side <em>{f?.cvd?.quality??'MISSING'}</em></p></div>
      </section>
      {!state?<div className="loading"><Activity/>Đang chờ backend…</div>:<>
      {tab==='overview'&&<div className="dashboard-grid">
        <section className="panel price-panel"><div className="panel-head"><div><h3>Price discovery</h3><span>VN30F · trade price / index points</span></div><div className="chart-legends"><span><i className="legend-dot mint-bg"/>Price</span><span><i className="legend-dot gold"/>VWAP</span><span><i className="legend-dot purple"/>MA21</span></div></div>
          <div className="chart-toolbar"><span className="pill">{live?'DNSE LIVE':'10s REPLAY'}</span><span>MA21 · completed 1m closes</span><span className="right-caption">{f?.ma21.quality==='WARMUP'?'MA21 WARMING UP':'AS-AVAILABLE OBSERVATIONS'}</span></div>
          <MarketChart points={state.history} lines={priceLines} height={290}/><div className="panel-foot"><span><CircleDot size={11}/> Event-time axis</span><span>{live?'Market event time · DNSE':'Session 09:00 ICT · synthetic fixture'}</span></div></section>
        <section className="panel health-panel"><div className="panel-head"><h3>Feed health</h3><Radio size={15} className="mint"/></div><div className="health-overall"><span className={state.health.quality==='GOOD'&&connected?'status-dot':'status-dot offline'}/><strong>{connected?(live?sourceStatus:state.health.quality):'DISCONNECTED'}</strong><span>{live?'DNSE SOURCE':'MOCK SOURCE'}</span></div>
          {live && <><div className="health-row"><span>Best bid</span><b>{fmt(state.market?.best_bid)}</b></div><div className="health-row"><span>Best ask</span><b>{fmt(state.market?.best_ask)}</b></div><div className="health-row"><span>Bid / ask levels</span><b>{fmt(state.market?.bid_depth_levels,0)} / {fmt(state.market?.ask_depth_levels,0)}</b></div><div className="health-row"><span>Last trade volume</span><b>{fmt(last?.quantity,0)}</b></div><div className="health-row"><span>VN30 Index</span><b>{fmt(state.market?.index)}</b></div><div className="health-row"><span>Last trade age</span><b>{fmt(state.market?.trade_age_seconds,1)} s</b></div><div className="health-row"><span>Last source update</span><b>{state.market?.last_source_at?clock(state.market.last_source_at)+' ICT':'—'}</b></div><div className="health-row"><span>Last received</span><b>{state.market?.last_received_at?clock(state.market.last_received_at)+' ICT':'—'}</b></div></>}
          <div className="health-row"><span>Quote freshness</span><b>{fmt(state.health.quote_age_seconds,1)} s</b></div><div className="health-row"><span>VN30 index freshness</span><b>{fmt(state.health.index_age_seconds,1)} s</b></div>
          <div className="health-row"><span>Rejected records</span><b>{state.health.rejected_records}</b></div><div className="health-row"><span>Reconnects</span><b>{state.health.reconnects}</b></div>
          <div className="health-rule"/><div className="health-note"><ShieldCheck size={16}/><p>Observation only<span>No execution routes or account access.</span></p></div>
          <div className="source-note"><span className="eyebrow">DATA INTERPRETATION</span><p>Aggregated market-by-price book. Trade direction is inferred; exchange aggressor identity is unconfirmed.</p></div></section>
        <section className="panel"><div className="panel-head"><div><h3>Trade flow</h3><span>{live?'Trade side unknown · contracts':'Inferred direction · contracts'}</span></div><div className="segmented"><button className={flowView==='cvd'?'chosen':''} onClick={()=>setFlowView('cvd')}>CVD</button><button className={flowView==='volume'?'chosen':''} onClick={()=>setFlowView('volume')}>Volume</button></div></div><MarketChart points={state.history} lines={flowView==='cvd'?cvdLines:(live?liveVolumeLines:flowLines)} histogram={flowView==='volume'} height={165}/></section>
        <section className="panel"><div className="panel-head"><div><h3>Liquidity structure</h3><span>Top 3 levels · aggregated MBP</span></div><span className="small-status">{f?.spread?.quality}</span></div><div className="liquidity-stats"><div><span>Spread</span><b>{fmt(f?.spread?.value)} <small>pts</small></b></div><div><span>Visible depth</span><b>{fmt(f?.depth?.value,0)}</b></div><div><span>Imbalance</span><b className="mint">{fmt(f?.imbalance?.value,3)}</b></div></div><MarketChart points={state.history} lines={spreadLines} height={110}/></section>
        <section className="panel basis-panel"><div className="panel-head"><div><h3>Futures–spot basis</h3><span>Last futures trade − official VN30 · points</span></div><span className="lavender">{fmt(f?.basis?.value)}</span></div><MarketChart points={state.history} lines={basisLines} height={145}/></section>
        <section className="panel event-preview"><div className="panel-head"><h3>Research events <span className="count">{state.events.length}</span></h3><button className="text-button" onClick={()=>setTab('events')}>Explore events ↗</button></div><EventList events={state.events.slice(-3).reverse()} onSelect={id=>{setSelected(id);setTab('events');}}/><div className="event-caption">Descriptive flow events · 30s markout horizon</div></section>
      </div>}
      {tab==='events'&&<section className="panel research-panel"><div className="panel-head"><div><h3>Event timeline</h3><span>Flow-size threshold ≥80 contracts · inferred direction · no trading signals</span></div><FlaskConical size={20}/></div><EventList events={[...state.events].reverse()} onSelect={setSelected}/>{event&&<div className="event-detail"><h3>{event.event_id}</h3><div className="detail-metrics"><span>Signed markout <b>{fmt(event.markout)} pts</b></span><span>Impact retention <b>{fmt(event.impact_retention)}</b></span><span>Spread recovery <b>{fmt(event.spread_recovery_seconds,1)} s</b></span><span>Depth recovery <b>{fmt(event.depth_recovery_seconds,1)} s</b></span></div>{event.transitions.map((t,i)=><p key={i}><time>{clock(t.at)}</time> <b>{t.status}</b> {t.reason}</p>)}</div>}</section>}
      {tab==='quality'&&<section className="panel research-panel"><div className="panel-head"><div><h3>Feature quality & availability</h3><span>Decision time {clock(state.snapshot.decision_time)} ICT · schema 1.0.0</span></div><Database size={20}/></div><div className="quality-table"><div className="quality-heading"><span>FEATURE</span><span>VALUE</span><span>QUALITY</span><span>AVAILABLE AT · ICT</span></div>{Object.entries(state.snapshot.values).map(([name,x])=><div key={name}><span>{name}</span><b>{fmt(x.value,3)}</b><span className={x.quality==='GOOD'?'mint':'gold-text'}>{x.quality}</span><time>{clock(x.available_at)}</time></div>)}</div><p className="quality-note">{live?'DNSE raw payloads and normalized observations are held separately in memory.':'Raw payloads and normalized records are stored separately.'} Estimated VN30 is excluded from official spot basis. Stale book values are unavailable; unknown sides reduce CVD quality.</p></section>}
      </>}
      <footer><span><i className="status-dot"/>VN30-DNSE-Live-Intelligence <b>v0.1</b></span><span>{state?(live?'DNSE DATA':'MOCK DATA'):'CHƯA CÓ DỮ LIỆU'} · RESEARCH ONLY · ALL TIMES ICT <ChevronDown size={11}/></span></footer>
    </main>
  </div>;
}
function EventList({events,onSelect}:{events:State['events'];onSelect:(id:string)=>void}) {
  return <div className="event-list">{events.length?events.map(e=><button className="event-row" key={e.event_id} onClick={()=>onSelect(e.event_id)}><span className="event-symbol"><Activity size={15}/></span><span className="event-name"><b>Flow shock <small>{e.direction===1?'inferred buy':e.direction===-1?'inferred sell':'unknown direction'}</small></b><span>{clock(e.event_time)} ICT · {e.quantity} contracts</span></span><span className={'event-status '+(e.status==='MATURED'?'mint':'gold-text')}>{e.status}</span><span className="event-markout">{fmt(e.markout)} <small>pts</small></span></button>):<p className="event-caption">No events observed yet.</p>}</div>;
}
export default function App(){ return <Workstation {...useMarket()}/>; }
