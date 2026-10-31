"""Folder navigation and approved UTF-8 text writes inside allowed roots."""
import ast
import json
import os
from pathlib import Path
import sys
import tempfile
from pydantic import BaseModel,Field,field_validator
from sqlalchemy import select,or_
from mitraa.db.models import FileAction,CodingJob
from mitraa.tools.base import Impact,RiskLevel,Tool,ToolResult
from mitraa.tools.files import PATH_HELP,_trash,_record

TEXT_SUFFIXES={'.txt','.md','.log','.csv','.json','.py'}
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
    path: str=Field(description='Destination .txt, .md, .log, .csv, .json or .py file. '+PATH_HELP)
    content: str=Field(max_length=250_000,description='Exact text to write. Preserve user-provided words and line breaks.')
    mode: str=Field(default='create',pattern='^(create|replace|append)$',description='create refuses existing files; replace overwrites; append adds exact text without an automatic newline.')
    output_name: str | None=Field(default=None,description='Only when the user explicitly supplies an output filename: plain filename with extension, in the same folder. Otherwise omit to keep the original and use its _byMitraa working copy.')
    overwrite_original: bool=Field(default=False,description='True only when the user explicitly requests overwriting the original itself. Normally leave false.')

    @field_validator('output_name')
    @classmethod
    def plain_output_name(cls,name):
        if name is not None and (not name or name in {'.','..'} or any(c in name for c in '/\\:\x00')):
            raise ValueError('Output name must be a plain filename with extension.')
        return name


def known_edit(path,ctx):
    record=ctx.session.scalars(select(FileAction).where(FileAction.action=='write_text_file',
        FileAction.undone.is_(False),or_(FileAction.src==str(path),FileAction.dst==str(path)))
        .order_by(FileAction.id.desc()).limit(1)).first()
    if record:return ctx.sandbox.resolve(record.dst)
    for job in ctx.session.scalars(select(CodingJob).where(CodingJob.status=='applied').order_by(CodingJob.updated_at.desc())):
        contract=json.loads(job.contract_json)
        root=Path(contract['workspace'])
        if not path.is_relative_to(root):continue
        result=json.loads(job.result_json)
        name=path.relative_to(root).as_posix()
        saved={**result.get('saved_files',{}),**result.get('working_copies',{})}
        if name in saved:return ctx.sandbox.resolve(saved[name])
    return None


def edit_destination(args,ctx):
    source=ctx.sandbox.resolve(args.path)
    if args.output_name is not None:
        name=args.output_name
        if not name or name in {'.','..'} or any(c in name for c in '/\\:\x00'):
            raise ValueError('Output name must be a plain filename with extension.')
        return source,ctx.sandbox.resolve(str(source.with_name(name)))
    if args.mode=='create' or args.overwrite_original:return source,source
    known=known_edit(source,ctx)
    if known is not None:return source,known
    if source.stem.lower().endswith('_bymitraa'):return source,source
    return source,ctx.sandbox.resolve(str(source.with_name(source.stem+'_byMitraa'+source.suffix)))

class WriteTextFile(Tool):
    name='write_text_file'
    description='Create or edit UTF-8 text including .py. Edits preserve the original by default and use a sibling named <stem>_byMitraa<extension>; later edits reuse the same working copy. output_name honors an explicit user filename. Read current working copy first. Always requires approval. Existing working-copy versions go to Recycle Bin. Python syntax checked without executing code.'
    args_model=WriteTextArgs
    base_risk=RiskLevel.HIGH
    mutates=True
    def impact(self,args,ctx):
        source,path=edit_destination(args,ctx)
        return Impact(paths=[source,path],count=1,overwrites=[path] if path.is_file() and args.mode!='create' else [])
    def run(self,args,ctx):
        source,path=edit_destination(args,ctx)
        if not ctx.approved: return ToolResult.fail('Writing text requires explicit approval.')
        if path.suffix.lower() not in TEXT_SUFFIXES: return ToolResult.fail('Choose a supported plain-text file extension: .txt, .md, .log, .csv, .json, .py.')
        if '\x00' in args.content: return ToolResult.fail('Text must not contain binary null characters.')
        if not path.parent.is_dir(): return ToolResult.fail('The parent folder must exist. Use create_folder first.')
        if path.exists() and not path.is_file(): return ToolResult.fail('The destination is a folder, not a text file.')
        if args.mode=='create' and path.exists(): return ToolResult.fail('That file already exists. Read it first, then request append or replace with approval.')
        if args.mode!='create' and not source.is_file(): return ToolResult.fail('That source file does not exist. Use create to make a new file.')
        if path!=source and path.exists() and args.output_name is None and known_edit(source,ctx)!=path:
            return ToolResult.fail('The default working-copy filename already exists and is not tracked. Read it and explicitly select it, or provide another output name.')
        content=args.content
        existing=path if path.exists() else source
        if args.mode!='create' and existing.exists():
            if existing.stat().st_size>MAX_BYTES: return ToolResult.fail('The existing file exceeds the 1 MB text-edit limit.')
            try:
                with existing.open('rb') as stream: raw=stream.read(MAX_BYTES+1)
                if len(raw)>MAX_BYTES: return ToolResult.fail('The existing file exceeds the 1 MB text-edit limit.')
                previous=raw.decode('utf-8-sig')
            except UnicodeError: return ToolResult.fail('The file is not UTF-8 text. No changes were made.')
            if '\x00' in previous: return ToolResult.fail('The existing file appears to be binary. No changes were made.')
            if args.mode=='append': content=previous+content
        encoded=content.encode('utf-8')
        if len(encoded)>MAX_BYTES: return ToolResult.fail('The resulting text exceeds the 1 MB limit.')
        if path.suffix.lower()=='.py':
            try: ast.parse(content,filename=path.name)
            except (SyntaxError,ValueError) as exc:
                return ToolResult.fail('Python syntax check failed'+(f' at line {exc.lineno}' if isinstance(exc,SyntaxError) else '')+'. No changes were made.')
        temporary=None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.mitraa-',suffix='.tmp',delete=False) as output:
                temporary=Path(output.name); output.write(encoded); output.flush(); os.fsync(output.fileno())
            # Re-resolve before mutation, as for all other sandboxed file tools.
            if edit_destination(args,ctx)!=(source,path): return ToolResult.fail('The destination changed. Please retry.')
            replaced=path.exists()
            if args.mode=='create' or not replaced:
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
        _record(ctx,self.name,source,path)
        return ToolResult.success(f'Wrote {path.name}.'+(' Original file preserved.' if source!=path else '')+(' Previous working version is in the Recycle Bin.' if replaced else '')+(' Python syntax checked; code was not run.' if path.suffix.lower()=='.py' else ''),path=str(path),source=str(source),mode=args.mode,bytes_written=len(encoded))
    def describe(self,args): return f'{args.mode.capitalize()} text file {args.path}'

ALL_TEXT_TOOLS=[OpenFolder(),WriteTextFile()]
