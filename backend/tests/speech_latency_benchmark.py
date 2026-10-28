"""Local synthesis timing only: no microphone, network, or playback."""
import time
from mitraa.assistant.neural_speaker import load_engine,speech_chunks

engine=load_engine('models/kokoro')
text='Your report is ready. I have organized the remaining tasks and prepared a detailed summary for you to review before the next meeting.'
engine.create('Ready.',voice='bm_george',speed=.96,lang='en-gb')
for label,value in [('full reply',text),('first phrase',speech_chunks(text)[0])]:
    start=time.perf_counter()
    samples,rate=engine.create(value,voice='bm_george',speed=.96,lang='en-gb')
    print(f'{label}: synthesis={time.perf_counter()-start:.3f}s audio={len(samples)/rate:.3f}s',flush=True)
