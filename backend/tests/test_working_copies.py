from mitraa.tools.text_files import WriteTextFile,WriteTextArgs
from mitraa.tools.files import ReadFile,ReadFileArgs
from mitraa.security.permissions import evaluate


def test_original_preserved_and_followups_reuse_copy(roots,make_ctx,trash):
    original=roots['Documents']/'test.py';original.write_text('print(1)\n')
    target=original.with_name('test_byMitraa.py');tool=WriteTextFile()
    for n in (2,3):
        args=WriteTextArgs(path=str(original),mode='replace',content=f'print({n})\n')
        assessment=evaluate(tool,args,make_ctx());assert assessment.needs_approval
        result=tool.run(args,make_ctx(approved=True));assert result.ok
        assert result.data['path']==str(target) and target.read_text()==f'print({n})\n'
        assert original.read_text()=='print(1)\n'
    assert len(trash)==1 and not target.with_stem('test_byMitraa_byMitraa').exists()
    assert ReadFile().run(ReadFileArgs(path=str(original)),make_ctx()).data['working_copy']==str(target)


def test_custom_name_is_reused(roots,make_ctx,trash):
    source=roots['Documents']/'test.py';source.write_text('print(1)\n');tool=WriteTextFile()
    args=WriteTextArgs(path=str(source),mode='replace',output_name='custom.py',content='print(2)\n')
    assert tool.run(args,make_ctx(approved=True)).ok
    args=WriteTextArgs(path=str(source),mode='append',content='print(3)\n')
    assert tool.run(args,make_ctx(approved=True)).ok
    assert (source.parent/'custom.py').read_text()=='print(2)\nprint(3)\n'
    assert source.read_text()=='print(1)\n'


def test_untracked_collision_is_not_overwritten(roots,make_ctx):
    source=roots['Documents']/'test.py';source.write_text('print(1)\n')
    target=source.with_stem('test_byMitraa');target.write_text('unrelated')
    result=WriteTextFile().run(WriteTextArgs(path=str(source),mode='replace',content='print(2)\n'),make_ctx(approved=True))
    assert not result.ok and target.read_text()=='unrelated'


def test_explicit_overwrite_and_suffixed_file(roots,make_ctx,trash):
    tool=WriteTextFile();source=roots['Documents']/'test.py';source.write_text('print(1)\n')
    assert tool.run(WriteTextArgs(path=str(source),mode='replace',content='print(2)\n',overwrite_original=True),make_ctx(approved=True)).ok
    assert source.read_text()=='print(2)\n'
    copy=source.with_stem('test_byMitraa');copy.write_text('print(1)\n')
    assert tool.run(WriteTextArgs(path=str(copy),mode='replace',content='print(3)\n'),make_ctx(approved=True)).ok
    assert copy.read_text()=='print(3)\n'
