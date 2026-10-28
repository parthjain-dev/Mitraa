"""Folder navigation and approved UTF-8 text writes inside allowed roots."""
import os
from pathlib import Path
import sys
import tempfile
from pydantic import BaseModel,Field
from mitraa.tools.base import Impact,RiskLevel,Tool,ToolResult
from mitraa.tools.files import PATH_HELP,_trash

TEXT_SUFFIXES={'.txt','.md','.log','.csv','.json'}
MAX_BYTES=1_000_000

class OpenFolderArgs(BaseModel):
    path: str=Field(description=PATH_HELP)

class OpenFolder(Tool):
    name='open_folder'
    description='Open an existing allowed folder in Windows File Explorer. Use list_folder to inspect contents instead. Find ambiguous folder names with search_files first.'
    args_model=OpenFolderArgs
    base_risk=RiskLevel.MEDIUM
    def impact(self,args,ctx): return Impact(paths=[ctx.sandbox.resolve(args.path)],count=0)
    def run(self,args,ctx):
        folder=ctx.sandbox.resolve(args.path)
        if not folder.is_dir(): return ToolResult.fail('That folder does not exist. Use search_files to locate it.')
        if sys.platform!='win32': return ToolResult.fail('Opening folders is currently supported on Windows only.')
        try: os.startfile(str(folder),'explore')
        except OSError: return ToolResult.fail('Windows could not open the folder. Please try again.')
        return ToolResult.success(f'Asked File Explorer to open {folder.name}.',path=str(folder))
    def describe(self,args): return f'Open folder {args.path}'

class WriteTextArgs(BaseModel):
    path: str=Field(description='Destination .txt, .md, .log, .csv or .json file. '+PATH_HELP)
    content: str=Field(max_length=250_000,description='Exact text to write. Preserve user-provided words and line breaks.')
    mode: str=Field(default='create',pattern='^(create|replace|append)$',description='create refuses existing files; replace overwrites; append adds exact text without an automatic newline.')

class WriteTextFile(Tool):
    name='write_text_file'
    description='Create, replace or append UTF-8 plain text. Always requires approval. Read an existing file first before editing it. Never replace the whole file using a truncated read. Parent folder must exist; existing versions go to the Recycle Bin. Does not execute files.'
    args_model=WriteTextArgs
    base_risk=RiskLevel.HIGH
    mutates=True
    def impact(self,args,ctx):
        path=ctx.sandbox.resolve(args.path)
        return Impact(paths=[path],count=1,overwrites=[path] if path.is_file() and args.mode!='create' else [])
    def run(self,args,ctx):
        path=ctx.sandbox.resolve(args.path)
        if not ctx.approved: return ToolResult.fail('Writing text requires explicit approval.')
        if path.suffix.lower() not in TEXT_SUFFIXES: return ToolResult.fail('Choose a supported plain-text file extension: .txt, .md, .log, .csv, .json.')
        if '\x00' in args.content: return ToolResult.fail('Text must not contain binary null characters.')
        if not path.parent.is_dir(): return ToolResult.fail('The parent folder must exist. Use create_folder first.')
        if path.exists() and not path.is_file(): return ToolResult.fail('The destination is a folder, not a text file.')
        if args.mode=='create' and path.exists(): return ToolResult.fail('That file already exists. Read it first, then request append or replace with approval.')
        if args.mode!='create' and not path.exists(): return ToolResult.fail('That file does not exist. Use create to make a new file.')
        content=args.content
        if path.exists():
            if path.stat().st_size>MAX_BYTES: return ToolResult.fail('The existing file exceeds the 1 MB text-edit limit.')
            try:
                with path.open('rb') as source: raw=source.read(MAX_BYTES+1)
                if len(raw)>MAX_BYTES: return ToolResult.fail('The existing file exceeds the 1 MB text-edit limit.')
                previous=raw.decode('utf-8-sig')
            except UnicodeError: return ToolResult.fail('The file is not UTF-8 text. No changes were made.')
            if '\x00' in previous: return ToolResult.fail('The existing file appears to be binary. No changes were made.')
            if args.mode=='append': content=previous+content
        encoded=content.encode('utf-8')
        if len(encoded)>MAX_BYTES: return ToolResult.fail('The resulting text exceeds the 1 MB limit.')
        temporary=None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.mitraa-',suffix='.tmp',delete=False) as output:
                temporary=Path(output.name); output.write(encoded); output.flush(); os.fsync(output.fileno())
            # Re-resolve before mutation, as for all other sandboxed file tools.
            if ctx.sandbox.resolve(args.path)!=path: return ToolResult.fail('The destination changed. Please retry.')
            if args.mode=='create':
                # Exclusive creation protects against a file appearing after approval.
                with path.open('xb') as destination: destination.write(encoded)
            else:
                _trash(path)
                os.replace(temporary,path); temporary=None
        except FileExistsError: return ToolResult.fail('A file appeared at the destination. It was not replaced.')
        except OSError:
            return ToolResult.fail('The write could not be completed. If replacement had begun, the previous version is in the Recycle Bin.')
        finally:
            if temporary is not None: temporary.unlink(missing_ok=True)
        return ToolResult.success(f'Wrote {path.name}.'+(' Previous version is in the Recycle Bin.' if args.mode!='create' else ''),path=str(path),mode=args.mode,bytes_written=len(encoded))
    def describe(self,args): return f'{args.mode.capitalize()} text file {args.path}'

ALL_TEXT_TOOLS=[OpenFolder(),WriteTextFile()]
