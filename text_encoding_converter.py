"""Strict batch text encoding conversion into a new directory; source files stay intact."""
import argparse
from collections import Counter
import hashlib
import os
from pathlib import Path
import queue
import stat
import sys
import tempfile
import threading

ENCODINGS = ('utf-8', 'utf-8-sig', 'gbk', 'gb18030', 'utf-16', 'utf-16-le', 'utf-16-be', 'ascii')
DEFAULT_EXTENSIONS = '.txt,.csv,.md,.json,.srt,.log'
MAX_BYTES = 50 * 1024 * 1024
for stream in (sys.stdout, sys.stderr):
    if stream is not None and hasattr(stream, 'reconfigure'):
        stream.reconfigure(encoding='utf-8', errors='replace')

def linked(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)

def identity(info):
    return info.st_size, info.st_mtime_ns, info.st_dev, info.st_ino

def read_file(path):
    before = path.lstat()
    if linked(before) or not stat.S_ISREG(before.st_mode):
        raise ValueError('链接、重解析点或非普通文件被跳过。')
    if before.st_size > MAX_BYTES:
        raise ValueError('单文件超过 50 MiB，请另用流式转换工具。')
    with path.open('rb') as source:
        if identity(os.fstat(source.fileno())) != identity(before):
            raise OSError('文件在开始读取前发生变化。')
        data = source.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES or identity(os.fstat(source.fileno())) != identity(before):
            raise OSError('文件在读取期间发生变化。')
    if identity(path.lstat()) != identity(before):
        raise OSError('文件在读取后发生变化。')
    return data, identity(before)

def encode(data, source_encoding, target_encoding):
    text = data.decode(source_encoding, errors='strict')
    if '\0' in text:
        raise ValueError('解码后含 NUL 字符，可能是二进制或源编码选择不正确。')
    return text.encode(target_encoding, errors='strict')

def preview(source, destination, source_encoding, target_encoding, extensions=DEFAULT_EXTENSIONS):
    if source_encoding not in ENCODINGS or target_encoding not in ENCODINGS:
        raise ValueError('请选择支持的源编码和目标编码。')
    source = Path(source).absolute()
    if linked(source.lstat()) or not source.is_dir():
        raise ValueError('源路径必须是普通文件夹，不能是链接或重解析点。')
    source = source.resolve()
    destination = Path(destination).absolute()
    if os.path.lexists(destination):
        raise FileExistsError('输出目录已存在；请选择不存在的新目录，不覆盖已有文件。')
    destination = destination.resolve()
    if destination.is_relative_to(source):
        raise ValueError('输出目录不能放在源文件夹内。')
    selected = {part.strip().lower() for part in extensions.split(',') if part.strip()}
    if not selected or any(not part.startswith('.') or len(part) < 2 or any(c in part for c in '\\/*?:') for part in selected):
        raise ValueError('扩展名应使用 .txt,.csv 这样的逗号分隔格式。')
    rows = []
    def issue(path, status, message):
        rows.append(dict(file=path.relative_to(source).as_posix(), status=status, input_bytes='', output_bytes='', message=message))
    def walk_error(exc):
        issue(Path(exc.filename or source), 'ERROR', str(exc))
    for directory, folders, files in os.walk(source, followlinks=False, onerror=walk_error):
        current = Path(directory)
        keep = []
        for name in folders:
            path = current / name
            try:
                if linked(path.lstat()):
                    issue(path, 'SKIPPED', '文件夹链接或重解析点未遍历。')
                else:
                    keep.append(name)
            except OSError as exc:
                issue(path, 'ERROR', str(exc))
        folders[:] = keep
        for name in sorted(files):
            path = current / name
            if path.suffix.lower() not in selected:
                continue
            row = dict(file=path.relative_to(source).as_posix(), status='READY', input_bytes='', output_bytes='', message='', _path=path)
            try:
                if linked(path.lstat()):
                    row.update(status='SKIPPED', message='文件链接或重解析点被跳过。')
                else:
                    data, fingerprint = read_file(path)
                    output = encode(data, source_encoding, target_encoding)
                    row.update(input_bytes=len(data), output_bytes=len(output), _identity=fingerprint, _sha256=hashlib.sha256(data).digest())
            except (OSError, ValueError, UnicodeError) as exc:
                row.update(status='ERROR', message=str(exc))
            rows.append(row)
    if not rows:
        raise ValueError('没有找到符合扩展名的文件。')
    return dict(source=source, destination=destination, source_encoding=source_encoding, target_encoding=target_encoding, rows=rows)

