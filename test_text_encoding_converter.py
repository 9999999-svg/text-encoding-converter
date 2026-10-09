"""One real-files integration check; can target the standalone EXE."""
import argparse
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import text_encoding_converter as tool

parser = argparse.ArgumentParser()
parser.add_argument('--exe', type=Path)
args = parser.parse_args()
program = [str(args.exe.resolve())] if args.exe else [sys.executable, str(Path(__file__).with_name('text_encoding_converter.py'))]
def run(*values, expected=0):
    result = subprocess.run(program + list(map(str, values)), capture_output=True, text=True, encoding='utf-8')
    assert result.returncode == expected, (result.returncode, result.stdout, result.stderr)
    return result
with tempfile.TemporaryDirectory(prefix='编码检查 中文 ') as folder:
    root = Path(folder)
    source = root / '原文件'
    (source / '子目录').mkdir(parents=True)
    text = '你好，GBK 文本\r\n第二行\n'
    (source / '中文 文件.txt').write_bytes(text.encode('gbk'))
    (source / '子目录/数据.csv').write_bytes('姓名,年龄\r\n小军,20\r\n'.encode('gbk'))
    (source / '不选.bin').write_bytes(b'\x00\xff\x81')
    original = {p: hashlib.sha256(p.read_bytes()).digest() for p in source.rglob('*') if p.is_file()}
    target = root / 'UTF8 输出'
    run('--help')
    run('--from', 'utf-8', expected=2)
    run(source, target)
    assert not target.exists(), 'Preview wrote files'
    run(source, target, '--write')
    assert (target / '中文 文件.txt').read_bytes() == text.encode('utf-8-sig')
    assert (target / '子目录/数据.csv').read_bytes().decode('utf-8-sig') == '姓名,年龄\r\n小军,20\r\n'
    assert not (target / '不选.bin').exists()
    saved = (target / '中文 文件.txt').read_bytes()
    run(source, target, '--write', expected=1)
    assert (target / '中文 文件.txt').read_bytes() == saved
    run(source, source / 'nested-output', '--write', expected=1)
    assert not (source / 'nested-output').exists()
    bad = root / '坏编码'
    bad.mkdir()
    (bad / '正常.txt').write_bytes(b'valid')
    (bad / '坏.txt').write_bytes(b'\x81')
    run(bad, root / '不应创建', '--write', expected=1)
    assert not (root / '不应创建').exists()
    emoji = root / 'UTF8'
    emoji.mkdir()
    (emoji / 'emoji.txt').write_bytes('你好 🌈\r\n'.encode())
    run(emoji, root / 'GBK 失败', '--from', 'utf-8', '--to', 'gbk', '--write', expected=1)
    assert not (root / 'GBK 失败').exists()
    run(emoji, root / 'UTF16', '--from', 'utf-8', '--to', 'utf-16', '--write')
    run(root / 'UTF16', root / 'UTF8 回转', '--from', 'utf-16', '--to', 'utf-8', '--write')
    assert (root / 'UTF8 回转/emoji.txt').read_bytes() == (emoji / 'emoji.txt').read_bytes()
    plan = tool.preview(source, root / '变动输出', 'gbk', 'utf-8')
    changed = source / '中文 文件.txt'
    changed.write_bytes('预览后修改'.encode('gbk'))
    rows = tool.write_plan(plan)
    assert any(r['file'] == '中文 文件.txt' and r['status'] == 'ERROR' for r in rows)
    assert not (root / '变动输出/中文 文件.txt').exists()
    changed.write_bytes(text.encode('gbk'))
    try:
        (source / '外部链接.txt').symlink_to(emoji / 'emoji.txt')
    except OSError:
        pass
    else:
        rows = tool.preview(source, root / '链接输出', 'gbk', 'utf-8')['rows']
        assert any(r['file'] == '外部链接.txt' and r['status'] == 'SKIPPED' for r in rows)
        run(source, root / '链接输出', '--write', expected=2)
        assert not (root / '链接输出/外部链接.txt').exists()
    assert all(hashlib.sha256(path.read_bytes()).digest() == digest for path, digest in original.items())
print('PASS: GBK/UTF-8/UTF-16, BOM, Chinese paths, original bytes/newlines, preview, invalid input, no overwrite and changed-file/link guards.')
