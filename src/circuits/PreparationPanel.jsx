export default function PreparationPanel({job,onPrepare,disabled=false}) {
  return <details className="circuit-dev-panel"><summary>Circuit preparation · {job?.state??'select a session'}</summary>
    <p>{job?.identity?.name??'Circuit unresolved'} · {job?.identity?.year??''} · {job?.identity?.layoutVersion??''}</p>
    <p>Stage: {job?.stage??'lookup'} · {job?.complete?'geometry, corners and sectors available':'annotations may be incomplete'} · generated assets remain provisional.</p>
    {job?.windowStart!=null&&<p>Sampling archive offset {job.windowStart}s (bounded 480s window).</p>}
    {job?.error&&<p role="alert">{job.error}</p>}
    {job?.warnings?.map((warning,i)=><p key={i}>{warning}</p>)}
    <button disabled={disabled||['preparing','geometry-ready'].includes(job?.state)||job?.complete} onClick={onPrepare}>Prepare / retry missing annotations</button>
    <p>Preparation does not change playback. First-time preparation can take several minutes. Cached assets load without running FastF1.</p>
  </details>;
}
