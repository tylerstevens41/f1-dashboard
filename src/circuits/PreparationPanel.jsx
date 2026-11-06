export default function PreparationPanel({job,onPrepare,disabled=false}) {
  return <details className="circuit-dev-panel"><summary>Circuit preparation · {job?.state??'select a session'}</summary>
    <p>{job?.identity?.name??'Circuit unresolved'} · {job?.identity?.year??''} · {job?.identity?.layoutVersion??''}</p>
    <p>Stage: {job?.stage??'lookup'} · {job?.complete?'geometry, corners and sectors available':'annotations may be incomplete'} · generated assets remain provisional.</p>
    {job?.windowStart!=null&&<p>Sampling archive offset {job.windowStart}s (bounded 480s window).</p>}
    {job?.error&&<p role="alert">{job.error}</p>}
    {job?.annotationDiagnostics && <details open><summary>FastF1 annotation diagnostics · {job.annotationDiagnostics.phase} · {job.annotationDiagnostics.state}</summary>
      <p>Elapsed {job.annotationDiagnostics.elapsedSeconds??0}s · current phase {job.annotationDiagnostics.phaseElapsedSeconds??0}s · started {job.annotationDiagnostics.startedAt?new Date(job.annotationDiagnostics.startedAt*1000).toISOString():'unknown'}</p>
      <p>Corner metadata {job.annotationDiagnostics.metadataCorners??'pending'} · aligned corners {job.annotationDiagnostics.corners??'pending'} · multi-lap accepted {job.annotationDiagnostics.accepted??'pending'}</p>
      {job.annotationDiagnostics.failedPhase&&<p>Failed phase: {job.annotationDiagnostics.failedPhase}</p>}
      {job.annotationDiagnostics.error&&<p role="alert">{job.annotationDiagnostics.error.exceptionType} · {job.annotationDiagnostics.error.code??''} · {job.annotationDiagnostics.error.hint}</p>}
      <pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{JSON.stringify(job.annotationDiagnostics,null,2)}</pre>
    </details>}
    {job?.windowDiagnostics?.map(window=><details key={window.offset}>
      <summary>Window {window.offset}s · {window.status} · {window.stage}{window.reason?` · ${window.reason}`:''}</summary>
      <p>Archive: {window.archiveRetrieved===null?'not reached':window.archiveRetrieved?'retrieved':'failed'}{window.sampleCacheHit?' (sample cache)':''} · events {window.eventCount??'unknown'} · Position.z messages {window.positionMessages??'unknown'} · decoded positions {window.decodedPositionRecords??'unknown'} · drivers {window.driversRepresented??'unknown'}</p>
      <p>Candidate laps {window.candidateLaps??'unknown'} · complete accepted {window.acceptedCompleteLaps??'unknown'} · calibration {window.calibrationAttempted?'attempted':'not attempted'}</p>
      {window.error&&<p role="alert">{window.error.exceptionType} at {window.error.stage} · {window.error.code??''} · {window.error.detail??window.error.hint} {window.error.location?`${window.error.location.file}:${window.error.location.line} (${window.error.location.function})`:''}</p>}
      <pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{JSON.stringify(window,null,2)}</pre>
    </details>)}
    {job?.warnings?.map((warning,i)=><p key={i}>{warning}</p>)}
    <button disabled={disabled||['preparing','geometry-ready'].includes(job?.state)||job?.complete} onClick={onPrepare}>Prepare / retry missing annotations</button>
    <p>Preparation does not change playback. First-time preparation can take several minutes. Cached assets load without running FastF1.</p>
  </details>;
}
