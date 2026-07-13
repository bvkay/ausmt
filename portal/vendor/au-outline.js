// au-outline.js — simplified Australia coastline + state/territory boundaries for the AusMT
// collection footprint mini-map (drawer.js collScatter, UX6 Wave E / E6). Loaded as a classic
// <script> that assigns one global, so collScatter can draw it synchronously with NO fetch (the
// portal's CSP is script-src 'self' — a remote GeoJSON fetch would be blocked; a same-origin asset
// is fine, and a JS global avoids the async fetch dance entirely).
//
// SOURCE / LICENCE ---------------------------------------------------------------------------------
//   Coastline geometry: hand-simplified to a schematic (~1-2° fidelity) from PUBLIC-DOMAIN data —
//   Natural Earth (https://www.naturalearthdata.com), whose vector data is released into the PUBLIC
//   DOMAIN with no restrictions or attribution requirement (CC0-equivalent; see
//   https://www.naturalearthdata.com/about/terms-of-use/).
//   Inter-state boundaries: the legislated straight segments follow meridians/parallels that are
//   plain geographic facts (129°E WA border; 26°S SA northern border; 138°E NT/QLD; 141°E SA east;
//   29°S QLD/NSW; the River Murray for NSW/VIC, approximated). No rights are claimed over this file —
//   reuse freely. It is a SCHEMATIC BACKDROP for context, NOT a survey-grade or legal boundary.
//
// FORMAT: coordinates are [longitude, latitude] in WGS84. `coast` is an array of closed rings
// (mainland, Tasmania); `borders` is an array of open polylines. collScatter projects both through
// the SAME fixed-Australia transform it uses for the station dots, so the outline stays registered
// to the dots automatically.
window.AU_OUTLINE = {
  coast: [
    // Mainland — clockwise from the tip of Cape York, down the east coast, along the south, up the
    // west coast, then across the Top End and around the Gulf of Carpentaria back to Cape York.
    [
      [142.5, -10.7], [145.3, -14.9], [146.3, -18.6], [149.2, -21.1], [150.5, -22.5],
      [151.9, -24.0], [153.1, -25.9], [153.6, -28.2], [153.1, -30.3], [152.5, -32.7],
      [151.6, -33.9], [150.2, -37.5], [149.9, -37.8], [147.0, -38.8], [146.3, -39.1],
      [144.7, -38.4], [143.5, -38.8], [141.6, -38.4], [140.0, -37.8], [139.0, -35.8],
      [138.5, -35.6], [137.9, -35.3], [137.5, -34.1], [136.8, -35.2], [135.9, -34.8],
      [134.0, -33.0], [132.0, -32.0], [131.0, -31.5], [129.0, -31.7], [126.0, -32.3],
      [123.6, -33.9], [121.9, -33.9], [120.0, -33.9], [117.9, -35.1], [115.0, -34.3],
      [115.7, -32.6], [115.7, -31.9], [114.9, -30.3], [114.6, -28.8], [113.7, -26.1],
      [113.4, -24.9], [113.8, -22.6], [114.9, -21.9], [116.7, -20.6], [118.6, -20.3],
      [121.6, -19.7], [122.2, -18.1], [123.6, -17.3], [124.4, -16.4], [125.8, -14.5],
      [126.9, -14.3], [128.0, -15.3], [129.0, -14.8], [130.6, -12.4], [132.0, -12.2],
      [132.6, -11.5], [133.3, -11.7], [135.0, -12.2], [136.5, -12.0], [136.9, -12.4],
      [137.0, -15.7], [139.5, -17.5], [140.9, -17.7], [141.6, -15.6], [141.5, -13.5],
      [142.1, -11.3], [142.5, -10.7]
    ],
    // Tasmania.
    [
      [146.0, -41.2], [148.3, -40.8], [148.3, -42.1], [147.9, -43.6], [146.0, -43.5],
      [145.5, -42.2], [145.2, -41.4], [146.0, -41.2]
    ]
  ],
  borders: [
    [[129.0, -14.8], [129.0, -31.9]],                     // WA border (129°E meridian)
    [[129.0, -26.0], [141.0, -26.0]],                     // SA northern border (26°S parallel)
    [[138.0, -26.0], [138.0, -17.7]],                     // NT / QLD (138°E meridian)
    [[141.0, -29.0], [141.0, -38.0]],                     // SA eastern border (141°E meridian)
    [[141.0, -29.0], [148.9, -29.0], [151.0, -28.9], [152.5, -28.2]],   // QLD / NSW (29°S + rivers)
    [[141.0, -34.1], [143.5, -35.3], [144.5, -35.9], [146.0, -36.1],
     [147.0, -36.1], [148.1, -36.8], [149.9, -37.8]]      // NSW / VIC (River Murray, approximated)
  ]
};
