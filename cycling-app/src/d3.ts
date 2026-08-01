// Modular d3 imports — pulls only the submodules we use instead of the full
// d3 meta-package (which bundles geo, force, hierarchy, zoom, etc. unused
// here). Re-exported as a `d3` namespace object so call sites keep the
// familiar `d3.select(...)`, `d3.scaleLinear()` etc. syntax.
import { select, selectAll } from "d3-selection";
import { scaleLinear, scaleBand, scaleOrdinal } from "d3-scale";
import { axisLeft, axisBottom, axisTop } from "d3-axis";
import { line, curveMonotoneX } from "d3-shape";
import { max, min, range } from "d3-array";

export const d3 = {
  select, selectAll,
  scaleLinear, scaleBand, scaleOrdinal,
  axisLeft, axisBottom, axisTop,
  line, curveMonotoneX,
  max, min, range,
};

export type { Selection } from "d3-selection";
export type { ScaleLinear, ScaleOrdinal, NumberValue } from "d3-scale";
