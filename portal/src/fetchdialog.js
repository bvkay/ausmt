"use strict";
// The "Fetch from your terminal" dialog, #wgetModal, shared by the SPA and every generated survey page. See
// docs: portal internals, fetchdialog.js.

// A missing element costs nothing, because a harness that stubs the document must still load this file.
function _fetchBind(id,fn){const el=document.getElementById(id);if(el)el.onclick=fn;}
// The SPA reports a copy in its toast (drawer.js copyTxt), a page in the button's own label.
function _fetchCopy(text,btn){
  if(typeof copyTxt==="function"){copyTxt(text);return;}
  const say=(msg)=>{if(!btn)return;const was=btn.textContent;btn.textContent=msg;setTimeout(()=>{btn.textContent=was;},1800);};
  if(!navigator.clipboard||!navigator.clipboard.writeText){say("Select and copy the command");return;}
  navigator.clipboard.writeText(text).then(()=>say("Copied"),()=>say("Copy failed; select manually"));}
var _wgetCmds=null;
function _paintWgetTab(os){
  const pre=document.getElementById("wgetCmd"),note=document.getElementById("wgetOsNote"),seg=document.getElementById("wgetOs");
  if(!_wgetCmds||!pre)return;
  pre.textContent=(os==="win")?_wgetCmds.win:(os==="mac"?_wgetCmds.mac:_wgetCmds.unix);
  if(note)note.textContent=WGET_OS_NOTES[os]||"";
  // aria-selected rides with the .on class, never separately, so the paint and the readable state agree.
  if(seg&&seg.querySelectorAll)[...seg.querySelectorAll("button")].forEach(b=>{
    const on=b.dataset.os===os;b.classList.toggle("on",on);b.setAttribute("aria-selected",String(on));});}
function showWgetDialog(cmds){
  const m=document.getElementById("wgetModal"),pre=document.getElementById("wgetCmd");
  if(!m||!pre){_fetchCopy(cmds.unix,null);return;}
  _wgetCmds=cmds;
  _paintWgetTab(detectOs());
  _wgetReturnFocus=(typeof document!=="undefined")?document.activeElement:null;
  m.classList.remove("hidden");
  if(m.querySelector){const box=m.querySelector(".introwelcome-box");if(box&&box.focus)box.focus();}}
// The dialog declares aria-modal, so it owes Escape, click-out and focus return, and drawer.js yields to it.
let _wgetReturnFocus=null;
function hideWgetDialog(){
  const m=document.getElementById("wgetModal");if(!m)return;
  m.classList.add("hidden");
  const f=_wgetReturnFocus;_wgetReturnFocus=null;
  if(f&&f.focus){try{f.focus();}catch(e){/* opener gone from the DOM: nothing to restore to */}}}
(function(){const seg=document.getElementById("wgetOs");
  if(seg&&seg.addEventListener)seg.addEventListener("click",e=>{
    const b=e.target.closest?e.target.closest("button"):null;
    if(b&&b.dataset.os)_paintWgetTab(b.dataset.os);});})();
_fetchBind("wgetClose",hideWgetDialog);
(function(){const m=document.getElementById("wgetModal");
  // Guarded, so a stubbed document still loads the module.
  if(!m||!m.addEventListener||!document.addEventListener)return;
  m.addEventListener("click",e=>{if(e.target===m)hideWgetDialog();});
  document.addEventListener("keydown",e=>{
    if(e.key==="Escape"&&!m.classList.contains("hidden"))hideWgetDialog();});})();
_fetchBind("wgetCopy",()=>{const pre=document.getElementById("wgetCmd"),btn=document.getElementById("wgetCopy");
  if(pre)_fetchCopy(pre.textContent,btn);});
