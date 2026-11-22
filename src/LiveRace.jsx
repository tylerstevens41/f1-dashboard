import LiveSession from "./LiveSession";

// Production and developer views share the same telemetry feed and race renderer.
export default function LiveRace({feed, wall=false, developer=false}) {
  return <LiveSession feed={feed} wall={wall} developer={developer && !wall}/>;
}
