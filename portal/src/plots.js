"use strict";
// Pure SVG transfer-function plotters (no data/DOM dependency): ρ, φ, |T|, phase tensor.
// Each plotter takes a TF entry `t` (one per station, from tf.json). Columns are POSITIONAL — see
// the legend in data.js / docs developer/data-files.md (TF_COLUMNS):
//   t[T.periods] periods · t[T.rho_xy] ρ_xy · t[T.rho_yx] ρ_yx · t[T.phs_xy] φ_xy · t[T.phs_yx_adj] φ_yx(+180°) · t[T.tip_mag] |T| ·
//   t[T.pt_min] pt_min · t[T.pt_max] pt_max · t[T.pt_az] pt_az · t[T.pt_beta] pt_β
const W=372,PADL=40,PADR=8;
const xScale=per=>{const lo=Math.log10(per[0]),hi=Math.log10(per[per.length-1]);return v=>PADL+(Math.log10(v)-lo)/(hi-lo||1)*(W-PADL-PADR);};
function decades(per){const o=[];const lo=Math.ceil(Math.log10(per[0])),hi=Math.floor(Math.log10(per[per.length-1]));for(let d=lo;d<=hi;d++)o.push(10**d);return o;}
function supTen(d){const m={"-":"⁻","0":"⁰","1":"¹","2":"²","3":"³","4":"⁴","5":"⁵","6":"⁶"};return "10"+String(d).split("").map(c=>m[c]||c).join("");}
function path(per,vals,x,y){let d="",pen=false;per.forEach((p,i)=>{const v=vals[i];if(v==null||!isFinite(y(v))){pen=false;return;}d+=(pen?"L":"M")+x(p).toFixed(1)+","+y(v).toFixed(1);pen=true;});return d;}
function dots(per,vals,x,y,c){return per.map((p,i)=>vals[i]==null||!isFinite(y(vals[i]))?"":`<circle cx="${x(p).toFixed(1)}" cy="${y(vals[i]).toFixed(1)}" r="2.1" fill="${c}"/>`).join("");}
function frame(H,x,per,yl){let g=`<rect x="${PADL}" y="4" width="${W-PADL-PADR}" height="${H-22}" fill="none" stroke="#2E4254"/>`;
  decades(per).forEach(d=>{g+=`<line x1="${x(d)}" y1="4" x2="${x(d)}" y2="${H-18}" stroke="#2E4254" stroke-dasharray="2,3"/><text x="${x(d)}" y="${H-6}" fill="#8FA3B0" font-size="8.5" text-anchor="middle" font-family="monospace">${supTen(Math.round(Math.log10(d)))}</text>`;});
  yl.forEach(([yy,t])=>g+=`<text x="${PADL-4}" y="${yy+3}" fill="#8FA3B0" font-size="8.5" text-anchor="end" font-family="monospace">${t}</text>`);return g;}
function rhoPlot(t){const per=t[T.periods];if(!per.length)return"";const vals=[...t[T.rho_xy],...t[T.rho_yx]].filter(v=>v!=null&&v>0);if(!vals.length)return"";
  const H=118,x=xScale(per);let lo=Math.floor(Math.log10(Math.min(...vals))),hi=Math.ceil(Math.log10(Math.max(...vals)));if(hi<=lo)hi=lo+1;
  const y=v=>4+(hi-Math.log10(v))/(hi-lo)*(H-26);const yl=[];for(let d=lo;d<=hi;d++)yl.push([y(10**d),supTen(d)]);
  return `<div class="plot"><div class="ptitle">apparent resistivity ρ (Ω·m)</div><svg width="${W}" height="${H}" role="img">`+frame(H,x,per,yl)+
   `<path d="${path(per,t[T.rho_xy],x,y)}" fill="none" stroke="#E0782F" stroke-width="1.1"/>`+dots(per,t[T.rho_xy],x,y,"#E0782F")+
   `<path d="${path(per,t[T.rho_yx],x,y)}" fill="none" stroke="#2E8FA3" stroke-width="1.1"/>`+dots(per,t[T.rho_yx],x,y,"#2E8FA3")+
   `<text x="${W-10}" y="14" fill="#E0782F" font-size="9" text-anchor="end" font-family="monospace">xy</text><text x="${W-10}" y="25" fill="#2E8FA3" font-size="9" text-anchor="end" font-family="monospace">yx</text></svg></div>`;}
