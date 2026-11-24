#!/usr/bin/env python3
"""Arrow Viewer - a fully local web viewer for Apache Arrow IPC files and HF datasets caches.

Usage:
    python arrow_viewer.py [path] [--port 8765] [--host 127.0.0.1]

`path` may be:
  - a directory saved by `datasets.save_to_disk()` (contains data-*.arrow + state.json)
  - one or more raw `.arrow` IPC files (a directory of them, or a single file)

Features: schema panel, paginated grid, substring search, full-cell view, CSV/JSONL export.
Only dependency: pyarrow (already in the evalscope offline wheels bundle). Stdlib http.server,
binds to 127.0.0.1 by default - nothing leaves the machine.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import tempfile
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pyarrow as pa
import pyarrow.csv as pv
import pyarrow.json as pj
import pyarrow.parquet as pq

MAX_CELL = 300  # truncated cell length in grid

_SESSIONS: dict[str, pa.Table] = {}
_SESSIONS_LOCK = threading.Lock()
_TMPDIR = tempfile.mkdtemp(prefix='arrow_viewer_')


def _read_ipc(path: str) -> pa.Table:
    try:
        with pa.OSFile(path, 'rb') as g:
            reader = pa.ipc.open_stream(g)
            batches = []
            while True:
                try:
                    b = reader.read_next_batch()
                except StopIteration:
                    break
                batches.append(b)
            return pa.Table.from_batches(batches)
    except pa.ArrowInvalid:
        with pa.OSFile(path, 'rb') as g:
            return pa.ipc.open_file(g).read_all()


def _iter_arrow_files(root: str) -> list[str]:
    files = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in sorted(filenames):
            if fn.endswith('.arrow') and not fn.startswith('._'):
                files.append(os.path.join(dirpath, fn))
    return files


def load_path(path: str) -> pa.Table:
    """Load a dataset directory, a directory of .arrow files, or a single .arrow/.parquet/.csv/.json file."""
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    if os.path.isdir(path):
        # HF save_to_disk layout: prefer data-*.arrow shards sorted; else any .arrow files
        files = _iter_arrow_files(path)
        data_files = [f for f in files if 'data-' in os.path.basename(f)] or files
        if not data_files:
            for ext in ('.parquet', '.jsonl', '.json'):
                cand = [f for f in _iter_any(path) if f.endswith(ext)]
                if cand:
                    data_files = cand
                    break
        if not data_files:
            raise ValueError(f'no .arrow/.parquet/.json files found under: {path}')
        tables = [_read_any(f) for f in data_files]
        return pa.concat_tables(tables, promote_options='default')
    return _read_any(path)


def _iter_any(root: str) -> list[str]:
    out = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in sorted(filenames):
            out.append(os.path.join(dirpath, fn))
    return out


def _read_any(f: str) -> pa.Table:
    low = f.lower()
    if low.endswith(('.parquet', '.pq')):
        return pq.read_table(f)
    if low.endswith(('.csv', '.tsv')):
        return pv.read_csv(f)
    if low.endswith(('.jsonl', '.ndjson')):
        return pj.read_json(f)
    if low.endswith('.json'):
        with open(f, 'r', encoding='utf-8') as fh:
            obj = json.load(fh)
        rows = obj if isinstance(obj, list) else [obj]
        return pa.Table.from_pylist(rows)
    return _read_ipc(f)


def _cell_json(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False, default=str)
    if isinstance(v, (bytes, bytearray)):
        return f'<bytes {len(v)}>'
    return str(v)


def table_info(table: pa.Table) -> dict:
    cols = []
    for i, name in enumerate(table.column_names):
        chunk = table.column(i)
        nulls = sum(c.null_count for c in chunk.chunks)
        cols.append({'name': name, 'type': str(chunk.type), 'nulls': nulls})
    return {'columns': cols, 'rows': table.num_rows, 'memory_mb': round(table.nbytes / 1048576, 2)}


def get_rows(table: pa.Table, offset: int, limit: int, query: str, col: str) -> dict:
    if query:
        idx_col = table.column_names.index(col) if col in table.column_names else None
        cols = [idx_col] if idx_col is not None else range(table.num_columns)
        mask = None
        q = query.lower()
        for ci in cols:
            chunk = table.column(ci)
            try:
                strs = chunk.cast(pa.string()).to_pylist()
            except (pa.ArrowInvalid, pa.ArrowNotImplementedError):
                strs = [json.dumps(v, ensure_ascii=False, default=str) if v is not None else None for v in chunk.to_pylist()]
            hits = pa.array([bool(s) and q in str(s).lower() for s in strs], type=pa.bool_())
            mask = hits if mask is None else pa.compute.or_(mask, hits)
        table = table.filter(mask)
    total = table.num_rows
    page = table.slice(max(0, offset), max(0, limit))
    rows = []
    for r in range(page.num_rows):
        rows.append([_cell_json(page.column(c)[r].as_py()) for c in range(page.num_columns)])
    return {'rows': rows, 'total': total}


def export_bytes(table: pa.Table, fmt: str) -> tuple[bytes, str, str]:
    if fmt == 'csv':
        buf = io.BytesIO()
        pv.write_csv(table, buf)
        return buf.getvalue(), 'text/csv', 'export.csv'
    if fmt == 'jsonl':
        cols = table.column_names
        lines = []
        for r in range(table.num_rows):
            lines.append(json.dumps({c: _cell_json(table.column(c)[r].as_py()) for c in cols}, ensure_ascii=False))
        return ('\n'.join(lines) + '\n').encode('utf-8'), 'application/x-ndjson', 'export.jsonl'
    rows = [table.slice(r, 1).to_pylist()[0] for r in range(table.num_rows)]
    return json.dumps(rows, ensure_ascii=False, default=str).encode('utf-8'), 'application/json', 'export.json'


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args: Any) -> None:  # quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj: Any, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False, default=str).encode('utf-8'), 'application/json')

    def _session(self, sid: str) -> pa.Table | None:
        with _SESSIONS_LOCK:
            return _SESSIONS.get(sid)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        if parsed.path == '/':
            self._send(200, INDEX_HTML.encode('utf-8'), 'text/html; charset=utf-8')
            return
        if parsed.path == '/api/open':
            path = (qs.get('path') or [''])[0]
            try:
                table = load_path(path)
            except Exception as e:  # noqa: BLE001
                self._json({'error': f'{type(e).__name__}: {e}'}, 400)
                return
            sid = os.urandom(6).hex()
            with _SESSIONS_LOCK:
                _SESSIONS[sid] = table
            info = table_info(table)
            info.update({'sid': sid, 'path': os.path.abspath(path)})
            self._json(info)
            return
        if parsed.path == '/api/rows':
            table = self._session((qs.get('sid') or [''])[0])
            if table is None:
                self._json({'error': 'session expired'}, 404)
                return
            try:
                res = get_rows(table, int((qs.get('offset') or ['0'])[0]), int((qs.get('limit') or ['100'])[0]),
                               (qs.get('q') or [''])[0], (qs.get('col') or [''])[0])
            except Exception as e:  # noqa: BLE001
                self._json({'error': str(e)}, 400)
                return
            self._json(res)
            return
        if parsed.path == '/api/cell':
            table = self._session((qs.get('sid') or [''])[0])
            if table is None:
                self._json({'error': 'session expired'}, 404)
                return
            r = int((qs.get('row') or ['0'])[0]) + int((qs.get('offset') or ['0'])[0])
            c = int((qs.get('col') or ['0'])[0])
            try:
                val = _cell_json(table.column(c)[r].as_py())
            except Exception as e:  # noqa: BLE001
                self._json({'error': str(e)}, 400)
                return
            self._json({'value': val})
            return
        if parsed.path == '/api/export':
            table = self._session((qs.get('sid') or [''])[0])
            if table is None:
                self._json({'error': 'session expired'}, 404)
                return
            data, ctype, fname = export_bytes(table, (qs.get('fmt') or ['csv'])[0])
            self._send(200, data, ctype, {'Content-Disposition': f'attachment; filename="{fname}"'})
            return
        self._json({'error': 'not found'}, 404)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != '/api/upload':
            self._json({'error': 'not found'}, 404)
            return
        length = int(self.headers.get('Content-Length', '0'))
        if length > 2 * 1024**3:
            self._json({'error': 'file too large (>2GB)'}, 413)
            return
        raw = self.rfile.read(length)
        ctype = self.headers.get('Content-Type', '')
        boundary = ctype.split('boundary=')[-1].encode() if 'boundary=' in ctype else b''
        name, payload = _parse_multipart(raw, boundary)
        if not name:
            self._json({'error': 'no file'}, 400)
            return
        safe = os.path.join(_TMPDIR, os.path.basename(name))
        with open(safe, 'wb') as f:
            f.write(payload)
        try:
            table = load_path(safe)
        except Exception as e:  # noqa: BLE001
            self._json({'error': f'{type(e).__name__}: {e}'}, 400)
            return
        sid = os.urandom(6).hex()
        with _SESSIONS_LOCK:
            _SESSIONS[sid] = table
        info = table_info(table)
        info.update({'sid': sid, 'path': safe})
        self._json(info)


def _parse_multipart(raw: bytes, boundary: bytes) -> tuple[str, bytes]:
    if not boundary:
        return '', b''
    parts = raw.split(b'--' + boundary)
    for part in parts:
        if b'filename="' not in part:
            continue
        head, _, body = part.partition(b'\r\n\r\n')
        disposition = head.decode('utf-8', 'ignore')
        fname = ''
        for tok in disposition.split(';'):
            tok = tok.strip().split('\r\n')[0]
            if tok.startswith('filename='):
                fname = tok.split('=', 1)[1].strip('"')
        body = body.rstrip(b'\r\n')
        return fname, body
    return '', b''


INDEX_HTML = r'''<!doctype html>
<html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Arrow Viewer</title><style>
:root{--bg:#f7f7f8;--card:#fff;--tx:#171717;--mut:#6b7280;--bd:#e4e4e7;--ac:#4b3fe3;--acbg:#f2f0ff;--mono:ui-monospace,Consolas,monospace}
@media(prefers-color-scheme:dark){:root{--bg:#141416;--card:#1d1d20;--tx:#e7e7ea;--mut:#9ca3af;--bd:#2e2e33;--ac:#8b7ff5;--acbg:#241f4d}}
*{box-sizing:border-box}body{margin:0;font:14px/1.5 -apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;background:var(--bg);color:var(--tx)}
header{padding:14px 20px;display:flex;gap:12px;align-items:center;border-bottom:1px solid var(--bd);background:var(--card);flex-wrap:wrap}
header h1{font-size:16px;margin:0 12px 0 0}
input[type=text]{flex:1;min-width:260px;padding:8px 10px;border:1px solid var(--bd);border-radius:8px;background:var(--bg);color:var(--tx);font-family:var(--mono);font-size:13px}
button{padding:8px 14px;border:1px solid var(--bd);border-radius:8px;background:var(--card);color:var(--tx);cursor:pointer;font-size:13px}
button.pri{background:var(--ac);border-color:var(--ac);color:#fff}
button:hover{filter:brightness(.95)}
main{padding:16px 20px}
#drop{border:2px dashed var(--bd);border-radius:12px;padding:36px;text-align:center;color:var(--mut);margin-bottom:16px}
#drop.on{border-color:var(--ac);background:var(--acbg);color:var(--ac)}
.hidden{display:none!important}
#meta{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:12px;color:var(--mut);font-size:13px}
#meta b{color:var(--tx)}
#schema{background:var(--card);border:1px solid var(--bd);border-radius:10px;margin-bottom:14px;overflow:auto}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{padding:6px 10px;border-bottom:1px solid var(--bd);text-align:left}
th{background:var(--card);position:sticky;top:0;font-weight:600;cursor:pointer;user-select:none;white-space:nowrap;z-index:2}
td{font-family:var(--mono);white-space:normal;word-break:break-word;vertical-align:top;max-width:520px;line-height:1.5}
td.rownum,th.rownum{width:44px;min-width:44px;color:var(--mut);text-align:right;position:sticky;left:0;background:var(--card);font-family:var(--font-sans)}
#gridwrap{background:var(--card);border:1px solid var(--bd);border-radius:10px;overflow:auto;max-height:calc(100vh - 260px)}
#pager{display:flex;gap:8px;align-items:center;margin-top:10px;color:var(--mut);font-size:13px}
#toolbar{display:flex;gap:8px;align-items:center;margin-bottom:12px;flex-wrap:wrap}
#q{max-width:280px}
#modal{position:fixed;inset:0;background:rgba(0,0,0,.45);display:flex;align-items:center;justify-content:center;z-index:9}
#modal .box{background:var(--card);border:1px solid var(--bd);border-radius:12px;max-width:min(900px,92vw);max-height:80vh;overflow:auto;padding:18px}
#modal pre{margin:0;white-space:pre-wrap;word-break:break-all;font-family:var(--mono);font-size:13px}
.err{color:#dc2626;margin:8px 0}
</style></head><body>
<header><h1>Arrow Viewer</h1>
<input type="text" id="path" placeholder="本机路径：数据集目录 / data-00000-of-00001.arrow / .parquet / .csv ...">
<button class="pri" onclick="openPath()">打开</button>
<label><button onclick="document.getElementById('file').click()">选择文件</button></label>
<input type="file" id="file" class="hidden" multiple>
</header>
<main>
<div id="drop">拖拽 .arrow / .parquet / .csv / .jsonl 文件到这里（文件仅在本机处理，不上传）</div>
<div id="meta" class="hidden"></div>
<div id="toolbar" class="hidden">
  <input type="text" id="q" placeholder="搜索（当前页全列 / 指定列）">
  <select id="qcol"><option value="">全部列</option></select>
  <button onclick="search()">搜索</button>
  <button onclick="exportAs('csv')">导出 CSV</button>
  <button onclick="exportAs('jsonl')">导出 JSONL</button>
  <button onclick="exportAs('json')">导出 JSON</button>
</div>
<div id="schema" class="hidden"><table id="schematbl"></table></div>
<div id="gridwrap" class="hidden"><table id="grid"></table></div>
<div id="pager" class="hidden"><button onclick="go(-1)">上一页</button><span id="pginfo"></span><button onclick="go(1)">下一页</button>
<select id="psize" onchange="state.offset=0;load()"><option>50</option><option selected>100</option><option>200</option><option>500</option></select><span>行/页</span></div>
<div id="err" class="err"></div>
</main>
<div id="modal" class="hidden" onclick="if(event.target===this)this.classList.add('hidden')"><div class="box"><pre id="modalbody"></pre></div></div>
<script>
const state={sid:null,offset:0,total:0,cols:[],q:'',col:''};
function esc(s){if(s==null)return '∅';return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}
function showErr(t){document.getElementById('err').textContent=t}
async function openPath(){
  const p=document.getElementById('path').value.trim();
  if(!p)return;
  try{const r=await fetch('/api/open?path='+encodeURIComponent(p));handle(await r.json())}catch(e){showErr('打开失败: '+e)}
}
document.getElementById('file').addEventListener('change',e=>uploadFiles(e.target.files));
const drop=document.getElementById('drop');
drop.addEventListener('dragover',e=>{e.preventDefault();drop.classList.add('on')});
drop.addEventListener('dragleave',()=>drop.classList.remove('on'));
drop.addEventListener('drop',e=>{e.preventDefault();drop.classList.remove('on');uploadFiles(e.dataTransfer.files)});
async function uploadFiles(files){
  if(!files||!files.length)return;
  const fd=new FormData();
  for(const f of files)fd.append('f'+files.length+Math.random(),f);
  try{const r=await fetch('/api/upload',{method:'POST',body:fd});handle(await r.json())}catch(e){showErr('上传失败: '+e)}
}
function handle(d){
  if(d.error){showErr(d.error);return}
  showErr('');
  state.sid=d.sid;state.offset=0;state.cols=d.columns;state.q='';document.getElementById('q').value='';
  const m=document.getElementById('meta');m.classList.remove('hidden');
  m.innerHTML=`<span>📄 <b>${esc(d.path)}</b></span><span>行数 <b>${d.rows.toLocaleString()}</b></span><span>列数 <b>${d.columns.length}</b></span><span>内存 <b>${d.memory_mb} MB</b></span>`;
  const sel=document.getElementById('qcol');sel.innerHTML='<option value="">全部列</option>'+d.columns.map((c,i)=>`<option value="${esc(c.name)}">${i+1}. ${esc(c.name)}</option>`).join('');
  const st=document.getElementById('schematbl');
  st.innerHTML='<tr><th>#</th><th>列名</th><th>类型</th><th>空值</th></tr>'+d.columns.map((c,i)=>`<tr><td>${i}</td><td>${esc(c.name)}</td><td>${esc(c.type)}</td><td>${c.nulls}</td></tr>`).join('');
  document.getElementById('schema').classList.remove('hidden');
  document.getElementById('toolbar').classList.remove('hidden');
  document.getElementById('drop').classList.add('hidden');
  load();
}
function go(d){const ps=+document.getElementById('psize').value;state.offset=Math.max(0,state.offset+d*ps);load()}
function search(){state.q=document.getElementById('q').value.trim();state.col=document.getElementById('qcol').value;state.offset=0;load()}
document.getElementById('q').addEventListener('keydown',e=>{if(e.key==='Enter')search()});
async function load(){
  if(!state.sid)return;
  const ps=+document.getElementById('psize').value;
  try{
  const r=await fetch(`/api/rows?sid=${state.sid}&offset=${state.offset}&limit=${ps}&q=${encodeURIComponent(state.q)}&col=${encodeURIComponent(state.col)}`);
  const d=await r.json();
  if(d.error){showErr(d.error);return}
  state.total=d.total;
  const cols=state.cols;
  let html='<tr><th class="rownum">#</th>'+cols.map((c,i)=>`<th title="${esc(c.name)} · ${esc(c.type)}" onclick="cellModal(${i},-1)">${esc(c.name)}</th>`).join('')+'</tr>';
  d.rows.forEach((row,ri)=>{html+='<tr><td class="rownum">'+(state.offset+ri+1)+'</td>'+row.map((v,ci)=>{
    const s=esc(v);const tr=s.length>MAX_CELL;
    return `<td title="点击展开" onclick="cellModal(${ci},${ri})">${tr?s.slice(0,MAX_CELL)+'…':s}</td>`}).join('')+'</tr>'});
  const g=document.getElementById('grid');g.innerHTML=html;
  document.getElementById('gridwrap').classList.remove('hidden');
  document.getElementById('pager').classList.remove('hidden');
  const from=state.total?state.offset+1:0;
  document.getElementById('pginfo').textContent=`${from} - ${Math.min(state.offset+ps,state.total)} / ${state.total.toLocaleString()}${state.q?'（筛选后）':''}`;
  window._rows=d.rows;
  }catch(e){showErr('加载数据失败: '+e)}
}
async function cellModal(ci,ri){
  let v;
  if(ri<0){v=state.cols[ci].name+'  ·  '+state.cols[ci].type;showModal(v);return}
  if(state.q){
    const r=await fetch(`/api/cell?sid=${state.sid}&offset=${state.offset}&row=${ri}&col=${ci}`);
    v=(await r.json()).value;
  }else v=window._rows[ri][ci];
  showModal(esc(v));
}
function showModal(t){document.getElementById('modalbody').textContent=t;document.getElementById('modal').classList.remove('hidden')}
function exportAs(fmt){location.href=`/api/export?sid=${state.sid}&fmt=${fmt}`}
</script></body></html>
'''


def main() -> None:
    ap = argparse.ArgumentParser(description='Local Arrow/HF-datasets viewer (http UI)')
    ap.add_argument('path', nargs='?', help='dataset dir or .arrow/.parquet/.csv file to open at startup')
    ap.add_argument('--port', type=int, default=8765)
    ap.add_argument('--host', default='127.0.0.1')
    args = ap.parse_args()
    if args.path:
        try:
            t = load_path(args.path)
            sid = os.urandom(6).hex()
            with _SESSIONS_LOCK:
                _SESSIONS[sid] = t
            print(f'[arrow-viewer] preloaded {args.path}: {t.num_rows} rows x {t.num_columns} cols')
        except Exception as e:  # noqa: BLE001
            print(f'[arrow-viewer] preload failed: {e}', file=sys.stderr)
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f'[arrow-viewer] serving http://{args.host}:{args.port}  (Ctrl+C to stop)')
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