def write_plan(plan):
    if any(row['status'] == 'ERROR' for row in plan['rows']):
        raise ValueError('预览有错误，未创建输出目录。请先检查编码、文件和扩展名。')
    if not any(row['status'] == 'READY' for row in plan['rows']):
        raise ValueError('没有可转换的普通文件。')
    destination = plan['destination']
    destination.mkdir(parents=True, exist_ok=False)
    rows = []
    for original in plan['rows']:
        row = dict(original)
        if row['status'] == 'READY':
            temporary = None
            try:
                data, fingerprint = read_file(row['_path'])
                if fingerprint != row['_identity'] or hashlib.sha256(data).digest() != row['_sha256']:
                    raise OSError('文件在预览后发生变化，未转换该文件。')
                output = encode(data, plan['source_encoding'], plan['target_encoding'])
                target = destination.joinpath(*Path(row['file']).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(prefix='.encoding-', suffix='.tmp', dir=target.parent, delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(output)
                # Windows rename refuses to replace existing files; POSIX link has the same guard.
                if os.name == 'nt':
                    temporary.rename(target)
                else:
                    os.link(temporary, target)
                row['status'] = 'CONVERTED'
            except (OSError, ValueError, UnicodeError) as exc:
                row.update(status='ERROR', message=str(exc))
            finally:
                if temporary is not None and temporary.exists():
                    temporary.unlink()
        rows.append(row)
    return rows

LABELS = {'READY': '可转换', 'CONVERTED': '已转换', 'SKIPPED': '跳过', 'ERROR': '错误'}

def summary(rows):
    counts = Counter(row['status'] for row in rows)
    return '；'.join(f'{label} {counts[key]}' for key, label in LABELS.items())

def launch_gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    root = tk.Tk()
    root.title('文本编码转换器 · 免费开源')
    root.geometry('960x560')
    values = [tk.StringVar(value=value) for value in ('', '', 'gbk', 'utf-8-sig', DEFAULT_EXTENSIONS)]
    status = tk.StringVar(value='指定源编码，先预览；仅写入不存在的新目录，原文件保持不变。')
    messages, state = queue.Queue(), {'plan': None, 'busy': False}
    fields = ttk.Frame(root, padding=12)
    fields.pack(fill='x')
    widgets = []
    for number, label in enumerate(['源文件夹', '新的输出目录', '源编码', '目标编码', '扩展名']):
        ttk.Label(fields, text=label).grid(row=number, column=0, sticky='w', pady=3)
        widget = ttk.Combobox(fields, textvariable=values[number], values=ENCODINGS, state='readonly') if number in (2, 3) else ttk.Entry(fields, textvariable=values[number])
        widget.grid(row=number, column=1, sticky='ew', padx=8)
        widgets.append((widget, 'readonly' if number in (2, 3) else 'normal'))
    def choose_source():
        folder = filedialog.askdirectory()
        if folder:
            values[0].set(folder)
            values[1].set(str(Path(folder).with_name(Path(folder).name + '-converted')))
    pick = ttk.Button(fields, text='选择…', command=choose_source)
    pick.grid(row=0, column=2)
    widgets.append((pick, 'normal'))
    ttk.Label(fields, text='可编辑为尚不存在的目录').grid(row=1, column=2)
    fields.columnconfigure(1, weight=1)
    buttons = ttk.Frame(root, padding=(12, 0))
    buttons.pack(fill='x')
    def worker(action, argument):
        try:
            result = preview(*argument) if action == 'preview' else write_plan(argument)
            messages.put((action, result))
        except (OSError, ValueError, UnicodeError) as exc:
            messages.put(('error', str(exc)))
    def start(action):
        if action == 'preview' and (not values[0].get().strip() or not values[1].get().strip()):
            messagebox.showerror('未开始', '请指定源文件夹和新的输出目录。', parent=root)
            return
        argument = tuple(value.get() for value in values) if action == 'preview' else state['plan']
        state['busy'] = True
        state['plan'] = None
        check.config(state='disabled'); convert.config(state='disabled')
        for widget, _ in widgets:
            widget.config(state='disabled')
        table.delete(*table.get_children())
        status.set('预览中…' if action == 'preview' else '转换中…')
        threading.Thread(target=worker, args=(action, argument), daemon=True).start()
    check = ttk.Button(buttons, text='预览检查', command=lambda: start('preview'))
    check.pack(side='left')
    convert = ttk.Button(buttons, text='转换到新目录', command=lambda: start('write'), state='disabled')
    convert.pack(side='left', padx=8)
    def invalidate(*_):
        state['plan'] = None
        convert.config(state='disabled')
    for value in values:
        value.trace_add('write', invalidate)
    panel = ttk.Frame(root, padding=12)
    panel.pack(fill='both', expand=True)
    table = ttk.Treeview(panel, columns=('file', 'status', 'bytes', 'message'), show='headings')
    for name, label, width in [('file', '相对文件名', 350), ('status', '状态', 90), ('bytes', '字节：输入 → 输出', 170), ('message', '说明', 290)]:
        table.heading(name, text=label)
        table.column(name, width=width, stretch=name in ('file', 'message'))
    bar = ttk.Scrollbar(panel, command=table.yview)
    table.config(yscrollcommand=bar.set)
    table.pack(side='left', fill='both', expand=True)
    bar.pack(side='right', fill='y')
    ttk.Label(root, textvariable=status, padding=12, wraplength=930).pack(fill='x')
    def poll():
        try:
            action, result = messages.get_nowait()
        except queue.Empty:
            pass
        else:
            state['busy'] = False
            check.config(state='normal')
            for widget, normal in widgets:
                widget.config(state=normal)
            if action == 'error':
                status.set('未完成：' + result)
            else:
                rows = result['rows'] if action == 'preview' else result
                if action == 'preview' and any(row['status'] == 'READY' for row in rows) and not any(row['status'] == 'ERROR' for row in rows):
                    state['plan'] = result
                    convert.config(state='normal')
                # ponytail: preview at most 1000 rows; the operation still processes every selected file.
                for row in rows[:1000]:
                    table.insert('', 'end', values=(row['file'], LABELS[row['status']], f"{row['input_bytes']} → {row['output_bytes']}", row['message']))
                status.set(summary(rows) + ('；预览前 1000 项' if len(rows) > 1000 else ''))
        root.after(150, poll)
    root.after(150, poll)
    root.mainloop()

def main():
    parser = argparse.ArgumentParser(description='严格转换文本编码：先预览，写入新目录，保留原文件。')
    parser.add_argument('source', nargs='?', type=Path)
    parser.add_argument('destination', nargs='?', type=Path)
    parser.add_argument('--from', dest='source_encoding', choices=ENCODINGS, default='gbk')
    parser.add_argument('--to', dest='target_encoding', choices=ENCODINGS, default='utf-8-sig')
    parser.add_argument('--extensions', default=DEFAULT_EXTENSIONS)
    parser.add_argument('--write', action='store_true', help='实际转换；不加时只预览')
    args = parser.parse_args()
    if len(sys.argv) == 1:
        launch_gui()
        return 0
    if args.source is None or args.destination is None:
        parser.error('请指定源文件夹和新的输出目录。')
    try:
        plan = preview(args.source, args.destination, args.source_encoding, args.target_encoding, args.extensions)
        rows = plan['rows']
        if args.write and not any(row['status'] == 'ERROR' for row in rows):
            rows = write_plan(plan)
        print(summary(rows))
        for row in rows:
            print(f"{row['status']} · {row['file']} · {row['input_bytes']} → {row['output_bytes']} · {row['message']}")
        if any(row['status'] == 'ERROR' for row in rows):
            return 1
        return 2 if any(row['status'] == 'SKIPPED' for row in rows) else 0
    except KeyboardInterrupt:
        print('已取消；请检查新目录中已完成的文件或临时文件，原文件未被改写。', file=sys.stderr)
        return 130
    except (OSError, ValueError, UnicodeError) as exc:
        print('错误：' + str(exc), file=sys.stderr)
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
