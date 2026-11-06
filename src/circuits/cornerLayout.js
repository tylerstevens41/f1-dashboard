import {pointAt} from './geometry.js';

const distance=(a,b)=>Math.hypot(a.x-b.x,a.y-b.y);
export function segmentDistance(p,a,b){
  const dx=b.x-a.x,dy=b.y-a.y,length=dx*dx+dy*dy;
  const t=length?Math.max(0,Math.min(1,((p.x-a.x)*dx+(p.y-a.y)*dy)/length)):0;
  return Math.hypot(p.x-a.x-t*dx,p.y-a.y-t*dy);
}
export function cornerFrame(geometry,at){
  const anchor=pointAt(geometry,at),radians=anchor.angle*Math.PI/180;
  return {anchor,tangent:{x:Math.cos(radians),y:Math.sin(radians)},normal:{x:-Math.sin(radians),y:Math.cos(radians)}};
}

// Pure, bounded and independent of driver state. Inputs/registry never mutate.
// Native SVG circles scale with the track; optional pixel padding converts once
// through pixelsPerUnit, without introducing a resize/viewBox feedback loop.
export function layoutCornerLabels({labels,geometry,padding=35,trackWidth=330,obstacles=[],pixelsPerUnit=1,pixelPadding=0}){
  const gap=Math.max(0,padding)+Math.max(0,pixelPadding)/Math.max(.0001,pixelsPerUnit);
  const ordered=[...labels].sort((a,b)=>Number(a.feature.number)-Number(b.feature.number)||String(a.feature.letter??'').localeCompare(String(b.feature.letter??''))||a.feature.at-b.feature.at);
  const placed=[],warnings=[];
  function conflicts(p,label,others){
    let count=0,penetration=0;
    for(const other of others){const overlap=label.radius+other.radius+gap-distance(p,other);if(overlap>1e-6){count++;penetration+=overlap;}}
    for(const obstacle of obstacles){const overlap=label.radius+(obstacle.radius??0)+gap-distance(p,obstacle);if(overlap>1e-6){count++;penetration+=overlap;}}
    let nearest=Infinity;
    for(let i=1;i<geometry.points.length;i++)nearest=Math.min(nearest,segmentDistance(p,geometry.points[i-1],geometry.points[i]));
    const overlap=label.radius+trackWidth/2+20+gap-nearest;
    if(overlap>1e-6){count++;penetration+=overlap;}
    return {count,penetration};
  }
  for(let index=0;index<ordered.length;index++){
    const label=ordered[index],{anchor,tangent,normal}=cornerFrame(geometry,label.feature.at);
    const dx=label.x-anchor.x,dy=label.y-anchor.y;
    const along=dx*tangent.x+dy*tangent.y,across=dx*normal.x+dy*normal.y;
    const sign=across<0?-1:1,length=Math.max(Math.hypot(dx,dy),label.radius+trackWidth/2+gap+20);
    const position=(n,t)=>({x:anchor.x+normal.x*n+tangent.x*t,y:anchor.y+normal.y*n+tangent.y*t});
    let chosen={x:label.x,y:label.y},strategy='preferred';
    // Lower numbered turns keep their preference. Only already placed turns
    // constrain preferred positions; unresolved higher turns must move first.
    if(conflicts(chosen,label,placed).count){
      const candidates=[{...position(-across,along),strategy:'flipped'}];
      for(const factor of [1,1.25,1.5,1.75])for(const side of [-sign,sign])for(const shift of [0,-.65,.65])
        candidates.push({...position(side*length*factor,along+shift*label.radius),strategy:'alternate'});
      const future=ordered.slice(index+1);
      let best=null;
      for(const candidate of candidates){
        // Every correction is checked against all labels, including those not
        // yet placed, to avoid flipping straight into another preferred label.
        const hard=conflicts(candidate,label,placed),all=conflicts(candidate,label,[...placed,...future]);
        const score=[hard.count,all.count,hard.penetration,all.penetration,distance(candidate,label)];
        if(all.count===0){chosen=candidate;strategy=candidate.strategy;best=null;break;}
        if(!best||score.some((v,i)=>v!==best.score[i]&&score.slice(0,i).every((x,j)=>x===best.score[j])&&v<best.score[i]))best={candidate,score};
      }
      if(best){chosen=best.candidate;strategy=chosen.strategy;}
    }
    placed.push({...label,...chosen,strategy});
  }
  // Final pass detects multi-label conflicts after every higher turn settled.
  for(const label of placed){
    const result=conflicts(label,label,placed.filter(other=>other!==label));
    if(result.count)warnings.push({corner:`${label.feature.number}${label.feature.letter??''}`,conflicts:result.count,reason:'bounded-placement-unresolved'});
  }
  return {labels:placed,warnings};
}
