"""Find useful on-track windows inside one already-bounded real clip."""
from .calibrate import collect_clip


def recommend_windows(clip):
    samples=collect_clip(clip)
    origin=clip['originMs']
    bins={}
    for sample in samples:
        if sample.get('status')!='OnTrack' or sample.get('inPit') is True:continue
        index=int((sample['time']-origin)//15000)
        if index<0:continue
        entry=bins.setdefault(index,{'drivers':set(),'samples':0})
        entry['drivers'].add(sample['driver']);entry['samples']+=1
    ranked=sorted(bins.items(),key=lambda pair:(len(pair[1]['drivers']),pair[1]['samples']),reverse=True)[:5]
    return [{'offsetMs':index*15000,'archiveOffsetSeconds':(clip.get('startOffsetSeconds') or 0)+index*15,
             'onTrackDrivers':len(info['drivers']),'samples':info['samples']} for index,info in ranked]
