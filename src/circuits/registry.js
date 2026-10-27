import austin from './tracks/austin';
export const circuits={Austin:austin};
export const findCircuit=name=>circuits[name]??null;
