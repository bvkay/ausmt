// geoFeatureCollection: the GeoJSON export's honesty pins. remote_ref is a POSITIVE claim, so a
// station with no usable sci row must omit the key (like quality/dimensionality already do), never
// emit a hard false. quality separates its two absences the other way round: a screened station
// whose score is WITHHELD carries an explicit null, and only a missing row leaves the key out, which
// is what the file's own GEO_SCI_UNAVAILABLE note reserves for a screening product that never
// loaded. Also pins the RFC 7946 basics: [lon, lat] order and null geometry for a withheld
// position. Loads the whole of exports.js in a vm with a permissive document stub (the panel
// elements are absent here; bindings must tolerate that).
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const SRC = fs.readFileSync(path.join(__dirname, "..", "src", "exports.js"), "utf8");

const el = () => ({ set onclick(v) {}, disabled: false, textContent: "", title: "", style: {}, classList: { add() {}, remove() {}, toggle() {} } });
const SCI = [
  [4.2, "e", 1, "BIRRP", "robust", "2-D"],   // full row: rr at index 2
  [],                                          // empty row: no claims
  [null, "s", 0, "BIRRP", "robust", null],   // screened tipper-only station: q withheld, no impedance to screen
];
const ctx = {
  document: { getElementById: () => el(), createElement: () => el() },
  console, JSON, Object, Array, String, Number, Math, Date, Promise, Set,
  SC: { q: 0, qb: 1, rr: 2, sw: 3, alg: 4, dim: 5 },
  sciRow: i => SCI[i] || [],
  hasPosition: s => s.lat != null && s.lon != null,
  SMETA: {}, LICENSES: {}, PROFILES: {}, TS_COLLECTION: { doi: "10.0/x", name: "x" },
  TS_LEVELS: [], track() {}, ST: [], selected: new Set(),
};
vm.createContext(ctx);
vm.runInContext(SRC, ctx);

const stations = [
  { i: 0, id: "A", ausmt_id: "au.s.A", country: "AU", org: "O", survey: "S", type: "BBMT",
    comps: "ZT", pmin: 0.01, pmax: 100, lat: -26.4531, lon: 132.0089, file: "A.edi" },
  { i: 1, id: "B", ausmt_id: "au.s.B", country: "AU", org: "O", survey: "S", type: "BBMT",
    comps: "ZT", pmin: 0.01, pmax: 100, lat: null, lon: null, file: "B.edi" },
  { i: 2, id: "C", ausmt_id: "au.s.C", country: "AU", org: "O", survey: "S", type: "GDS",
    comps: "T", pmin: 10, pmax: 10000, lat: -23.1, lon: 138.7, file: "C.edi" },
];
const fc = ctx.geoFeatureCollection(stations, true);
const fails = [];
const ok = (cond, msg) => { if (!cond) fails.push(msg); };

const [a, b, c] = fc.features;
ok(fc.type === "FeatureCollection" && fc.features.length === 3, "FeatureCollection shape");
ok(a.geometry && a.geometry.coordinates[0] === 132.0089 && a.geometry.coordinates[1] === -26.4531,
   "coordinates must be [longitude, latitude]");
ok(b.geometry === null, "a withheld position must be a null-geometry feature");
ok(a.properties.remote_ref === true, "a station with a full sci row keeps its remote_ref claim");
// The FILE is the contract: assert on the serialised form (JSON.stringify drops undefined keys).
const bs = JSON.parse(JSON.stringify(b.properties));
ok(!("remote_ref" in bs),
   "a station with no usable sci row must OMIT remote_ref from the file (a hard false is a claim from no data), got " +
   JSON.stringify(bs.remote_ref));
ok(!("quality" in bs), "quality stays absent on the empty row");
// A WITHHELD score is not a missing one. C is screened and carries a row; its q is null because it
// has no impedance to screen, and the file must say so in place rather than drop the key, which
// would put it in the same shape as the load failure the note describes. A carries a real score in
// the same collection, so the null is the withheld case and not the export losing every number.
const as = JSON.parse(JSON.stringify(a.properties));
const cs = JSON.parse(JSON.stringify(c.properties));
ok("quality" in cs && cs.quality === null,
   "a present sci row with a withheld score must keep quality as an explicit null in the file, got " +
   ("quality" in cs ? JSON.stringify(cs.quality) : "no key at all"));
ok(as.quality === 4.2, "a scored station in the same collection still carries its number, got " +
   JSON.stringify(as.quality));

if (fails.length) { fails.forEach(f => console.error("FAIL: " + f)); process.exit(1); }
console.log("GEOJSON-EXPORT PASSED");
