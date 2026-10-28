// Annotation positions are fractions of the canonical centreline, in travel order.
// Do not populate official features until their positions have been calibrated.
const austin = {
  id: "austin", layoutVersion: "austin-livef1-v1", calibrationFile: "/circuits/austin-calibration.json", calibrationStatus: "missing", name: "Circuit of the Americas", geometryVersion: 1,
  cornerFile: "/circuits/austin-corners.json",
  annotationFile: "/circuits/austin-annotations.json",
  decorativeSvg: "/circuits/austin.svg", // Not GPS-calibrated; intentionally unused.
  sources: {
    livef1: { sessionName: "Austin", referenceFile: "/circuits/austin-gps-reference.json", matrix: [1, 0, 0, 1, 0, 0] },
    // OpenF1 uses the reference embedded in that replay, NOT the LiveF1 reference.
    openf1: { reference: "replay", matrix: [1, 0, 0, 1, 0, 0] },
  },
  motion: { minBufferMs: 100, maxBufferMs: 5000, maxGapMs: 1500, staleMs: 2500, maxUnitsPerMs: 2 },
  // Native units/ms is a conservative configurable spike guard, not a speed in metres/s.
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
