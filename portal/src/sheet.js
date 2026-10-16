"use strict";
// sheet.js - the phone layout's bottom sheet. See docs: portal internals, sheet.js.
const SHEET_QUERY="(max-width:900px)";
const SHEET_CARD_QUERY="(min-width:761px)";
const SHEET_SNAPS=["peek","half","full"];
const SHEET_WORDS={peek:"peek",half:"half height",full:"full height"};
const SHEET_PEEK_PX=120,SHEET_HEADER_PX=52,SHEET_CARD_GAP_PX=16,SHEET_CARD_W_PX=420;
const SHEET_TAP_SLOP_PX=6;
const _sheetEl=document.getElementById("sheet");
const _sheetHandle=document.getElementById("sheetHandle");
const _sheetBack=document.getElementById("sheetBack");
function _sheetMq(q){try{return (typeof window!=="undefined"&&window.matchMedia)?window.matchMedia(q):null;}catch(e){return null;}}
const _sheetPhoneMq=_sheetMq(SHEET_QUERY);
let _sheetPrevSnap="half",_sheetUncollapsed=false;
const _sheetDrawerHome=(function(){const d=document.getElementById("drawer");return d?[d.parentElement,d.nextSibling]:null;})();

function sheetPhone(){return !!(_sheetEl&&_sheetPhoneMq&&_sheetPhoneMq.matches);}
function sheetActive(){return sheetPhone()&&(typeof curView==="undefined"||curView==="map");}
function sheetCard(){const m=_sheetMq(SHEET_CARD_QUERY);return !!(m&&m.matches);}
function sheetSnapState(){return (_sheetEl&&_sheetEl.dataset.snap)||"half";}
function sheetSnapHeights(){
  const vh=window.innerHeight||0;
  const box=_sheetEl&&_sheetEl.getBoundingClientRect?_sheetEl.getBoundingClientRect().height:0;
  const full=box>0?box:vh-SHEET_HEADER_PX-(sheetCard()?2*SHEET_CARD_GAP_PX:0);
  return {peek:SHEET_PEEK_PX,half:Math.round(vh*0.5),full:Math.max(SHEET_PEEK_PX,full)};}
function sheetNearestSnap(px,h){
  let best="half",d=Infinity;
  SHEET_SNAPS.forEach(k=>{const e=Math.abs(h[k]-px);if(e<d){d=e;best=k;}});
  return best;}
function _sheetLabel(){
  if(!_sheetHandle)return;
  const s=sheetSnapState();
  _sheetHandle.setAttribute("aria-expanded",String(s!=="peek"));
  _sheetHandle.setAttribute("aria-label","Panel at "+SHEET_WORDS[s]+". Tap to change its height, or drag it.");}
function sheetSnap(name){
  if(!_sheetEl||SHEET_SNAPS.indexOf(name)<0)return;
  _sheetEl.dataset.snap=name;_sheetLabel();}
function sheetCycle(){sheetSnap(SHEET_SNAPS[(SHEET_SNAPS.indexOf(sheetSnapState())+1)%SHEET_SNAPS.length]);}

function _sheetSendDrawerHome(){
  const d=document.getElementById("drawer");
  if(!d||!_sheetDrawerHome||d.parentElement!==_sheetEl)return;
  const [p,n]=_sheetDrawerHome;p.insertBefore(d,(n&&n.parentNode===p)?n:null);}
function sheetHostDrawer(){
  if(!_sheetEl)return false;
  if(!sheetActive()){sheetReleaseDrawer();_sheetSendDrawerHome();return false;}
  const d=document.getElementById("drawer");
  if(d&&d.parentElement!==_sheetEl)_sheetEl.appendChild(d);
  if(_sheetEl.dataset.host!=="drawer"){_sheetPrevSnap=sheetSnapState();_sheetEl.dataset.host="drawer";}
  sheetSnap("half");
  return true;}
function sheetReleaseDrawer(){
  if(!_sheetEl||_sheetEl.dataset.host!=="drawer")return;
  _sheetEl.dataset.host="filters";sheetSnap(_sheetPrevSnap);}
function sheetFreeArea(w,h,card,visible){
  return card?{left:Math.min(w,SHEET_CARD_GAP_PX+SHEET_CARD_W_PX),top:0,right:w,bottom:h}
             :{left:0,top:0,right:w,bottom:Math.max(0,h-visible)};}
