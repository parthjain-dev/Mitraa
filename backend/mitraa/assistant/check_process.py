"""Windows resource-bounded test process. Not a filesystem/network sandbox."""
import ctypes
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

OUTPUT_LIMIT=32_768


class WindowsJob:
    def __init__(self,seconds):
        if sys.platform!='win32':raise ValueError('Approved code checks currently require Windows.')
        class Basic(ctypes.Structure):
            _fields_=[('process_time',ctypes.c_longlong),('job_time',ctypes.c_longlong),
                ('flags',W.DWORD),('minimum',ctypes.c_size_t),('maximum',ctypes.c_size_t),
                ('active',W.DWORD),('affinity',ctypes.c_size_t),('priority',W.DWORD),('scheduling',W.DWORD)]
        class IO(ctypes.Structure):
            _fields_=[(name,ctypes.c_ulonglong) for name in ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]
        class Extended(ctypes.Structure):
            _fields_=[('basic',Basic),('io',IO),('process_memory',ctypes.c_size_t),('job_memory',ctypes.c_size_t),
                ('peak_process',ctypes.c_size_t),('peak_job',ctypes.c_size_t)]
        self.api=ctypes.WinDLL('kernel32',use_last_error=True)
        self.api.CreateJobObjectW.argtypes=[ctypes.c_void_p,W.LPCWSTR];self.api.CreateJobObjectW.restype=W.HANDLE
        self.api.SetInformationJobObject.argtypes=[W.HANDLE,ctypes.c_int,ctypes.c_void_p,W.DWORD]
        self.api.SetInformationJobObject.restype=W.BOOL
        self.api.AssignProcessToJobObject.argtypes=[W.HANDLE,W.HANDLE];self.api.AssignProcessToJobObject.restype=W.BOOL
        self.api.CloseHandle.argtypes=[W.HANDLE];self.api.CloseHandle.restype=W.BOOL
        self.handle=self.api.CreateJobObjectW(None,None)
        if not self.handle:raise ValueError('Windows could not establish process limits. No check started.')
        info=Extended();info.basic.flags=0x2000|0x8|0x100|0x4
        info.basic.active=1;info.basic.job_time=seconds*10_000_000
        info.process_memory=256*1024*1024
        if not self.api.SetInformationJobObject(self.handle,9,ctypes.byref(info),ctypes.sizeof(info)):
            self.close();raise ValueError('Windows could not establish process limits. No check started.')

    def attach(self,process):
        if not self.api.AssignProcessToJobObject(self.handle,W.HANDLE(int(process._handle))):
            raise ValueError('Windows could not attach process limits. Selected code was not started.')

    def close(self):
        if self.handle:self.api.CloseHandle(self.handle);self.handle=None


def run_check(root,recipe,cancelled):
    """Only a fixed Python driver; no shell or user-supplied command arguments."""
    job=WindowsJob(recipe['timeout_seconds']);process=None;threads=[]
    buffers=[bytearray(),bytearray()];overflow=threading.Event()
    started=time.monotonic();status=None
    def drain(stream,buffer):
        try:
            while True:
                chunk=stream.read(4096)
                if not chunk:break
                remaining=OUTPUT_LIMIT-len(buffer)
                buffer.extend(chunk[:remaining])
                if len(chunk)>remaining:overflow.set()
        finally:stream.close()
    try:
        env={key:value for key,value in os.environ.items() if key.upper() in {'SYSTEMROOT','WINDIR'}}
        temporary=Path(root)/'mitraa-temp';temporary.mkdir()
        env.update(TEMP=str(temporary),TMP=str(temporary))
        # Windows venv python.exe is a redirector which launches a second process.
        # Use the real interpreter so the one-process limit does not reject it.
        interpreter=getattr(sys,'_base_executable',sys.executable)
        process=subprocess.Popen([interpreter,'-I','-S','-B','-X','utf8',str(Path(__file__).with_name('check_driver.py'))],
            cwd=root,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            shell=False,creationflags=subprocess.CREATE_NO_WINDOW)
        job.attach(process)
        for stream,buffer in zip((process.stdout,process.stderr),buffers):
            thread=threading.Thread(target=drain,args=(stream,buffer),daemon=True);thread.start();threads.append(thread)
        process.stdin.write((json.dumps({'root':str(root),'file':recipe['file'],'kind':recipe['kind']})+'\n').encode())
        process.stdin.close()
        while process.poll() is None:
            if cancelled.is_set():status='cancelled';break
            if overflow.is_set():status='output_limit';break
            if time.monotonic()-started>recipe['timeout_seconds']:status='timed_out';break
            time.sleep(.03)
    finally:
        job.close()  # Kill-on-close, also on failure/shutdown; children cannot break away.
        if process is not None:
            if process.poll() is None:process.kill()
            process.wait(timeout=5)
            if process.stdin and not process.stdin.closed:process.stdin.close()
        for thread in threads:thread.join(timeout=5)
    stdout,stderr=(bytes(b).decode('utf-8',errors='replace') for b in buffers)
    status=status or ('output_limit' if overflow.is_set() else 'passed' if process.returncode==0 else 'failed')
    receipt={}
    try:
        path=Path(root)/'.mitraa-check-result.json'
        if path.is_symlink():raise ValueError('Invalid check completion record.')
        with path.open('rb') as stream:receipt=json.loads(stream.read(4096))
        if not isinstance(receipt,dict):receipt={}
    except (OSError,ValueError):pass
    if status=='passed' and not(receipt.get('completed') is True and receipt.get('kind')==recipe['kind']):
        status='failed'
    if status=='passed' and recipe['kind']=='output':
        normalize=lambda text:text.replace('\r\n','\n').removesuffix('\n')
        if normalize(stdout)!=normalize(recipe['expected_output']):status='failed'
    return dict(status=status,exit_code=process.returncode,stdout=stdout,stderr=stderr,
        completion=receipt,output_truncated=overflow.is_set(),duration_seconds=round(time.monotonic()-started,3))
