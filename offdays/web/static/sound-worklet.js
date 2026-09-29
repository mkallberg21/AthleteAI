// Runs on the audio thread. Its only job is to hand each 128-sample block to
// the page with the audio-clock time it started at; all the listening happens
// in sound.js. Blocks are copied because the engine reuses the buffer.
class Blocks extends AudioWorkletProcessor {
  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (channel) {
      this.port.postMessage({ samples: channel.slice(0), t: currentTime });
    }
    return true;
  }
}

registerProcessor('offdays-blocks', Blocks);
