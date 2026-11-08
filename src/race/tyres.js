// Exact public artwork; aliases describe compounds, never numeric tyre specifications.
const aliases = {S:'soft',SOFT:'soft',M:'medium',MEDIUM:'medium',H:'hard',HARD:'hard',I:'intermediate',INTER:'intermediate',INTERS:'intermediate',INTERMEDIATE:'intermediate',W:'wet',WET:'wet',FULLWET:'wet',FULLWETS:'wet'};
export function tyreAsset(compound, base='/') {
  const key=String(compound??'').trim().toUpperCase().replace(/[\s_-]+/g,'');
  const name=aliases[key];
  return name ? {name,src:`${base.endsWith('/')?base:base+'/'}tyres/${name}.svg`} : null;
}
