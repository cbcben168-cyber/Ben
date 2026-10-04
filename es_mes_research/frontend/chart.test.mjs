import test from 'node:test';
import assert from 'node:assert/strict';
import {aggregate,chart} from '../src/es_mes/web/chart.js';
const bars=Array.from({length:16},(_,i)=>({time:new Date(Date.UTC(2026,9,2,13,30+i)).toISOString(),open:6000+i,high:6001+i,low:5999+i,close:6000.5+i,volume:10}));
test('5m aggregation preserves OHLCV and omits incomplete candles',()=>{
 const result=aggregate(bars,5);assert.equal(result.length,3);assert.equal(result[0].open,6000);assert.equal(result[0].close,6004.5);assert.equal(result[0].high,6005);assert.equal(result[0].low,5999);assert.equal(result[0].volume,50);
});
test('chart exposes actual entry and exit marker prices and selection',()=>{
 const marks=[{time:bars[10].time,price:6010.25,kind:'ENTRY',label:'模拟入场',trade_id:'one',direction:1},{time:bars[14].time,price:6014.25,kind:'EXIT',label:'模拟平仓',trade_id:'one',direction:1}];let selected;
 const node=chart({bars,markers:marks,trades:[{id:'one',entry_price:6010.25,stop:6009,target:6014}],opening:{high:6005,low:5999}},1,'one',id=>selected=id);
 const svg=node.children[0];const groups=svg.children.filter(n=>n.props?.class==='marker');assert.equal(groups.length,2);
 assert.match(groups[0].props['aria-label'],/6010.25/);assert.match(groups[1].props['aria-label'],/6014.25/);
 groups[0].props.onClick();assert.equal(selected,'one');assert.ok(Number.isFinite(groups[0].children[1].props.cx));
});
test('no real bars means an empty state, never generated prices',()=>{
 const node=chart({bars:[],markers:[],trades:[]},1,null,()=>{});assert.equal(node.props.class,'empty');assert.equal(node.children[1].children,'等待真实行情数据');
});
