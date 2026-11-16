import { fireEvent, render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { Workstation, isMarketState } from './App';
import { fmt, type State } from './types';
vi.mock('./Chart',()=>({MarketChart:()=> <div data-testid="chart"/>}));
const time='2026-01-05T02:30:00Z';
const features=Object.fromEntries(['vwap','cvd','basis','ma21','spread','depth','imbalance'].map(key=>[key,{value:key==='vwap'?1850:null,quality:key==='cvd'?'INVALID':'MISSING',available_at:time}]));
const state={mode:'MOCK',version:'0.1.0',clock:'SIMULATED',instrument:{symbol:'MOCK-VN30-NEAR',expiry:'2026-01-15'},
 snapshot:{decision_time:time,session_id:'fixture',values:features},history:[],
 events:[{event_id:'shock:test',status:'MARKOUT_PENDING',quantity:100,direction:1,event_time:time,markout:null,
 impact_retention:null,spread_recovery_seconds:null,depth_recovery_seconds:null,
 transitions:[{status:'MARKOUT_PENDING',at:time,reason:'awaiting observation horizon'}]}],
 health:{connected:true,quality:'GOOD',quote_age_seconds:0,index_age_seconds:0,rejected_records:0,reconnects:0,message:'fixture'}} as State;
describe('research workstation',()=>{
 it('labels mock source and inference without replacing unavailable data with zero',()=>{
  render(<Workstation state={state} connected error={null}/>);
  expect(screen.getByText('MOCK REPLAY')).toBeInTheDocument();
  expect(screen.getByText('READ ONLY')).toBeInTheDocument();
  expect(screen.getByText(/exchange aggressor identity is unconfirmed/)).toBeInTheDocument();
  expect(fmt(null)).toBe('—');
  expect(fmt(0)).toBe('0.00');
 });
 it('opens lifecycle details without inventing pending markouts',()=>{
  render(<Workstation state={state} connected error={null}/>);
  fireEvent.click(screen.getByText('Explore events ↗'));
  fireEvent.click(screen.getByRole('button',{name:/Flow shock/}));
  expect(screen.getByText('awaiting observation horizon')).toBeInTheDocument();
  expect(screen.getByText('Signed markout')).toHaveTextContent('— pts');
 });
 it('opens the point-in-time feature quality table',()=>{
  render(<Workstation state={state} connected error={null}/>);
  fireEvent.click(screen.getAllByRole('button',{name:'Data quality'})[0]);
  expect(screen.getByText('Feature quality & availability')).toBeInTheDocument();
  expect(screen.getAllByText('INVALID')).toHaveLength(2);
 });
 it('reports frozen values on disconnect',()=>{
  render(<Workstation state={state} connected={false} error="Feed disconnected · displayed values are frozen"/>);
  expect(screen.getByRole('alert')).toHaveTextContent('values are frozen');
  expect(screen.getByText('DISCONNECTED')).toBeInTheDocument();
 });
 it('renders a truthful loading state before data arrives',()=>{
  render(<Workstation state={null} connected={false} error={null}/>);
  expect(screen.getByText(/Đang chờ backend/)).toBeInTheDocument();
  expect(screen.queryByTestId('chart')).not.toBeInTheDocument();
  expect(screen.getByText('CHỜ NGUỒN')).toBeInTheDocument();
  expect(screen.queryByText('MOCK REPLAY')).not.toBeInTheDocument();
 });
});

describe('LIVE trạng thái nguồn',()=>{
 it('hiển thị BLOCKED mà không giả lập giá hoặc chuyển sang MOCK',()=>{
  const live={...state,mode:'LIVE',history:[],events:[],health:{...state.health,quality:'STALE',status:'BLOCKED'},
   market:{best_bid:null,best_ask:null,index:null,last_source_at:null,last_received_at:null,trade_age_seconds:null}} as State;
  render(<Workstation state={live} connected error={null}/>);
  expect(screen.getByText(/LIVE · BLOCKED/)).toBeInTheDocument();
  expect(screen.getByText('DNSE SOURCE')).toBeInTheDocument();
  expect(screen.getByText('Best bid')).toBeInTheDocument();
  expect(screen.queryByText('MOCK REPLAY')).not.toBeInTheDocument();
  expect(screen.queryByText(/synthetic fixture/)).not.toBeInTheDocument();
 });
});

describe('LIVE dữ liệu giả lập để kiểm thử',()=>{
 it('hiển thị giá bid ask, volume và nguồn DNSE',()=>{
  const live={...state,mode:'LIVE',health:{...state.health,status:'LIVE'},
   market:{best_bid:100,best_ask:101,index:99,last_source_at:time,last_received_at:time,trade_age_seconds:1},
   history:[{time,available_at:time,price:100.5,quantity:7,side:'UNKNOWN',vwap:null,ma21:null,cvd:null,
    signed_volume:null,spread:1,depth:null,imbalance:null,basis:null}]} as State;
  render(<Workstation state={live} connected error={null}/>);
  expect(screen.getByText(/LIVE · LIVE/)).toBeInTheDocument();
  expect(screen.getByText('100.00')).toBeInTheDocument();
  expect(screen.getByText('101.00')).toBeInTheDocument();
  expect(screen.getByText('100.5')).toBeInTheDocument();
  expect(screen.getByText('Last trade volume')).toBeInTheDocument();
  expect(screen.queryByText('MOCK REPLAY')).not.toBeInTheDocument();
 });
});

it.each(['CONNECTED_NO_TRADES','STALE','DISCONNECTED'])('giữ trạng thái %s khi nguồn LIVE đổi trạng thái', status=>{
 const live={...state,mode:'LIVE',history:[],events:[],health:{...state.health,quality:'STALE',status},
  market:{best_bid:null,best_ask:null,index:null,last_source_at:null,last_received_at:null,trade_age_seconds:null}} as State;
 render(<Workstation state={live} connected error={null}/>);
 expect(screen.getByText(new RegExp(`LIVE · ${status}`))).toBeInTheDocument();
 expect(screen.queryByText('MOCK REPLAY')).not.toBeInTheDocument();
});


it('từ chối dữ liệu backend thiếu cấu trúc thay vì làm trắng giao diện',()=>{
 expect(isMarketState(null)).toBe(false);
 expect(isMarketState({mode:'LIVE', snapshot:{values:{}}, history:[]})).toBe(false);
 expect(isMarketState(state)).toBe(true);
 expect(isMarketState({...state, events:[null]})).toBe(false);
 expect(isMarketState({...state, history:[null]})).toBe(false);
 expect(isMarketState({...state, snapshot:{...state.snapshot, values:{vwap:null}}})).toBe(false);
});


it('LIVE thiếu credentials báo rõ mà không chuyển thành MOCK',()=>{
 const live={...state,mode:'LIVE',history:[],events:[],health:{...state.health,quality:'STALE',status:'BLOCKED',reason:'missing_credentials'}} as State;
 render(<Workstation state={live} connected error={null}/>);
 expect(screen.getByText(/Thiếu biến DNSE_API_KEY/)).toBeInTheDocument();
 expect(screen.getByText(/LIVE · BLOCKED/)).toBeInTheDocument();
 expect(screen.queryByText('MOCK REPLAY')).not.toBeInTheDocument();
});