// See docs: portal internals, sheet.js.
function sheetClearArea(w,h,hostTop){
  let vis=sheetSnapHeights()[sheetSnapState()];
  const r=_sheetEl&&_sheetEl.getBoundingClientRect?_sheetEl.getBoundingClientRect():null;
  if(r&&r.height>0)vis=hostTop+h-r.top;
  return sheetFreeArea(w,h,sheetCard(),Math.max(0,Math.min(h,vis)));}
function sheetRecentre(ll){
  if(!sheetActive()||typeof map==="undefined"||!map||typeof map.panBy!=="function"||
     typeof map.getSize!=="function"||typeof map.latLngToContainerPoint!=="function")return;
  const sz=map.getSize(),pt=map.latLngToContainerPoint(ll);
  const f=sheetFreeArea(sz.x,sz.y,sheetCard(),sheetSnapHeights()[sheetSnapState()]);
  const off=[pt.x-(f.left+f.right)/2,pt.y-(f.top+f.bottom)/2];
  if(!isFinite(off[0])||!isFinite(off[1]))return;
  const still=_sheetMq("(prefers-reduced-motion:reduce)");
  map.panBy(off,{animate:!(still&&still.matches)});}

function sheetSync(){
  const d=document.getElementById("drawer"),pane=document.getElementById("filterPane");
  if(sheetPhone()){
    if(pane&&pane.classList.contains("collapsed")){pane.classList.remove("collapsed");_sheetUncollapsed=true;}
    if(d&&d.classList.contains("open")&&sheetActive())sheetHostDrawer();
  }else{
    sheetReleaseDrawer();_sheetSendDrawerHome();
    if(_sheetUncollapsed&&pane){pane.classList.add("collapsed");_sheetUncollapsed=false;}
  }
  if(typeof placeCounts==="function")placeCounts();}
if(_sheetPhoneMq){
  const onChange=()=>{sheetSync();if(typeof map!=="undefined"&&map&&typeof map.invalidateSize==="function")map.invalidateSize();};
  if(typeof _sheetPhoneMq.addEventListener==="function")_sheetPhoneMq.addEventListener("change",onChange);
  else if(typeof _sheetPhoneMq.addListener==="function")_sheetPhoneMq.addListener(onChange);}

let _sheetDrag=null,_sheetSwallowClick=false;
function _sheetDragVisible(d,y){const h=sheetSnapHeights();return Math.max(h.peek,Math.min(h.full,d.from-(y-d.y0)));}
if(_sheetEl&&_sheetHandle){
  _sheetHandle.addEventListener("pointerdown",e=>{
    if(!sheetPhone())return;
    _sheetSwallowClick=false;
    _sheetDrag={y0:e.clientY,from:sheetSnapHeights()[sheetSnapState()],moved:false};
    try{if(e.pointerId!=null&&_sheetHandle.setPointerCapture)_sheetHandle.setPointerCapture(e.pointerId);}catch(err){/* no capture */}});
  _sheetHandle.addEventListener("pointermove",e=>{
    const d=_sheetDrag;if(!d)return;
    if(Math.abs(e.clientY-d.y0)>SHEET_TAP_SLOP_PX)d.moved=true;
    if(!d.moved)return;
    _sheetEl.classList.add("dragging");
    _sheetEl.style.transform="translateY("+(sheetSnapHeights().full-_sheetDragVisible(d,e.clientY))+"px)";});
  const end=e=>{
    const d=_sheetDrag;if(!d)return;
    _sheetDrag=null;_sheetEl.classList.remove("dragging");_sheetEl.style.transform="";
    if(!d.moved&&Math.abs(e.clientY-d.y0)<=SHEET_TAP_SLOP_PX)return;
    _sheetSwallowClick=true;setTimeout(()=>{_sheetSwallowClick=false;},0);
    sheetSnap(sheetNearestSnap(_sheetDragVisible(d,e.clientY),sheetSnapHeights()));};
  _sheetHandle.addEventListener("pointerup",end);
  _sheetHandle.addEventListener("pointercancel",()=>{_sheetDrag=null;_sheetEl.classList.remove("dragging");_sheetEl.style.transform="";});
  _sheetHandle.addEventListener("click",()=>{if(_sheetSwallowClick){_sheetSwallowClick=false;return;}sheetCycle();});
}
if(_sheetBack)_sheetBack.addEventListener("click",()=>{if(typeof closeDrawer==="function")closeDrawer();else sheetReleaseDrawer();});
