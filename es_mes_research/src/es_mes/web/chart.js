import {h} from './vue.js';
const fmt=(n,d=2)=>n==null?'—':Number(n).toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d});
const time=t=>t?new Date(t).toLocaleTimeString('en-GB',{timeZone:'America/New_York',hour12:false}):'—';
const empty=(heading,description)=>h('div',{class:'empty'},[h('div',{class:'empty-icon'},'↗'),h('h3',heading),h('p',description)]);
export function aggregate(bars,interval){if(interval===1)return bars;const groups=new Map();for(const b of bars){const t=Math.floor(new Date(b.time).getTime()/300000)*300000;const a=groups.get(t);if(a){a.high=Math.max(a.high,b.high);a.low=Math.min(a.low,b.low);a.close=b.close;a.volume+=b.volume;a.count++;}else groups.set(t,{...b,time:new Date(t).toISOString(),count:1});}return [...groups.values()].filter(b=>b.count===5);}
export function chart(view,interval,selected,choose){
 const data=aggregate(view.bars||[],interval);if(!data.length)return empty('等待真实行情数据','启动观察后显示 K 线、模拟买卖点、止损和目标。当前不填充示例行情。');
 const trade=view.trades.find(t=>t.id===selected)||view.trades.at(-1),levels=[];
 if(view.opening)levels.push(['OR 高',view.opening.high,'#73a8fa'],['OR 低',view.opening.low,'#73a8fa']);
 if(trade)levels.push(['入场',trade.entry_price,'#e9edf5'],['止损',trade.stop,'#f47e8a'],['3R 目标',trade.target,'#44d5af']);
 const values=[...data.flatMap(b=>[b.low,b.high]),...levels.map(l=>l[1]),...view.markers.map(m=>m.price)];let low=Math.min(...values),high=Math.max(...values);const pad=Math.max((high-low)*.1,.5);low-=pad;high+=pad;
 const W=960,H=380,L=16,R=100,T=24,B=34,start=new Date(data[0].time).getTime();const end=Math.max(new Date(data.at(-1).time).getTime()+interval*60000,...view.markers.map(m=>new Date(m.time).getTime()))+interval*60000;
 const x=t=>L+(new Date(t).getTime()-start)/(end-start)*(W-L-R),y=p=>T+(high-p)/(high-low)*(H-T-B),width=Math.max(1,Math.min(9,(W-L-R)/data.length*.58)),nodes=[];
 for(let i=0;i<5;i++){const p=low+(high-low)*i/4;nodes.push(h('line',{x1:L,x2:W-R,y1:y(p),y2:y(p),class:'grid-line'}),h('text',{x:W-R+12,y:y(p)+4,class:'axis'},fmt(p)));}
 for(const b of data){const c=b.close>=b.open?'#45d5ad':'#ee7c8a';nodes.push(h('g',[h('title',`${time(b.time)} ET · O ${b.open} H ${b.high} L ${b.low} C ${b.close}`),h('line',{x1:x(b.time),x2:x(b.time),y1:y(b.high),y2:y(b.low),stroke:c}),h('rect',{x:x(b.time)-width/2,y:Math.min(y(b.open),y(b.close)),width,height:Math.max(1,Math.abs(y(b.close)-y(b.open))),fill:c})]));}
 for(const [period,color] of [[9,'#e6be68'],[20,'#ae8ceb'],[50,'#56bce1']]){const points=[];for(let i=period-1;i<data.length;i++)points.push(`${x(data[i].time)},${y(data.slice(i-period+1,i+1).reduce((s,b)=>s+b.close,0)/period)}`);if(points.length)nodes.push(h('polyline',{points:points.join(' '),fill:'none',stroke:color,'stroke-width':1.3}));}
 for(const [name,p,color] of levels)nodes.push(h('line',{x1:L,x2:W-R,y1:y(p),y2:y(p),stroke:color,'stroke-dasharray':'5 5',opacity:.65}),h('text',{x:W-R+10,y:y(p)-6,fill:color,class:'axis'},name));
 for(const mark of view.markers){const color=mark.trade_id===selected?'#f6cf77':mark.kind==='SIGNAL'?'#73a8fa':mark.kind==='ENTRY'?'#45d5ad':'#f47e8a';nodes.push(h('g',{class:'marker',onClick:()=>choose(mark.trade_id),tabindex:0,role:'button','aria-label':`${mark.label} ${time(mark.time)} ${mark.price}`,onKeydown:e=>{if(e.key==='Enter')choose(mark.trade_id)}},[h('title',`${mark.label} · ${time(mark.time)} ET · ${mark.price}`),h('circle',{cx:x(mark.time),cy:y(mark.price),r:mark.trade_id===selected?7:5,fill:color,stroke:'#0d1727','stroke-width':2})]));}
 for(const i of [0,Math.floor(data.length/2),data.length-1])nodes.push(h('text',{x:x(data[i].time),y:H-10,class:'axis','text-anchor':'middle'},time(data[i].time).slice(0,5)));
 return h('div',{class:'chart-wrap'},[h('svg',{viewBox:`0 0 ${W} ${H}`,role:'img','aria-label':'真实 K 线与模拟买卖点'},nodes),h('div',{class:'legend'},['蓝点 突破确认','绿点 模拟入场','红点 模拟平仓','MA9 / MA20 / MA50'].map(t=>h('span',t)))]);
}
