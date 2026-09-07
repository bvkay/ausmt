"use strict";
// The survey page's driver for "Build a download script", which fetches the page's hand-off document and
// opens the dialog over the clicked level, the href being the SPA deep link. See docs: portal internals, page-fetch.js.

// The one navigation this file performs, behind a window-level name a jsdom driver can replace.
function pageFetchFallback(href){location.href=href;}
// One level's rows in the document's own order, a station with nothing at that level left out.
function pageFetchRows(doc,level){
  return ((doc&&doc.stations)||[])
    .map(r=>Object.assign({},r,{levels:(r.levels||[]).filter(l=>l&&l.level===level&&l.url)}))
    .filter(r=>r.levels.length);}
(function(){
  if(typeof document==="undefined"||!document.querySelectorAll)return;
  document.querySelectorAll("a[data-fetch]").forEach(a=>a.addEventListener("click",e=>{
    e.preventDefault();
    const url=a.getAttribute("data-fetch"),level=a.getAttribute("data-level"),href=a.getAttribute("href");
    fetch(url,{credentials:"same-origin"})
      .then(r=>{if(!r||!r.ok)throw new Error("hand-off document "+(r&&r.status));return r.json();})
      .then(doc=>{
        const rows=pageFetchRows(doc,level);
        if(!rows.length)throw new Error("no routed row at "+level);
        showWgetDialog({unix:tsWgetCommand(rows),mac:tsCurlCommand(rows,"curl"),win:tsCurlCommand(rows,"curl.exe")});})
      .catch(()=>pageFetchFallback(href));}));
})();
