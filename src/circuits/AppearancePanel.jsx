import {defaultAppearance} from './annotations';
export default function AppearancePanel({value,onChange,preview,setPreview}){
  const change=(key,v)=>onChange({...value,[key]:v});
  return <details className="circuit-dev-panel"><summary>Track appearance (development)</summary>
    <label>Base <select value={value.base} onChange={e=>change('base',e.target.value)}><option value="black">Black</option><option value="charcoal">Charcoal</option><option value="grey">Grey</option></select></label>{' '}
    <label>Track width <input type="range" min="150" max="600" value={value.trackWidth} onChange={e=>change('trackWidth',Number(e.target.value))}/></label>{' '}
    <label>Centre line <input type="range" min="20" max="150" value={value.lineWidth} onChange={e=>change('lineWidth',Number(e.target.value))}/></label>
    {Object.keys(defaultAppearance).filter(k=>typeof defaultAppearance[k]==='boolean').map(k=><label key={k}><input type="checkbox" checked={value[k]} onChange={e=>change(k,e.target.checked)}/>{k} </label>)}
    <label><input type="checkbox" checked={preview} onChange={e=>setPreview(e.target.checked)}/>Preview provisional annotations</label>
    <p>Palette: magenta / gold / cyan. Appearance changes never alter GPS or annotation data.</p>
  </details>;
}
