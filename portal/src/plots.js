"use strict";
// Pure SVG transfer-function plotters (no data/DOM dependency): ρ, φ, phase tensor, induction arrows.
// Each plotter takes a TF entry `t` (one per station, from tf.json). Columns are POSITIONAL — see
// the legend in data.js / docs developer/data-files.md (TF_COLUMNS):
//   t[T.periods] periods · t[T.rho_xy] ρ_xy · t[T.rho_yx] ρ_yx · t[T.phs_xy] φ_xy · t[T.phs_yx_adj] φ_yx(+180°) · t[T.tip_mag] |T| ·
//   t[T.pt_min] pt_min · t[T.pt_max] pt_max · t[T.pt_az] pt_az · t[T.pt_beta] pt_β ·
//   t[T.rho_xy_err]/t[T.rho_yx_err] ρ errors · t[T.phs_xy_err]/t[T.phs_yx_err] φ errors (°) ·
//   t[T.tzx_re]/t[T.tzx_im] Tx (Hz/Hx) · t[T.tzy_re]/t[T.tzy_im] Ty (Hz/Hy)
// Source-data frame: x = north, y = east (so Tx couples Hz to the north field, Ty to the east field).
// The SVG builders are viewBox-responsive. svgOpen emits the DESIGN size
// as width/height AND the same design coordinates as the viewBox, so ONE plotter serves both surfaces: the
// drawer renders it at 1:1 and the expand modal CSS-stretches the identical markup to fill its capped
// content column. No geometry is recomputed and every pinned <line/rect/path> signature is untouched. The
// former `_k` display-scale argument (a fixed 2x pixel blow-up in the modal, which grew with the monitor
// rather than with the layout) is gone: modal sizing is CSS now. Series markers are shape-differentiated
// (xy = circle, yx = square) so the copper/teal pair is not colour-only. The curve COLOURS are frozen.
const W=372,PADL=40,PADR=8;
const xScale=per=>{const lo=Math.log10(per[0]),hi=Math.log10(per[per.length-1]);return v=>PADL+(Math.log10(v)-lo)/(hi-lo||1)*(W-PADL-PADR);};
function decades(per){const o=[];const lo=Math.ceil(Math.log10(per[0])),hi=Math.floor(Math.log10(per[per.length-1]));for(let d=lo;d<=hi;d++)o.push(10**d);return o;}
function supTen(d){const m={"-":"⁻","0":"⁰","1":"¹","2":"²","3":"³","4":"⁴","5":"⁵","6":"⁶"};return "10"+String(d).split("").map(c=>m[c]||c).join("");}
// Open an <svg> whose viewBox carries the design coordinates and whose width/height carry that
// SAME design size (the viewBox is purely additive, so every pinned coordinate signature still matches).
// Consumers do the resizing in CSS: the drawer leaves it at 1:1, the expand modal stretches it to
// width:100% of a capped column, and the viewBox keeps the render crisp at whatever size it lands on.
function svgOpen(w,h){return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" role="img">`;}
function path(per,vals,x,y){let d="",pen=false;per.forEach((p,i)=>{const v=vals[i];if(v==null||!isFinite(y(v))){pen=false;return;}d+=(pen?"L":"M")+x(p).toFixed(1)+","+y(v).toFixed(1);pen=true;});return d;}
function dots(per,vals,x,y,c){return per.map((p,i)=>vals[i]==null||!isFinite(y(vals[i]))?"":`<circle cx="${x(p).toFixed(1)}" cy="${y(vals[i]).toFixed(1)}" r="2.1" fill="${c}"/>`).join("");}
// Square markers for the yx series (xy keeps circles) - a shape difference so the two curves
// stay distinguishable without relying on the copper/teal colour pair alone. Same 3.8px extent centred on
// the sample so it reads at the circle's visual weight.
function sqs(per,vals,x,y,c){return per.map((p,i)=>vals[i]==null||!isFinite(y(vals[i]))?"":`<rect x="${(x(p)-1.9).toFixed(1)}" y="${(y(vals[i])-1.9).toFixed(1)}" width="3.8" height="3.8" fill="${c}"/>`).join("");}
// Vertical error bars. For each period draw a whisker between y(lo(v,e)) and y(hi(v,e)),
// only where BOTH the value and its error are present. `lo`/`hi` let the caller clip the low end
// (rho lives in the log domain and cannot go <=0, so it clips at a small positive floor). No bar is
// emitted for absent errors, so a survey without errors renders exactly as before.
function ebars(per,vals,errs,x,y,c,lo,hi){if(!errs)return"";return per.map((p,i)=>{const v=vals[i],e=errs[i];
    if(v==null||e==null||!(e>0))return"";const y1=y(hi(v,e)),y0=y(lo(v,e));if(!isFinite(y0)||!isFinite(y1))return"";
    const xx=x(p).toFixed(1);return `<line x1="${xx}" y1="${y0.toFixed(1)}" x2="${xx}" y2="${y1.toFixed(1)}" stroke="${c}" stroke-width=".8" stroke-opacity=".55"/>`;}).join("");}
function frame(H,x,per,yl){let g=`<rect x="${PADL}" y="4" width="${W-PADL-PADR}" height="${H-22}" fill="none" stroke="#2B3557"/>`;
  decades(per).forEach(d=>{g+=`<line x1="${x(d)}" y1="4" x2="${x(d)}" y2="${H-18}" stroke="#2B3557" stroke-dasharray="2,3"/><text x="${x(d)}" y="${H-6}" fill="#8FA3B0" font-size="11" text-anchor="middle" font-family="monospace">${supTen(Math.round(Math.log10(d)))}</text>`;});
  yl.forEach(([yy,t])=>g+=`<text x="${PADL-4}" y="${yy+3}" fill="#8FA3B0" font-size="11" text-anchor="end" font-family="monospace">${t}</text>`);return g;}
function rhoSvg(t){const per=t[T.periods];if(!per.length)return"";const vals=[...t[T.rho_xy],...t[T.rho_yx]].filter(v=>v!=null&&v>0);if(!vals.length)return"";
  const H=118,x=xScale(per);let lo=Math.floor(Math.log10(Math.min(...vals))),hi=Math.ceil(Math.log10(Math.max(...vals)));if(hi<=lo)hi=lo+1;
  const y=v=>4+(hi-Math.log10(v))/(hi-lo)*(H-26);const yl=[];for(let d=lo;d<=hi;d++)yl.push([y(10**d),supTen(d)]);
  // Rho error bars in the LOG domain - the low end is clipped at the axis floor (10**lo) so a
  // large error can never drive the endpoint to <=0 (which log() cannot map). Bars only where present.
  const rfloor=10**lo,rlo=(v,e)=>Math.max(v-e,rfloor),rhi=(v,e)=>v+e;
  return svgOpen(W,H)+frame(H,x,per,yl)+
   ebars(per,t[T.rho_xy],t[T.rho_xy_err],x,y,"#EF7256",rlo,rhi)+ebars(per,t[T.rho_yx],t[T.rho_yx_err],x,y,"#2E8FA3",rlo,rhi)+
   `<path d="${path(per,t[T.rho_xy],x,y)}" fill="none" stroke="#EF7256" stroke-width="1.1"/>`+dots(per,t[T.rho_xy],x,y,"#EF7256")+
   `<path d="${path(per,t[T.rho_yx],x,y)}" fill="none" stroke="#2E8FA3" stroke-width="1.1"/>`+sqs(per,t[T.rho_yx],x,y,"#2E8FA3")+
   `<text x="${W-10}" y="14" fill="#EF7256" font-size="11" text-anchor="end" font-family="monospace">○ xy</text><text x="${W-10}" y="25" fill="#2E8FA3" font-size="11" text-anchor="end" font-family="monospace">□ yx</text></svg>`;}
function phaseSvg(t){const per=t[T.periods];if(!per.length)return"";if(!t[T.phs_xy].some(v=>v!=null)&&!t[T.phs_yx_adj].some(v=>v!=null))return"";
  const H=92,x=xScale(per);const y=v=>4+(105-v)/120*(H-22);
  // Phase error bars in DEGREES (symmetric ± the propagated error). The yx error rides its
  // +180°-adjusted value (the error is orientation-independent). Bars only where the error is present.
  const plo=(v,e)=>v-e,phi=(v,e)=>v+e;
  return svgOpen(W,H)+frame(H,x,per,[[y(0),"0"],[y(45),"45"],[y(90),"90"]])+
   `<line x1="${PADL}" y1="${y(45)}" x2="${W-PADR}" y2="${y(45)}" stroke="#2B3557" stroke-dasharray="2,3"/>`+
   ebars(per,t[T.phs_xy],t[T.phs_xy_err],x,y,"#EF7256",plo,phi)+ebars(per,t[T.phs_yx_adj],t[T.phs_yx_err],x,y,"#2E8FA3",plo,phi)+
   `<path d="${path(per,t[T.phs_xy],x,y)}" fill="none" stroke="#EF7256" stroke-width="1.1"/>`+dots(per,t[T.phs_xy],x,y,"#EF7256")+
   `<path d="${path(per,t[T.phs_yx_adj],x,y)}" fill="none" stroke="#2E8FA3" stroke-width="1.1"/>`+sqs(per,t[T.phs_yx_adj],x,y,"#2E8FA3")+`</svg>`;}
// Induction-arrow panel - REPLACES the |T|-magnitude plot, rendered below the phase tensor.
// One vector arrow pair per thinned period, from a baseline on the log-period axis:
//   REAL (Parkinson convention): (east, north) = (-tzy_re, -tzx_re), solid copper — real arrows point
//     TOWARD conductors.
//   IMAGINARY (unreversed):      (east, north) = ( tzy_im,  tzx_im), lighter.
// Screen mapping is the standard map view: east -> +x (right), north -> +y (UP, i.e. screen -y). A
// |T| = 0.5 reference arrow is drawn in the corner at the SAME scale. Absent/masked tippers (all four
// components null) render the "no tipper" state — the panel simply does not appear (as the old |T|
// plot did when tip_mag was absent). The x=north / y=east source frame is documented in data-files.md.
const ARROW_UNIT_PX=54;        // pixels per unit |T| (so a |T|=0.5 arrow is 27 px) — the fixed scale
function arrowHead(x0,y0,x1,y1,c){const dx=x1-x0,dy=y1-y0,L=Math.hypot(dx,dy);if(L<0.5)return"";
  const ux=dx/L,uy=dy/L,hl=4.2,hw=2.4;const bx=x1-ux*hl,by=y1-uy*hl,px=-uy,py=ux;
  return `<polygon points="${x1.toFixed(1)},${y1.toFixed(1)} ${(bx+px*hw).toFixed(1)},${(by+py*hw).toFixed(1)} ${(bx-px*hw).toFixed(1)},${(by-py*hw).toFixed(1)}" fill="${c}"/>`;}
function arrow(x0,y0,east,north,scale,c,w){const x1=x0+east*scale,y1=y0-north*scale;   // north -> screen up (-y)
  return `<line x1="${x0.toFixed(1)}" y1="${y0.toFixed(1)}" x2="${x1.toFixed(1)}" y2="${y1.toFixed(1)}" stroke="${c}" stroke-width="${w}"/>`+arrowHead(x0,y0,x1,y1,c);}
function arrowSvg(t){const per=t[T.periods];if(!per.length)return"";
  const zxr=t[T.tzx_re],zxi=t[T.tzx_im],zyr=t[T.tzy_re],zyi=t[T.tzy_im];
  if(!zxr||!zxr.some((v,i)=>v!=null&&zyr[i]!=null))return"";   // no tipper present -> no-tipper state (panel absent)
  const REAL="#EF7256",IMAG="#E7B98C";   // solid copper (primary) + a lighter copper for the imaginary
  // Baseline CENTERED (not at the bottom) so arrows can point north (up) OR south (down) with room;
  // the period-decade labels sit at the very bottom, clear of the vectors.
  const H=112,x=xScale(per),base=56,scale=ARROW_UNIT_PX;let g="";
  per.forEach((p,i)=>{const xr=zxr[i],xi=zxi[i],yr=zyr[i],yi=zyi[i];const x0=x(p);
    if(xr!=null&&yr!=null){g+=arrow(x0,base,-yr,-xr,scale,REAL,"1.2");}          // REAL: Parkinson (east,north)=(-tzy_re,-tzx_re)
    if(xi!=null&&yi!=null){g+=arrow(x0,base, yi, xi,scale,IMAG,"1.0");}          // IMAG: unreversed (east,north)=(tzy_im,tzx_im)
  });
  // |T| = 0.5 unit-scale reference arrow (points north/up) in the top-left corner, at the SAME scale.
  const refx=PADL+6,ref=0.5,refTail=18;
  const legend=arrow(refx,refTail+ref*scale,0,ref,scale,"#8FA3B0","1.1")+
    `<text x="${(refx+5).toFixed(1)}" y="${(refTail-2).toFixed(1)}" fill="#8FA3B0" font-size="10" font-family="monospace">|T|=0.5</text>`;
  return svgOpen(W,H)+
   `<line x1="${PADL}" y1="${base}" x2="${W-PADR}" y2="${base}" stroke="#2B3557"/>`+
   decades(per).map(d=>`<text x="${x(d)}" y="${H-4}" fill="#8FA3B0" font-size="11" text-anchor="middle" font-family="monospace">${supTen(Math.round(Math.log10(d)))}</text>`).join("")+
   legend+g+
   `<rect x="${W-70}" y="2" width="8" height="8" fill="${REAL}"/><text x="${W-58}" y="9" fill="#8FA3B0" font-size="10">real</text>`+
   `<rect x="${W-38}" y="2" width="8" height="8" fill="${IMAG}"/><text x="${W-26}" y="9" fill="#8FA3B0" font-size="10">imag</text>`+
   `</svg>`;}
function betaCol(b){if(b==null)return"#5A6E7D";if(b<=-3)return"#3B82C4";if(b>=3)return"#C44B3B";return"#D8CFC0";}
function ptSvg(t){const per=t[T.periods];if(!per.length||!t[T.pt_min].some(v=>v!=null))return"";const H=84,x=xScale(per),cy=37,maxR=23;let ell="";
  per.forEach((p,i)=>{const mn=t[T.pt_min][i],mx=t[T.pt_max][i],az=t[T.pt_az][i],b=t[T.pt_beta][i];if(mn==null||mx==null)return;
    const r=mx>0?mn/mx:1;const ry=maxR,rx=Math.max(1.4,maxR*Math.min(1,Math.max(0,r)));   // FIXED scale (MTpy-style): every ellipse's major axis = maxR; only the shape (φmin/φmax) varies
    ell+=`<ellipse cx="${x(p).toFixed(1)}" cy="${cy}" rx="${rx.toFixed(1)}" ry="${ry.toFixed(1)}" transform="rotate(${(az||0).toFixed(1)} ${x(p).toFixed(1)} ${cy})" fill="${betaCol(b)}" fill-opacity=".85" stroke="#11182D" stroke-width=".5"/>`;});
  return svgOpen(W,H)+
   `<line x1="${PADL}" y1="${H-18}" x2="${W-PADR}" y2="${H-18}" stroke="#2B3557"/>`+
   decades(per).map(d=>`<text x="${x(d)}" y="${H-6}" fill="#8FA3B0" font-size="11" text-anchor="middle" font-family="monospace">${supTen(Math.round(Math.log10(d)))}</text>`).join("")+ell+
   `<rect x="${PADL}" y="2" width="8" height="8" fill="#3B82C4"/><text x="${PADL+11}" y="9" fill="#8FA3B0" font-size="10">β≤−3</text><rect x="${PADL+48}" y="2" width="8" height="8" fill="#D8CFC0"/><text x="${PADL+59}" y="9" fill="#8FA3B0" font-size="10">|β|&lt;3</text><rect x="${PADL+96}" y="2" width="8" height="8" fill="#C44B3B"/><text x="${PADL+107}" y="9" fill="#8FA3B0" font-size="10">β≥3</text></svg>`;}

// Plot kind registry. Each kind has a heading, an always-visible subline (the convention /
// axis-key text that must survive VISIBLY, not hover-only — C4 for the arrows), and an svg builder that
// takes only the TF row. plotBlock renders the always-shown in-drawer form (all four panels); plotCollapsible
// renders the collapsed-by-default <details> form (phase tensor + induction arrows) with the heading +
// subline living in the ALWAYS-VISIBLE <summary> so the convention never hides behind a closed panel.
const PLOT_META={
  rho:  {title:"apparent resistivity ρ (Ω·m)", sub:"", svg:rhoSvg},
  phase:{title:"phase φ (°, yx +180°)",        sub:"", svg:phaseSvg},
  pt:   {title:"phase tensor",                 sub:"axis = azimuth, fill = skew β", svg:ptSvg},
  // Short heading + always-visible convention subline.
  arrow:{title:"Induction arrows (Parkinson)", sub:"Real arrows point toward conductors; imaginary unreversed.", svg:arrowSvg},
};
// ONE expand control for the WHOLE response section. Every plot block used to
// carry its own ⤢ button and all four opened the SAME full-station modal, so the drawer showed four controls
// for one action. The per-plot buttons are gone; the drawer puts this single control on the "Response
// functions" section heading row instead (same affordance style, section-level label). It is a real
// <button>, so it is tab-reachable and Enter/Space activate it, and the delegated [data-act="expand"]
// handler in drawer.js is unchanged.
function responseExpandBtn(){return `<button class="plotexp rspexp" type="button" data-act="expand" aria-label="Expand full response" title="Expand full response">⤢</button>`;}
const _paxis=`<div class="paxis">period (s) · log scale</div>`;   // x-axis unit, shared by all four plots
// Always-shown block (all four panels): title row → optional subline → svg → axis unit. No expand control
// lives inside a plot block any more (the section heading owns the only one).
function plotBlock(kind,t){const m=PLOT_META[kind];if(!m)return"";const svg=m.svg(t);if(!svg)return"";
  return `<div class="plot" data-plot="${kind}"><div class="ptitle">${m.title}</div>`+
    (m.sub?`<div class="psubline">${m.sub}</div>`:"")+svg+_paxis+`</div>`;}
// Collapsed <details> block: the heading + subline sit in the summary (always visible); the svg + axis unit
// are the collapsible body. Empty svg -> "". Retained as the reversible collapsed form; unused since the
// pt and arrows are always shown.
function plotCollapsible(kind,t,open){const m=PLOT_META[kind];if(!m)return"";const svg=m.svg(t);if(!svg)return"";
  return `<details class="plot plotcollapse" data-plot="${kind}"${open?" open":""}>`+
    `<summary><span class="ptitle">${m.title}</span>${m.sub?`<span class="psubline">${m.sub}</span>`:""}</summary>`+
    `<div class="plotbody">${svg}${_paxis}</div></details>`;}

// The expand affordance opens ONE full-station RESPONSE modal, not a single-plot
// popup. It carries a station-identity header (built by the drawer, which owns the honest coordCellHtml /
// orgNameLink) plus ALL response panels: apparent resistivity, phase, phase tensor, and the induction
// arrows ONLY when the station carries tipper (arrowSvg returns "" otherwise, so that panel is simply
// absent, exactly as in the drawer). The overlay is appended to <body>, scrolls, and
// closes on Esc, click-out, or the close button, with focus returned to the opener. The drawer's own Esc
// handler yields while the modal is open (it checks for #plotmodal) so Esc closes the modal, not the
// drawer. All data is already client-side (the stashed TF row); no fetches.
//
// SIZING. A fixed STATION_MODAL_SCALE pixel blow-up sizes the modal to the MONITOR rather than to the
// layout, so there is no such constant.
// The panels are emitted at design size and stretched by CSS to FILL a CAPPED content column
// (.plotmodal-capw in index.html: max-width min(92vw,760px), centred, with the overlay's viewport margin;
// .plotmodal-svg svg{width:100%;min-width:372px}). So the modal is comfortably larger than the drawer
// plots (~1.95x at the cap) but never wall-sized, the svg never renders NARROWER than the drawer's 372px
// design width (axis/label text can never end up smaller than in the drawer), and the height keeps the
// box's existing internal scroll.
const MODAL_PANELS=["rho","phase","pt","arrow"];   // stacked in this order (arrow absent for a non-tipper station)
// One modal panel: title + optional convention subline + svg + axis unit. An empty svg
// (arrowSvg for a non-tipper station, or any uncollected panel) yields "" so the panel is ABSENT, no empty
// box, mirroring plotBlock's guard. No expand button here (the modal IS the expansion).
function modalPanel(kind,t){const m=PLOT_META[kind];if(!m)return"";const svg=m.svg(t);if(!svg)return"";
  return `<div class="plot" data-plot="${kind}"><div class="ptitle">${m.title}</div>`+
    (m.sub?`<div class="psubline">${m.sub}</div>`:"")+svg+_paxis+`</div>`;}
let _plotModalReturnFocus=null;
function closePlotModal(){const ov=document.getElementById("plotmodal");if(ov)ov.remove();
  document.removeEventListener("keydown",_plotModalKey);
  const f=_plotModalReturnFocus;_plotModalReturnFocus=null;if(f&&typeof f.focus==="function"){try{f.focus();}catch(e){}}}
function _plotModalKey(e){if(e.key==="Escape")closePlotModal();}
// headerHtml is the station-identity block the drawer builds (stationModalHeader); t is the stashed TF row.
function openStationModal(headerHtml,t){
  const panels=MODAL_PANELS.map(k=>modalPanel(k,t)).join("");
  if(!panels)return;                               // nothing plottable (withheld curves); open no empty modal
  closePlotModal();
  _plotModalReturnFocus=(typeof document!=="undefined")?document.activeElement:null;
  const ov=document.createElement("div");ov.id="plotmodal";ov.className="plotmodal";
  ov.setAttribute("role","dialog");ov.setAttribute("aria-modal","true");ov.setAttribute("aria-label","Station response functions");
  // .plotmodal-capw is the CAP marker: it carries the max-width rule, so the class being present on the
  // content column IS the capped-width contract the driver pins.
  ov.innerHTML=`<div class="plotmodal-box plotmodal-capw"><div class="plotmodal-head"><div class="plotmodal-ident">${headerHtml||""}</div>`+
    `<button class="plotmodal-close" type="button" aria-label="Close">✕</button></div>`+
    `<div class="plotmodal-svg">${panels}</div></div>`;
  ov.addEventListener("click",e=>{if(e.target===ov||(e.target.closest&&e.target.closest(".plotmodal-close")))closePlotModal();});
  document.body.appendChild(ov);
  document.addEventListener("keydown",_plotModalKey);
  const btn=ov.querySelector(".plotmodal-close");if(btn&&typeof btn.focus==="function"){try{btn.focus();}catch(e){}}}
