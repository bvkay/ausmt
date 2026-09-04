"use strict";
// HTML-escaping helpers. ALL survey/station metadata is escaped through these before it reaches innerHTML.
// See docs: portal internals, security.js.
function esc(s){return String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
function escAttr(s){return esc(s);}
// The "/" branch is a SAME-ORIGIN path and nothing else. See docs: portal internals, security.js.
function escUrl(u){u=String(u==null?"":u);return /^(https?:|mailto:|#|\/(?![\/\\]))/i.test(u)?esc(u):"#";}
