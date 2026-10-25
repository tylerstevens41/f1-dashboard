import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createGeometry, pointAt, transformPoint } from '../src/circuits/geometry.js';

test('source-specific affine mapping and Y inversion share the same projection', () => {
  const reference = [{x:10,y:20},{x:20,y:30}];
  const live = createGeometry(reference, {padding:5});
  const replay = createGeometry([{x:1,y:2},{x:2,y:3}], {padding:5,matrix:[10,0,0,10,0,0]});
  assert.deepEqual(live.points, replay.points);
  assert.deepEqual(replay.project(2,3), live.project(20,30));
  assert.deepEqual(live.project(10,20), {x:5,y:15});
});
test('annotations follow arc length rather than sample index', () => {
  const track = createGeometry([{x:0,y:0},{x:1,y:0},{x:10,y:0},{x:10,y:10}],{padding:0});
  assert.equal(pointAt(track,0.5).x,10);
  assert.equal(pointAt(track,0.5).y,10);
  assert.equal(pointAt(track,1).y,0);
});
test('invalid coordinates and degenerate references are rejected', () => {
  assert.equal(transformPoint({x:null,y:2}),null);
  assert.equal(createGeometry([]),null);
  assert.equal(createGeometry([{x:1,y:1},{x:1,y:1}]),null);
});
