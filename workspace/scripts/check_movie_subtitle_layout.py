"""Measure all current SRTs with the runtime's own FreeType DLL (Windows ABI).

Uses 96dpi character sizes and ceil font height as ScummVM TTFFont does.
Word wrapping is a conservative whitespace model, not a game screenshot.
"""
import argparse
import ctypes as C
import json
import re
from functools import lru_cache
from pathlib import Path


class Generic(C.Structure):
    _fields_ = [('data', C.c_void_p), ('finalizer', C.c_void_p)]


class Metrics(C.Structure):
    _fields_ = [('x_ppem', C.c_ushort), ('y_ppem', C.c_ushort)] + [(k, C.c_long) for k in ('x_scale','y_scale','ascender','descender','height','max_advance')]


class Size(C.Structure):
    _fields_ = [('face',C.c_void_p),('generic',Generic),('metrics',Metrics)]


class Face(C.Structure):
    _fields_ = [(k,C.c_long) for k in ('num_faces','face_index','face_flags','style_flags','num_glyphs')] + [
        ('family_name',C.c_void_p),('style_name',C.c_void_p),('num_fixed_sizes',C.c_int),('available_sizes',C.c_void_p),
        ('num_charmaps',C.c_int),('charmaps',C.c_void_p),('generic',Generic),('bbox',C.c_long*4),('units_per_EM',C.c_ushort)
    ] + [(k,C.c_short) for k in ('ascender','descender','height','max_advance_width','max_advance_height','underline_position','underline_thickness')] + [
        ('glyph',C.c_void_p),('size',C.POINTER(Size))]


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('build',type=Path)
    ap.add_argument('--font-size',type=int,default=13)
    ap.add_argument('--width',type=int,default=600)
    ap.add_argument('--height',type=int,default=100)
    ap.add_argument('--report',type=Path)
    args=ap.parse_args()
    dll=C.CDLL(str((args.build/'runtime/freetype.dll').resolve()))
    dll.FT_Init_FreeType.argtypes=[C.POINTER(C.c_void_p)]
    dll.FT_New_Face.argtypes=[C.c_void_p,C.c_char_p,C.c_long,C.POINTER(C.POINTER(Face))]
    dll.FT_Set_Char_Size.argtypes=[C.POINTER(Face),C.c_long,C.c_long,C.c_uint,C.c_uint]
    dll.FT_Get_Char_Index.argtypes=[C.POINTER(Face),C.c_ulong]
    dll.FT_Get_Advance.argtypes=[C.POINTER(Face),C.c_uint,C.c_int32,C.POINTER(C.c_long)]
    dll.FT_MulFix.argtypes=[C.c_long,C.c_long]
    dll.FT_MulFix.restype=C.c_long
    dll.FT_Done_Face.argtypes=[C.POINTER(Face)]
    dll.FT_Done_FreeType.argtypes=[C.c_void_p]
    library=C.c_void_p(); face=C.POINTER(Face)()
    assert dll.FT_Init_FreeType(C.byref(library))==0
    assert dll.FT_New_Face(library,str((args.build/'ShiversKorean.ttf').resolve()).encode('utf-8'),0,C.byref(face))==0
    assert dll.FT_Set_Char_Size(face,0,args.font_size*64,96,96)==0
    line_height=(dll.FT_MulFix(face.contents.height,face.contents.size.contents.metrics.y_scale)+63)//64
    @lru_cache(None)
    def advance(char):
        index=dll.FT_Get_Char_Index(face,ord(char))
        assert index, f'Missing glyph: {char}'
        value=C.c_long()
        assert dll.FT_Get_Advance(face,index,0,C.byref(value))==0
        return value.value//65536
    records=[]
    for path in sorted((args.build/'MOVIES').glob('*.srt')):
        for block in re.split(r'\n\n',path.read_text(encoding='utf-8-sig').strip()):
            lines=[]
            for paragraph in block.splitlines()[2:]:
                current=''
                for word in paragraph.split(' '):
                    candidate=(current+' '+word).strip()
                    if current and sum(map(advance,candidate))>args.width:
                        lines.append(current); current=word
                    else: current=candidate
                lines.append(current)
            height=len(lines)*line_height+2
            records.append({'movie':path.name,'entry':int(block.splitlines()[0]),'lines':len(lines),'height':height,'fits':height<=args.height})
    report={'font_size':args.font_size,'dpi':96,'bbox':[args.width,args.height],'line_height':line_height,
            'entries':len(records),'max_lines':max(r['lines'] for r in records),'max_height':max(r['height'] for r in records),
            'overflow':[r for r in records if not r['fits']], 'scope':'Static FreeType metrics, 640x480 overlay; manual runtime visual QA pending'}
    dll.FT_Done_Face(face); dll.FT_Done_FreeType(library)
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))
    raise SystemExit(1 if report['overflow'] else 0)


if __name__=='__main__':
    main()
