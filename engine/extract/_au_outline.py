#!/usr/bin/env python3
"""Schematic Australia outline for the survey-page location minimap.

SAME GEOMETRY as portal/vendor/au-outline.js (the collections footprint minimap), so the two
surfaces draw one map. Coastline hand-simplified (~1-2 degree fidelity) from PUBLIC-DOMAIN
Natural Earth data (naturalearthdata.com, CC0-equivalent terms); inter-state borders are the
legislated meridian/parallel segments, which are plain geographic facts. A SCHEMATIC BACKDROP
for locating a survey, never a survey-grade or legal boundary. Coordinates are (longitude,
latitude), WGS84; COAST is closed rings (mainland, Tasmania), BORDERS open polylines.
"""

COAST = (
    [(142.5, -10.7), (145.3, -14.9), (146.3, -18.6), (149.2, -21.1), (150.5, -22.5), (151.9, -24), (153.1, -25.9), (153.6, -28.2), (153.1, -30.3), (152.5, -32.7), (151.6, -33.9), (150.2, -37.5), (149.9, -37.8), (147, -38.8), (146.3, -39.1), (144.7, -38.4), (143.5, -38.8), (141.6, -38.4), (140, -37.8), (139, -35.8), (138.5, -35.6), (137.9, -35.3), (137.5, -34.1), (136.8, -35.2), (135.9, -34.8), (134, -33), (132, -32), (131, -31.5), (129, -31.7), (126, -32.3), (123.6, -33.9), (121.9, -33.9), (120, -33.9), (117.9, -35.1), (115, -34.3), (115.7, -32.6), (115.7, -31.9), (114.9, -30.3), (114.6, -28.8), (113.7, -26.1), (113.4, -24.9), (113.8, -22.6), (114.9, -21.9), (116.7, -20.6), (118.6, -20.3), (121.6, -19.7), (122.2, -18.1), (123.6, -17.3), (124.4, -16.4), (125.8, -14.5), (126.9, -14.3), (128, -15.3), (129, -14.8), (130.6, -12.4), (132, -12.2), (132.6, -11.5), (133.3, -11.7), (135, -12.2), (136.5, -12), (136.9, -12.4), (137, -15.7), (139.5, -17.5), (140.9, -17.7), (141.6, -15.6), (141.5, -13.5), (142.1, -11.3), (142.5, -10.7)],
    [(146, -41.2), (148.3, -40.8), (148.3, -42.1), (147.9, -43.6), (146, -43.5), (145.5, -42.2), (145.2, -41.4), (146, -41.2)],
)

BORDERS = (
    [(129, -14.8), (129, -31.9)],
    [(129, -26), (141, -26)],
    [(138, -26), (138, -17.7)],
    [(141, -29), (141, -38)],
    [(141, -29), (148.9, -29), (151, -28.9), (152.5, -28.2)],
    [(141, -34.1), (143.5, -35.3), (144.5, -35.9), (146, -36.1), (147, -36.1), (148.1, -36.8), (149.9, -37.8)],
)

# The fixed drawing extent the portal's collScatter uses: the outline and any dots projected
# through the same equirectangular fit stay registered automatically.
EXTENT = {"w": 112, "e": 154, "s": -44, "n": -9}
