// SPDX-License-Identifier: GPL-3.0-only
"use strict";
const root = document.querySelector("#main"), banner = document.querySelector("#connection"), error = document.querySelector("#error");
const menus = ["Play","Setlist","Parameters","Scripts","Devices","Status","System"];
let state = null, menu = "Play", online = false, generation = 0;
const bindings = new Map();
function el(tag, value, parent, attrs = {}) {
  const node = document.createElement(tag);
  if (value !== null) node.textContent = String(value);
  for (const [key,val] of Object.entries(attrs)) node.setAttribute(key,String(val));
  if (parent) parent.append(node);
  return node;
}
function button(parent, label, action, selected = null) {
  const b = el("button",label,parent,{type:"button"});
  if (selected !== null) b.setAttribute("aria-current",selected);
  b.addEventListener("click",action); return b;
}
function showError(e) { error.textContent = e.message || String(e); }
async function command(type, fields = {}) {
  error.textContent = "";
  try {
    const response = await fetch("/api/v1/command", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({type,...fields})});
    const reply = await response.json();
    if (!response.ok || !reply.ok) throw new Error((reply.code || response.status)+": "+(reply.message || "Command refused"));
    return reply.result || {};
  } catch(e) { showError(e); throw e; }
}
function act(type, fields = {}) { return command(type,fields).catch(()=>null); }
function title() {
  const entry = state?.setlist.find(x=>x.index===state.current.index);
  const message = (online?"Connected":"Disconnected — reconnecting")+" · "+(state?.engine.state || "waiting")+" · "+(entry?.title || "No patch")+
    (state?.current.switching?" · Switching…":"")+(state?.current.error?" · "+state.current.error:"");
  if(banner.textContent!==message) banner.textContent=message;
}
function group(parent,name) { const s=el("section",null,parent);el("h2",name,s);return s; }
function row(parent) { return el("div",null,parent,{class:"row"}); }
function format(v,unit="") { return v == null?"—":(typeof v==="number"?Number(v.toPrecision(5)):String(v))+(unit?" "+unit:""); }
function bind(key,fn) { if (key) { if(!bindings.has(key)) bindings.set(key,[]);bindings.get(key).push(fn); } }
function numeric(parent,label,meta,value,norm,key,fields,disabled=false) {
  const box=el("div",null,parent,{class:"control"});
  const id="control-"+root.querySelectorAll(".control").length;
  const lab=el("label",label,box,{for:id});
  const out=el("span",format(value,meta.unit),lab,{class:"value"});
  let input;
  if (Array.isArray(meta.choices)&&meta.choices.length) {
    input=el("select",null,box,{id,"aria-label":label});
    meta.choices.forEach((choice,i)=>{const n=typeof choice==="object"?(choice.value??i):i;el("option",typeof choice==="object"?(choice.label??choice.name??n):choice,input,{value:n});});
    input.value=String(value);
  } else {
    input=el("input",null,box,{id,type:"range",min:0,max:1,step:"0.001","aria-label":label});
    input.value=String(norm??0);
  }
  input.disabled=disabled;
  if(disabled) out.textContent="Unavailable";
  let pending=false, dragging=false;
  input.addEventListener('pointerdown',()=>{dragging=true;});
  for(const kind of ['pointerup','pointercancel','lostpointercapture','blur']) input.addEventListener(kind,()=>{dragging=false;});
  input.addEventListener("change",async()=>{
    pending=true;
    const result=await act("set",{...fields,...(input.tagName==="SELECT"?{value:Number(input.value)}:{norm:Number(input.value)})});
    pending=false;
    if(result) update(result);
    else update({value,norm});
  });
  function update(v) {
    if(disabled||pending) return;
    value=v.value;norm=v.norm;out.textContent=format(value,meta.unit);
    if(!dragging) input.value=String(input.tagName==="SELECT"?value:norm??0);
  }
  bind(key,update);
}
function play() {
  if(!state.pages.length) el("p","No control pages in this patch.",root);
  for(const page of state.pages) {
    const grid=el("div",null,group(root,page.title),{class:"controls"});
    for(const id of page.controls) {
      const c=state.controls[id];
      if(c) numeric(grid,c.label,c,c.value,c.norm,c.key,{control:id},!c.resolved);
    }
  }
}
function setlist() {
  const r=row(root);
  button(r,"Previous",()=>act("prev"));button(r,"Next",()=>act("next"));
  const list=el("div",null,root,{class:"setlist"});
  state.setlist.forEach(e=>button(list,e.title,()=>act("select",{index:e.index}),e.index===state.current.index));
}
async function parameters(g) {
  const data=await act("params.list");
  if(!data||g!==generation)return;
  for(const m of data.modules||[]) {
    const grid=el("div",null,group(root,m.name+" · "+m.id),{class:"controls"});
    for(const p of m.parameters) numeric(grid,p.name||p.id,p,p.value,p.norm,p.key,{target:{param:{module:m.id,param:p.id}}},p.mapped);
  }
  const grid=el("div",null,group(root,"Modulation cables"),{class:"controls"});
  for(const c of data.cables||[]) if(!c.mapping) numeric(grid,c.from.module+":"+c.from.port+" → "+c.to.module+":"+c.to.param,{},c.amount,(c.amount+1)/2,c.key,{target:{modAmount:{from:c.from,to:c.to}}});
}
function scripts() {
  if(!state.scripts.length)el("p","No scripts in this entry.",root);
  for(const s of state.scripts) {
    const panel=group(root,s.file),r=row(panel);
    el("p",s.state+" · Restarts: "+s.restarts,r);
    for(const a of ["start","stop","restart"])button(r,a[0].toUpperCase()+a.slice(1)+" script",()=>act("script."+a,{file:s.file}));
    const grid=el("div",null,panel,{class:"controls"});
    for(const [id,c] of Object.entries(state.controls))if(c.target?.script?.file===s.file)numeric(grid,c.label,c,c.value,c.norm,c.key,{control:id},!c.resolved);
    if(!s.controls.length)el("p","No declared controls available yet.",panel);
    for(const c of s.controls) {
      if(Object.values(state.controls).some(x=>x.target?.script?.file===s.file&&x.target.script.control===c.id))continue;
      const lo=c.min??c.lo??0,hi=c.max??c.hi??1,v=c.value??c.default??lo;
      if(typeof v==="number"&&hi>lo)numeric(grid,c.label||c.id,c,v,(v-lo)/(hi-lo), "script:"+s.file+":"+c.id,{target:{script:{file:s.file,control:c.id}}});
      else el("p",(c.label||c.id)+": "+String(v),grid);
    }
  }
}
function select(parent,label,options,current,callback) {
  const r=row(parent), id="select-"+root.querySelectorAll("select").length;
  el("label",label,r,{for:id}); const s=el("select",null,r,{id});
  for(const o of options)el("option",o.label,s,{value:o.value});
  if(current!=null)s.value=String(current);
  s.addEventListener("change",()=>callback(s.value));return s;
}
async function devices(g) {
  const [audio,midi]=await Promise.all([act("audio.devices"),act("midi.devices")]);
  if(g!==generation)return;
  const a=group(root,"Audio"), d=audio?.devices||[], current=state.engine.audio||{};
  select(a,"Audio device",d.map(x=>({label:x.name,value:x.id})),current.deviceId,v=>act("audio.select",{deviceId:v}));
  select(a,"Sample rate",[44100,48000,96000].map(v=>({label:v+" Hz",value:v})),current.sampleRate,v=>act("audio.rate",{hz:Number(v)}));
  select(a,"Buffer frames",[64,128,256,512,1024].map(v=>({label:v,value:v})),current.bufferFrames,v=>act("audio.buffer",{frames:Number(v)}));
  const m=group(root,"MIDI");
  for(const dev of midi?.devices||state.midi.devices) {
    const r=row(m);const cb=el("input",null,r,{type:"checkbox",id:"midi-"+m.querySelectorAll("input").length});
    cb.checked=!!dev.enabled;el("label",dev.name,r,{for:cb.id});cb.addEventListener("change",async()=>{if(!await act("midi.enable",{deviceId:dev.id,on:cb.checked}))cb.checked=!cb.checked;});
  }
}
function details(parent,name,content){const p=el("pre",JSON.stringify(content,null,2),group(parent,name));p.dataset.detail=name;return p;}
function refreshStatus(){
  const fields={"Engine":state.engine,"OSC routes":state.osc,"Controller drops":state.engine.controllerDrops??state.osc.controllerDrops??"Not reported by this Player version","Bundle check":state.bundle.check,"Warnings":state.warnings};
  for(const p of root.querySelectorAll("pre[data-detail]")) { const v=JSON.stringify(fields[p.dataset.detail],null,2); if(p.textContent!==v)p.textContent=v; }
}
function status() {
  details(root,"Engine",state.engine);
  details(root,"OSC routes",state.osc);
  details(root,"Controller drops",state.engine.controllerDrops??state.osc.controllerDrops??"Not reported by this Player version");
  details(root,"Bundle check",state.bundle.check);
  details(root,"Warnings",state.warnings);
}
async function system(g) {
  button(root,"Restart engine",()=>act("engine.restart"));
  const b=await act("bundle.list");if(!b||g!==generation)return;
  const p=group(root,"Bundles");
  for(const x of b.bundles||[]) {
    const r=row(p);button(r,x.title||x.name,()=>act("bundle.load",{name:x.name}),x.name===b.current);
    button(r,"Check "+(x.title||x.name),async()=>{const v=await act("bundle.check",{name:x.name});if(v&&g===generation)details(p,"Check result",v);});
  }
}
function render() {
  const g=++generation;bindings.clear();root.replaceChildren();el("h1",menu,root);
  if(!state){el("p","Waiting for Player…",root);return;}
  ({Play:play,Setlist:setlist,Parameters:parameters,Scripts:scripts,Devices:devices,Status:status,System:system})[menu](g);
}
for(const m of menus) {
  const b=button(document.querySelector("#menus"),m,()=>{menu=m;for(const x of document.querySelectorAll("#menus button"))x.setAttribute("aria-pressed",String(x.textContent===m));render();});
  b.setAttribute("aria-pressed",String(m===menu));
}
document.querySelector("#panic").addEventListener("click",()=>act("panic"));
const events=new EventSource("/api/v1/events");
events.addEventListener("open",()=>{online=true;title();});
events.addEventListener("error",()=>{online=false;title();});
events.addEventListener("state",e=>{state=JSON.parse(e.data);online=true;title();render();});
events.addEventListener("values",e=>{
  const d=JSON.parse(e.data);if(!state||state.rev!==d.rev)return;
  for(const [k,v] of Object.entries(d.values)){
    for(const c of Object.values(state.controls))if(c.key===k)Object.assign(c,v);
    for(const fn of bindings.get(k)||[])fn(v);
  }
});
events.addEventListener("status",e=>{
  const d=JSON.parse(e.data);if(!state||state.rev!==d.rev)return;
  Object.assign(state.engine,d.engine);state.osc=d.osc||state.osc;
  if(d.scripts?.length)state.scripts=d.scripts;
  title();if(menu==="Status")refreshStatus();
});
