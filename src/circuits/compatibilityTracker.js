import {gpsCompatibility} from './prepared.js';
// Geometry evidence is session-scoped, not a marker freshness timer.
export class CompatibilityTracker {
 constructor(scope=null){this.scope=scope;this.records=new Map();this.allowed=false;this.lastSuccess=null;this.lastP95=null;}
 update(geometry,drivers,clockMs){
  let changed=false;
  const rejected={invalid:0,future:0,old:0,offTrack:0};
  for(const driver of drivers){
   const gps=driver.gps,id=String(driver.driver_number??driver.number);
   if(!gps||![gps.X,gps.Y,gps._sampleTimeMs].every(Number.isFinite)){rejected.invalid++;continue;}
   if(clockMs-gps._sampleTimeMs < -2000){rejected.future++;continue;}
   if(clockMs-gps._sampleTimeMs>30000){rejected.old++;continue;}
   if(driver.timing?.InPit===true||driver.timing?.PitIn===true||String(gps.Status??'OnTrack').toLowerCase()!=='ontrack'){rejected.offTrack++;continue;}
   const old=this.records.get(id);
   if(!old||gps._sampleTimeMs>old.gps._sampleTimeMs||gps.X!==old.gps.X||gps.Y!==old.gps.Y){this.records.set(id,driver);changed=true;}
  }
  for(const [id,driver] of this.records)if(clockMs-driver.gps._sampleTimeMs>30000)this.records.delete(id);
  const result=gpsCompatibility(geometry,[...this.records.values()],clockMs,5,30000);
  if(result.status==='incompatible')this.allowed=false;
  if(result.status==='compatible-sample'){
   this.allowed=true;
   if(changed){this.lastSuccess=clockMs;this.lastP95=result.p95FractionOfDiagonal;}
  }
  const blockedDrivers=[];
  for(const [id,driver] of this.records){
   const one=gpsCompatibility(geometry,[driver],clockMs,1,30000);
   if(one.status==='incompatible')blockedDrivers.push(id);
  }
  const ages=drivers.map(d=>clockMs-d.gps?._sampleTimeMs).filter(Number.isFinite);
  return {...result,status:this.allowed?(changed&&result.status==='compatible-sample'?'compatible-sample':'compatible-retained'):result.status,
   allowed:this.allowed,blockedDrivers,lastSuccessMs:this.lastSuccess,p95FractionOfDiagonal:result.p95FractionOfDiagonal??this.lastP95,
   recentDrivers:ages.filter(a=>a>=-2000&&a<=2500).length,newestSampleAgeMs:ages.length?Math.min(...ages):null,rejected};
 }
}
