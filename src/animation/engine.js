// One timestamped sample store + monotonic presentation clock for every car.
// Native coordinates only: calibration projection happens at the final DOM write.
const percentile = (values, fraction) => {
  if (!values.length) return 0;
  const sorted = [...values].sort((a,b)=>a-b);
  return sorted[Math.ceil((sorted.length-1)*fraction)];
};
const clamp = (v,lo,hi) => Math.max(lo,Math.min(hi,v));

export class AnimationEngine {
  constructor(options = {}) {
    this.options = { maxGapMs:1500, staleMs:2500, maxUnitsPerMs:2, minBufferMs:100, maxBufferMs:5000, ...options };
    this.listeners = new Map();
    this.manualBufferMs = null;
    this.tracing = false;
    this.reset();
  }
  reset(generation = null) {
    this.generation = generation;
    this.sequence = -1;
    this.drivers = new Map();
    this.clock = null;
    this.cursor = null;
    this.frameAt = null;
    this.running = false;
    this.speed = 1;
    this.mode = 'LIVE';
    this.jitter = [];
    this.arrival = null;
    this.deliveryIntervals = [];
    this.underruns = 0;
    this.lastFrame = new Map();
    this.targetDelay = 0;
    this.phaseError = 0;
    this.syncErrors = [];
    this.lastCorrectionAt = null;
    this.correction = 0;
    this.presentationRate = 0;
    this.rebuffers = 0;
    this.lastRebufferAt = -Infinity;
    this.pendingRebuffer = false;
    this.trace = [];
    this.traceDriver = null;
    this.previousMeasurement = null;
    this.serverClock = null;
    this.serverRate = null;
  }
  sourceTime(now) {
    return this.clock ? this.clock.time + (this.running ? Math.max(0,now-this.clock.at)*this.clock.rate : 0) : null;
  }
  sync(message, now) {
    if (!Number.isFinite(message.clockMs)) return;
    const running = message.mode === 'LIVE' || message.playback === 'playing';
    const speed = message.mode === 'LIVE' ? 1 : (message.speed || 1);
    const predicted = this.sourceTime(now);
    const changing = running !== this.running || speed !== this.speed;
    this.phaseError = predicted === null ? 0 : message.clockMs-predicted;
    if (Number.isFinite(message.transportMs)) {
      if(this.serverClock && message.transportMs>this.serverClock.transportMs)
        this.serverRate=(message.clockMs-this.serverClock.time)/(message.transportMs-this.serverClock.transportMs);
      this.serverClock={time:message.clockMs,transportMs:message.transportMs};
    }
    if(changing){
      this.arrival=null;this.deliveryIntervals=[];this.jitter=[];
      this.syncErrors=[];this.correction=0;this.lastCorrectionAt=now;
    }
    // TEST rate is exactly the selected rate. Packet lateness changes phase
    // measurements, never velocity. LIVE corrects only sustained clock drift:
    // at most 0.1%, held >=30 s, with a 50 ms deadband and sign hysteresis.
    if(!changing && running && message.mode==='LIVE') {
      this.syncErrors.push({time:now,error:this.phaseError});
      this.syncErrors=this.syncErrors.filter(p=>now-p.time<=30000);
      if(this.lastCorrectionAt===null)this.lastCorrectionAt=now;
      if(now-this.lastCorrectionAt>=30000 && this.syncErrors.length>=10){
        const robust=percentile(this.syncErrors.map(p=>p.error),0.9);
        const requested=Math.abs(robust)>50 ? Math.sign(robust)*0.001 : 0;
        // A reversal requires an interval at nominal rate first.
        this.correction=requested*this.correction<0 ? 0 : requested;
        this.lastCorrectionAt=now;
      }
    }
    const anchor=predicted===null || changing || !running ? message.clockMs : predicted;
    this.clock={time:anchor,at:now,rate:speed*(1+this.correction)};
    this.running=running;this.speed=speed;this.mode=message.mode;
    if(changing){this.frameAt=now;this.previousMeasurement=null;}
  }
  ingest(message, now) {
    if (message?.version !== 1 || !['snapshot','topic','status','clock'].includes(message.type)) return;
    if (message.type !== 'snapshot' && this.generation !== null &&
      (message.generation < this.generation || (message.generation === this.generation && message.sequence <= this.sequence))) return;
    if (message.type === 'snapshot' || message.generation !== this.generation) this.reset(message.generation);
    this.sequence = message.sequence;
    // Topic clockMs is an event timestamp, not the playback transport clock.
    if (message.type !== 'topic') this.sync(message,now);
    const positions = message.type === 'snapshot' ? message.topics?.['Position.z'] : message.topic === 'Position.z' ? message.data : null;
    if (!positions) return;
    let newest = null;
    for (const [number,record] of Object.entries(positions)) {
      if (!record || typeof record !== 'object') { this.add(number,{}); continue; }
      const samples = Array.isArray(record._history) ? record._history : [{x:record.X,y:record.Y,time:record._sampleTimeMs}];
      for (const point of [...samples].sort((a,b)=>(a?.time ?? Infinity)-(b?.time ?? Infinity))) {
        this.add(number,point);
        if (Number.isFinite(point?.time)) newest = Math.max(newest ?? -Infinity,point.time);
      }
      const driver=this.drivers.get(String(number));
      if(driver)driver.sourceRejected=record._rejectedSamples ?? driver.sourceRejected ?? 0;
    }
    if (newest !== null) {
      if (this.arrival && newest > this.arrival.source) {
        this.deliveryIntervals=[...this.deliveryIntervals,now-this.arrival.wall].slice(-80);
        const variation = Math.max(0,(now-this.arrival.wall)*this.speed-(newest-this.arrival.source));
        this.jitter = [...this.jitter,variation].slice(-80);
      }
      if (!this.arrival || newest > this.arrival.source) this.arrival = {wall:now,source:newest};
    }
  }
  add(number, point) {
    number = String(number);
    let driver = this.drivers.get(number);
    if (!driver) { driver = {samples:[],rejected:0,duplicates:0,intervals:[],state:'waiting',underruns:0,rejectedTimes:new Set()}; this.drivers.set(number,driver); }
    if (![point?.x,point?.y,point?.time].every(Number.isFinite)) { this.reject(driver,point); return; }
    if (driver.rejectedTimes.has(point.time)) return;
    const samples = driver.samples;
    const index = samples.findIndex(p=>p.time>=point.time);
    if (index >= 0 && samples[index].time === point.time) { driver.duplicates++; return; }
    const previous = index === 0 ? null : index < 0 ? samples.at(-1) : samples[index-1];
    const next = index < 0 ? null : samples[index];
    const gap = previous ? point.time-previous.time : 0;
    if (previous && gap <= this.options.maxGapMs && Math.hypot(point.x-previous.x,point.y-previous.y)/gap>this.options.maxUnitsPerMs) { this.reject(driver,point); return; }
    if (next && next.time-point.time <= this.options.maxGapMs && Math.hypot(next.x-point.x,next.y-point.y)/(next.time-point.time)>this.options.maxUnitsPerMs) { this.reject(driver,point); return; }
    const copy = {x:point.x,y:point.y,time:point.time};
    if (index < 0) samples.push(copy); else samples.splice(index,0,copy);
    if (gap > 0 && gap <= 10000) driver.intervals = [...driver.intervals,gap].slice(-80);
    // A larger bounded store protects against packet batching and fast TEST playback.
    while (samples.length > 512 || (samples.length>2 && samples.at(-1).time-samples[0].time>30000)) samples.shift();
  }
  reject(driver,point) {
    if(!Number.isFinite(point?.time) || !driver.rejectedTimes.has(point.time))driver.rejected++;
    if(Number.isFinite(point?.time))driver.rejectedTimes.add(point.time);
    while(driver.rejectedTimes.size>512)driver.rejectedTimes.delete(driver.rejectedTimes.values().next().value);
  }
  configure(options) { this.options = {...this.options,...options}; }
  bufferMs() {
    if (this.manualBufferMs !== null) return this.manualBufferMs;
    const cadence = percentile([...this.drivers.values()].flatMap(d=>d.intervals),0.95) || 250;
    const deliverySpan=percentile(this.deliveryIntervals,0.95)*this.speed;
    return clamp(Math.max(2*cadence,deliverySpan+cadence)+percentile(this.jitter,0.95),this.options.minBufferMs,this.options.maxBufferMs);
  }
  setBuffer(value) {
    const next=value === null || !Number.isFinite(Number(value)) ? null : clamp(Number(value),0,5000);
    if(next!==this.manualBufferMs && this.cursor!==null)this.pendingRebuffer=true;
    this.manualBufferMs=next;
  }
  inspect(number) { this.traceDriver=number===null || number==='' ? null : String(number);this.trace=[];this.previousMeasurement=null; }
  rebuffer(now) {
    this.cursor=null;this.frameAt=now;this.previousMeasurement=null;this.pendingRebuffer=false;
    this.lastRebufferAt=now;this.rebuffers++;
    for(const callback of this.listeners.values())callback({state:'recovering',point:null});
    this.lastFrame=new Map();
  }
  evaluate(driver, time, source) {
    const samples = driver.samples;
    if (!samples.length || time === null) return {state:'waiting',point:null};
    if (source-samples.at(-1).time>this.options.staleMs) return {state:'stale',point:null};
    let low=0,high=samples.length;
    while(low<high){const mid=(low+high)>>1;if(samples[mid].time<=time)low=mid+1;else high=mid;}
    const a=samples[low-1],b=samples[low];
    if (!a) return {state:'waiting',point:null};
    if (!b) {
      const before=samples[low-2];
      if(before && a.time-before.time>this.options.maxGapMs)return {state:'recovering',point:null};
      return {state:'waiting',point:{x:a.x,y:a.y},underrun:true};
    }
    if (b.time-a.time>this.options.maxGapMs) return {state:'recovering',point:null};
    const fraction=(time-a.time)/(b.time-a.time);
    return {state:'interpolating',point:{x:a.x+(b.x-a.x)*fraction,y:a.y+(b.y-a.y)*fraction},
      sourceIntervalMs:b.time-a.time,sourceSpeed:Math.hypot(b.x-a.x,b.y-a.y)/(b.time-a.time)*1000,
      repeated:a.x===b.x && a.y===b.y};
  }
  frame(now) {
    const source=this.sourceTime(now);
    if (source === null) return this.lastFrame;
    const rawElapsed=this.frameAt === null ? 0 : now-this.frameAt;
    if((rawElapsed>1000 && this.running) || this.pendingRebuffer){this.rebuffer(now);return this.lastFrame;}
    const elapsed=Math.max(0,rawElapsed);
    if(this.cursor===null){
      if(![...this.drivers.values()].some(d=>d.samples.length>=2)){this.frameAt=now;return this.lastFrame;}
      this.targetDelay=this.bufferMs();this.cursor=source-this.targetDelay;
    }else if(this.running){
      // Locked delay, stable velocity. Do not chase per-packet buffer estimates.
      this.presentationRate=this.speed*(1+this.correction);
      this.cursor+=elapsed*this.presentationRate;
    }else this.presentationRate=0;
    this.frameAt=now;
    const result=new Map();
    for(const [number,driver] of this.drivers){
      const output=this.evaluate(driver,this.cursor,source);
      if(output.underrun && driver.state!=='waiting'){driver.underruns++;this.underruns++;}
      if(output.underrun){if(driver.waitingSince===undefined)driver.waitingSince=now;}
      else delete driver.waitingSince;
      driver.state=output.state;result.set(number,output);
      this.listeners.get(number)?.(output);
    }
    this.lastFrame=result;
    const active=[...this.drivers.values()].filter(d=>d.samples.length>=2);
    const waiting=active.filter(d=>d.waitingSince!==undefined && now-d.waitingSince>300);
    if(this.running && this.manualBufferMs===null && active.length && waiting.length>active.length/2 && now-this.lastRebufferAt>5000){
      this.rebuffer(now);return this.lastFrame;
    }
    this.measure(now,source,result);
    return result;
  }
  setTracing(enabled) { this.tracing=enabled;this.previousMeasurement=null; }
  measure(now,source,result) {
    if(!this.tracing)return;
    const number=this.traceDriver ?? result.keys().next().value;
    const output=result.get(number);
    if(!output?.point){this.previousMeasurement=null;return;}
    const previous=this.previousMeasurement;
    const dt=previous ? now-previous.wallMs : 0;
    const dc=previous ? this.cursor-previous.cursorMs : 0;
    let distance=0;
    if(previous && dc>0){
      let point=previous.point;
      for(const sample of this.drivers.get(number).samples){
        if(sample.time>previous.cursorMs && sample.time<this.cursor){distance+=Math.hypot(sample.x-point.x,sample.y-point.y);point=sample;}
      }
      distance+=Math.hypot(output.point.x-point.x,output.point.y-point.y);
    }
    if(dt>0 && dt<=1000 && previous?.driver===number){
      const rate=dc/dt;
      this.trace.push({wallMs:now,sourceMs:source,cursorMs:this.cursor,driver:number,requestedRate:this.speed,
        presentationRate:rate,clockRate:this.clock.rate,serverRate:this.serverRate,phaseErrorMs:this.phaseError,
        lockedBufferMs:this.targetDelay,recommendedBufferMs:this.bufferMs(),effectiveDelayMs:source-this.cursor,
        sourceIntervalMs:output.sourceIntervalMs??null,sourceSegmentSpeed:output.sourceSpeed??null,
        sourcePathSpeed:dc>0 ? distance/dc*1000 : 0,
        renderedPathSpeed:distance/dt*1000/this.speed,
        renderedChordSpeed:Math.hypot(output.point.x-previous.point.x,output.point.y-previous.point.y)/dt*1000/this.speed,
        repeated:output.repeated??false,state:output.state});
      if(this.trace.length>3600)this.trace.shift();
    }
    this.previousMeasurement={wallMs:now,cursorMs:this.cursor,driver:number,point:output.point};
  }
  traceCsv() {
    if(!this.trace.length)return '';
    const keys=Object.keys(this.trace[0]);
    return [keys.join(','),...this.trace.map(row=>keys.map(k=>row[k]??'').join(','))].join('\n');
  }
  subscribe(number, callback) {
    number=String(number);this.listeners.set(number,callback);
    callback(this.lastFrame.get(number) ?? {state:'waiting',point:null});
    return()=>{if(this.listeners.get(number)===callback)this.listeners.delete(number);};
  }
  start(request=requestAnimationFrame,cancel=cancelAnimationFrame) {
    let id;
    const draw=now=>{this.frame(now);id=request(draw);};
    id=request(draw);
    return()=>cancel(id);
  }
  diagnostics(now) {
    return {mode:this.mode,running:this.running,speed:this.speed,sourceTime:this.sourceTime(now),interpolationTime:this.cursor,
      bufferMs:this.targetDelay,effectiveDelayMs:this.cursor===null?null:this.sourceTime(now)-this.cursor,
      recommendedMs:this.bufferMs(),presentationRate:this.presentationRate,clockRate:this.clock?.rate,
      serverRate:this.serverRate,phaseErrorMs:this.phaseError,correctionPpm:this.correction*1e6,rebuffers:this.rebuffers,
      trace:this.trace.slice(-600),automatic:this.manualBufferMs===null,underruns:this.underruns,
      deliveryHz:this.deliveryIntervals.length ? 1000/percentile(this.deliveryIntervals,0.5) : null,
      drivers:[...this.drivers].map(([number,d])=>({number,state:d.state,buffered:d.samples.length,rejected:d.rejected+(d.sourceRejected??0),
        frequencyHz:d.intervals.length ? 1000/percentile(d.intervals,0.5):null,underruns:d.underruns}))};
  }
}
