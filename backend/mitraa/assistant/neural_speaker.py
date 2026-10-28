"""Local Kokoro neural playback with the same lifecycle as Windows speech."""
import logging
from pathlib import Path
import queue
import threading
import time
from collections import OrderedDict
import numpy as np
from mitraa.assistant.voice import Speaker

logger=logging.getLogger(__name__)

def load_engine(folder,threads=4):
    from kokoro_onnx import Kokoro
    import onnxruntime as ort
    options=ort.SessionOptions()
    options.intra_op_num_threads=threads
    options.inter_op_num_threads=1
    session=ort.InferenceSession(str(Path(folder)/'kokoro-v1.0.onnx'),sess_options=options,providers=['CPUExecutionProvider'])
    return Kokoro.from_session(session,str(Path(folder)/'voices-v1.0.bin'))

def speech_chunks(text):
    """Short first phrase, then bounded phrases; never drop or split words."""
    chunks=[]; words=[]; length=0
    for word in text.split():
        limit=60 if not chunks else 100
        if words and length+len(word)+1>limit:
            chunks.append(' '.join(words)); words=[]; length=0
        words.append(word); length+=len(word)+1
        if word.endswith(('.', '!', '?', ';', ':')):
            chunks.append(' '.join(words)); words=[]; length=0
    if words: chunks.append(' '.join(words))
    return chunks

class NeuralSpeaker(Speaker):
    def __init__(self, folder, voice='bm_george', speed=.96):
        self.folder=folder; self.neural_voice=voice; self.speed=speed
        self._closing=threading.Event()
        self._synthesis_lock=threading.Lock()
        self._audio_cache=OrderedDict()
        super().__init__(voice,0)

    def close(self):
        self._closing.set(); self.stop()
        super().close()

    def _run(self):
        try:
            engine=load_engine(self.folder)
            self.voice_description=f'Kokoro {self.neural_voice} (local neural)'
            logger.info('Speaking with voice: %s',self.voice_description)
        except Exception:
            logger.exception('Local neural voice initialization failed')
            self.available=False; self.error='Local neural voice unavailable. Check the downloaded model and neural voice dependencies.'
            self.idle.set()
            while True:
                item=self._queue.get()
                if item is None: return
                item[1](('speech_error',self.error))
        while not self._closing.is_set():
            item=self._queue.get()
            if item is None: return
            while not self._queue.empty():
                item=self._queue.get()
                if item is None: self.idle.set(); return
            text,post,generation=item
            with self._state_lock:
                if generation!=self._generation: self.idle.set(); continue
                self._interrupt.clear()
            try:
                self._speak_chunks(engine,text,post,generation)
            except Exception:
                self.idle.set()
                logger.exception('Neural speech failed')
                post(('speech_error','Could not play the local neural voice. Please retry.'))

    def _speak_chunks(self,engine,text,post,generation):
        chunks=queue.Queue(maxsize=2)
        cancelled=threading.Event()
        began=time.perf_counter()
        def enqueue(value):
            while not cancelled.is_set() and not self._closing.is_set() and not self._interrupt.is_set():
                try: chunks.put(value,timeout=.05); return
                except queue.Full: pass
        def synthesize():
            try:
                for phrase in speech_chunks(text):
                    if cancelled.is_set() or self._closing.is_set() or self._interrupt.is_set(): return
                    with self._synthesis_lock:
                        if cancelled.is_set() or self._interrupt.is_set(): return
                        key=(phrase,self.neural_voice,self.speed)
                        audio=self._audio_cache.get(key)
                        if audio is None:
                            samples,rate=engine.create(phrase,voice=self.neural_voice,speed=self.speed,lang='en-gb')
                            audio=(np.asarray(samples,dtype=np.float32),rate)
                            if len(audio[0])<=240000:
                                self._audio_cache[key]=audio
                                while len(self._audio_cache)>16: self._audio_cache.popitem(last=False)
                        else: self._audio_cache.move_to_end(key)
                    enqueue(('audio',audio))
                enqueue(('done',None))
            except Exception as exc: enqueue(('error',exc))
        producer=threading.Thread(target=synthesize,name='mitraa-synthesize',daemon=True)
        producer.start()
        announced=False; first=True
        def playback_event(event):
            nonlocal announced
            if event[0]=='speech_started':
                if announced: return
                announced=True
            if event[0]!='speech_stopped': post(event)
        try:
            while not self._interrupt.is_set() and not self._closing.is_set():
                try: kind,payload=chunks.get(timeout=.05)
                except queue.Empty: continue
                if kind=='done': break
                if kind=='error': raise payload
                if first:
                    logger.info('Neural first audio ready in %.3fs',time.perf_counter()-began); first=False
                samples,rate=payload
                self._play(samples,rate,playback_event,generation,final=False)
                post(('speech_level',0.))
        finally:
            cancelled.set(); self.idle.set()
        post(('speech_stopped' if self._interrupt.is_set() or self._closing.is_set() else 'speech_finished',None))

    def _play(self,samples,rate,post,generation,*,final=True):
        import sounddevice as sd
        started=threading.Event(); cursor=0; level=0.
        def callback(out,frames,timing,status):
            nonlocal cursor,level
            out.fill(0)
            if self._interrupt.is_set() or self._closing.is_set(): raise sd.CallbackAbort
            count=min(frames,len(samples)-cursor)
            if count:
                block=samples[cursor:cursor+count]
                out[:count,0]=block; cursor+=count
                level=float(np.sqrt(np.mean(block*block)))
                started.set()
            if cursor>=len(samples): raise sd.CallbackStop
        stream=sd.OutputStream(samplerate=rate,channels=1,dtype='float32',blocksize=1024,callback=callback)
        announced=False
        try:
            with self._state_lock:
                if generation!=self._generation or self._interrupt.is_set():
                    post(('speech_stopped',None)); return
                stream.start()
            while stream.active:
                if started.is_set() and not announced:
                    post(('speech_started',None)); announced=True
                if announced: post(('speech_level',level))
                if self._interrupt.wait(.03) or self._closing.is_set():
                    stream.abort(); break
            if started.is_set() and not announced: post(('speech_started',None))
        finally:
            stream.close()
            if final or self._interrupt.is_set() or self._closing.is_set(): self.idle.set()
        if final or self._interrupt.is_set() or self._closing.is_set():
            post(('speech_stopped' if self._interrupt.is_set() or self._closing.is_set() else 'speech_finished',None))
