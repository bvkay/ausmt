# Distortion and Decomposition (in development)

An observed MT response mixes regional conductivity structure with local structure near the
measurement site. **Distortion** is the name for what that local structure does to the observed
impedance tensor: it can change amplitude and directional character, which shifts apparent
resistivity, strike estimates, dimensionality indicators and tensor geometry. Distortion does
not mean the data are wrong. It means the response contains information from more than one
spatial scale.

Decomposition methods try to separate those scales, which helps with understanding site
responses, comparing neighbouring stations, assessing strike stability and testing
dimensionality assumptions. They provide context rather than definitive corrections.

> **Status: planned (in development).** Decomposition products are **not yet generated**. The
> `ausmt_science/decomposition` module is an optional, MTpy-v2-backed Tier-3 stub. Everything
> below is background and intended scope, not what ships. See
> [Science products](science-products.md) for the authoritative implemented-versus-planned
> list.

## Methods

**Groom-Bailey** (Groom & Bailey, 1989) remains the most widely used approach to galvanic
distortion. It assumes a two-dimensional regional structure and represents the observed
response with a set of distortion operators plus regional impedance parameters, yielding twist,
shear, anisotropy, site gain and regional strike. Read those parameters inside the method's
assumptions.

**Multi-site decomposition** extends that framework across stations simultaneously; McNeice and
Jones (2001) is the standard example. Using neighbouring stations together tends to give more
stable regional strike and distortion estimates than single-station fitting, which is why it is
common in regional studies.

**Newer approaches** based on phase tensor analysis, multi-site inversion, statistical
decomposition and tensor invariants address limitations of the earlier methods and suit more
complex settings. Each emphasises a different aspect of the response.

**Lilley invariants and Mohr circles** offer a view that does not depend on a preferred
coordinate system. Lilley (1993, 1998) introduced tensor invariant representations that
describe dimensionality, rotational behaviour and tensor geometry, and Mohr circles give a
graphical way to see departures from simple dimensionality assumptions. Both are useful
diagnostically and as teaching tools.

## Intended products

Once the module is wired in, and depending on the survey and the available processing products:
Groom-Bailey parameters, multi-site decomposition products, regional strike estimates, tensor
invariant products, Mohr circle products, and survey-level decomposition summaries. The set may
change as methods and community practice do.

## Interpretation

Decomposition products do not give a unique description of the Earth, and different methods
produce different estimates because they assume different things about dimensionality, regional
structure and distortion mechanisms. Most decomposition assumes a 1-D or 2-D regional
structure, so results become unstable where the Earth is strongly three-dimensional. Read them
against the [phase tensor](phase-tensor.md), [strike](strike-analysis.md) and
[dimensionality](dimensionality.md) diagnostics, and the geology; the value is usually in
whether independent diagnostics agree. The transfer functions remain authoritative.

## References

Booker, J. R. (2014). The magnetotelluric phase tensor: A critical review. Surveys in Geophysics, 35, 7–40.

Chave, A. D., & Jones, A. G. (2012). The Magnetotelluric Method: Theory and Practice. Cambridge University Press.

Groom, R. W., & Bailey, R. C. (1989). Decomposition of magnetotelluric impedance tensors in the presence of local three-dimensional galvanic distortion. Journal of Geophysical Research, 94(B2), 1913–1925.

Lilley, F. E. M. (1993). Magnetotelluric analysis using Mohr circles. Geophysics, 58(10), 1498–1507.

Lilley, F. E. M. (1998). Magnetotelluric tensor decomposition: Part I. Theory for a basic procedure. Geophysics, 63(6), 1885–1897.

McNeice, G. W., & Jones, A. G. (2001). Multisite, multifrequency tensor decomposition of magnetotelluric data. Geophysics, 66(1), 158–173.
