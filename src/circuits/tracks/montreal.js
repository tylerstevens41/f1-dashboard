
const montreal = {
  name: "Circuit Gilles-Villeneuve",

  rotation: "auto",

  // Temporary sector boundaries.
  // We will calibrate these to official positions later.
  sectorBoundaries: [0.2504, 0.5705],

  sectorColors: [
    "#35B8F2",
    "#F5C542",
    "#F06478",
  ],

  // Position is a fraction of the SVG circuit path.
  // 0 = beginning of Sector 1 / end of Sector 3.
  startFinish: {
    show: true,
    position: 0,
    label: "START / FINISH",
    chequerSize: 90,
  },
};

export default montreal;
