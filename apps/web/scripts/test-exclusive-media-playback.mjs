import assert from 'node:assert/strict';
import { installExclusiveMediaPlayback } from '../src/lib/exclusive-media-playback.ts';
class Media extends EventTarget {
  paused = true;
  currentTime = 12;
  pause() { this.paused = true; }
}
globalThis.HTMLMediaElement = Media;
const source = new Media(), output = new Media(), audio = new Media();
const root = new EventTarget();
root.querySelectorAll = () => [source, output, audio];
const channel = new EventTarget();
const messages = [];
channel.postMessage = (message) => messages.push(message);
channel.close = () => { channel.closed = true; };
const dispose = installExclusiveMediaPlayback(root, channel);
function play(media) {
  media.paused = false;
  const event = new Event('play');
  Object.defineProperty(event, 'target', { value: media });
  root.dispatchEvent(event);
}
play(source);
play(output);
assert.equal(source.paused, true, 'starting the result stops the reference');
assert.equal(output.paused, false, 'the selected result keeps playing');
assert.equal(source.currentTime, 12, 'pause preserves playback position');
play(audio);
assert.equal(output.paused, true, 'audio and video share the same playback rule');
assert.equal(audio.paused, false);
root.dispatchEvent(new Event('play'));
assert.equal(audio.paused, false, 'wrapper events do not stop the active player');
assert.equal(messages.length, 3, 'only native play events are broadcast');
channel.dispatchEvent(new MessageEvent('message', { data: 'play' }));
assert.equal(audio.paused, true, 'another tab starting playback stops this tab');
assert.equal(messages.length, 3, 'remote pause does not echo back');
dispose();
assert.equal(channel.closed, true);
play(source);play(output);
assert.equal(source.paused, false, 'cleanup removes the listener');
console.log('Exclusive media playback regression checks passed');
