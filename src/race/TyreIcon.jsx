import {useState} from 'react';
import {tyreAsset} from './tyres';

export default function TyreIcon({compound}) {
  const asset=tyreAsset(compound,import.meta.env.BASE_URL);
  const [failed,setFailed]=useState(null);
  if(!asset || failed===asset.src)return <span className="live-tyre-missing" aria-label="Tyre compound unavailable">—</span>;
  return <img className="live-tyre-icon" src={asset.src} alt={`${asset.name} tyre`} title={`${asset.name.toUpperCase()} tyre`} onError={()=>setFailed(asset.src)}/>;
}
