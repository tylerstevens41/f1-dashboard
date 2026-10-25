// Annotation positions are fractions of the canonical centreline, in travel order.
// Do not populate official features until their positions have been calibrated.
const austin = {
  id: "austin", name: "Circuit of the Americas", geometryVersion: 1,
  decorativeSvg: "/circuits/austin.svg", // Not GPS-calibrated; intentionally unused.
  sources: {
    livef1: { sessionName: "Austin", referenceFile: "/circuits/austin-gps-reference.json", matrix: [1, 0, 0, 1, 0, 0] },
    // OpenF1 uses the reference embedded in that replay, NOT the LiveF1 reference.
    openf1: { reference: "replay", matrix: [1, 0, 0, 1, 0, 0] },
  },
  annotations: {
    corners: [], // { number, at, offset: { x, y } }
    detectionPoints: [], // { id, at, label }
    zones: [], // { id, start, end, label }; end < start wraps across finish.
    sectors: [], // { at, label }
    startFinish: null, // { at, label }
  },
  flagColors: { GREEN: "#e7eaf0", YELLOW: "#ffd43b", DOUBLE_YELLOW: "#ffd43b", RED: "#e10600", SC: "#ffd43b", VSC: "#ffd43b", CHEQUERED: "#ffffff" },
};
export default austin;
