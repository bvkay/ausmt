"use strict";
// The survey page's driver for "Build a download script": the hand-off document is fetched and the dialog
// opened over the clicked level, the href being the SPA deep link. See docs: portal internals, page-fetch.js.

// The one navigation here, behind a window-level name a jsdom driver can replace.
function pageFetchFallback(href){location.href=href;}
// One level's rows, a station with nothing at that level left out.
function pageFetchRows(doc,level){
  return ((doc&&doc.stations)||[])
    .map(r=>Object.assign({},r,{levels:(r.levels||[]).filter(l=>l&&l.level===level&&l.url)}))
    .filter(r=>r.levels.length);}
(function(){
  if(typeof document==="undefined"||!document.querySelectorAll)return;
  document.querySelectorAll("a[data-fetch]").forEach(a=>a.addEventListener("click",e=>{
    // A modified or secondary click is the browser's own gesture, which the href answers.
    if(e.defaultPrevented||e.button!==0||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;
    e.preventDefault();
    if(a.dataset.fetching)return;
    const url=a.getAttribute("data-fetch"),level=a.getAttribute("data-level"),href=a.getAttribute("href");
    if(!document.getElementById("wgetModal")){pageFetchFallback(href);return;}
    a.dataset.fetching="1";
    fetch(url,{credentials:"same-origin"})
      .then(r=>{if(!r||!r.ok)throw new Error("hand-off document "+(r&&r.status));return r.json();})
      .then(doc=>{
        const rows=pageFetchRows(doc,level);
        if(!rows.length)throw new Error("no routed row at "+level);
        if(!showWgetDialog({unix:tsWgetCommand(rows),mac:tsCurlCommand(rows,"curl"),win:tsCurlCommand(rows,"curl.exe")}))throw new Error("no dialog");})
      .catch(()=>pageFetchFallback(href))
      .then(()=>{delete a.dataset.fetching;});}));
})();
