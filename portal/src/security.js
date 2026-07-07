"use strict";
// HTML-escaping helpers. ALL survey/station metadata is escaped through these before it
// reaches innerHTML. esc -> text nodes; escAttr -> quoted attribute values; escUrl -> hrefs.
function esc(s){return String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
function escAttr(s){return esc(s);}
function escUrl(u){u=String(u==null?"":u);return /^(https?:|mailto:|#|\/)/i.test(u)?esc(u):"#";}