function phasePlot(t){const per=t[T.periods];if(!per.length)return"";if(!t[T.phs_xy].some(v=>v!=null)&&!t[T.phs_yx_adj].some(v=>v!=null))return"";
  const H=92,x=xScale(per);const y=v=>4+(105-v)/120*(H-22);
  return `<div class="plot"><div class="ptitle">phase φ (°, yx +180°)</div><svg width="${W}" height="${H}" role="img">`+frame(H,x,per,[[y(0),"0"],[y(45),"45"],[y(90),"90"]])+
   `<line x1="${PADL}" y1="${y(45)}" x2="${W-PADR}" y2="${y(45)}" stroke="#2E4254" stroke-dasharray="2,3"/>`+
   `<path d="${path(per,t[T.phs_xy],x,y)}" fill="none" stroke="#E0782F" stroke-width="1.1"/>`+dots(per,t[T.phs_xy],x,y,"#E0782F")+
   `<path d="${path(per,t[T.phs_yx_adj],x,y)}" fill="none" stroke="#2E8FA3" stroke-width="1.1"/>`+dots(per,t[T.phs_yx_adj],x,y,"#2E8FA3")+`</svg></div>`;}
function tipPlot(t){const per=t[T.periods],tv=t[T.tip_mag];if(!per.length||!tv.some(v=>v!=null))return"";const H=80,x=xScale(per);
  const mx=Math.max(0.5,...tv.filter(v=>v!=null));const y=v=>4+(mx-v)/mx*(H-24);
  return `<div class="plot"><div class="ptitle">tipper magnitude |T|</div><svg width="${W}" height="${H}" role="img">`+frame(H,x,per,[[y(0),"0"],[y(mx),mx.toFixed(1)]])+
   `<path d="${path(per,tv,x,y)}" fill="none" stroke="#5BAE6A" stroke-width="1.1"/>`+dots(per,tv,x,y,"#5BAE6A")+`</svg></div>`;}
function betaCol(b){if(b==null)return"#5A6E7D";if(b<=-3)return"#3B82C4";if(b>=3)return"#C44B3B";return"#D8CFC0";}
function ptPlot(t){const per=t[T.periods];if(!per.length||!t[T.pt_min].some(v=>v!=null))return"";const H=84,x=xScale(per),cy=37,maxR=23;let ell="";
  per.forEach((p,i)=>{const mn=t[T.pt_min][i],mx=t[T.pt_max][i],az=t[T.pt_az][i],b=t[T.pt_beta][i];if(mn==null||mx==null)return;
    const r=mx>0?mn/mx:1;const ry=maxR,rx=Math.max(1.4,maxR*Math.min(1,Math.max(0,r)));   // FIXED scale (MTpy-style): every ellipse's major axis = maxR; only the shape (φmin/φmax) varies
    ell+=`<ellipse cx="${x(p).toFixed(1)}" cy="${cy}" rx="${rx.toFixed(1)}" ry="${ry.toFixed(1)}" transform="rotate(${(az||0).toFixed(1)} ${x(p).toFixed(1)} ${cy})" fill="${betaCol(b)}" fill-opacity=".85" stroke="#13202B" stroke-width=".5"/>`;});
  return `<div class="plot"><div class="ptitle">phase tensor (axis = azimuth, fill = skew β)</div><svg width="${W}" height="${H}" role="img">`+
   `<line x1="${PADL}" y1="${H-18}" x2="${W-PADR}" y2="${H-18}" stroke="#2E4254"/>`+
   decades(per).map(d=>`<text x="${x(d)}" y="${H-6}" fill="#8FA3B0" font-size="8.5" text-anchor="middle" font-family="monospace">${supTen(Math.round(Math.log10(d)))}</text>`).join("")+ell+
   `<rect x="${PADL}" y="2" width="8" height="8" fill="#3B82C4"/><text x="${PADL+11}" y="9" fill="#8FA3B0" font-size="8">β≤−3</text><rect x="${PADL+48}" y="2" width="8" height="8" fill="#D8CFC0"/><text x="${PADL+59}" y="9" fill="#8FA3B0" font-size="8">|β|&lt;3</text><rect x="${PADL+96}" y="2" width="8" height="8" fill="#C44B3B"/><text x="${PADL+107}" y="9" fill="#8FA3B0" font-size="8">β≥3</text></svg></div>`;}
