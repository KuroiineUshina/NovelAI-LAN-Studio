import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseRepeatCount, sequenceProgress } from '../src/sequentialGeneration.ts';

test('only explicit whole repeat counts from 1 through 100 are accepted', () => {
  for (const value of ['', ' ', '0', '-1', '2.5', '101', 'NaN', 'Infinity']) assert.equal(parseRepeatCount(value), null);
  for (const value of ['1', '10', '100']) assert.equal(parseRepeatCount(value), Number(value));
});
test('round progress is separate from image count and remains backward compatible', () => {
  assert.deepEqual(sequenceProgress({request:{repeat_count:10},completed_requests:3}), {total:10,completed:3,remaining:7});
  assert.deepEqual(sequenceProgress({request:{}}), {total:1,completed:0,remaining:1});
});
