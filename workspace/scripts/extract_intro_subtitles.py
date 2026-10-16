#!/usr/bin/env python3
"""Create the reviewed-source SSOT for Shivers intro movie 1002 subtitles."""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path


SOURCE_HEAP_SHA256 = "9A45F316D43ED635D2C48F15D5C614D39E5EDB5925249671765A39C0668BA39E"
SOURCE_HEAP_SIZE = 1728
START_FRAMES = [142, 200, 270, 320, 360, 445, 495, 530, 675, 750, 850, 890, 950, 990, 1030]
END_FRAMES = [200, 270, 320, 360, 445, 495, 530, 675, 750, 850, 890, 950, 990, 1030, 1100]
KOREAN_DRAFTS = [
    "이 내기는 네가 낸 생각이었잖아. 그래도 안에 있는 게 내가 아니라 너라서 다행이야.",
    "그런 다정한 말은 전에도 들은 것 같은데. 너희가 공동묘지에서 하룻밤 보내라고 했을 때 말이야.",
    "오늘 밤 박물관에서 죽으면, 네 장례식 추도사는 꼭 얘한테 맡길게.",
    "네가 이곳 이야기를 그렇게 많이 하지 않았으면 여기서 밤을 보내게 하진 않았을 거야.",
    "그래. 박물관에서 목소리 같은 게 들린다며 좀... 뭐랄까, 집착했잖아. 난 너무 섬뜩해!",
    "있잖아, 어쩌면 15년 전에 사라진 아이들의 목소리일지도 몰라.",
    "맞아. 경찰은 시신도... 범인도 찾지 못했지.",
    "언니 말로는 윈들넛 교수가 아이들을 죽여 지하에 묻었대. 지금도 박물관에 숨어 다음 희생자를 기다리면 어떡해?",
    "유령들이 널 부르는 거야... 경고하는 거지.\n따르릉, 여보세요... 네 전화야.\n(아이들 웃음)",
    "(속삭이며)\n나가... 그들은 사악해... 안 돼에에에!\n(늑대 울음)",
    "그건 그냥 개가 짖은 거야.\n그것 말고 뭔가 더 있었어.",
    "난 아무것도 못 들었어. 여기 분위기에 다들 겁먹은 것 같아.",
    "정말 이대로 할 거야? 지금이라도 그만둬도 돼.",
    "물론 그랬다간 겁쟁이라고 평생 놀림받겠지만.\n그건 그렇지.",
    "넌 괜찮을 거야. 영화에 늦겠다. 새벽에 돌아와 꺼내 줄게.\n잘 있어! 또 봐!",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def extract_strings(heap: bytes) -> list[tuple[int, bytes]]:
    end_of_strings, object_words = struct.unpack_from("<HH", heap, 0)
    position = object_words * 2 + 4
    while True:
        object_position = position
        block_type = struct.unpack_from("<H", heap, position)[0]
        position += 2
        if block_type != 0x1234:
            break
        property_count = struct.unpack_from("<H", heap, position)[0]
        position = object_position + property_count * 2
    strings: list[tuple[int, bytes]] = []
    while position < end_of_strings:
        nul = heap.find(b"\0", position, end_of_strings)
        if nul < 0:
            raise ValueError("Unterminated heap string")
        strings.append((position, heap[position:nul]))
        position = nul + 1
    return strings


def main() -> int:
    project = Path(__file__).resolve().parents[2]
    heap_path = project / "extracted" / "sci" / "heap" / "00930.hep"
    output_path = project / "workspace" / "translation" / "intro_movie_1002.json"
    if heap_path.stat().st_size != SOURCE_HEAP_SIZE or sha256(heap_path) != SOURCE_HEAP_SHA256:
        raise ValueError("Heap 930 identity mismatch")

    heap = heap_path.read_bytes()
    strings = extract_strings(heap)
    subtitle_strings = strings[:15]
    if len(subtitle_strings) != len(KOREAN_DRAFTS):
        raise AssertionError("Intro subtitle count mismatch")

    entries = []
    for index, ((offset, raw), ko, start_frame, end_frame) in enumerate(
        zip(subtitle_strings, KOREAN_DRAFTS, START_FRAMES, END_FRAMES), start=1
    ):
        ko_raw = ko.encode("cp949")
        entries.append(
            {
                "entry_id": index,
                "heap_offset": offset,
                "raw_hex": raw.hex().upper(),
                "source": raw.decode("cp1252"),
                "ko": ko,
                "status": "needs_human_review",
                "timing": {"start_frame": start_frame, "end_frame": end_frame},
                "slot": {
                    "source_byte_length": len(raw),
                    "ko_cp949_byte_length": len(ko_raw),
                    "fits_original_slot": len(ko_raw) <= len(raw),
                },
                "notes": [],
            }
        )

    document = {
        "schema_version": 1,
        "table_id": "shivers_intro_movie_1002",
        "source": {
            "script_number": 930,
            "heap_path": "extracted/sci/heap/00930.hep",
            "heap_size": SOURCE_HEAP_SIZE,
            "heap_sha256": SOURCE_HEAP_SHA256,
            "encoding": "cp1252",
            "runtime_evidence": "introMovie:init drawText calls at frames listed per entry",
        },
        "target": {
            "encoding": "cp949",
            "language": "ko",
            "build_eligible": False,
            "reason": "Draft translation and Korean runtime glyph path both require review",
        },
        "entries": entries,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"output={output_path}")
    print(f"entries={len(entries)}")
    print(f"fits_original_slot={sum(entry['slot']['fits_original_slot'] for entry in entries)}")
    print(f"needs_relocation={sum(not entry['slot']['fits_original_slot'] for entry in entries)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
